"""
DeepSeek-R1 Query Backend System

This module implements the core backend services for the LLM Query Interface,
providing the following key capabilities:

1. WebSocket-based real-time terminal output
2. REST API endpoints for chat operations
3. SSH-managed remote execution
4. GPU resource monitoring
5. Conversation context management
6. Integrated web search functionality

Architecture Components:
- WebSocketHandler: Manages real-time client communication
- APIRouterHandler: Configures and manages all API endpoints
- ChatHandler: Implements chat-specific business logic
- WebSocketLogHandler: Custom logging system for WebSocket

Dependencies:
- FastAPI (REST API framework)
- WebSockets (Real-time communication)
- Paramiko (SSH client)
- Uvicorn (ASGI server)
"""

import os
import sys
import io
from io import BytesIO
import json
import re
import shlex
import logging
import paramiko
import requests
import asyncio
import uvicorn
import subprocess
import websockets
import webbrowser
import pystray
import signal
import threading
import edge_tts
import speech_recognition as sr
from asyncio import Queue, create_task
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import StreamingResponse
from logging.handlers import QueueHandler
from PIL import Image
from asyncio import Lock

tray_icon = None
server_task = None

#region WebSocket Handler
class WebSocketHandler:
    """Manages WebSocket connections and log distribution.
    
    Implements pub-sub pattern for real-time log streaming to connected clients.
    
    Attributes:
        log_queue (Queue): Buffer for log messages
        connected_clients (set): Active WebSocket connections
    """

    def __init__(self):
        """Initializes WebSocket handler with empty client set and log queue."""
        self.log_queue = Queue()
        self.connected_clients = set()

    async def handle_ws(self, websocket, path=None):
        """Main WebSocket connection handler.
        
        Args:
            websocket (websockets.WebSocketServerProtocol): Client connection object
            path (Optional[str]): Request path (unused)
            
        Flow:
            1. Adds client to connected set
            2. Continuously sends queued logs
            3. Handles graceful disconnect
        """
        self.connected_clients.add(websocket)
        try:
            async for message in websocket:
                if message == "QueryComplete":
                    self.logger.info("[WebSocket] 收到前端 QueryComplete 信号")
                elif not self.log_queue.empty():
                    log_entry = await self.log_queue.get()
                    await websocket.send(log_entry)
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
#endregion

#region APIRouterHandler
class APIRouterHandler:
    """Configures and manages all FastAPI routes.
    
    Attributes:
        app (FastAPI): FastAPI application instance
        logger (logging.Logger): Configured logger instance
        chat_handler (ChatHandler): Chat operation handler
        config (dict): Application configuration
        is_remote (bool): Current execution mode flag
    """

    def __init__(self, app, logger, chat_handler, ws_handler):
        """Initializes router with dependencies.
        
        Args:
            app (FastAPI): Main app instance
            logger (logging.Logger): Shared logger
            chat_handler (ChatHandler): Chat operations handler
            ws_handler (WebSocketHandler): WebSocket manager
        """
        self.app = app
        self.logger = logger
        self.chat_handler = chat_handler
        self.ws_handler = ws_handler
        self.is_remote = False 
        self.all_messages = [{"role": "system", "content": "You are a helpful assistant"}]
        self.voice_task = None
        self.is_voice_active = True  # 默认开启语音识别
        self.voice_lock = Lock()
        self.voice_service = VoiceRecognitionService(logger)
        self.voice_service_task = None
        self._load_config()
        self.logger.info("[System] Initializing APIRouterHandler")

    def _load_config(self):
        """Loads SSH configuration from .deepquery.config file."""
        with open('.deepquery.config', 'r') as f:
            self.config = json.load(f)
        self.SSH_HOST = self.config.get('SSH_HOST')
        self.SSH_PORT = self.config.get('SSH_PORT', 22)
        self.SSH_USER = self.config.get('SSH_USER')
        self.SSH_PASSWORD = self.config.get('SSH_PASSWORD')

    async def start_voice_recognition(self):
        """启动语音识别任务"""
        if not self.is_voice_active:
            return

        self.voice_service_task = create_task(self.voice_service.start_listening()) 
        while self.is_voice_active:
            try:
                prompt = await self.voice_service.audio_queue.get()
                self.logger.info(f"[Voice] 处理语音输入: {prompt}")
                self.all_messages.append({"role": "user", "content": prompt})
                # 推送给前端
                for client in self.ws_handler.connected_clients:
                   try:
                       await client.send(f"VoicePrompt: {prompt}")
                   except Exception as e:
                       self.logger.error(f"[WebSocket] 发送失败: {e}")

