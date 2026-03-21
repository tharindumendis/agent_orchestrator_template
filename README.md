# Agent_head — Main Autonomous Orchestrator

**Agent_head** is the central orchestrator agent for the `orchestra` multi-agent system. It coordinates multiple specialized **Worker Agents** (based on the Agent_a template) and direct MCP (Model Context Protocol) tool servers through a unified LangGraph ReAct loop. This enables complex, multi-step tasks that require coordination across different domains and tools.

## What is Agent_head?

Agent_head acts as the "brain" of your agent orchestra:

- **Autonomous Execution**: Uses LangChain/LangGraph for reasoning and tool calling
- **Multi-Agent Coordination**: Spawns and delegates tasks to specialized worker agents
- **MCP Integration**: Connects to any MCP-compatible tool servers
- **Memory & Context**: Maintains conversation history, facts, and auto-injects relevant context
- **Interactive & Batch Modes**: REPL interface or single-shot task execution
- **Rich Logging**: Per-job structured logs for debugging and auditing
- **API Server**: REST API for programmatic access

## Architecture

```
┌─────────────────┐
│   Agent_head    │ ← Main Orchestrator (this repo)
│                 │
│ ┌─────────────┐ │
│ │ LangGraph   │ │ ← ReAct Loop with all tools
│ │   Agent     │ │
│ └─────────────┘ │
│                 │
│ ┌─────────────┐ │ ← Memory System (SQLite + RAG)
│ │  Memory     │ │
│ │  (RAG)      │ │
│ └─────────────┘ │
│                 │
│ ┌─────────────┐ │ ← Conversation Summarizer
│ │ Summarizer  │ │
│ └─────────────┘ │
└─────────────────┘
         │
    ┌────┴────┐
    │         │
┌───▼───┐ ┌───▼───┐
│Worker │ │Worker │ ← Agent_a-style sub-agents
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

### Key Components

- **main.py**: Entry point with CLI and interactive REPL
- **core/agent.py**: LangGraph ReAct agent implementation
- **core/config_loader.py**: Typed configuration loading
- **core/mcp_loader.py**: MCP client/server connection management
- **core/memory.py**: Long-term memory with RAG (SQLite + ChromaDB)
- **core/conversation_summarizer.py**: Rolling conversation compression
- **core/session_manager.py**: Persistent chat sessions
- **api/server.py**: FastAPI REST server for external access
- **config.yaml**: Main configuration file

## Features

- **Multi-Modal LLM Support**: Ollama, OpenAI, Google Gemini
- **Worker Agent Delegation**: Automatic task routing to specialists
- **Direct MCP Tools**: Filesystem, Git, web scraping, etc.
- **Memory System**: Fact storage and semantic search
- **Conversation Persistence**: Resume sessions across runs
- **Auto-Context Injection**: Relevant memory fed to LLM
- **Notification Listening**: Real-time tool change monitoring
- **Structured Logging**: Job-specific logs with full traces
- **Colorized Output**: Rich console display (when supported)
- **Graceful Error Handling**: Tool failures don't crash the agent

## Installation

### Prerequisites

- Python 3.10+
- `uv` package manager (recommended) or `pip`
- For Ollama: Running Ollama server with models
- For OpenAI/Gemini: API keys

### Quick Setup

```bash
uv tool install --force git+https://github.com/tharindumendis/agent_orchestrator_template.git
```

```bash
# Clone the repo
git clone <repository-url>
cd agent_orchestrator_template

# Create virtual environment
uv venv .venv

# Activate environment
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

# Install dependencies
uv sync

# Or with pip
pip install -e .
```

### Development Setup

```bash
# Install dev dependencies
uv sync --group dev
# Or
pip install -e ".[dev]"
```

## Configuration

The main configuration is in `config.yaml`. Copy `config.yaml` and modify as needed.

### Agent Configuration

```yaml
agent:
  name: "OrchestratorAgent"
  version: "1.0.0"
  system_prompt: |
    You are a powerful autonomous orchestrator agent...
    [Detailed system prompt]
  max_iterations: 50
  debug: false # Enable debug logging
```

### Model Configuration

```yaml
model:
  provider: "ollama" # "ollama", "openai", "gemini"
  model_name: "qwen3-coder:480b-cloud"
  temperature: 0.0
  base_url: "http://localhost:11434" # For Ollama
  api_key: null # Required for OpenAI/Gemini
```

### Worker Agents

Configure sub-agents (Agent_a clones):

```yaml
worker_agents:
  - name: "agent_a"
    description: "General-purpose worker with shell and file tools"
    command: "python" # Or full path to executable
    args: ["path/to/agent_a/main.py"]
    env: # Optional environment variables
      SOME_VAR: "value"
```

### Direct MCP Clients

Connect MCP servers directly:

```yaml
mcp_clients:
  - name: "filesystem"
    transport: "stdio" # "stdio" or "sse"
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
    url: null # For SSE transport
```

### Memory Configuration

```yaml
memory:
  enabled: true
  backend: "rag" # "rag" or "sqlite"
  memory_dir: "memory"
  max_save_length: 10000
  rag_server:
    host: "localhost"
    port: 8000
  auto_feed_top_k: 5
  auto_feed_category: "all" # "all", "history", "facts"
