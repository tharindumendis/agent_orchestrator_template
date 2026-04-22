# Agent_head — Main Autonomous Orchestrator

**Agent_head** is the central orchestrator agent for the `orchestra` multi-agent system. It coordinates multiple specialized **Worker Agents** and direct MCP (Model Context Protocol) tool servers through a unified LangGraph ReAct loop. This enables complex, multi-step tasks that require coordination across different domains and tools.

Agent_head can also natively run as an **MCP server itself** or as a **REST API Backend**, enabling you to build expansive agent networks spanning multiple orchestrators collaborating on heavy computation tasks.

---

## 📚 Documentation

Detailed system mechanics and configuration guides have been moved to dedicated documentation files:

- **[capabilities and User Guide](documentation.md)**: Explore the different operational modes, details on Multi-Agent brains, native tooling details, and `config.yaml` breakdowns.
- **[Technical Implementation](implementation.md)**: Deep dive into the internal component architecture (LangGraph loop, summarizers, loading systems).

---

## What is Agent_head?

Agent_head acts as the highly-agile "brain" of your software interface:

- **Autonomous Execution**: Uses LangChain/LangGraph for reasoning and tool calling
- **Multi-Agent Coordination**: Spawns and delegates tasks to specialized worker agents
- **MCP Server Mode**: Expose the orchestrator as an MCP server for other agents/clients
- **Agent Networking**: Connect multiple Agent_head instances together with shared sessions
- **MCP Integration**: Connects to any MCP-compatible tool servers
- **Persistent Session History**: Full conversation archive in SQLite — never lost, even after summarisation
- **Memory & Context**: Maintains conversation history, facts, and auto-injects relevant context
- **Interactive & Batch Modes**: REPL interface or single-shot task execution
- **Rich Logging**: Per-job structured logs for debugging and auditing
- **API Server**: REST API with streaming SSE for programmatic access

## Architecture

```
                          ┌──────────────┐
                          │ Claude       │
                          │ Desktop /    │ ← External MCP clients
                          │ Cursor / etc │
                          └──────┬───────┘
                                 │ (MCP)
┌────────────────────────────────▼────────────────────────────────┐
│                        Agent_head                               │
│                    (Orchestrator + MCP Server)                  │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │ LangGraph    │  │   Memory     │  │   MCP Server          │  │
│  │ ReAct Agent  │  │   (RAG)      │  │   (8 tools exposed)   │  │
│  └──────────────┘  └──────────────┘  └───────────────────────┘  │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │ Summarizer   │  │  Sessions    │  │  Progress Streaming   │  │
│  │ (windowed)   │  │  (SQLite)    │  │  (SSE / ctx.info)     │  │
│  └──────────────┘  └──────────────┘  └───────────────────────┘  │
└────────────────────────────┬───────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
       ┌──────▼─────┐ ┌──────▼─────┐ ┌──────▼─────┐
       │  Worker    │ │  Worker    │ │   MCP      │
       │  Agent A   │ │  Agent B   │ │  Tools     │ ← filesystem, search, etc.
       │  (Agent_a) │ │  (Agent_a) │ │  (direct)  │
       └────────────┘ └────────────┘ └────────────┘

       ┌──────────────────────────────────────────┐
       │         Agent Network (optional)          │
       │                                          │
       │  Agent_head ◄──SSE/HTTP──► Agent_head    │
       │      ↕                        ↕          │
       │  Agent_head ◄──stdio──► Agent_head       │
       │                                          │
       │  Shared sessions, multi-agent identity   │
       └──────────────────────────────────────────┘
```

### Key Components