#               # 等待前端查询完成
#               async with websockets.connect('ws://localhost:8765') as ws:
#                   while True:
#                       message = await ws.recv()
#                       if message == "QueryComplete":
#                           self.logger.info("[Voice] 收到前端查询完成信号，继续监听")
#                           break
                       
            except asyncio.CancelledError:
                self.logger.info(f"[Voice] 语音识别任务被取消")
                break
            except Exception as e:
                self.logger.error(f"[Voice] 处理语音输入出错: {e}")
                await asyncio.sleep(1)
                
    def setup_routes(self):
        """Configures all API endpoints."""
        @self.app.get("/favicon.ico")
        async def favicon():
            # 处理favicon.ico的逻辑
            return FileResponse(os.path.join(base_dir, 'static', 'favicon.ico'), media_type='image/vnd.microsoft.icon')

        @self.app.get("/")
        async def index(request: Request):
            return templates.TemplateResponse("index.html", {"request": request})

        @self.app.post("/toggle-voice")
        async def toggle_voice(request: Request):
            data = await request.json()
            self.is_voice_active = data.get("isVoiceActive", False)
            self.logger.info(f"[Voice] 语音识别状态切换为: {self.is_voice_active}")
            if self.is_voice_active:
                self.logger.info("[Voice] 语音识别已激活")
                # 取消已有任务（避免重复）
                if self.voice_task and not self.voice_task.done():
                    self.voice_task.cancel()
                if self.voice_service_task:
                    self.voice_service_task.cancel()
                # 启动新任务
                self.voice_task = create_task(self.start_voice_recognition())
            else:
                self.voice_service.stop()
                if self.voice_task:
                    self.voice_task.cancel()
                if self.voice_service_task:
                    self.voice_service_task.cancel()
            return JSONResponse(content={"status": "success"})
        
        @self.app.post("/query")
        async def query(request: Request):
            """Handles LLM query requests.
            
            Flow:
                1. Validates input
                2. Performs web search (if enabled)
                3. Constructs LLM prompt
                4. Executes locally or via SSH
                5. Returns formatted response
                
            Raises:
                HTTP 400: Invalid input format
                HTTP 500: Execution failure
            """

            # 处理查询的逻辑
            self.logger.info("[Query] Received query request")
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
#               parts = re.split(r'(<think>.*?</think>)', generated_response, flags=re.IGNORECASE | re.DOTALL)
#               for part in parts:
#                   if part.startswith('<think>') and part.endswith('</think>'):
#                       think_content = part[7:-8]  # Remove the <think> tag
#                   elif part:
#                       ai_response = ""  # 初始化变量                        
#                       for part in parts:
#                           if ...:
#                               ...
#                           elif part:
#                               ai_response += part.replace("\n", "").strip()

#               if ai_response:
#                   self.logger.info(f"[AI response] {ai_response}")

