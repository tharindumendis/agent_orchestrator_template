# Agent Head Implementation Guide

## Overview

Agent Head is a sophisticated multi-agent orchestration system built with LangGraph and MCP (Model Context Protocol). When published as a Python package, it provides three main entry points for different use cases:

- `agent-head`: Interactive CLI orchestrator
- `agent-api`: REST API server with SSE streaming
- `agent-mcp`: MCP server for tool integration

## Architecture

```
┌─────────────────┐
│   Agent Head    │ ← Published Package
│                 │
│ ┌─────────────┐ │
│ │ LangGraph   │ │ ← Core orchestration engine
│ │   Agent     │ │
│ └─────────────┘ │
│                 │
│ ┌─────────────┐ │ ← Memory system (SQLite + ChromaDB)
│ │  Memory     │ │
│ │  (RAG)      │ │
│ └─────────────┘ │
└─────────────────┘
         │
    ┌────┴────┐
    │         │
┌───▼───┐ ┌───▼───┐
│Worker │ │Worker │ ← External MCP subprocesses
│Agent  │ │Agent  │
│  A    │ │  B    │
└───────┘ └───────┘
    │         │
┌───▼───┐ ┌───▼───┐
│ MCP   │ │ MCP   │ ← Direct MCP tool servers
│Server │ │Server │
│  X    │ │  Y    │
└───────┘ └───────┘
```

## Installation

After publishing to PyPI, users can install with:

```bash
pip install agent-head
# or
uv pip install agent-head
```

### Optional Dependencies

For development:

```bash
pip install agent-head[dev]
# or
uv pip install agent-head[dev]
```

## Entry Points

### 1. agent-head (CLI Orchestrator)

**Purpose**: Interactive command-line interface for running orchestration tasks.

**Usage**:

```bash
agent-head [OPTIONS]
```

**Options**:

- `--task TASK, -t TASK`: Run a single task non-interactively
- `--session SESSION, -s SESSION`: Resume/start persistent session
- `--config CONFIG, -c CONFIG`: Custom config file path
- `--model MODEL, -m MODEL`: Override model name
- `--provider PROVIDER, -p PROVIDER`: Override LLM provider (ollama/openai/gemini)
- `--api-key API_KEY`: API key override
- `--base-url BASE_URL`: Base URL override

**Examples**:

```bash
# Interactive mode
agent-head

# Single task
agent-head --task "Analyze the codebase and suggest improvements"

# Custom model
agent-head --provider openai --model gpt-4o --api-key sk-your-key

# Resume session
agent-head --session my-session-123
```

**How it works**:

1. Loads configuration from `config.yaml` (searches in current directory, then package data)
2. Initializes LangGraph agent with configured tools
3. Runs ReAct loop for task execution
4. Logs all steps to `logs/jobs/` and `logs/runs/`
5. Saves memory to configured backend

### 2. agent-api (REST API Server)

**Purpose**: FastAPI-based REST server with Server-Sent Events for real-time streaming.

**Usage**:

```bash
agent-api [OPTIONS]
```

**Options**:

- `--host HOST`: Bind host (default: 0.0.0.0)
- `--port PORT`: Bind port (default: 8000)
- `--config CONFIG`: Path to config.yaml
- `--reload`: Enable auto-reload (development only)

**API Endpoints**:

#### GET /health

Health check endpoint.

```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

#### GET /sessions

List all known session IDs.

```json
{
  "sessions": ["session-123", "session-456"]
}
```

#### POST /sessions

Create or resume a session.

```json
{
  "session_id": "new-session-123",
  "config": {
    "model": "gpt-4",
    "provider": "openai"
  }
}
```

#### GET /sessions/{session_id}

Get session metadata and message count.

```json
{
  "session_id": "session-123",
  "message_count": 15,
  "created_at": "2024-01-15T10:30:00Z",
  "last_activity": "2024-01-15T10:45:00Z"
}
```

#### DELETE /sessions/{session_id}

Clear session history.

#### POST /sessions/{session_id}/chat

Send a message and get SSE stream response.

```json
{
  "message": "Analyze this codebase",
  "stream": true
}
```

**SSE Events**:

```
event: tool_call
data: {"type": "tool_call", "name": "run_terminal", "args": {"command": "ls"}}