| File | Purpose |
|------|---------|
| `main.py` | CLI entry point — REPL, single-shot, session management |
| `api/server.py` | FastAPI REST + SSE server |
| `core/mcp_server.py` | MCP server mode (8 tools exposed) |
| `core/config_loader.py` | Typed configuration loading |
| `core/mcp_loader.py` | MCP client/server connection management |
| `core/memory.py` | Long-term memory backends |
| `core/conversation_summarizer.py` | Rolling history compression (windowed) |
| `core/history.py` | Abstract session history backend interface |
| `core/history_sqlite.py` | SQLite session persistence (working copy + full archive) |
| `core/llm.py` | LLM provider factory |
| `core/image_tools.py` | Image read / save / screenshot / OCR |
| `core/audio_tools.py` | Audio transcribe / TTS / record / play |
| `core/job_logger.py` | Structured per-job logging |
| `config.yaml` | Main configuration file |

## Features

- **Multi-Modal LLM Support**: Ollama, OpenAI, Google Gemini, Anthropic, AWS Bedrock, NVIDIA NIM
- **Worker Agent Delegation**: Automatic task routing to specialists
- **MCP Server Mode**: Expose the orchestrator as an MCP server with 8 tools
- **Agent Networking**: Connect multiple agents — shared sessions, identity tagging, supervisor monitoring
- **All MCP Transports**: stdio, SSE, and Streamable HTTP
- **Configurable Progress Streaming**: None / Summary / Full verbosity per call
- **Direct MCP Tools**: Filesystem, shell execution, web scraping, etc.
- **Memory System**: Fact storage and semantic search (RAG / ChromaDB)
- **Persistent Session History**: Two-layer SQLite storage — windowed working copy for the LLM, unabridged archive for debugging
- **Auto-Context Injection**: Relevant memory auto-fed to LLM before each turn
- **Rolling Summarisation**: Keeps the LLM context window bounded; full history still preserved in archive
- **Image & Audio Tools**: Screenshot, OCR, TTS, transcription, recording
- **Notification Listening**: Real-time tool-change monitoring via Agent_notify
- **Structured Logging**: Per-job logs with full traces
- **Graceful Error Handling**: Tool failures don't crash the agent

## Installation

### Prerequisites

- Python 3.10+
- `uv` package manager (recommended) or `pip`
- For Ollama: Running Ollama server with models pulled
- For OpenAI / Gemini / Anthropic: API keys configured

### Setup using UV

```bash
uv tool install --force git+https://github.com/tharindumendis/agent_orchestrator_template.git
```

### Setup via Source

```bash
# Clone the repo
git clone <repository-url>
cd agent_orchestrator_template

# Create virtual environment
uv venv .venv

# Activate environment (Windows)
.venv\Scripts\activate

# Install dependencies
uv sync

# Or with pip
pip install -e .
```

### Development Setup

```bash
uv sync --group dev
# Or
pip install -e ".[dev]"
```

## Configuration

Run the setup wizard to generate a config in the current directory:

```bash
agent-head --setup
```

This creates `.agents/config.yaml` which is auto-loaded on next run.  Edit it to configure models, workers, memory, etc.

### Agent Configuration

```yaml
agent:
  name: "OrchestratorAgent"
  version: "1.0.0"
  debug: false         # true → writes full prompt/response logs to .agents/logs/runs/
  system_prompt: |
    You are a powerful autonomous orchestrator agent...
  max_iterations: 50
```

### Model Configuration

```yaml
model:
  provider: "ollama"   # "ollama" | "openai" | "gemini" | "anthropic" | "bedrock" | "nvidia"
  model_name: "qwen3:32b"
  temperature: 0.0
  base_url: "http://localhost:11434"   # Ollama only
  api_key: ""                          # OpenAI / Gemini / Anthropic
```

### Worker Agents

```yaml
worker_agents:
  - name: "core-agent"
    description: "General-purpose worker"
    command: "agent-mcp"
    args: []
    env:
      WORKER_AGENT_CONFIG: "./service_config/worker_config.yaml"
```

### Direct MCP Clients

```yaml
mcp_clients:
  - name: "filesystem"
    command: "npx.cmd"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]

  - name: "shell"
    command: "npx.cmd"
    args: ["-y", "shell-exec-mcp"]
```

