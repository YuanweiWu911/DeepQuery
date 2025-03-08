import asyncio
import os
import sys
import uvicorn
import logging
import websockets
import threading
import webbrowser
import websockets
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from services.websocket_handler import WebSocketHandler
from services.api_handler import APIRouterHandler
from services.chat_handler import ChatHandler
from services.log_handler import WebSocketLogHandler, StdoutLogger
from utils.tray_icon import run_tray_icon
from config import *


tray_icon = None
server_task = None

base_dir = os.path.dirname(os.path.abspath(__file__))
static_folder = os.path.join(base_dir, 'static')
templates_folder = os.path.join(base_dir, 'templates')
templates = Jinja2Templates(directory=templates_folder)

# 创建FastAPI应用实例
app = FastAPI()

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory=static_folder), name="static")


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
ws_handler = WebSocketHandler(logger)
log_queue = ws_handler.log_queue

ws_log_handler = WebSocketLogHandler(log_queue)
api_handler = APIRouterHandler(app, logger, chat_handler, ws_handler, templates)

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
    api_handler = APIRouterHandler(app, logger, chat_handler, ws_handler, templates)
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
        logger.info("[WebSocket] Server started at ws://localhost:8765")
        
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
            await ws_server.close()
            await server.shutdown()
            
    # 清理托盘图标
    if tray_icon:
        tray_icon.stop()
