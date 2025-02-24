import os
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import json
import logging
import paramiko
import re
import requests
import shlex
import webbrowser
import asyncio
import websockets

###################################################################
# Get the directory where the current script is located
base_dir = os.path.dirname(os.path.abspath(__file__))

# Build the paths for static files and template files
static_folder = os.path.join(base_dir, 'static')
template_folder = os.path.join(base_dir, 'templates')

# Create a FastAPI application instance
app = FastAPI()

# Mount the static file directory
app.mount("/static", StaticFiles(directory=static_folder), name="static")  # New mount

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Read the configuration file
with open('~/.deepquery.config', 'r') as f:
    config = json.load(f)

# SSH connection parameters
SSH_HOST = config.get('SSH_HOST')
SSH_PORT = config.get('SSH_PORT')
SSH_USER = config.get('SSH_USER')
# Read the password from the configuration file
SSH_PASSWORD = config.get('SSH_PASSWORD')  # If using a private key, you can leave it blank

#
is_remote = False
# Used to store the conversation history
all_messages = [{"role": "system", "content": "You are a helpful assistant"}]

# Store WebSocket connections
connected_clients = set()

# WebSocket handler function
async def handle_ws(websocket, path=None):
    connected_clients.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        connected_clients.remove(websocket)

# Asynchronous function to start the WebSocket server
async def start_ws_server():
    server = await websockets.serve(handle_ws, "localhost", 8765)
    await server.wait_closed()

@app.get("/favicon.ico")
async def favicon():
    return FileResponse(os.path.join(base_dir, 'static', 'favicon.ico'), media_type='image/vnd.microsoft.icon')

@app.get("/")
async def index():
    with open(os.path.join(template_folder, 'index.html'), 'r', encoding='utf-8') as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.post("/query")
