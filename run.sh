#!/bin/bash

echo "🚀 Starting Agent Orchestrator..."
clear
echo "instaling python"
# for windows
winget install Python.Python.3.12
# for linux
sudo apt-get install python3.12

# 1. Start the Backend (Agent API) in the background
echo "installing dependencies..."
echo "Ollma instaling.."
curl -fsSL https://ollama.com/install.sh | bash
echo "Ollama server starting.."
ollama serve &
echo "Ollama signin..please login using provided url"
ollama signin
echo "Ollama emverding model instaling.. (this may take a while)"
ollama pull nomic-embed-text
echo "Ollama LLM model instaling.. (this may take a while)"
ollama pull qwen3.5:397b-cloud
clear

# curl -LsSf https://astral.sh/uv/install.sh | bash
# uv tool install git+https://github.com/tharindumendis/agent_orchestrator_template.git
echo "Starting Backend (uv)..."
uv run agent-head --setup -y
uv run agent-head &
uv run agent-mcp --port 8001&
uv run agent-api --port 8000& 

# 2. Navigate to frontend and start it
echo "Starting Frontend (npm)..."
cd ./frontend
npm install
npm run build
npm start