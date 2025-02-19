import json
from datetime import datetime
from flask import Flask, request, jsonify, render_template
import paramiko
import re

app = Flask(__name__)

# SSH连接参数
SSH_HOST = '192.168.182.124'
SSH_PORT = 22
SSH_USER = 'ywwu'
SSH_PASSWORD = 'wjswyw119'  # 如果使用私钥，则可以不填

# 用于存储对话历史
all_messages = [{"role": "system", "content": "You are a helpful assistant"}]
web_context = "" 

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/query', methods=['POST'])
def query():
    user_input = request.json.get('prompt').strip()
    selected_model = request.json.get('model', 'deepseek-r1:32b')  # 获取选择的模型，默认为 deepseek-r1:32b
    if not user_input:
        return jsonify({"error": "Prompt is required!"}), 400

    try:
        print(f"Received prompt: '{user_input}'")

        # 建立SSH连接
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(SSH_HOST, port=SSH_PORT, username=SSH_USER, password=SSH_PASSWORD)

        # 添加用户消息到对话历史
        all_messages.append({"role": "user", "content": user_input})

        # 构建 prompt
        prompt = f"[系统指令] 你是一个AI助手, 当前日期为{datetime.now().strftime('%Y-%m-%d')} \
以下是来自网络的实时信息片段(可能不完整): {web_context} [用户问题] {user_input} "
        print("prompt: ", prompt)
        
        command = f"""
        curl -s -X POST http://localhost:11434/api/generate \
        -H "Content-Type: application/json" \
        -d '{{"model": "{selected_model}", "prompt": "{prompt}",\
        "stream": false, "max_tokens": 2048, "temperature": 0.6, "top_p": 0.9,\
        "history":{json.dumps(all_messages)}}}'
        """
        
        print(f"Executing command: {command}")

        stdin, stdout, stderr = ssh.exec_command(command)

        # 获取执行结果
        response = stdout.read().decode()
        error = stderr.read().decode()

        ssh.close()

        if error:
            return jsonify({"error": error}), 500
        
#       print(f"Raw response from model: {response}")

        response_json = json.loads(response)
        generated_response = response_json.get("response", "")
#       print("generated_response: \n", generated_response)
        
        # 解析 <think> 标签
        parts = re.split(r'(<think>.*?</think>)', generated_response, flags=re.IGNORECASE | re.DOTALL)
        print(parts)
        think_content = ""
        for part in parts:
            if part.startswith('<think>') and part.endswith('</think>'):
                think_content = part[7:-8]  # 去掉 <think> 标签
                print("think_content: \n", think_content)
            elif part:
                ai_response = part.replace("\n", "").strip()
                print("ai_response: \n", ai_response)
        
        # 更新上下文
        all_messages.append({"role": "system", "content": ai_response})
        formatted_messages = json.dumps(all_messages, indent=4, ensure_ascii=False)
        print("formatted_messages: \n", formatted_messages)
        
        return jsonify({
            "response": generated_response
        })

    except Exception as e:
        print(f"An exception occurred: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0')