```

### Chat History

```yaml
chat_history:
  backend: "sqlite" # "sqlite" only for now
  connection_string: "chat_history.db"
```

### Summarizer

```yaml
summarizer:
  enabled: true
  model: # Uses main model if not specified
    provider: "ollama"
    model_name: "qwen3-coder:32b"
  max_history_length: 100
  compression_ratio: 0.5
  save_to_memory: true
```

### Notification Server

```yaml
notify_server:
  enabled: true
  command: "python"
  args: ["path/to/agent_notify/main.py"]
  env: {}
```

## Usage

### Interactive REPL

```bash
python main.py
```

Starts an interactive prompt where you can enter tasks. Type "quit" to exit.

### Single-Shot Task

```bash
python main.py --task "Analyze the codebase and suggest improvements"
```

### Custom Configuration

```bash
python main.py --config path/to/custom_config.yaml
```

### Override Model at Runtime

```bash
# OpenAI
python main.py --provider openai --model gpt-4o --api-key sk-your-key

# Gemini
python main.py --provider gemini --model gemini-2.0-flash --api-key AIza...

# Ollama
python main.py --provider ollama --model llama3.2:70b
```

### Resume Session

```bash
python main.py --session my-session-id
```

### API Server

Start the REST API server:

```bash
python -m api.server
# Or
agent-api
```

API endpoints:

- `POST /task`: Execute a task
- `GET /health`: Health check

## Examples

### Basic Task

```
>> Task: List all Python files in the project
[Orchestrator] I'll help you find Python files...
[Tool Call] run_terminal_command
   command: find . -name "*.py" -type f
[Tool Result] run_terminal_command
   ./main.py
   ./core/agent.py
   ...
[Final Answer] Found 15 Python files in the project.
```

### Multi-Agent Coordination

```
>> Task: Create a new feature branch and implement user authentication
[Orchestrator] This requires Git operations and code changes. I'll delegate to the code specialist.
[Tool Call] execute_agent_code_task
   instruction: Create feature branch 'auth-feature' and implement basic auth
[Tool Result] execute_agent_code_task
   Branch created and auth implemented.
[Final Answer] Feature branch created with authentication implemented.
```

### Memory Usage

The agent automatically remembers facts and past tasks:

```
>> Task: What's the current project structure?
[Orchestrator] Let me check what I know about the project...
[~] Auto-injected 1200 chars of memory context.
[Final Answer] Based on previous analysis, the project has...
```

## Logs and Debugging

### Job Logs

Each task creates a log file in `logs/jobs/` with full execution trace:

```
logs/jobs/
├── 2024-01-15_14-30-45_task123.log
└── 2024-01-15_14-35-12_task124.log
```

### Debug Mode

Enable debug logging:

```yaml
agent:
  debug: true
```

Or set environment variable:

```bash
export AGENT_HEAD_DEBUG=1
python main.py
```

### Session Logs

For interactive sessions, logs are in `logs/runs/`:

```
logs/runs/
└── 2024-01-15_14-30-45_session123.log
```

## Troubleshooting

### Common Issues

**Worker agents not connecting:**

- Check paths in `config.yaml`
- Ensure worker virtual environments are activated
- Verify worker agents are running and listening

**MCP tools failing:**

- Check MCP server installation: `npx @modelcontextprotocol/server-filesystem --help`
- Verify transport settings (stdio vs sse)

**Memory not working:**

- Check ChromaDB installation
- Verify `memory/` directory permissions
- Ensure RAG server is running if using remote

**Colors not displaying:**

- On Windows, ensure terminal supports ANSI (use Windows Terminal)
- Colors are automatically disabled if not supported

### Performance Tuning

- Reduce `max_iterations` for faster responses
- Adjust `temperature` for more/less creativity
- Use smaller models for local execution
- Enable summarization to reduce context length

## Development

### Project Structure

```
agent_orchestrator_template/
├── main.py                 # CLI entry point
├── main_test.py           # Test runner
├── api/
│   └── server.py          # REST API
├── core/
│   ├── agent.py           # LangGraph agent
│   ├── config_loader.py   # Config parsing
│   ├── mcp_loader.py      # MCP connections
│   ├── memory.py          # Memory system
│   ├── session_manager.py # Chat persistence
│   └── conversation_summarizer.py
├── config.yaml            # Default config
├── pyproject.toml         # Package config
├── logs/                  # Runtime logs
├── memory/                # Memory storage
└── service_config/        # Service configs
```

### Adding New Features

1. **New Tools**: Add to `core/mcp_loader.py` or create custom tools
2. **New Memory Backends**: Implement in `core/memory.py`
3. **New Summarizers**: Extend `core/conversation_summarizer.py`

### Testing

```bash
# Run tests
pytest

# With coverage
pytest --cov=core --cov-report=html
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Submit a pull request

### Code Style

- Use `black` for formatting
- Follow PEP 8
- Add type hints
- Write docstrings

## License

MIT License - see LICENSE file for details.

## Changelog

### v1.0.0

- Initial release
- Multi-agent orchestration
- MCP integration
- Memory system
- REST API
- Interactive REPL

---

For more information, see the [orchestra system documentation](https://github.com/tharindumendis/agent_orchestrator_template).