event: tool_result
data: {"type": "tool_result", "name": "run_terminal", "content": "file1.txt\nfile2.txt"}

event: token
data: {"type": "token", "content": "The analysis shows"}

event: done
data: {"type": "done", "content": "Complete analysis result"}
```

#### POST /sessions/{session_id}/shutdown

Tear down the live agent for a session.

**How it works**:

1. Starts FastAPI server with CORS enabled
2. Manages session state in memory (configurable backend)
3. Routes requests to orchestrator agent
4. Streams responses via SSE
5. Provides OpenAPI docs at `/docs`

### 3. agent-mcp (MCP Server)

**Purpose**: MCP server exposing the orchestrator as a tool for other MCP clients.

**Usage**:

```bash
agent-mcp [OPTIONS]
```

**Options**:

- `--transport {stdio,sse,http}`: Transport protocol (default: stdio)
- `--host HOST`: Host for network transports (default: 127.0.0.1)
- `--port PORT`: Port for network transports (default: 8000)

**Transport Modes**:

#### stdio (Default)

For subprocess integration:

```bash
agent-mcp
```

#### SSE

For legacy SSE endpoints:

```bash
agent-mcp --transport sse --port 8001
```

#### HTTP (Streamable)

For modern HTTP streaming:

```bash
agent-mcp --transport http --port 8002
```

**MCP Tools Exposed**:

#### orchestrate_task

Execute a high-level task using the agent orchestrator.

**Parameters**:

- `task` (string, required): Natural language task description
- `session_id` (string, optional): Session ID for memory continuity

**Example**:

```json
{
  "method": "tools/call",
  "params": {
    "name": "orchestrate_task",
    "arguments": {
      "task": "Research quantum computing and write a summary",
      "session_id": "research-session-1"
    }
  }
}
```

**How it works**:

1. Uses FastMCP framework for MCP protocol handling
2. Exposes `orchestrate_task` tool that calls the core agent
3. Supports stdio, SSE, and HTTP transports
4. Loads configuration from environment/package defaults

## Configuration

### Config File (config.yaml)

The package includes a default `config.yaml` that users can override:

```yaml
agent:
  name: "OrchestratorAgent"
  version: "1.0.0"
  system_prompt: |
    You are a powerful autonomous orchestrator agent...
  max_iterations: 50
  debug: false

model:
  provider: "ollama"
  model_name: "qwen3-coder:32b"
  temperature: 0.0
  base_url: "http://localhost:11434"
  api_key: null

worker_agents:
  - name: "agent_a"
    description: "General-purpose worker"
    command: "python"
    args: ["path/to/agent_a/main.py"]
    env: {}

mcp_clients:
  - name: "filesystem"
    transport: "stdio"
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    url: null

memory:
  enabled: true
  backend: "rag"
  memory_dir: "memory"
  max_save_length: 10000
  rag_server:
    host: "localhost"
    port: 8000
  auto_feed_top_k: 5
  auto_feed_category: "all"

chat_history:
  backend: "sqlite"
  connection_string: "chat_history.db"

summarizer:
  enabled: true
  model:
    provider: "ollama"
    model_name: "qwen3-coder:32b"
  max_history_length: 100
  compression_ratio: 0.5
  save_to_memory: true

notify_server:
  enabled: true
  command: "python"
  args: ["path/to/agent_notify/main.py"]
  env: {}
