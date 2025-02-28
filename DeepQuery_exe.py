###################################################################
import os
import sys
import io
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import json
import logging
import paramiko
import re
import requests
import shlex
import webbrowser
import asyncio
import uvicorn
from asyncio import Queue, create_task
import pynvml
import websockets

###################################################################
class StdoutLogger:
    def write(self, message):
        if message.strip():
            logger.info(message.strip())
    
    def flush(self):
        pass

    def isatty(self):
        return False

sys.stdout = StdoutLogger()

class WebSocketLogHandler(logging.Handler):
    def __init__(self, log_queue):
        # 先调用父类的构造函数，传递默认的日志级别
        super().__init__(level=logging.NOTSET)
        self.log_queue = log_queue

    def emit(self, record):
        log_message = self.format(record)
        asyncio.run_coroutine_threadsafe(log_queue.put(log_message), asyncio.get_event_loop())

async def handle_ws(websocket, path=None):
    connected_clients.add(websocket)
    try:
        async for message in websocket:
            pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        connected_clients.remove(websocket)

# 创建自定义日志处理器实例
log_queue = Queue()
ws_handler = WebSocketLogHandler(log_queue)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ws_handler.setFormatter(formatter)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(ws_handler)

# Get the directory where the current script is located
if getattr(sys, 'frozen', False):
    base_dir = sys._MEIPASS
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))
# Build the paths for static files and template files
static_folder = os.path.join(base_dir, 'static')
template_folder = os.path.join(base_dir, 'templates')

# Create a FastAPI application instance
app = FastAPI()

# Mount the static file directory
app.mount("/static", StaticFiles(directory=static_folder), name="static")  # New mount

config = {
    "SSH_HOST": "000.000.000.000", 
    "SSH_PORT": "22",
    "SSH_USER": "user",
    "SSH_PASSWORD": "user_pass",
    "SERPER_API_KEY": "your_serper_api_key"
}

# SSH connection parameters
SSH_HOST = config.get('SSH_HOST')
SSH_PORT = config.get('SSH_PORT')
SSH_USER = config.get('SSH_USER')
# Read the password from the configuration file
SSH_PASSWORD = config.get('SSH_PASSWORD')  # If using a private key, you can leave it blank
SERPER_API_KEY = config.get('SERPER_API_KEY')

#
is_remote = False
# Used to store the conversation history
all_messages = [{"role": "system", "content": "You are a helpful assistant"}]

# 定义一个全局的WebSocket连接集合
connected_clients = set()


log_queue = Queue()

# 修改log_consumer协程，增加去重逻辑
# 保持现有的log_consumer实现
async def log_consumer():
    last_message = None
    while True:
        message = await log_queue.get()
        if message != last_message:
            for client in connected_clients.copy():
                try:
                    await client.send(message)
                except:
                    connected_clients.remove(client)
            last_message = message

# Asynchronous function to start the WebSocket server
async def start_ws_server():
    server = await websockets.serve(handle_ws, "localhost", 8765)
    await server.wait_closed()

@app.get("/favicon.ico")
async def favicon():
    return FileResponse(os.path.join(base_dir, 'static', 'favicon.ico'), media_type='image/vnd.microsoft.icon')

@app.get("/")
async def index():
    with open(os.path.join(template_folder, 'index.html'), 'r', encoding='utf-8') as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.post("/query")
