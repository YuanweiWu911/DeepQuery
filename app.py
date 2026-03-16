import asyncio
import os
import sys
import uvicorn
import logging
import websockets
import threading
import webbrowser
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from services.websocket_handler import WebSocketHandler
from services.api_handler import APIRouterHandler
from services.chat_handler import ChatHandler
from services.log_handler import WebSocketLogHandler, StdoutLogger
from utils.tray_icon import run_tray_icon

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
    from config import HTTP_PORT, WEBSOCKET_PORT
    bind_host = os.getenv("DEEPQUERY_BIND_HOST", "127.0.0.1")

    # 启动系统托盘图标（新线程）
    tray_thread = threading.Thread(target=run_tray_icon, daemon=True)
    tray_thread.start()

    # 配置服务器
    uvicorn_config = uvicorn.Config(app, host=bind_host, port=HTTP_PORT)
    server = uvicorn.Server(uvicorn_config)

    # 并行启动WebSocket和HTTP服务器
    async with websockets.serve(ws_handler.handle_ws, bind_host, WEBSOCKET_PORT) as ws_server:
        # 正确启动Uvicorn服务
        server_task = asyncio.create_task(server.serve())
        logger.info(f"[WebSocket] Server started at ws://{bind_host}:{WEBSOCKET_PORT}")
        
        if os.getenv("DEEPQUERY_AUTO_OPEN_BROWSER", "0") == "1":
            try:
                webbrowser.open(f'http://localhost:{HTTP_PORT}/')
            except Exception as e:
                logger.warning(f"[System] Failed to open browser: {e}")
        
        try:
            # 启动语音识别任务
            # 检查语音识别是否激活，并创建异步任务
            if api_handler.is_voice_active:
                voice_recognition_task = asyncio.create_task(
                    api_handler.start_voice_recognition()
                )
                setattr(api_handler, 'voice_task', voice_recognition_task)

            # 启动日志消费任务
            ws_task = asyncio.create_task(ws_handler.log_consumer())

            # 等待服务器任务完成
            await server_task

        except asyncio.CancelledError:
            logger.info("服务正常终止")
        finally:
            # 清理任务
            tasks_to_cancel = []
            
            if hasattr(api_handler, 'voice_task') and api_handler.voice_task:
                api_handler.voice_task.cancel()
                tasks_to_cancel.append(api_handler.voice_task)
            
            # ws_task is always created, so we can directly cancel it
            # Check if ws_task exists and is not done before cancelling
            # 检查ws_task是否存在且已定义
            if 'ws_task' in locals():
                try:
                    if ws_task and not ws_task.done() and not ws_task.cancelled():
                        ws_task.cancel()
                        tasks_to_cancel.append(ws_task)
                except Exception as e:
                    logger.error(f"[System] Error checking ws_task status: {e}")
                    # 尝试取消任务，即使状态检查失败
                    try:
                        ws_task.cancel()
                    except Exception:
                        pass
            
            # Clean up tasks with error handling
            if tasks_to_cancel:
                try:
                    await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
                except Exception as e:
                    logger.error(f"[System] Error during task cleanup: {e}")
                finally:
                    # Ensure all tasks are properly cleaned up
                    for task in tasks_to_cancel:
                        if not task.done():
                            task.cancel()
            
            # Gracefully close WebSocket server
            try:
                ws_server.close()  # WebSocket server的close()方法不是异步的，移除await
                logger.info("[WebSocket] Server closed successfully")
            except Exception as e:
                logger.error(f"[WebSocket] Error during server shutdown: {e}")
            await server.shutdown()
            
    # 清理托盘图标
    if tray_icon:
        tray_icon.stop()

# 在现有路由之后添加以下路由

