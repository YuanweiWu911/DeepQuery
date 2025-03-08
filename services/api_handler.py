import os
import re
import paramiko
import asyncio
import json
import pygame
import shlex
import requests
import subprocess
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from .voice_service import VoiceRecognitionService
from asyncio import create_task, Lock
from services.audio_util import AudioUtil

class APIRouterHandler:
    """Configures and manages all FastAPI routes.
    
    Attributes:
        app (FastAPI): FastAPI application instance
        logger (logging.Logger): Configured logger instance
        chat_handler (ChatHandler): Chat operation handler
        config (dict): Application configuration
        is_remote (bool): Current execution mode flag
    """

    def __init__(self, app, logger, chat_handler, ws_handler, templates):
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
        self.templates = templates
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 指向项目根目录
        self.is_remote = False 
        self.all_messages = [{"role": "system", "content": "You are a helpful assistant"}]
        self.voice_task = None
        self.is_voice_active = True  # 默认开启语音识别
        self.voice_lock = Lock()
        self.voice_service = VoiceRecognitionService(logger, ws_handler = ws_handler)
        self.voice_service_task = None
        self._load_config()
        self.audio_util = AudioUtil()
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
            self.logger.info("[Voice] 语音识别未激活，跳过启动")
            return

        # 如果已有任务正在运行，先取消
        if self.voice_service_task and not self.voice_service_task.done():
            self.voice_service_task.cancel()
            try:
                await self.voice_service_task
            except asyncio.CancelledError:
                self.logger.info("[Voice] 旧语音任务已取消")

        while self.is_voice_active:
            self.voice_service_task = create_task(self.voice_service.start_listening()) 
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

            except asyncio.CancelledError:
                self.logger.info(f"[Voice] 语音识别任务被取消")
                self.is_voice_active = False
                break
            except Exception as e:
                self.logger.error(f"[Voice] 处理语音输入出错: {e}")
                await asyncio.sleep(1)
                
    def setup_routes(self):
        """Configures all API endpoints."""
        @self.app.get("/favicon.ico")
        async def favicon():
            # 处理favicon.ico的逻辑
            return FileResponse(os.path.join(self.base_dir, 'static', 'favicon.ico'), media_type='image/vnd.microsoft.icon')

        @self.app.get("/")
        async def index(request: Request):
            return self.templates.TemplateResponse("index.html", {"request": request})

        @self.app.post("/toggle-voice")
        async def toggle_voice(request: Request):
            data = await request.json()
            self.is_voice_active = data.get("isVoiceActive", False)
            # 同步 ChatHandler 的语音状态
            self.chat_handler.set_voice_active(self.is_voice_active)
            self.logger.info(f"[Voice] 语音识别状态切换为: {self.is_voice_active}")
            
            # 如果关闭语音，停止当前播放
            if not self.is_voice_active and pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                pygame.mixer.music.stop() 

            if self.is_voice_active:
                self.logger.info("[Voice] 语音识别已激活")
                # 取消旧任务,并启动新任务
                if self.voice_task and not self.voice_task.done():
                    self.voice_task.cancel()
                if self.voice_service_task:
                    self.voice_service_task.cancel()
                # 启动新任务
                self.voice_task = create_task(self.start_voice_recognition())
            else:
                self.logger.info("[Voice] 语音识别已禁用")
                self.voice_service.stop()
                if self.voice_task and not self.voice_task.done():
                    self.voice_task.cancel()
                if self.voice_service_task and not self.voice_service_task.done():
                    self.voice_service_task.cancel()
                # 等待任务清理完成
                # 修复【1】await 语法错误
                try:
                    if self.voice_task:
                        await asyncio.wait_for(self.voice_task, timeout=1.0)
                    if self.voice_service_task:
                        await asyncio.wait_for(self.voice_service_task, timeout=1.0)
                except asyncio.TimeoutError:
                    self.logger.info("[Voice] 任务取消超时，强制结束")
                except asyncio.CancelledError:
                    self.logger.info("[Voice] 所有语音任务已清理")

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
            # 检查输入类型是否为字符串
            if not isinstance(user_input, str):
                # 如果是bytes类型则解码为字符串
                if isinstance(user_input, bytes):
                    try:
                        user_input = user_input.decode('utf-8')
                    except UnicodeDecodeError:
                        self.logger.error(f"[System] Failed to decode bytes input: {user_input}")
                        return JSONResponse(content={"error": "Invalid input encoding"}, status_code=400)
                else:
                    self.logger.error(f"[System] Unexpected data type for user_input: {type(user_input)}")
                    return JSONResponse(content={"error": "Invalid user_input data type"}, status_code=400)
            
            # 添加用户消息到对话历史
            self.all_messages.append({"role": "user", "content": user_input})
            
            self.logger.info(f"[User Message]: {user_input}")
           
            selected_model = data.get('model', 'deepseek-r1:7b')
            self.logger.info(f"[System] use {selected_model} LLM model")
           
            is_search_on = data.get('search_toggle', False)  
            web_context = ""  # Default value when search is off
           
            # If search is on, call the web_search function
            if is_search_on:
                self.logger.info(f"[Web Search]: {user_input}")
                web_context = self.chat_handler.web_search(user_input)
                self.logger.info(f"[Search result]: {web_context}")
                if not isinstance(web_context, (str, bytes)):
                    self.logger.error(f"[System] Unexpected data type for web_context: {type(web_context)}")
                    return JSONResponse(content={"error": "Invalid web_context data type"}, status_code=400)
           
            try:
                # Notify the front end to start executing the command
                for client in self.ws_handler.connected_clients:
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
                try:
                    data_json = json.dumps(data, ensure_ascii=False)
                except TypeError as e:
                    self.logger.error(f"[System] JSON serialization error: {e}")
                    return JSONResponse(content={"error": "Invalid data format"}, status_code=400)
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
                    # 确保ssh连接存在并可用
                    if ssh and ssh.get_transport() and ssh.get_transport().is_active():
                        stdin, stdout, stderr = ssh.exec_command(' '.join(command))
                    else:
                        raise Exception("SSH连接未建立或已断开")
                
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

                try:
                    # 尝试提取 <think> 内容（如果存在）
                    think_content = ""
                    ai_response = await self.chat_handler.process_response(generated_response)
                    
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
                    
                    # 删除这一行，因为语音播放已经在 chat_handler.process_response 中处理
                    # if self.is_voice_active:
                    #     create_task(self.audio_util.say_response(ai_response))

                except Exception as parse_error:
                    self.logger.error(f"[System] 响应解析失败: {parse_error}")
                    self.all_messages.append({"role": "system", "content": "[System] 响应解析错误"})

                formatted_messages = json.dumps(self.all_messages, indent=4, ensure_ascii=False)
            
                for client in self.ws_handler.connected_clients:
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

        @self.app.get("/voice-stream")
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