async def query(request: Request):
    global is_remote
    data = await request.json()
    user_input = data.get('prompt').strip()
    if not isinstance(user_input, (str, bytes)):
        logger.error(f"[System] Unexpected data type for user_input: {type(user_input)}")
        return JSONResponse(content={"error": "Invalid user_input data type"}, status_code=400)
    else:
        # Add the user message to the conversation history
        all_messages.append({"role": "user", "content": user_input})
    
    logger.info(f"[User Message]: {user_input}")

    selected_model = data.get('model', 'deepseek-r1:7b')
    logger.info(f"[System] use {selected_model} LLM model")

    is_search_on = data.get('search_toggle', False)  
    web_context = ""  # Default value when search is off

    # If search is on, call the web_search function
    if is_search_on:
        logger.info(f"[Web Search]: {user_input}")
        web_context = web_search(user_input)
        logger.info(f"[Search result]: {web_context}")
        if not isinstance(web_context, (str, bytes)):
            logger.error(f"[System] Unexpected data type for web_context: {type(web_context)}")
            return JSONResponse(content={"error": "Invalid web_context data type"}, status_code=400)

    try:
        # Notify the front end to start executing the command
        for client in connected_clients:
            try:
                await client.send(datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]+" - __main__ - INFO - "+"[front end] start query")
                logger.info("[System]: send message to client")  # New log record
            except Exception as e:
                logger.error(f"[System] Failed to send 'start' message: {e}")

        if is_remote:
           # Establish an SSH connection
           try:
              ssh = paramiko.SSHClient()                                                                  
              ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
              ssh.connect(SSH_HOST, port=SSH_PORT, username=SSH_USER, password=SSH_PASSWORD)
           except paramiko.AuthenticationException:
              logger.error("[System] SSH authentication failed.")
              return JSONResponse(content={"error": "SSH authentication failed"}, status_code=500)
           except paramiko.SSHException as ssh_ex:
              logger.error(f"[System] SSH connection error: {ssh_ex}")
              return JSONResponse(content={"error": f"SSH connection error: {ssh_ex}"}, status_code=500)

        # Build the prompt
        prompt = f"""[System Instruction] You are an AI assistant. The current date is {datetime.now().strftime('%Y-%m-%d')}.
        The following is a real-time information snippet from the web (may be incomplete): {web_context} [User Question] {user_input} """
        print(f"prompt: {prompt}")
    
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
            "history": all_messages
        }
        data_json = json.dumps(data, ensure_ascii=False)
        if is_remote:
            command = [
                "curl",
                "-s",
                "-X", "POST",
                "http://localhost:11434/api/generate",
                "-H", "Content-Type: application/json",
                "-d", shlex.quote(data_json)
            ]
            logger.info("[Remote SSH]: " + ' '.join(command))
    
            # Execute the command on SSH
            stdin, stdout, stderr = ssh.exec_command(' '.join(command))
        
            # Get the execution result
            response = stdout.read().decode()
            error = stderr.read().decode()
        
            ssh.close()
            if '{"error":"unexpected EOF"}' in response:
                logger.error(f"[System] SSH command error: {response}")
                return JSONResponse(content={"error": response}, status_code=500)
            if error:
                logger.error(f"[System] SSH command error: {error}")
                return JSONResponse(content={"error": error}, status_code=500)
        
            try:
                response_json = json.loads(response)
                generated_response = response_json.get("response", "")
        
            except json.JSONDecodeError as e:
                logger.error(f"[System] JSON decode error: {e}")
                return JSONResponse(content={"error": f"JSON decode error: {e}"}, status_code=500)
    
        else:
            # Send the request directly to the local server
            logger.info(f"[Local Request] "+"http://localhost:11434/api/generate "+data_json)
            response = requests.post(
                "http://localhost:11434/api/generate",
                data=data_json
            )
            response.raise_for_status()
   
            response_text = response.text
            if '{"error":"unexpected EOF"}' in response_text:
                logger.error(f"[System] HTTP request error: {response_text}")
                return JSONResponse(content={"error": response_text}, status_code=500)
    
            try:
                response_json = json.loads(response_text)
                generated_response = response_json.get("response", "")
    
            except json.JSONDecodeError as e:
                logger.error(f"[System] JSON decode error: {e}")
                return JSONResponse(content={"error": f"JSON decode error: {e}"}, status_code=500)

        # Parse the <think> tag
        parts = re.split(r'(<think>.*?</think>)', generated_response, flags=re.IGNORECASE | re.DOTALL)
        for part in parts:
            if part.startswith('<think>') and part.endswith('</think>'):
                think_content = part[7:-8]  # Remove the <think> tag
            elif part:
                ai_response = part.replace("\n", "").strip()
        if ai_response:
            logger.info(f"[AI response] {ai_response}")
        # Update the context
        all_messages.append({"role": "system", "content": ai_response})
        formatted_messages = json.dumps(all_messages, indent=4, ensure_ascii=False)
    
        # Notify the front end that the command execution is complete
        for client in connected_clients:
            await client.send(datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]+" - __main__ - INFO - "+"[front end] query end")
    
        return JSONResponse(content={"response": generated_response})
    
    except Exception as e:
        logger.error(f"[System] An exception occurred: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.post("/new-chat")
async def new_chat():
    global all_messages
    all_messages = [{"role": "system", "content": "You are a helpful assistant"}]
    return JSONResponse(content={"status": "success"})

# New load chat route
@app.post("/load-chat")
async def load_chat(request: Request):
    global all_messages
    data = await request.json()
    all_messages = data
    return JSONResponse(content=all_messages)

# New web_search function for web search
# If you need it as a route function, uncomment the following line
@app.post("/web_search")
async def handle_web_search(request: Request):
    data = await request.json()
    prompt = data.get('prompt')
    search_result = web_search(prompt)
    return JSONResponse(content={"web_context": search_result})

@app.post("/save-markdown")
async def save_markdown(request: Request):
    # 这里可以添加更多逻辑，比如保存markdown文件等
    # 目前只需要输出日志信息
    print('"POST /save-markdown HTTP/1.1" 200 OK')
    return JSONResponse(content={"status": "success"})

def web_search(prompt):
    """
    Execute a web search synchronously and return a list of the top 10 search result contents using the google.serper API.
    """
    api_key = SERPER_API_KEY
    if api_key is None:
        logger.error("[System] SERPER_API_KEY 未设置")
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
        logger.error(f"[System] RequestException: {e}")
        return f"RequestException: {str(e)}"
    except ValueError as e:
        logger.error(f"[System] JSON error: {e}")
        return f"JSON error: {str(e)}"
    except Exception as e:
        logger.error(f"[System] Unknown error: {e}")
        return f"unknown error: {str(e)}"

@app.get("/get-all-messages")
async def get_all_messages():
    global all_messages
    return JSONResponse(content=all_messages)

@app.post("/toggle-local-remote")
async def toggle_local_remote(request: Request):
    global is_remote
    data = await request.json()
    is_remote = data.get('isRemote')
    if is_remote:
        logger.info('[Access] remote model via SSH')
    else:
        logger.info('[Access] local model directly')
    return JSONResponse(content={"status": "success"})

@app.get("/get-gpu-info")
async def get_gpu_info():
    global is_remote
    try:
        if is_remote:
            # 远程服务器获取GPU信息
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(SSH_HOST, port=SSH_PORT, username=SSH_USER, password=SSH_PASSWORD)
            
            stdin, stdout, stderr = ssh.exec_command('nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv')
            output = stdout.read().decode()
            error = stderr.read().decode()
            ssh.close()
            
            if error:
                return {"status": "error", "message": f"Remote error: {error}"}
            return {"status": "success", "data": output}
        else:
            # 本地获取GPU信息
            pynvml.nvmlInit()
            device_count = pynvml.nvmlDeviceGetCount()
            info = []
            
            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                
                info.append(
                    f"GPU {i}: "
                    f"Utilization {util.gpu}%, "
                    f"Memory {mem.used//1024**2}MB/{mem.total//1024**2}MB"
                )
            
            pynvml.nvmlShutdown()
            return {"status": "success", "data": "\n".join(info)}
            
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def main():
    #sys.stdout = StdoutLogger()
    
    if os.getenv("SERPER_API_KEY") is None:
        logger.error("[System] SERPER_API_KEY is not set.")
    else:
        webbrowser.open('http://localhost:8000/')

    consumer_task = create_task(log_consumer())
    
    async with websockets.serve(handle_ws, "localhost", 8765) as server:
        config = uvicorn.Config(app, host='0.0.0.0', port=8000)
        server = uvicorn.Server(config)
        await server.serve()
        await consumer_task

if __name__ == "__main__":
    asyncio.run(main())

