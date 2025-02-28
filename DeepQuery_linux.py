import os
import sys
import io
import logging
import paramiko
import requests
import json
import asyncio
import uvicorn
import subprocess
import re
import shlex
import webbrowser
import websockets
#####only for windows
#import pynvml
import pystray
import threading
import signal
from PIL import Image, ImageDraw
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from asyncio import Queue, create_task
########################################################################
tray_icon = None
server_task = None
# 处理WebSocket相关逻辑的类
class WebSocketHandler:
    def __init__(self):
        self.log_queue = Queue()
        self.connected_clients = set()

    async def handle_ws(self, websocket, path=None):
        # 处理WebSocket连接的逻辑
        self.connected_clients.add(websocket)
        try:
            while True:
                if not self.log_queue.empty():
                    log_entry = await self.log_queue.get()
                    await websocket.send(log_entry)
                await asyncio.sleep(0.1)
        except websockets.exceptions.ConnectionClosedOK:
            pass
        finally:
            self.connected_clients.remove(websocket)

    async def log_consumer(self):
        # 处理日志消费的逻辑
        while True:
            if not self.log_queue.empty():
                log_entry = await self.log_queue.get()
                for client in self.connected_clients:
                    try:
                        await client.send(log_entry)
                    except websockets.exceptions.ConnectionClosedOK:
                        self.connected_clients.remove(client)
            await asyncio.sleep(0.1)

    async def start_ws_server(self):
        server = await websockets.serve(self.handle_ws, "localhost", 8765)
        await server.wait_closed()

