# DeepQuery Web Interface

This project provides a web-based interface to interact with an AI model, utilizing a Flask backend for querying an LLM (Large Language Model) remotely via SSH.

![GUI Demo](Demo_DeepQuery.png) <!-- Replace with actual screenshot -->

## Features

- **User-Friendly Interface**: The web interface allows you to enter prompts, select AI models, and view AI responses in a clean format.
- **Real-Time AI Responses**: The system sends queries to a remote server and receives real-time responses from the AI model.
- **New Chat Functionality**: You can start a fresh conversation at any time.

## Requirements

- **Python 3.x**: The application is built using Python 3 and the Flask framework.
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
