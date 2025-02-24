# LLM Query Interface

This is a web application that provides an interface for querying the LLM (Large Language Model) remotely. It allows users to send queries, start new chats, and toggle the search function.

![GUI Demo](Demo_DeepQuery.png) <!-- Replace with actual screenshot -->

## Features

- **Model Selection**: Users can select different LLM models (`deepseek-r1:7b`, `deepseek-r1:32b`, `deepseek-r1:70b`) to use for querying.
- **Search Function**: There is a search toggle button that can be used to enable or disable the web search function. When enabled, relevant web search results will be included in the prompt sent to the LLM.
- **New Chat**: Users can start a new chat session, which clears the chat history and the response area.
- **Speech**: Users can enable or disable the speech function, which may be used to convert text to speech or vice versa depending on the implementation.
- **Reasoning**: There is a reasoning toggle button that can be used to enable or disable the reasoning feature. This could potentially be used to get more detailed and logical explanations from the LLM.
- **Load Chat**: Users can load a previously saved chat session from a JSON file.
- **Save Chat**: Users can save the chat content in two formats:
  - **JSON**: The chat messages are saved in a JSON file, which can be used to store the conversation history in a structured format.
  - **Markdown**: The AI response content can be saved as a Markdown file, which is useful for sharing or further processing.

## File Structure

- `index.html`: The main HTML file for the web interface.
- `styles.css`: The CSS file for styling the web interface.
- `DeepQuery.py`: The Python Flask application that handles the backend logic.
- `requirements.txt`: Python dependencies for the project.

## API Endpoints

- `/`: Returns the main HTML page.
- `/query`: Accepts POST requests with the query prompt, selected model, and search toggle status. It sends the query to the LLM and returns the response.
- `/new-chat`: Accepts POST requests to start a new chat session.
- `/web_search`: Accepts POST requests with the search query and returns the web search results.

## Windows system compile to exe file
```powershell
pyinstaller --add-data "templates;templates" --add-data "static;static" --add-data "icon.ico;." --onefile --name DeepQuery --icon=icon.ico DeepQuery.py
