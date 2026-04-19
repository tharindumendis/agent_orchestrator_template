#!/bin/bash

echo "🚀 Starting Agent Orchestrator..."

# 1. Start the Backend (Agent API) in the background
echo "Starting Backend (uv)..."
uv tool install --force ./
uv run agent-head --setup -y
uv run agent-api & 

# 2. Navigate to frontend and start it
echo "Starting Frontend (npm)..."
cd ./frontend
npm install
npm run build
npm start