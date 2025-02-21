import os
import json
from datetime import datetime
from flask import Flask, request, jsonify, render_template
import paramiko
import re
import webbrowser
import logging
import requests

# 配置日志记录
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

###################################################################
# 获取当前脚本所在的目录
base_dir = os.path.dirname(os.path.abspath(__file__))

# 构建静态文件和模板文件的路径
static_folder = os.path.join(base_dir, 'static')
template_folder = os.path.join(base_dir, 'templates')

# 创建 Flask 应用实例，并指定静态文件和模板文件的路径
app = Flask(__name__, static_folder=static_folder, template_folder=template_folder)

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

@app.before_request
def ignore_favicon():
    if request.path == '/favicon.ico':
        return '', 204

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/query', methods=['POST'])
def query():
    user_input = request.json.get('prompt').strip()
    logger.info(f"Received User message: {user_input}")

    selected_model = request.json.get('model', 'deepseek-r1:32b')
    logger.info(f"Use {selected_model} LLM model")

    is_search_on = request.json.get('search_toggle', False)  # 修改默认值为 False
    web_context = ""  # Default value when search is off

    # If search is on, call the web_search function
    if is_search_on:
        logger.info(f"web search User message: {user_input}")
        web_context = web_search(user_input)
    
    if not user_input:
        return jsonify({"error": "Prompt is required!"}), 400

    try:

        # 建立SSH连接
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(SSH_HOST, port=SSH_PORT, username=SSH_USER, password=SSH_PASSWORD)

        # 添加用户消息到对话历史
        all_messages.append({"role": "user", "content": user_input})

        # 构建 prompt
        prompt = f"""[系统指令] 你是一个AI助手, 当前日期为{datetime.now().strftime('%Y-%m-%d')} \
以下是来自网络的实时信息片段(可能不完整): {web_context} [用户问题] {user_input} """
#       print("prompt: ", prompt)
        
        # 构建请求数据
        data = {
            "model": selected_model,
            "prompt": prompt,
            "stream": False,
            "max_tokens": 2048,
            "temperature": 0.6,
            "top_p": 0.9,
            "history": all_messages
        }
        
        command = [
            "curl",
            "-s",
            "-X", "POST",
            "http://localhost:11434/api/generate",
            "-H", "\"Content-Type: application/json\"",
            "-d", f"\'{json.dumps(data)}\'"
        ]
    
#       print(f"Executing command: {' '.join(command)}")
        
        # 在 SSH 上执行命令
        stdin, stdout, stderr = ssh.exec_command(' '.join(command))

        # 获取执行结果
        response = stdout.read().decode()
        error = stderr.read().decode()

        ssh.close()

        if error:
            print(f"SSH command error: {error}")
            return jsonify({"error": error}), 500
        
        try:
            response_json = json.loads(response)
            generated_response = response_json.get("response", "")
#           print("generated_response: ", generated_response)
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            return jsonify({"error": f"JSON decode error: {e}"}), 500
        
        # 解析 <think> 标签
        parts = re.split(r'(<think>.*?</think>)', generated_response, flags=re.IGNORECASE | re.DOTALL)
        for part in parts:
            if part.startswith('<think>') and part.endswith('</think>'):
                think_content = part[7:-8]  # 去掉 <think> 标签
            elif part:
                ai_response = part.replace("\n", "").strip()
        if ai_response:
            logger.info("AI answer finished!")
        # 更新上下文
        all_messages.append({"role": "system", "content": ai_response})
        formatted_messages = json.dumps(all_messages, indent=4, ensure_ascii=False)
#       print("formatted_messages: \n", formatted_messages)
        
        return jsonify({
            "response": generated_response
        })

    except Exception as e:
        print(f"An exception occurred: {e}")
        return jsonify({"error": str(e)}), 500
@app.route('/new-chat', methods=['POST'])
def new_chat():
    global all_messages
    all_messages = [{"role": "system", "content": "You are a helpful assistant"}]
    return jsonify({"status": "success"})

# 新增 web_search 函数，用于进行网络搜索
# 如果需要作为路由函数，取消下面一行的注释
@app.route('/web_search', methods=['POST'])
def handle_web_search():
    prompt = request.json.get('prompt')
    search_result = web_search(prompt)
    return jsonify({"web_context": search_result})

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

if __name__ == "__main__":
    # 检查 SERPER_API_KEY 是否设置
    if os.getenv("SERPER_API_KEY") is None:
        logger.error("SERPER_API_KEY 未设置，请设置该环境变量后再运行程序。")
    else:
        webbrowser.open('http://127.0.0.1:5000/')
        app.run(debug=True, host='0.0.0.0')