# 处理FastAPI路由的类
class APIRouterHandler:
    def __init__(self, app, logger, chat_handler, ws_handler):
        self.app = app
        self.logger = logger
        self.chat_handler = chat_handler
        self.ws_hander = ws_handler
        # 读取配置文件
        with open('.deepquery.config', 'r') as f:
            self.config = json.load(f)
        # SSH连接参数
        self.SSH_HOST = self.config.get('SSH_HOST')
        self.SSH_PORT = self.config.get('SSH_PORT')
        self.SSH_USER = self.config.get('SSH_USER')
        self.SSH_PASSWORD = self.config.get('SSH_PASSWORD')
        # 其他初始化逻辑
        self.is_remote = False
        self.all_messages = [{"role": "system", "content": "You are a helpful assistant"}]

    def setup_routes(self):
        @self.app.get("/favicon.ico")
        async def favicon():
            # 处理favicon.ico的逻辑
            return FileResponse(os.path.join(base_dir, 'static', 'favicon.ico'), media_type='image/vnd.microsoft.icon')

        @self.app.get("/")
        async def index(request: Request):
            return templates.TemplateResponse("index.html", {"request": request})

        @self.app.post("/query")
        async def query(request: Request):
            # 处理查询的逻辑
            data = await request.json()
            user_input = data.get('prompt').strip()
            if not isinstance(user_input, (str, bytes)):
                self.logger.error(f"[System] Unexpected data type for user_input: {type(user_input)}")
                return JSONResponse(content={"error": "Invalid user_input data type"}, status_code=400)
            else:
                # Add the user message to the conversation history
                self.all_messages.append({"role": "user", "content": user_input})
            
            self.logger.info(f"[User Message]: {user_input}")
           
            selected_model = data.get('model', 'deepseek-r1:7b')
            self.logger.info(f"[System] use {selected_model} LLM model")
           
            is_search_on = data.get('search_toggle', False)  
            web_context = ""  # Default value when search is off
           
            # If search is on, call the web_search function
            if is_search_on:
                self.logger.info(f"[Web Search]: {user_input}")
                web_context = chat_handler.web_search(user_input)
                self.logger.info(f"[Search result]: {web_context}")
                if not isinstance(web_context, (str, bytes)):
                    self.logger.error(f"[System] Unexpected data type for web_context: {type(web_context)}")
                    return JSONResponse(content={"error": "Invalid web_context data type"}, status_code=400)
           
            try:
                # Notify the front end to start executing the command
                for client in ws_handler.connected_clients:
                    try:
                        await client.send(datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]+" - __main__ - INFO - "+"[front end] start query")
                        self.logger.info("[System]: send message to client")  # New log record
                    except Exception as e:
                        self.logger.error(f"[System] Failed to send 'start' message: {e}")
           
                if self.is_remote:
                   # Establish an SSH connection
                   try:
                       ssh = paramiko.SSHClient()                                                                  
                       ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                       ssh.connect(
                              self.SSH_HOST,
                              port=self.SSH_PORT,
                              username=self.SSH_USER,
                              password=self.SSH_PASSWORD)
                       
                   except paramiko.AuthenticationException:
                      self.logger.error("[System] SSH authentication failed.")
                      return JSONResponse(content={"error": "SSH authentication failed"}, status_code=500)
                   except paramiko.SSHException as ssh_ex:
                      self.logger.error(f"[System] SSH connection error: {ssh_ex}")
                      return JSONResponse(content={"error": f"SSH connection error: {ssh_ex}"}, status_code=500)
           
                # Build the prompt
                prompt = f"""[System Instruction] You are an AI assistant. The current date is {datetime.now().strftime('%Y-%m-%d')}.
                The following is a real-time information snippet from the web (may be incomplete): {web_context}.\n [User Question] {user_input}. """
                self.logger.info(f"[User prompt]: {prompt}")
            
                # Build the request data
                data = {
                    "model": selected_model,
                    "prompt": prompt,
                    "stream": False,
                    "max_tokens": 20480,
                    "temperature": 0.6,
                    "top_p": 0.9,
                    "n": 2,
                    "best_of": 3,
                    "history": self.all_messages
                }
                data_json = json.dumps(data, ensure_ascii=False)
                if self.is_remote:
                    command = [
                        "curl",
                        "-s",
                        "-X", "POST",
                        "http://localhost:11434/api/generate",
                        "-H", "Content-Type: application/json",
                        "-d", shlex.quote(data_json)
                    ]
                    self.logger.info("[Remote SSH]: " + ' '.join(command))
            
                    # Execute the command on SSH
                    stdin, stdout, stderr = ssh.exec_command(' '.join(command))
                
                    # Get the execution result
                    response = stdout.read().decode()
                    error = stderr.read().decode()
                
                    ssh.close()
                    if '{"error":"unexpected EOF"}' in response:
                        self.logger.error(f"[System] SSH command error: {response}")
                        return JSONResponse(content={"error": response}, status_code=500)
                    if error:
                        self.logger.error(f"[System] SSH command error: {error}")
                        return JSONResponse(content={"error": error}, status_code=500)
                
                    try:
                        response_json = json.loads(response)
                        generated_response = response_json.get("response", "")
                
                    except json.JSONDecodeError as e:
                        self.logger.error(f"[System] JSON decode error: {e}")
                        return JSONResponse(content={"error": f"JSON decode error: {e}"}, status_code=500)
            
                else:
                    # Send the request directly to the local server
                    self.logger.info(f"[Local Request] "+"http://localhost:11434/api/generate "+data_json)
                    response = requests.post(
                        "http://localhost:11434/api/generate",
                        data=data_json
                    )
                    response.raise_for_status()
            
                    response_text = response.text
                    if '{"error":"unexpected EOF"}' in response_text:
                        self.logger.error(f"[System] HTTP request error: {response_text}")
                        return JSONResponse(content={"error": response_text}, status_code=500)
            
                    try:
                        response_json = json.loads(response_text)
                        generated_response = response_json.get("response", "")
            
                    except json.JSONDecodeError as e:
                        self.logger.error(f"[System] JSON decode error: {e}")
                        return JSONResponse(content={"error": f"JSON decode error: {e}"}, status_code=500)
           
                # Parse the <think> tag
                parts = re.split(r'(<think>.*?</think>)', generated_response, flags=re.IGNORECASE | re.DOTALL)
                for part in parts:
                    if part.startswith('<think>') and part.endswith('</think>'):
                        think_content = part[7:-8]  # Remove the <think> tag
                    elif part:
                        ai_response = ""  # 初始化变量                        
                        for part in parts:
                            if ...:
                                ...
                            elif part:
                                ai_response += part.replace("\n", "").strip()

                if ai_response:
                    self.logger.info(f"[AI response] {ai_response}")
                # Update the context
                self.all_messages.append({"role": "system", "content": ai_response})
                formatted_messages = json.dumps(self.all_messages, indent=4, ensure_ascii=False)
            
                # Notify the front end that the command execution is complete
                for client in ws_handler.connected_clients:
                    await client.send(datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]+" - __main__ - INFO - "+"[front end] query end")
            
                return JSONResponse(content={"response": generated_response})
            
            except Exception as e:
                self.logger.error(f"[System] An exception occurred: {e}")
                return JSONResponse(content={"error": str(e)}, status_code=500)

        @self.app.post("/new-chat")
        async def new_chat():
            # 处理新建聊天的逻辑
            self.all_messages = [{"role": "system", "content": "You are a helpful assistant"}]
            return JSONResponse(content={"status": "success"})

        @self.app.post("/load-chat")
        async def load_chat(request: Request):
            # 处理加载聊天的逻辑
            data = await request.json()
            self.all_messages = data
            return JSONResponse(content=self.all_messages)

        @self.app.post("/web_search")
        async def handle_web_search(request: Request):
            # 处理网页搜索的逻辑
            data = await request.json()
            prompt = data.get('prompt')
            search_result = web_search(prompt)
            return JSONResponse(content={"web_context": search_result})


        @self.app.post("/save-markdown")
        async def save_markdown(request: Request):
            # 处理保存Markdown的逻辑
            self.logger.info('"POST /save-markdown HTTP/1.1" 200 OK')
            return JSONResponse(content={"status": "success"})

        @self.app.get("/get-all-messages")
        async def get_all_messages():
            # 处理获取所有消息的逻辑
            return JSONResponse(content=self.all_messages)

        @self.app.post("/toggle-local-remote")
        async def toggle_local_remote(request: Request):
            # 处理切换本地/远程模式的逻辑
            data = await request.json()
            self.is_remote = data.get('isRemote')
            if self.is_remote:
                self.logger.info('[Access] remote model via SSH')
            else:
                self.logger.info('[Access] local model directly')
            return JSONResponse(content={"status": "success"})

        @self.app.get("/get-gpu-info")
        async def get_gpu_info():
            # 处理获取GPU信息的逻辑
            try:
                if self.is_remote:
                    # 远程服务器获取GPU信息
                    ssh = paramiko.SSHClient()
                    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    ssh.connect(
                           self.SSH_HOST,
                           port=self.SSH_PORT,
                           username=self.SSH_USER,
                           password=self.SSH_PASSWORD)
                    
                    stdin, stdout, stderr = ssh.exec_command('nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv')
                    output = stdout.read().decode()
                    error = stderr.read().decode()
                    ssh.close()
                    
                    if error:
                        return {"status": "error", "message": f"Remote error: {error}"}
                    return {"status": "success", "data": output}
                else:
                    try:
                        # 执行 nvidia-smi 命令
                        result = subprocess.run(\
                            ['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total', '--format=csv'],
                            capture_output=True, text=True, check=True)
                        # 获取标准输出
                        output = result.stdout
                        return {"status": "success", "data": output}

                    except subprocess.CalledProcessError as e:
                        # 处理命令执行错误
                        error = e.stderr
                        return {"status": "error", "message": f"Remote error: {error}"}
                    except Exception as e:
                        # 处理其他异常
                        return {"status": "error", "message": f"An unexpected error occurred: {str(e)}"}                    
            except Exception as e:
                return {"status": "error", "message": str(e)}


