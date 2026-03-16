import os
import json

# 配置文件路径
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

# 从配置文件加载配置
def load_config():
    """从config.json加载配置，如果文件不存在则使用默认配置"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"无法加载配置文件: {e}")
        # 返回默认配置
        return {
            "SSH_CONFIG": {
                "HOST": os.getenv('SSH_HOST', ''),
                "PORT": int(os.getenv('SSH_PORT', 22)),
                "USER": os.getenv('SSH_USER', ''),
                "PASSWORD": os.getenv('SSH_PASSWORD', '')
            },
            "WEBSOCKET_PORT": 8765,
            "HTTP_PORT": 8000,
            "MODELS": [
                {"value": "deepseek-r1:1.5b", "name": "deepseek-r1:1.5b", "selected": False},
                {"value": "deepseek-r1:7b", "name": "deepseek-r1:7b", "selected": False},
                {"value": "deepseek-r1:32b", "name": "deepseek-r1:32b", "selected": False},
                {"value": "deepseek-r1:70b", "name": "deepseek-r1:70b", "selected": False},
                {"value": "qwq", "name": "qwq", "selected": True},
                {"value": "deepseek-r1:671b", "name": "deepseek-r1:671b", "selected": False}
            ],
            "WEB_SEARCH_CONFIG": {
                "SERPER_API_KEY": os.getenv('SERPER_API_KEY', '')
            },
            "SPEECH_RECOGNITION_CONFIG": {
                "PROVIDER": os.getenv("SPEECH_PROVIDER", "google"),
                "BAIDU_APP_KEY": os.getenv("BAIDU_APP_KEY", ""),
                "BAIDU_SECRET_KEY": os.getenv("BAIDU_SECRET_KEY", ""),
                "WHISPER_MODEL": os.getenv("WHISPER_MODEL", "small"),
                "WHISPER_DEVICE": os.getenv("WHISPER_DEVICE", "cuda"),
                "WHISPER_COMPUTE_TYPE": os.getenv("WHISPER_COMPUTE_TYPE", ""),
                "WHISPER_DOWNLOAD_ROOT": os.getenv("WHISPER_DOWNLOAD_ROOT", "")
            }
        }

# 加载配置
config = load_config()

# 导出配置变量，保持与原代码兼容
SSH_CONFIG = config["SSH_CONFIG"]
WEBSOCKET_PORT = config["WEBSOCKET_PORT"]
HTTP_PORT = config["HTTP_PORT"]
MODELS = config["MODELS"]
WEB_SEARCH_CONFIG = config["WEB_SEARCH_CONFIG"]
SPEECH_RECOGNITION_CONFIG = config.get("SPEECH_RECOGNITION_CONFIG", {"PROVIDER": "google"})

# 保存配置到文件
def save_config():
    """将当前配置保存到config.json文件"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"保存配置文件失败: {e}")
        return False