### Memory Configuration

```yaml
memory:
  enabled: true
  backend: "rag"           # "rag" (ChromaDB) or "jsonl"
  memory_dir: "./memory"
  max_save_length: 500
  auto_feed_top_k: 3       # chunks injected before each turn
  auto_feed_category: "all" # "all" | "history" | "facts"

  rag_server:
    command: "uvx"
    args: ["agent-rag-mcp"]
    env:
      RAG_CONFIG: "./service_config/rag_config.yaml"
```

### Chat History (Session Persistence)

```yaml
chat_history:
  backend: "sqlite"
  connection_string: "./session_db/sessions.db"
```

Two tables are maintained automatically:

| Table | Contents | Trimmed? |
|-------|----------|----------|
| `sessions` | Working copy — windowed slice fed to LLM | Yes (after summarisation) |
| `session_archive` | Full archive — every message ever sent | **Never** |

### Summarizer

```yaml
summarizer:
  enabled: true
  summarize_every_n_messages: 8   # compress after this many new Human+AI messages
  keep_recent_messages: 8         # keep this many raw messages for the LLM feed
  save_to_memory: true            # persist extracted facts to long-term memory

  model:                          # can be a lighter/cheaper model than the main LLM
    provider: "ollama"
    model_name: "qwen3:8b"
    temperature: 0
```

> **Note**: Summarisation only shrinks the *working copy* fed to the LLM.  The full unabridged conversation is always preserved in the `session_archive` table and accessible via `GET /history/sessions/{id}/full-export`.

## Usage

### Interactive REPL

```bash
agent-head
```
This command seamlessly creates the `.agents` hidden folder in your working directory and instantiates `config.yaml` alongside specialized agent configs, keeping your agent logic tightly bound to your project environment.

Starts an interactive prompt.  History is **always saved** — the session automatically resumes from where you left off.  Type `quit` or press Ctrl-C to exit.

### Session Modes

```bash
# Default — uses the "default" session, fully persistent
agent-head

# Named session — useful for keeping separate project contexts
agent-head --session my-project

# Ephemeral — no persistence, history is lost on exit
agent-head --session no
```

| Flag | Session ID | Persistence |
|------|-----------|-------------|
| *(none)* | `"default"` | ✅ Always saved |
| `--session myname` | `"myname"` | ✅ Always saved |
| `--session no` | *(none)* | ❌ Ephemeral, lost on exit |

### Running the Orchestrator

**Command Line Mode (REPL):**
```bash
agent-head --task "Analyse the codebase and suggest improvements"

# With a named session for memory continuity
agent-head --session myproject --task "Continue where we left off"
```

**Single-Shot Prompting:**
```bash
agent-head --config /path/to/custom_config.yaml
```

**MCP Provider Mode:**
```bash
# OpenAI
agent-head --provider openai --model gpt-4o --api-key sk-your-key

# Gemini
agent-head --provider gemini --model gemini-2.5-flash --api-key AIza...

# Ollama (local)
agent-head --provider ollama --model llama3.3:70b
```

### Export Config for Editing

```bash
# Export to current directory (.agents/ subfolder)
agent-head --setup

# Export to a specific project directory
agent-head --setup /path/to/my-project
```

### API Server

```bash
agent-api                          # http://0.0.0.0:8000
agent-api --port 9001
agent-api --config /path/to/config.yaml
```

#### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `GET` | `/sessions` | List live sessions |
| `POST` | `/sessions` | Create / resume a session |
| `GET` | `/sessions/{id}` | Session metadata |
| `DELETE` | `/sessions/{id}` | Clear session |
| `POST` | `/sessions/{id}/chat` | Send message → SSE stream |
| `POST` | `/sessions/{id}/shutdown` | Tear down agent (keep history) |
| `GET` | `/history/sessions` | List all saved session IDs |
| `GET` | `/history/sessions/{id}/export` | Export working-copy history (JSON) |
| `GET` | `/history/sessions/{id}/full-export` | Export **full archive** (JSON) — never trimmed |