# 处理聊天相关逻辑的类
class ChatHandler:
    def __init__(self, logger):
        self.logger = logger

    def web_search(self, prompt):
        """
        Execute a web search synchronously and return a list of the top 10 search result contents using the google.serper API.
        """
        api_key = os.getenv("SERPER_API_KEY")
        if api_key is None:
            self.logger.error("[System] SERPER_API_KEY 未设置")
            return "未找到搜索结果"
        headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json"
        }
        proxy_url = os.getenv("PROXY_URL")
        try:
            if proxy_url:
                proxies = {
                    "http": proxy_url,
                    "https": proxy_url
                }
                response = requests.post(
                    "https://google.serper.dev/search",
                    headers=headers,
                    json={"q": prompt, "num": 20},
                    proxies=proxies
                )
            else:
                response = requests.post(
                    "https://google.serper.dev/search",
                    headers=headers,
                    json={"q": prompt, "num": 10}
                )
            response.raise_for_status()
            data = response.json()
            results = data.get("organic", [])[:10]
            if results:
                formatted_results = "\n\n".join(
                    f"Title: {result.get('title', 'N/A')}\nLink: {result.get('link', 'N/A')}\nSnippet: {result.get('snippet', 'N/A')}"
                    for result in results
                )
                return formatted_results
            else:
                return "find no searching result"
        except requests.RequestException as e:
            self.logger.error(f"[System] RequestException: {e}")
            return f"RequestException: {str(e)}"
        except ValueError as e:
            self.logger.error(f"[System] JSON error: {e}")
            return f"JSON error: {str(e)}"
        except Exception as e:
            self.logger.error(f"[System] Unknown error: {e}")
            return f"unknown error: {str(e)}"