async def query(request: Request):
    global is_remote
    data = await request.json()
    user_input = data.get('prompt').strip()
    if not isinstance(user_input, (str, bytes)):
        logger.error(f"Unexpected data type for user_input: {type(user_input)}")
        return JSONResponse(content={"error": "Invalid user_input data type"}, status_code=400)
    else:
        # Add the user message to the conversation history
        all_messages.append({"role": "user", "content": user_input})
    
    logger.info(f"[User Message]: {user_input}")
    if is_remote:
        # Here you can add code to access the remote model via SSH
        logger.info('Accessing remote model via SSH')
    else:
        # Here you can add code to access the local model directly
        print('Accessing local model directly')
        logger.info('Accessing local model directly')

    selected_model = data.get('model', 'deepseek-r1:7b')
    logger.info(f"Use {selected_model} LLM model")

    is_search_on = data.get('search_toggle', False)  
    web_context = ""  # Default value when search is off

    # If search is on, call the web_search function
    if is_search_on:
        logger.info(f"[Web Search]: {user_input}")
        web_context = web_search(user_input)
        logger.info(f"[Search result]: {web_context}")
        if not isinstance(web_context, (str, bytes)):
            logger.error(f"Unexpected data type for web_context: {type(web_context)}")
            return JSONResponse(content={"error": "Invalid web_context data type"}, status_code=400)

    try:
        # Notify the front end to start executing the command
        for client in connected_clients:
            try:
                await client.send("start")
                logger.info("[Message Sent]: 'start' message to client")  # New log record
            except Exception as e:
                logger.error(f"Failed to send 'start' message: {e}")

        if is_remote:
           # Establish an SSH connection
           ssh = paramiko.SSHClient()
           ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
           ssh.connect(SSH_HOST, port=SSH_PORT, username=SSH_USER, password=SSH_PASSWORD)

        # Build the prompt
        prompt = f"""[System Instruction] You are an AI assistant. The current date is {datetime.now().strftime('%Y-%m-%d')}.
        The following is a real-time information snippet from the web (may be incomplete): {web_context} [User Question] {user_input} """
        print(f"prompt: {prompt}")
    
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
            "history": all_messages
        }
        data_json = json.dumps(data, ensure_ascii=False)
        if is_remote:
            command = [
                "curl",
                "-s",
                "-X", "POST",
                "http://localhost:11434/api/generate",
                "-H", "Content-Type: application/json",
                "-d", shlex.quote(data_json)
            ]
            logger.info("[Remote SSH]: " + ' '.join(command))
    
            # Execute the command on SSH
            stdin, stdout, stderr = ssh.exec_command(' '.join(command))
        
            # Get the execution result
            response = stdout.read().decode()
            error = stderr.read().decode()
        
            ssh.close()
            if '{"error":"unexpected EOF"}' in response:
                logger.error(f"SSH command error: {response}")
                return JSONResponse(content={"error": response}, status_code=500)
            if error:
                logger.error(f"SSH command error: {error}")
                return JSONResponse(content={"error": error}, status_code=500)
        
            try:
                response_json = json.loads(response)
                generated_response = response_json.get("response", "")
        
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                return JSONResponse(content={"error": f"JSON decode error: {e}"}, status_code=500)
    
        else:
            # Send the request directly to the local server
            logger.info(f"[Local Request] "+"http://localhost:11434/api/generate "+data_json)
            response = requests.post(
                "http://localhost:11434/api/generate",
                data=data_json
            )
            response.raise_for_status()
   
            response_text = response.text
            if '{"error":"unexpected EOF"}' in response_text:
                logger.error(f"HTTP request error: {response_text}")
                return JSONResponse(content={"error": response_text}, status_code=500)
    
            try:
                response_json = json.loads(response_text)
                generated_response = response_json.get("response", "")
    
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                return JSONResponse(content={"error": f"JSON decode error: {e}"}, status_code=500)

        # Parse the <think> tag
        parts = re.split(r'(<think>.*?</think>)', generated_response, flags=re.IGNORECASE | re.DOTALL)
        for part in parts:
            if part.startswith('<think>') and part.endswith('</think>'):
                think_content = part[7:-8]  # Remove the <think> tag
            elif part:
                ai_response = part.replace("\n", "").strip()
        if ai_response:
            logger.info(f"[AI response] {ai_response}")
        # Update the context
        all_messages.append({"role": "system", "content": ai_response})
        formatted_messages = json.dumps(all_messages, indent=4, ensure_ascii=False)
    
        # Notify the front end that the command execution is complete
        for client in connected_clients:
            await client.send("end")
    
        return JSONResponse(content={"response": generated_response})
    
    except Exception as e:
        logger.error(f"An exception occurred: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.post("/new-chat")
async def new_chat():
    global all_messages
    all_messages = [{"role": "system", "content": "You are a helpful assistant"}]
    return JSONResponse(content={"status": "success"})

# New load chat route
@app.post("/load-chat")
async def load_chat(request: Request):
    global all_messages
    data = await request.json()
    all_messages = data
    return JSONResponse(content=all_messages)

# New web_search function for web search
# If you need it as a route function, uncomment the following line
@app.post("/web_search")
async def handle_web_search(request: Request):
    data = await request.json()
    prompt = data.get('prompt')
    search_result = web_search(prompt)
    return JSONResponse(content={"web_context": search_result})

def web_search(prompt):
    """
    Execute a web search synchronously and return a list of the top 10 search result contents using the google.serper API.
    """
    api_key = os.getenv("SERPER_API_KEY")
    if api_key is None:
        logger.error("SERPER_API_KEY 未设置")
        return "未找到搜索结果"
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json"
    }
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
            return "find no searching result"
    except requests.RequestException as e:
        logger.error(f"RequestException: {e}")
        return f"RequestException: {str(e)}"
    except ValueError as e:
        logger.error(f"JSON error: {e}")
        return f"JSON error: {str(e)}"
    except Exception as e:
        logger.error(f"Unknown error: {e}")
        return f"unknown error: {str(e)}"

@app.get("/get-all-messages")
async def get_all_messages():
    global all_messages
    return JSONResponse(content=all_messages)

async def main():
    # Check if SERPER_API_KEY is set
    if os.getenv("SERPER_API_KEY") is None:
        logger.error("SERPER_API_KEY is not set. Please set this environment variable before running the program.")
    else:
        webbrowser.open('http://localhost:8000/')

        # Start the WebSocket server
        ws_server_task = asyncio.create_task(start_ws_server())

        # Start the FastAPI application
        import uvicorn
        config = uvicorn.Config(app, host='0.0.0.0', port=8000)
        server = uvicorn.Server(config)
        await server.serve()
        await ws_server_task

@app.post("/toggle-local-remote")
async def toggle_local_remote(request: Request):
    global is_remote
    data = await request.json()
    is_remote = data.get('isRemote')
    if is_remote:
        # Here you can add code to access the remote model via SSH
        logger.info('[Access] remote model via SSH')
    else:
        # Here you can add code to access the local model directly
        logger.info('[Access] local model directly')
    return JSONResponse(content={"status": "success"})

if __name__ == "__main__":
    asyncio.run(main())
