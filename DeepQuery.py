import os
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
import websockets

###################################################################
# 获取当前脚本所在的目录
base_dir = os.path.dirname(os.path.abspath(__file__))

# 构建静态文件和模板文件的路径
static_folder = os.path.join(base_dir, 'static')
template_folder = os.path.join(base_dir, 'templates')

# 创建 FastAPI 应用实例
app = FastAPI()

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory=static_folder), name="static")  # 新增挂载

# 配置日志记录
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 读取配置文件
with open('config.json', 'r') as f:
    config = json.load(f)

# SSH连接参数
SSH_HOST = config.get('SSH_HOST')
SSH_PORT = config.get('SSH_PORT')
SSH_USER = config.get('SSH_USER')
# 从配置文件中读取密码
SSH_PASSWORD = config.get('SSH_PASSWORD')  # 如果使用私钥，则可以不填

# 用于存储对话历史
all_messages = [{"role": "system", "content": "You are a helpful assistant"}]

# 存储WebSocket连接
connected_clients = set()

# WebSocket处理函数
async def handle_ws(websocket, path=None):
    connected_clients.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        connected_clients.remove(websocket)

# 启动WebSocket服务器的异步函数
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
    data = await request.json()
    user_input = data.get('prompt').strip()
    logger.info(f"Received User message: {user_input}")
    if not isinstance(user_input, (str, bytes)):
        logger.error(f"Unexpected data type for user_input: {type(user_input)}")
        return JSONResponse(content={"error": "Invalid user_input data type"}, status_code=400)

    selected_model = data.get('model', 'deepseek-r1:32b')
    logger.info(f"Use {selected_model} LLM model")

    is_search_on = data.get('search_toggle', False)  # 修改默认值为 False
    web_context = ""  # Default value when search is off

    # If search is on, call the web_search function
    if is_search_on:
        logger.info(f"web search: {user_input}")
        web_context = web_search(user_input)
        logger.info(f"search results: {web_context}")
        if not isinstance(web_context, (str, bytes)):
            logger.error(f"Unexpected data type for web_context: {type(web_context)}")
            return JSONResponse(content={"error": "Invalid web_context data type"}, status_code=400)

    try:
        # 建立SSH连接
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(SSH_HOST, port=SSH_PORT, username=SSH_USER, password=SSH_PASSWORD)

        # 添加用户消息到对话历史
        all_messages.append({"role": "user", "content": user_input})
        logger.info(f"all_messages: {all_messages}")

        # 构建 prompt
        prompt = f"""[系统指令] 你是一个AI助手, 当前日期为{datetime.now().strftime('%Y-%m-%d')} \
以下是来自网络的实时信息片段(可能不完整): {web_context} [用户问题] {user_input} """
        print(f"prompt: {prompt}")

        # 构建请求数据
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
        data_json = json.dumps(data)
        print(data_json)
        command = [
            "curl",
            "-s",
            "-X", "POST",
            "http://localhost:11434/api/generate",
            "-H", "Content-Type: application/json",
            "-d", shlex.quote(data_json)
        ]
        logger.info("ssh exec_command: " + ' '.join(command))

        # 通知前端开始执行命令
        for client in connected_clients:
            try:
               await client.send("start")
               logger.info("Sent 'start' message to client")  # 新增日志记录
            except Exception as e:
               logger.error(f"Failed to send 'start' message: {e}")

        # 在 SSH 上执行命令
        stdin, stdout, stderr = ssh.exec_command(' '.join(command))

        # 获取执行结果
        response = stdout.read().decode()
        error = stderr.read().decode()

        ssh.close()
        if '{"error":"unexpected EOF"}' in response:
            logger.error(f"SSH command error: {response}")
            return JSONResponse(content={"error": response}, status_code=500)
        if error:
            logger.error(f"SSH command error: {error}")
            return JSONResponse(content={"error": error}, status_code=500)

        try:
            response_json = json.loads(response)
            generated_response = response_json.get("response", "")

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            return JSONResponse(content={"error": f"JSON decode error: {e}"}, status_code=500)

        # 解析 <think> 标签
        parts = re.split(r'(<think>.*?</think>)', generated_response, flags=re.IGNORECASE | re.DOTALL)
        for part in parts:
            if part.startswith('<think>') and part.endswith('</think>'):
                think_content = part[7:-8]  # 去掉 <think> 标签
            elif part:
                ai_response = part.replace("\n", "").strip()
        if ai_response:
            logger.info(f"{ai_response}")
            logger.info("AI answer finished!")
        # 更新上下文
        all_messages.append({"role": "system", "content": ai_response})
        formatted_messages = json.dumps(all_messages, indent=4, ensure_ascii=False)

        # 通知前端命令执行完毕
        for client in connected_clients:
            await client.send("end")

        return JSONResponse(content={"response": generated_response})

    except Exception as e:
        logger.error(f"An exception occurred: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.post("/new-chat")
async def new_chat():
    global all_messages
    all_messages = [{"role": "system", "content": "You are a helpful assistant"}]
    return JSONResponse(content={"status": "success"})

# 新增 web_search 函数，用于进行网络搜索
# 如果需要作为路由函数，取消下面一行的注释
@app.post("/web_search")
async def handle_web_search(request: Request):
    data = await request.json()
    prompt = data.get('prompt')
    search_result = web_search(prompt)
    return JSONResponse(content={"web_context": search_result})

def web_search(prompt):
    """
    同步执行网络搜索，使用 google.serper API 返回前10个搜索结果内容列表。
    """
    api_key = os.getenv("SERPER_API_KEY")
    if api_key is None:
        logger.error("SERPER_API_KEY 未设置")
        return "未找到搜索结果"
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json"
    }
    logger.info(f"web search Using API key: {api_key}")
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
                json={"q": prompt, "num": 5},
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
            return "未找到搜索结果"
    except requests.RequestException as e:
        logger.error(f"RequestException: {e}")
        return f"请求异常: {str(e)}"
    except ValueError as e:
        logger.error(f"JSON error: {e}")
        return f"JSON解析异常: {str(e)}"
    except Exception as e:
        logger.error(f"Unknown error: {e}")
        return f"未知异常: {str(e)}"



@app.get("/get-all-messages")
async def get_all_messages():
    global all_messages
    return JSONResponse(content=all_messages)

async def main():
    # 检查 SERPER_API_KEY 是否设置
    if os.getenv("SERPER_API_KEY") is None:
        logger.error("SERPER_API_KEY 未设置，请设置该环境变量后再运行程序。")
    else:
        webbrowser.open('http://127.0.0.1:8000/')

        # 启动WebSocket服务器
        ws_server_task = asyncio.create_task(start_ws_server())

        # 启动FastAPI应用
        import uvicorn
        config = uvicorn.Config(app, host='0.0.0.0', port=8000)
        server = uvicorn.Server(config)
        await server.serve()
        await ws_server_task

if __name__ == "__main__":
    asyncio.run(main())
