# Agent_head — Main Autonomous Orchestrator

The **orchestrator agent** for the `orchestra` system. Coordinates multiple specialist **Worker Agents** (Agent_a-style) and direct MCP tool servers via a single LangGraph ReAct loop.

```
orchestra/
├── Agent_a/        ← Worker Agent (template)
├── Agent_head/     ← YOU ARE HERE — Orchestrator
│   ├── config.yaml         orchestration config
│   ├── main.py             entry point
│   └── core/
│       ├── agent.py        ReAct loop
│       ├── config_loader.py  typed config
│       └── job_logger.py   per-job logs
```

---

## Quick Start

```bash
# 1. Create virtual environment
cd Agent_head
uv venv .venv

# 2. Activate + install
.venv\Scripts\activate          # Windows
source .venv/bin/activate     # Linux/macOS
uv pip install -e .

# 3. Run interactive REPL
python main.py

# 4. Or run a single task
python main.py --task "List all Python files in Agent_a"
```

---

## Configuration (`config.yaml`)

### Agent settings

```yaml
agent:
  name: "OrchestratorAgent"
  system_prompt: |
    You are a powerful autonomous orchestrator...
  max_iterations: 50
```

### LLM (supports ollama / openai / gemini)

```yaml
model:
  provider: "ollama" # or "openai" / "gemini"
  model_name: "qwen3-coder:480b-cloud"
  temperature: 0.0
  base_url: "http://localhost:11434"
  # api_key: "sk-..."              # needed for openai/gemini
```

### Worker Agents (sub-agents)

Each worker is an Agent_a-style MCP subprocess. The orchestrator spawns it and uses its `execute_task` tool.

```yaml
worker_agents:
  - name: "agent_a"
    description: "General-purpose worker with shell tools."
    command: "D:\\path\\to\\Agent_a\\.venv\\Scripts\\python.exe"
    args: ["D:\\path\\to\\Agent_a\\main.py"]
```

### Direct MCP Tools (optional)

Any MCP server can be connected directly (no sub-agent loop):

```yaml
mcp_clients:
  - name: "filesystem"
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "D:/DEV"]
```

---

## CLI Reference

| Flag               | Description                                    |
| ------------------ | ---------------------------------------------- |
| `--task`, `-t`     | Single-shot task (non-interactive)             |
| `--config`, `-c`   | Path to custom config.yaml                     |
| `--model`, `-m`    | Override model name                            |
| `--provider`, `-p` | Override provider (`ollama`/`openai`/`gemini`) |
| `--api-key`        | Override API key                               |
| `--base-url`       | Override base URL                              |

```bash
# OpenAI example
python main.py --task "..." --provider openai --model gpt-4o --api-key sk-...

# Gemini example
python main.py --task "..." --provider gemini --model gemini-2.0-flash --api-key AIza...

# Custom config
python main.py --config /path/to/prod_config.yaml
```

---

## Adding More Workers

1. Clone `Agent_a` → rename (e.g. `Agent_code`)
2. Edit `Agent_code/config.yaml` with its own prompt, model, and tools
3. Add it to `Agent_head/config.yaml`:

```yaml
worker_agents:
  - name: "agent_a"
    command: "...Agent_a\\.venv\\Scripts\\python.exe"
    args: ["...Agent_a\\main.py"]
  - name: "agent_code"
    description: "Code generation specialist."
    command: "...Agent_code\\.venv\\Scripts\\python.exe"
    args: ["...Agent_code\\main.py"]
```

The orchestrator LLM automatically picks the right worker based on the task.

---

## Logs

Every job writes a structured log to `logs/jobs/YYYY-MM-DD_HH-MM-SS_<id>.log`.  
Logs capture: worker connections, LLM turns, tool calls, tool results, and the final answer.