@app.get('/get-config')
async def get_config(request: Request):
    """获取当前配置"""
    from config import config
    client_host = request.client.host if request.client else None
    if client_host not in ("127.0.0.1", "::1"):
        return JSONResponse(content={"error": "forbidden"}, status_code=403)

    safe_config = {
        **config,
        "SSH_CONFIG": {
            **config.get("SSH_CONFIG", {}),
            "PASSWORD": "",
        },
        "WEB_SEARCH_CONFIG": {
            **config.get("WEB_SEARCH_CONFIG", {}),
            "SERPER_API_KEY": "",
        },
        "SPEECH_RECOGNITION_CONFIG": {
            **config.get("SPEECH_RECOGNITION_CONFIG", {}),
            "BAIDU_APP_KEY": "",
            "BAIDU_SECRET_KEY": "",
        },
    }
    return safe_config

@app.post('/save-config')
async def save_config(request: Request):
    """保存配置"""
    try:
        client_host = request.client.host if request.client else None
        if client_host not in ("127.0.0.1", "::1"):
            return JSONResponse(content={"success": False, "message": "forbidden"}, status_code=403)

        new_config = await request.json()
        from config import config, save_config
        
        # 更新配置
        if "SSH_CONFIG" in new_config and isinstance(new_config["SSH_CONFIG"], dict):
            ssh_in = new_config["SSH_CONFIG"]
            ssh_existing = config.get("SSH_CONFIG", {})
            ssh_password = ssh_in.get("PASSWORD")
            ssh_merged = {**ssh_existing, **ssh_in}
            if ssh_password is None or str(ssh_password).strip() == "":
                if "PASSWORD" in ssh_existing:
                    ssh_merged["PASSWORD"] = ssh_existing.get("PASSWORD")
            config["SSH_CONFIG"] = {
                **ssh_merged,
            }
        if "WEBSOCKET_PORT" in new_config:
            config["WEBSOCKET_PORT"] = int(new_config["WEBSOCKET_PORT"])
        if "HTTP_PORT" in new_config:
            config["HTTP_PORT"] = int(new_config["HTTP_PORT"])
        if "WEB_SEARCH_CONFIG" in new_config and isinstance(new_config["WEB_SEARCH_CONFIG"], dict):
            web_in = new_config["WEB_SEARCH_CONFIG"]
            web_existing = config.get("WEB_SEARCH_CONFIG", {})
            serper_key = web_in.get("SERPER_API_KEY")
            web_merged = {**web_existing, **web_in}
            if serper_key is None or str(serper_key).strip() == "":
                if "SERPER_API_KEY" in web_existing:
                    web_merged["SERPER_API_KEY"] = web_existing.get("SERPER_API_KEY")
            config["WEB_SEARCH_CONFIG"] = {
                **web_merged,
            }

        if "SPEECH_RECOGNITION_CONFIG" in new_config and isinstance(new_config["SPEECH_RECOGNITION_CONFIG"], dict):
            speech_in = new_config["SPEECH_RECOGNITION_CONFIG"]
            speech_existing = config.get("SPEECH_RECOGNITION_CONFIG", {})
            speech_merged = {**speech_existing, **speech_in}

            baidu_app_key = speech_in.get("BAIDU_APP_KEY")
            if baidu_app_key is None or str(baidu_app_key).strip() == "":
                if "BAIDU_APP_KEY" in speech_existing:
                    speech_merged["BAIDU_APP_KEY"] = speech_existing.get("BAIDU_APP_KEY")

            baidu_secret_key = speech_in.get("BAIDU_SECRET_KEY")
            if baidu_secret_key is None or str(baidu_secret_key).strip() == "":
                if "BAIDU_SECRET_KEY" in speech_existing:
                    speech_merged["BAIDU_SECRET_KEY"] = speech_existing.get("BAIDU_SECRET_KEY")

            config["SPEECH_RECOGNITION_CONFIG"] = speech_merged
        
        # 保存配置
        if save_config():
            return {"success": True}
        else:
            return {"success": False, "message": "保存配置文件失败"}
    except Exception as e:
        return {"success": False, "message": str(e)}

if __name__ == "__main__":
    # 运行主函数
    import asyncio
    asyncio.run(main())