#### SSE Event Types

```jsonc
{"type": "tool_call",   "name": "...", "args": {...}}
{"type": "tool_result", "name": "...", "content": "..."}
{"type": "token",       "content": "..."}   // intermediate AI text
{"type": "done",        "content": "..."}   // final answer
{"type": "error",       "content": "..."}   // something went wrong
```

### MCP Server Mode

Run Agent_head as an MCP server so other agents, Claude Desktop, or Cursor can connect:

```bash
# stdio transport (default — Claude Desktop, Cursor, other agent_mcp instances)
agent-mcp
agent-mcp --config /path/to/config.yaml

# SSE transport (LAN / internet agent networks)
agent-mcp --transport sse --port 9000 --host 0.0.0.0

# Streamable HTTP (modern MCP standard, production use)
agent-mcp --transport http --port 9000
```

**8 MCP tools exposed:**

| Tool | Description |
|------|-------------|
| `orchestrate_task` | One-shot task execution |
| `create_session` | Create or join a persistent session with agent identity |
| `chat` | Multi-turn conversation in a session |
| `list_sessions` | List all active sessions |
| `get_session_history` | Retrieve conversation history |
| `list_agents` | List configured workers & tools |
| `get_status` | Agent health + workload (for supervisors) |
| `close_session` | Tear down a session and persist history |

## Session History — How It Works

Agent_head uses a **two-layer storage model** so you never lose conversation history:

```
Every turn
  │
  ├─► append_to_archive()    ← PERMANENT — every message, never trimmed
  │
  ├─► save_session()         ← WORKING COPY — windowed slice for LLM input
  │
  └─► [if threshold hit] summarize()
        │
        └─► save_session(trimmed_history)   ← WORKING COPY shrinks
            (archive stays untouched)
```

On session resume:
- LLM is fed the **working copy** (summary + recent N messages)
- Full archive is available via `GET /history/sessions/{id}/full-export` for debugging

## Logs and Debugging

### Debug Mode

```yaml
# config.yaml
agent:
  debug: true
```

When enabled, every prompt fed to the LLM is written to `.agents/logs/runs/<session_id>.log`.

### Job Logs (MCP mode)

Each MCP task creates a structured log in the configured `log_dir`:

```
logs/mcp/jobs/
├── 2025-04-20_12-00-00_abc123.log
└── 2025-04-20_12-05-30_def456.log
```

### Session Debug Log (REPL mode)

```
.agents/logs/runs/
├── default.log          ← default session
├── my-project.log       ← --session my-project
└── 20250420_120530.log  ← ephemeral --session no
```

## Troubleshooting

### Worker agents not connecting

- Check paths / commands in `config.yaml`
- Ensure worker virtual environments are activated
- Verify the worker command is on PATH (e.g. `agent-mcp`)

### MCP tools failing

```bash
npx @modelcontextprotocol/server-filesystem --help   # verify install
```

- Check transport settings (stdio vs SSE vs HTTP)
- Look for port conflicts

### Memory not working

- Check ChromaDB installation: `pip show chromadb`
- Verify `memory/` directory has write permissions
- Ensure the RAG server command (`uvx agent-rag-mcp`) is installed

### History / archive not saving

- Confirm `chat_history.backend: "sqlite"` in config
- Check that `connection_string` path is writable
- Verify you are NOT using `--session no` (ephemeral disables persistence)

### Performance Tuning

- Lower `summarize_every_n_messages` to compress more aggressively
- Set `keep_recent_messages: 4-6` for smaller context windows
- Use a lighter model for the summarizer (separate `summarizer.model` config)
- Reduce `max_iterations` for faster single-turn responses

## Project Structure

