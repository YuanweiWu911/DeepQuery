# DeepQuery Web Interface

This project provides a web-based interface to interact with an AI model, utilizing a Flask backend for querying an LLM (Large Language Model) remotely via SSH.

![GUI Demo](Demo_DeepQuery.png) <!-- Replace with actual screenshot -->

## Features

- **User-Friendly Interface**: The web interface allows you to enter prompts, select AI models, and view AI responses in a clean format.
- **Real-Time AI Responses**: The system sends queries to a remote server and receives real-time responses from the AI model.
- **New Chat Functionality**: You can start a fresh conversation at any time.

## Requirements

- **Python 3.10.11: The application is built using Python 3 and the Flask framework.
- **Flask**: A micro web framework for Python.
- **Paramiko**: For SSH connection to a remote server.
- **A DeepSeek-R1 AI Model**: The system interacts with the DeepSeek-R1 AI model hosted on a remote server via an API.

## Setup

### Install Dependencies

1. Clone the repository or download the necessary files.
2. Install the required Python libraries by running:
   ```bash
   pip install -r requirements.txt
   ```
### Configuration

The project requires an SSH connection to a remote server for querying the AI model.

1. In the `config.json` file, fill in your SSH connection details:
   ```json
   {
     "SSH_HOST": "your_ssh_host",
     "SSH_PORT": 22,
     "SSH_USER": "your_ssh_username",
     "SSH_PASSWORD": "your_ssh_password"
   }
   ```

2. Ensure the remote server has the DeepSeek-R1 model running and accessible.

### Running the Application

1. Start the Flask application by running:
   ```bash
   python app.py
   ```

2. Open the web interface by visiting `http://127.0.0.1:5000/` in your browser.

### Windows system compile to exe file
```powershell
pyinstaller --add-data "templates;templates" --add-data "static;static" --add-data "icon.ico;." --onefile --name DeepQuery --icon=icon.ico DeepQuery.py
```
## Usage

1. **Prompt Input**: Enter your query in the text box and press **Enter** to send it.
2. **Model Selection**: Choose the desired AI model from the dropdown list (e.g., `deepseek-r1:32b`).
3. **View AI Response**: The AI's response will appear in the `AI Response` section. If the AI needs time to think, it will be indicated separately.

### New Chat

You can start a new chat at any time by clicking the **New Chat** button, which will reset the conversation context.

## Files

- **app.py**: The main Flask application that handles backend logic.
- **index.html**: The frontend interface for interacting with the backend.
- **config.json**: Configuration file for SSH and model settings.
- **requirements.txt**: Python dependencies for the project.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

# DeepQuery 网页界面

这个项目提供了一个基于网页的界面，用于与人工智能模型进行交互，利用 Flask 后端通过 SSH 远程查询大型语言模型（LLM）。

![GUI 演示](Demo_DeepQuery.png) <!-- 请替换为实际截图 -->

## 功能特点

- **用户友好的界面**：网页界面允许你输入提示信息，选择人工智能模型，并以清晰的格式查看人工智能的回复。
- **实时人工智能回复**：系统将查询发送到远程服务器，并从人工智能模型接收实时回复。
- **新的聊天功能**：你可以随时开始一段新的对话。

## 要求

- **Python 3.x**：该应用程序使用 Python 3 和 Flask 框架构建。
- **Flask**：一个 Python 的微型网络框架。
- **Paramiko**：用于与远程服务器建立 SSH 连接。
- **DeepSeek-R1 人工智能模型**：系统通过 API 与托管在远程服务器上的 DeepSeek-R1 人工智能模型进行交互。

## 安装设置

### 安装依赖项

1. 克隆存储库或下载必要的文件。
2. 运行以下命令安装所需的 Python 库：
   ```bash
   pip install -r requirements.txt
   ```

### 配置

该项目需要通过 SSH 连接到远程服务器以查询人工智能模型。

1. 在 `config.json` 文件中，填写你的 SSH 连接详细信息：
   ```json
   {
     "SSH_HOST": "你的 SSH 主机",
     "SSH_PORT": 22,
     "SSH_USER": "你的 SSH 用户名",
     "SSH_PASSWORD": "你的 SSH 密码"
   }
   ```

2. 确保远程服务器上的 DeepSeek-R1 模型正在运行并且可以访问。

### 运行应用程序

1. 运行以下命令启动 Flask 应用程序：
   ```bash
   python app.py
   ```

2. 在浏览器中访问 `http://127.0.0.1:5000/` 以打开网页界面。

### Windows 系统编译为 exe 文件
```powershell
pyinstaller --add-data "templates;templates" --add-data "static;static" --add-data "icon.ico;." --onefile --name DeepQuery --icon=icon.ico DeepQuery.py
```

## 使用方法

1. **提示信息输入**：在文本框中输入你的查询内容，然后按 **Enter** 键发送。
2. **模型选择**：从下拉列表中选择所需的人工智能模型（例如，`deepseek-r1:32b`）。
3. **查看人工智能回复**：人工智能的回复将显示在“人工智能回复”部分。如果人工智能需要时间思考，将会有单独的提示。

### 开始新的聊天

你可以随时点击“新的聊天”按钮开始一段新的聊天，这将重置对话上下文。

## 文件

- **app.py**：处理后端逻辑的主要 Flask 应用程序。
- **index.html**：用于与后端交互的前端界面。
- **config.json**：SSH 和模型设置的配置文件。
- **requirements.txt**：项目的 Python 依赖项。

## 许可证

本项目采用 MIT 许可证 - 有关详细信息，请参阅 [LICENSE](LICENSE) 文件。
