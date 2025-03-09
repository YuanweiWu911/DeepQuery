import os

# 配置常量
SSH_CONFIG = {
    'HOST': os.getenv('SSH_HOST', '192.168.182.124'),
    'PORT': int(os.getenv('SSH_PORT', 22)),
    'USER': os.getenv('SSH_USER', 'ywwu'),
    'PASSWORD': os.getenv('SSH_PASSWORD', 'wjswyw119')
}

WEBSOCKET_PORT = 8765
HTTP_PORT = 8000

# 模型配置
MODELS = [
    {"value": "qwq", "name": "qwq", "selected": True},
    {"value": "deepseek-r1:1.5b", "name": "deepseek-r1:1.5b", "selected": False},
    {"value": "deepseek-r1:7b", "name": "deepseek-r1:7b", "selected": False},
    {"value": "deepseek-r1:32b", "name": "deepseek-r1:32b", "selected": False},
    {"value": "deepseek-r1:70b", "name": "deepseek-r1:70b", "selected": False},
    {"value": "deepseek-r1:671b", "name": "deepseek-r1:671b", "selected": False}
]