# 替换原有的 <think> 标签解析逻辑
                try:
                    # 尝试提取 <think> 内容（如果存在）
                    think_content = ""
                    ai_response = generated_response  # 默认使用完整响应
                    
                    # 查找所有 <think> 标签内容
                    think_matches = re.findall(r'<think>(.*?)</think>', generated_response, flags=re.DOTALL)
                    if think_matches:
                        think_content = think_matches[0]
                        # 移除所有 <think> 标签，保留剩余内容作为 AI 响应
                        ai_response = re.sub(r'<think>.*?</think>', '', generated_response, flags=re.DOTALL).strip()
                    
                    # 记录 AI 响应
                    self.logger.info(f"[AI response] {ai_response}")
                    
                    # 更新上下文（确保 ai_response 不为空）
                    if not ai_response:
                        ai_response = "[System] 未能获取有效响应"
                    self.all_messages.append({"role": "system", "content": ai_response})
                    
                except Exception as parse_error:
                    self.logger.error(f"[System] 响应解析失败: {parse_error}")
                    self.all_messages.append({"role": "system", "content": "[System] 响应解析错误"})

                # Update the context
                #self.all_messages.append({"role": "system", "content": ai_response})
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
            self.all_messages = [
                {"role": "system", "content": "You are a helpful assistant"}
            ]
            self.logger.info("[System] new chat, history cleared!")
            return JSONResponse(content={"status": "success", "message": "chat init."},
                                status_code=200
            )

        @self.app.post("/load-chat")
        async def load_chat(request: Request):
            try:
                data = await request.json()
                
                # 验证数据格式
                if not isinstance(data, list):
                    raise ValueError("无效的对话格式：必须为消息列表")
                    
                for msg in data:
                    if "role" not in msg or "content" not in msg:
                        raise ValueError("消息缺少必要字段：role 或 content")
                    if msg["role"] not in ("system", "user"):
                        raise ValueError(f"非法角色类型：{msg['role']}")
                
                # 加载合法数据
                self.all_messages = data
                self.logger.info(f"[System] 已加载 {len(data)} 条历史消息")
                return JSONResponse(
                    content=self.all_messages,
                    status_code=200
                )
                
            except json.JSONDecodeError:
                return JSONResponse(
                    content={"error": "无效的JSON格式"},
                    status_code=400
                )
            except ValueError as ve:
                return JSONResponse(
                    content={"error": str(ve)},
                    status_code=400
                )

        @self.app.post("/web_search")
        async def handle_web_search(request: Request):
            # 处理网页搜索的逻辑
            data = await request.json()
            prompt = data.get('prompt')
            search_result = self.chat_handler.web_search(prompt)
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

        @app.get("/voice-stream")
        async def voice_stream(request: Request):
            return JSONResponse(
                content={"error": "接口已弃用"},
                status_code=410
            ) 
                
        @self.app.get("/get-gpu-info")
        async def get_gpu_info():
            """Retrieves GPU utilization metrics.
            
            Behavior:
                - Local mode: Executes nvidia-smi directly
                - Remote mode: Executes via SSH connection
                
            Returns:
                JSON: {
                    'status': 'success'|'error',
                    'data': str|None,
                    'message': str|None
                }
            """
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

        @app.post("/synthesize-speech")
        async def synthesize_speech(request: Request):
            data = await request.json()
            text = data.get('text')
            voice = data.get('voice',"zh-CN-YunyangNeural" )
            rate = "+20%"
            pitch = "+20Hz"
            try:
                """
                "zh-CN-YunxiNeural"    # 青年男声（默认）
                "zh-CN-YunyangNeural"   # 新闻男声
                "zh-CN-XiaoxiaoNeural"  # 年轻女声（多情感）
                "zh-CN-XiaoyiNeural"    # 少女音
                "zh-CN-YunjianNeural"   # 成熟男声
                """
                communicate = edge_tts.Communicate(text,voice)
                audio_stream = BytesIO()
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_stream.write(chunk["data"])
                audio_stream.seek(0)
                
                return StreamingResponse(
                    iter([audio_stream.getvalue()]),
                    media_type="audio/mpeg"
                )
                
            except Exception as e:
                logger.error(f"语音合成失败: {str(e)}")
                return JSONResponse(
                    content={"error": "语音合成失败"},
                    status_code=500
                )

#endregion