class StdoutLogger:
    def __init__(self, logger):
        # 初始化时传入日志记录器实例
        self.logger = logger

    def write(self, message):
        if message.strip():
            self.logger.info(message.strip())

    def flush(self):
        pass

    def isatty(self):
        return False

class WebSocketLogHandler(logging.Handler):
    def __init__(self, log_queue):
        # 先调用父类的构造函数，传递默认的日志级别
        super().__init__(level=logging.NOTSET)
        self.log_queue = log_queue

    def emit(self, record):
        # 处理日志发送的逻辑
        log_entry = self.format(record)
        try:
            self.log_queue.put_nowait(log_entry)
        except asyncio.QueueFull:
            pass  # 队列满了，忽略这条日志

def create_tray_icon():
   # 创建托盘图标
   global tray_icon
   base_dir = os.path.dirname(os.path.abspath(__file__))
   icon_path = os.path.join(base_dir, 'static', 'favicon.ico')  # 修改图标路径
   image = Image.open(icon_path)
   menu = pystray.Menu(
       pystray.MenuItem('打开界面', lambda: webbrowser.open('http://localhost:8000')),
       pystray.MenuItem('退出程序', terminate_app)
   )
   tray_icon = pystray.Icon("name", image, "title", menu)
   tray_icon.run()
   return tray_icon

def terminate_app():
   global tray_icon
   # 终止程序
   os.kill(os.getpid(), signal.CTRL_C_EVENT)
   if tray_icon:
       tray_icon.stop()

def run_tray_icon():
   global tray_icon
   tray_icon = create_tray_icon()
   tray_icon.run()

# 创建FastAPI应用实例
app = FastAPI()

# 挂载静态文件目录
base_dir = os.path.dirname(os.path.abspath(__file__))
static_folder = os.path.join(base_dir, 'static')
app.mount("/static", StaticFiles(directory=static_folder), name="static")

templates_folder = os.path.join(base_dir, 'templates')
templates = Jinja2Templates(directory=templates_folder)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 初始化各个处理类
chat_handler = ChatHandler(logger)

# Configure paramiko logging
paramiko_logger = logging.getLogger("paramiko.transport")
paramiko_logger.setLevel(logging.INFO)

# 初始化各个处理类
ws_handler = WebSocketHandler()
log_queue = ws_handler.log_queue

ws_log_handler = WebSocketLogHandler(log_queue)
api_handler = APIRouterHandler(app, logger, chat_handler, ws_handler)

# 创建自定义日志处理器格式
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ws_log_handler.setFormatter(formatter)
paramiko_logger.addHandler(ws_log_handler)
logger.addHandler(ws_log_handler)
sys.stdout = StdoutLogger(logger)

# 设置路由
api_handler.setup_routes()

# 增强错误处理：
@app.exception_handler(Exception)
async def universal_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        content={"error": "Internal server error"},
        status_code=500
    )

async def main():
    # 启动系统托盘图标（在新线程中）
    tray_thread = threading.Thread(target=run_tray_icon, daemon=True)
    tray_thread.start()

    # 解除环境变量强制限制
    if os.getenv("SERPER_API_KEY") is None:
        logger.warning("[System] SERPER_API_KEY is not set. Web search will be disabled.")
    else:
        webbrowser.open('http://localhost:8000/')

    config = uvicorn.Config(app, host="0.0.0.0", port=8000)
    server = uvicorn.Server(config)
    
    ws_task = create_task(ws_handler.log_consumer()) 
 
    async with websockets.serve(ws_handler.handle_ws, "localhost", 8765):
        await server.serve()
        ws_task.cancel()
        try:
            await ws_task
        except asyncio.CancelledError:
            pass

    # 清理托盘图标
    if tray_icon:
        tray_icon.stop()

if __name__ == "__main__":
    asyncio.run(main())