```
Agent_head/
├── main.py                         # CLI entry point (REPL + single-shot)
├── api/
│   └── server.py                   # FastAPI REST + SSE server
├── core/
│   ├── agent.py                    # LangGraph ReAct agent
│   ├── mcp_server.py               # MCP server mode (8 tools)
│   ├── config_loader.py            # Typed config loading
│   ├── mcp_loader.py               # MCP client connections
│   ├── llm.py                      # LLM provider factory
│   ├── memory.py                   # Memory backends
│   ├── memory_rag.py               # RAG memory (ChromaDB)
│   ├── history.py                  # Abstract history backend
│   ├── history_sqlite.py           # SQLite: working copy + full archive
│   ├── conversation_summarizer.py  # Rolling history compression
│   ├── image_tools.py              # Image read/save/screenshot/OCR
│   ├── audio_tools.py              # Audio transcribe/TTS/record/play
│   ├── skill_loader.py             # Skills discovery and injection
│   └── job_logger.py               # Structured job logging
├── skills/                         # Skills directory (SKILL.md files)
├── docs/
│   └── mcp-server.md               # MCP server documentation
├── config.yaml                     # Default config
├── pyproject.toml                  # Package config
├── .agents/                        # Local project config (auto-created by --setup)
│   ├── config.yaml
│   ├── service_config/
│   ├── logs/runs/                  # Per-session debug logs
│   └── skills/                     # Project-local skills
├── memory/                         # Long-term memory storage
└── service_config/                 # Worker + service configs
```

## Development

### Adding New Features

- **New Tools**: Create a `@lc_tool` decorated function and add it to `all_tools` in `main.py` / `api/server.py` / `core/mcp_server.py`
- **New LLM Providers**: Add a branch in `core/llm.py`'s `get_llm()` factory
- **New Memory Backends**: Implement `ConversationHistoryBackend` in `core/history.py`
- **New Skills**: Create `skills/<name>/SKILL.md` — auto-discovered, no code changes needed

### Testing

```bash
pytest
pytest --cov=core --cov-report=html
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Submit a pull request

Code style: `black` formatting, PEP 8, type hints, docstrings.

## License

MIT License — see LICENSE file for details.

## Changelog

### v1.2.0

- **Full Session Archive**: Two-layer SQLite storage — `sessions` (windowed, LLM feed) + `session_archive` (append-only, never trimmed). Full history preserved even after summarisation.
- **`GET /history/sessions/{id}/full-export`**: New API endpoint to retrieve the complete, unabridged session conversation.
- **Default Session**: REPL now always persists — no `--session` flag defaults to `"default"` session. Use `--session no` for ephemeral (no persistence) mode.
- **System Prompt Guarantee**: System prompt is always position-0 in conversation history on resume, even if summarisation had previously trimmed it.
- **`mcp_server.py` Bug Fixes**: Fixed `datetime.now()` crash (was calling method on module, not class), fixed image tools loading inside `except` block (only loaded when memory failed), added archive support.
- **Anthropic / Bedrock Support**: Added provider support in `core/llm.py`.

### v1.1.0

- **MCP Server Mode**: Agent_head can now run as an MCP server (`agent-mcp`)
- **Agent Networking**: Multi-agent shared sessions with identity tagging
- **8 MCP Tools**: orchestrate_task, chat, create_session, list_sessions, get_session_history, list_agents, get_status, close_session
- **Configurable Progress Streaming**: none / summary / full verbosity
- **All MCP Transports**: stdio, SSE, Streamable HTTP
- **Image Tools**: read, save, screenshot, OCR
- **Audio Tools**: transcribe, TTS, save, record, play, speak

### v1.0.0

- Initial release
- Multi-agent orchestration
- MCP integration
- Memory system
- REST API
- Interactive REPL

---

For more information, see the [orchestra system documentation](https://github.com/tharindumendis/agent_orchestrator_template).