#region Chat Handler
class ChatHandler:
    """Implements chat-specific business logic.
    
    Attributes:
        logger (logging.Logger): Configured logger instance
    """
 
    def __init__(self, logger):
        self.logger = logger

    def web_search(self, prompt: str) -> str:
        """Performs web search using Google Serper API.
        
        Args:
            prompt (str): Search query text
            
        Returns:
            str: Formatted results or error message
            
        Raises:
            requests.RequestException: On network failures
            ValueError: On invalid API response
            
        Note:
            Requires SERPER_API_KEY environment variable
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
#endregion

#region StdoutLogger
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
#endregion

#region WebSocketLogHandler
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
#endregion

# 新增语音服务类
class VoiceRecognitionService:
    def __init__(self, logger):
        self.logger = logger
        self.recognizer = sr.Recognizer()
        self.is_listening = True
        self.audio_queue = Queue()
        self.last_query = ""
        self.full_query = ""
        self.has_started = False
        self.unrecognized_count = 0
        self.max_retries = 3  # 最大重试次数
        self.wake_words = ["小弟", "小迪", "小D"]
    
    def stop(self):
        self.is_listening = False
        self.logger.info("[Voice] 语音服务已停止")
        # 增加清理音频队列逻辑
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except QueueEmpty:
                break

    def reset_state(self):
        self.full_query = ""
        self.has_started = False
        self.unrecognized_count = 0
        self.logger.info("[Voice] 会话状态已重置，准备新一轮对话")        
        
    async def start_listening(self):
        while self.is_listening:
            mic = None
            retry_count = 0
            while retry_count < self.max_retries and self.is_listening:
                try:
                    mic = sr.Microphone()
                    with mic as source:
                        self.recognizer.adjust_for_ambient_noise(source, duration=2)
                        self.logger.info("[Voice] 麦克风准备就绪")
                        retry_count = 0  # 重置重试计数
                        while self.is_listening:
                            try:
                                self.logger.info("[Voice] 开始监听音频...")
                                audio = await asyncio.to_thread(
                                    self.recognizer.listen,
                                    source,
                                    timeout=3,
                                    phrase_time_limit=8
                                )
                                self.logger.info("[Voice] 音频捕获成功，正在识别...")
                                text = await asyncio.to_thread(
                                    self.recognizer.recognize_google,
                                    audio,
                                    language="zh-CN"
                                )
                                
                                wake_word_detected = None
                                for wake_word in self.wake_words:
                                    if wake_word in text and not self.has_started:
                                        wake_word_detected = wake_word
                                        break
                                if wake_word_detected:
                                    self.has_started = True
                                    self.full_query = text.split(wake_word_detected, 1)[-1].lstrip()
                                    self.logger.info(f"[Voice] 检测到唤醒词'{wake_word_detected}'，开始记录查询: {self.full_query}")
                                    continue
                        
                                if text.strip() and self.has_started:
                                    self.last_query = text
                                    self.logger.info(f"[Voice] 识别结果入队: {text}")
                                    self.unrecognized_count = 0
                                    self.full_query = (self.full_query + " " + text).strip()
                                    self.logger.info(f"[Voice] 当前累积查询: {self.full_query}")
                        
                            except sr.UnknownValueError:
                                self.logger.warning(f"[Voice] 无法识别语音输入 (环境噪音: {self.recognizer.energy_threshold})")
                                self.recognizer.adjust_for_ambient_noise(source, duration=1)
                                self.unrecognized_count += 1
                                
                                if self.has_started and self.unrecognized_count >= 2 and self.full_query:
                                    self.logger.info(f"[Voice] 连续2次未识别，提交查询: {self.full_query}")
                                    await self.audio_queue.put(self.full_query)
                                    self.reset_state()
                                    continue
                                    
                            except sr.WaitTimeoutError:
                                if self.has_started and self.full_query and self.unrecognized_count >= 2:
                                    await self.audio_queue.put(self.full_query)
                                    self.reset_state()
                                    continue
                                
                            except sr.RequestError as e:
                                self.logger.error(f"[Voice] 识别服务暂不可用: {str(e)}")
                                await asyncio.sleep(3)
                                continue

                except OSError as e:
                    self.logger.error(f"[Voice] 麦克风不可用: {str(e)}")
                    retry_count += 1
                    self.logger.info(f"[Voice] 尝试重启麦克风 ({retry_count}/{self.max_retries})")
                    if mic:
                        mic.__exit__(None, None, None)
                        mic = None
                    await asyncio.sleep(2)  # 等待后重试
                    if retry_count >= self.max_retries:
                        self.logger.error("[Voice] 麦克风重试次数耗尽，停止语音服务")
                        self.stop()
                        break
                except Exception as e:
                    self.logger.error(f"[Voice] 未预期的错误: {str(e)}")
                    await asyncio.sleep(1)
                    break
                finally:
                    if mic:
                        mic.__exit__(None, None, None)
                        mic = None
            
            if not self.is_listening:
                self.logger.info("[Voice] 退出语音服务")
                break
               
def create_tray_icon():
    """Creates system tray icon with menu items.
    
    Returns:
        pystray.Icon: Configured tray icon instance
        
    Menu Items:
        - Open Interface: Launches web interface
        - Exit: Terminates application
    """

    global tray_icon
    base_dir = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(base_dir, 'static', 'favicon.ico')  # 修改图标路径
    image = Image.open(icon_path)
    menu = pystray.Menu(
        pystray.MenuItem('打开界面', lambda: webbrowser.open('http://localhost:8000')),
        pystray.MenuItem('退出程序', terminate_app)
    )
    tray_icon = pystray.Icon("name", image, "DeepQuery", menu)
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
    # 初始化API处理器
    api_handler = APIRouterHandler(app, logger, chat_handler, ws_handler)
    # 启动系统托盘图标（新线程）
    tray_thread = threading.Thread(target=run_tray_icon, daemon=True)
    tray_thread.start()

    # 配置服务器
    config = uvicorn.Config(app, host="0.0.0.0", port=8000)
    server = uvicorn.Server(config)

    # 并行启动WebSocket和HTTP服务器
    async with websockets.serve(ws_handler.handle_ws, "localhost", 8765) as ws_server:
        # 正确启动Uvicorn服务
        server_task = asyncio.create_task(server.serve())
        
        # 打开浏览器
        webbrowser.open('http://localhost:8000/')
        
        try:
            # 启动语音识别任务
            if api_handler.is_voice_active:
                api_handler.voice_task = asyncio.create_task(
                    api_handler.start_voice_recognition()
                )

            # 启动日志消费任务
            ws_task = asyncio.create_task(ws_handler.log_consumer())

            # 等待服务器任务完成
            await server_task

        except asyncio.CancelledError:
            logger.info("服务正常终止")
        finally:
            # 清理任务
            if api_handler.voice_task:
                api_handler.voice_task.cancel()
            ws_task.cancel()
            await asyncio.gather(
                api_handler.voice_task,
                ws_task,
                return_exceptions=True
            )
            await server.shutdown()
            
    # 清理托盘图标
    if tray_icon:
        tray_icon.stop()
        
if __name__ == "__main__":
    """Application entry point."""
    asyncio.run(main())