```

### Environment Variables

- `ORCHESTRATOR_CONFIG`: Path to custom config file
- `AGENT_HEAD_DEBUG`: Enable debug logging (set to "1")

## Data Directories

When installed, the package creates these directories in the working directory:

- `logs/jobs/`: Job execution logs
- `logs/runs/`: Interactive session logs
- `memory/`: Long-term memory storage
- `service_config/`: Configuration files

## Dependencies

### Core Dependencies

- `langchain>=0.3.0`: LLM framework
- `langgraph>=0.2.0`: Agent orchestration
- `mcp>=1.0.0`: Model Context Protocol
- `fastapi>=0.110.0`: REST API framework
- `uvicorn>=0.29.0`: ASGI server

### Optional Providers

- `langchain-openai>=0.1.0`: OpenAI integration
- `langchain-google-genai>=1.0.0`: Google Gemini
- `langchain-ollama>=0.2.0`: Ollama integration

## Integration Examples

### As CLI Tool

```bash
# Install
pip install agent-head

# Configure
cp config.yaml my_config.yaml
# Edit my_config.yaml with your settings

# Run
agent-head --config my_config.yaml --task "Build a web scraper"
```

### As API Service

```bash
# Start server
agent-api --port 8080

# Use from another application
curl -X POST http://localhost:8080/sessions \
  -H "Content-Type: application/json" \
  -d '{"session_id": "test"}'

curl -X POST http://localhost:8080/sessions/test/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello world"}'
```

### As MCP Tool

```bash
# Start MCP server
agent-mcp --transport http --port 8002

# Connect from MCP client
# The server will be available at http://localhost:8002/mcp
```

### In Python Code

```python
from agent_head.core.agent import run_orchestrator
from agent_head.core.config_loader import load_config

config = load_config("my_config.yaml")
result = run_orchestrator("Analyze this code", config)
print(result)
```

## Logging and Monitoring

### Job Logs

Each orchestration run creates:

- `logs/jobs/YYYY-MM-DD_HH-MM-SS_jobid.log`: Detailed execution trace
- Memory updates in configured backend

### Session Logs

Interactive sessions log to:

- `logs/runs/YYYY-MM-DD_HH-MM-SS_sessionid.log`: Full conversation

### Debug Mode

Enable with `--debug` flag or `AGENT_HEAD_DEBUG=1` environment variable.

## Security Considerations

- API server includes CORS middleware (configurable origins)
- MCP server supports authentication via MCP protocol
- Sensitive data should be stored in secure config files
- API keys should use environment variables

## Performance Tuning

- Adjust `max_iterations` for complex tasks
- Configure memory backend based on use case
- Use appropriate LLM model for task complexity
- Monitor memory usage for long-running sessions

## Troubleshooting

### Common Issues

1. **"No tools available"**
   - Configure `worker_agents` or `mcp_clients` in config
   - Ensure external MCP servers are running

2. **LLM API errors**
   - Check API keys and endpoints
   - Verify model availability

3. **Memory errors**
   - Check disk space for memory directory
   - Verify ChromaDB configuration

4. **MCP connection failures**
   - Test MCP server connectivity separately
   - Check transport configurations

### Debug Commands

```bash
# Test MCP server
agent-mcp --transport stdio 2>&1 | head -20

# Test API server
agent-api --reload &
curl http://localhost:8000/health

# Test CLI with debug
AGENT_HEAD_DEBUG=1 agent-head --task "echo hello"
```

## Development vs Production

### Development

- Use `--reload` flag for API server
- Enable debug logging
- Use local Ollama instance
- Test with small models

### Production

- Use production LLM providers (OpenAI, Gemini)
- Configure proper memory backends
- Set up monitoring and logging
- Use reverse proxy for API server
- Configure authentication

## Version Compatibility

- Python 3.10+
- MCP protocol v1.0+
- LangChain v0.3+
- FastAPI 0.110+

## Contributing

When extending the published package:

1. Maintain backward compatibility
2. Update configuration schema
3. Add comprehensive tests
4. Update this documentation
5. Follow semantic versioning

## License

MIT License - see package metadata for details.</content>
<parameter name="filePath">d:\DEV\mcp\universai\agent_orchestrator_template\implementation.md
