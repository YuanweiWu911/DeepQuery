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
