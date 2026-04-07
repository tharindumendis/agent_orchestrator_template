# Agent_head — MCP Server Mode

Run Agent_head as an MCP server so other agents, Claude Desktop, Cursor, or any MCP client can connect and use the orchestrator's full capabilities as tools.

## Quick Start

```bash
# Install (if not already installed)
uv tool install --force git+https://github.com/tharindumendis/agent_orchestrator_template.git

# Run as MCP server (stdio — default)
agent-mcp

# Run with a custom config
agent-mcp --config /path/to/config.yaml
```

## Transports

Agent_head supports all three MCP transports:

### stdio (default)

Used when the MCP server is spawned as a subprocess by a parent client (Claude Desktop, Cursor, another Agent_head).

```bash
agent-mcp
agent-mcp --config ./config.yaml
```

### SSE (Server-Sent Events)

Used for network agent-to-agent communication over LAN or internet.

```bash
agent-mcp --transport sse --host 0.0.0.0 --port 9000
```

### Streamable HTTP

The modern MCP standard for production deployments.

```bash
agent-mcp --transport http --host 0.0.0.0 --port 9000
```

## CLI Options

```
agent-mcp [OPTIONS]

Options:
  --transport {stdio,sse,http}  Transport mode (default: stdio)
  --host HOST                   Host for SSE/HTTP (default: from config or 127.0.0.1)
  --port PORT                   Port for SSE/HTTP (default: from config or 8000)
  --config, -c PATH             Path to a custom config.yaml
  --help                        Show help
```

## Tools Exposed

When running as an MCP server, Agent_head exposes **8 tools**:

### `orchestrate_task`

One-shot task execution. The orchestrator breaks down the task, delegates to worker agents and MCP tool servers, and returns the final result.

```
Parameters:
  task       (str, required)   — Natural-language description of the task
  session_id (str, optional)   — Session ID for memory continuity
  progress   (str, optional)   — "none" | "summary" | "full"
```

**Example**: A calling agent sends `orchestrate_task(task="Summarize all Python files in the project")` and receives the final summary.

### `create_session`

Create a new persistent session or join an existing one. Sessions enable multi-turn conversations and multi-agent collaboration.

```
Parameters:
  session_id (str, required)   — Unique session identifier
  agent_name (str, optional)   — Identity of the joining agent
  purpose    (str, optional)   — Description of what this session is for
```

**Example**: `create_session(session_id="collab-001", agent_name="Supervisor", purpose="Research project")`

### `chat`

Multi-turn conversation in a persistent session. Messages from different agents are tagged with their identity.

```
Parameters:
  session_id (str, required)   — The session to chat in
  message    (str, required)   — The message to send
  agent_name (str, optional)   — Identity of the sending agent
  progress   (str, optional)   — "none" | "summary" | "full"
```

**Example**: `chat(session_id="collab-001", message="I found 5 papers on quantum ML", agent_name="Researcher")`

### `list_sessions`

List all active sessions with metadata (session_id, participants, message count, timestamps).

```
Parameters: none
```

### `get_session_history`

Retrieve conversation history for a session.

```
Parameters:
  session_id (str, required)   — The session to retrieve history for
  last_n     (int, optional)   — Only return the last N messages (0 = all)
```

### `list_agents`

List all configured worker agents and MCP tool servers from config.

```
Parameters: none
```

### `get_status`

Get agent health, workload, and capacity information. Essential for supervisor agents that need to assess an agent's state before assigning tasks.

```
Parameters: none
```

Returns: agent name/version, model info, active sessions, busy sessions count, configured workers and tools.

### `close_session`

Tear down a session. Persists conversation history and frees resources. The session can be resumed later by creating a new session with the same ID.

```
Parameters:
  session_id (str, required)   — The session to close
```

## Configuration

Add the `mcp_server` section to your `config.yaml`:

```yaml
mcp_server:
  name: "agent-orchestrator"     # MCP server identity name
  host: "127.0.0.1"             # bind host for SSE/HTTP transports
  port: 8000                    # bind port for SSE/HTTP transports
  default_progress: "summary"   # "none" | "summary" | "full"
```

### Progress Streaming Levels

| Level | What gets streamed via `ctx.info()` | Use Case |
|-------|-------------------------------------|----------|
| `none` | Nothing — only the final answer is returned | Simple one-shot callers |
| `summary` | Tool call names + success/failure status | Lightweight monitoring |
| `full` | Tool calls with args, results, intermediate LLM text | Supervisor/debugger agents |

Progress level can be configured:
1. **Per-call**: Pass `progress="full"` to any tool call
2. **Server default**: Set `default_progress` in config.yaml

## Connecting to Agent_head

### From Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "orchestrator": {
      "command": "agent-mcp",
      "args": ["--config", "D:/path/to/config.yaml"]
    }
  }
}
```

### From Cursor

Add to your Cursor MCP settings:

```json
{
  "mcpServers": {
    "orchestrator": {
      "command": "agent-mcp",
      "args": ["--config", "D:/path/to/config.yaml"]
    }
  }
}
```

### From Another Agent_head (as worker agent)

In the parent orchestrator's `config.yaml`:

```yaml
mcp_clients:
  - name: "helper-agent"
    command: "agent-mcp"
    args:
      - --config
      - D:/path/to/helper_config.yaml
```

### Over Network (SSE)

Start the server:

```bash
agent-mcp --transport sse --host 0.0.0.0 --port 9000 --config ./config.yaml
```

Connect from another agent:

```yaml
mcp_clients:
  - name: "remote-orchestrator"
    transport: "sse"
    url: "http://192.168.1.10:9000/sse"
```

### Over Network (Streamable HTTP)

Start the server:

```bash
agent-mcp --transport http --host 0.0.0.0 --port 9000 --config ./config.yaml
```

Connect from another agent:

```yaml
mcp_clients:
  - name: "remote-orchestrator"
    transport: "http"
    url: "http://192.168.1.10:9000/mcp"
```

## Building Agent Networks

Agent_head's MCP server mode enables building sophisticated agent networks where multiple orchestrators connect to each other.

### Multi-Agent Shared Sessions

Multiple agents can join the same session. Messages are tagged with agent identity so the orchestrator LLM can distinguish who said what:

```
Supervisor  → create_session("project-x", agent_name="Supervisor", purpose="Build feature X")
Researcher  → chat("project-x", "Found relevant papers on the topic", agent_name="Researcher")
Coder       → chat("project-x", "Implemented the algorithm from paper #3", agent_name="Coder")
Supervisor  → get_session_history("project-x")   → sees all messages tagged by agent
```

Inside the conversation history, messages appear as:

```
[Researcher]: Found relevant papers on the topic
[Coder]: Implemented the algorithm from paper #3
```

This prevents hallucination — the orchestrator LLM knows exactly which agent said what.

### Supervisor Pattern

A supervisor agent can monitor other agents using `get_status` and `get_session_history`:

```
Supervisor  → get_status()                              → check if agent is busy
Supervisor  → orchestrate_task("do X", progress="full") → watch every step via ctx.info()
Supervisor  → get_session_history("session-123")        → review what was done
```

### Hub-and-Spoke Topology

```
                    ┌──────────────┐
                    │  Supervisor  │
                    │  Agent_head  │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
       ┌──────▼─────┐ ┌───▼──────┐ ┌───▼──────┐
       │  Research   │ │  Code    │ │  Deploy  │
       │  Agent_head │ │  Agent   │ │  Agent   │
       └─────────────┘ └──────────┘ └──────────┘
```

Each Agent_head runs `agent-mcp`, and the supervisor connects to all of them:

```yaml
# supervisor config.yaml
mcp_clients:
  - name: "research-agent"
    command: "agent-mcp"
    args: ["--config", "./research_config.yaml"]

  - name: "code-agent"
    command: "agent-mcp"
    args: ["--config", "./code_config.yaml"]

  - name: "deploy-agent"
    command: "agent-mcp"
    args: ["--config", "./deploy_config.yaml"]
```

### Mesh Topology (SSE)

All agents connect to each other over the network:

```bash
# Agent 1 on machine A
agent-mcp --transport sse --port 9001 --config ./agent1.yaml

# Agent 2 on machine B
agent-mcp --transport sse --port 9002 --config ./agent2.yaml
```

Each agent's config references the other:

```yaml
# agent1.yaml
mcp_clients:
  - name: "agent2"
    transport: "sse"
    url: "http://machine-b:9002/sse"
```

## Testing with MCP Inspector

Use the official MCP Inspector to test your server interactively:

```bash
npx @modelcontextprotocol/inspector agent-mcp -- --config ./config.yaml
```

This opens a web UI where you can:
- See all 8 tools and their schemas
- Call tools interactively
- View progress notifications
- Test session creation and chat flows

## Troubleshooting

### Server won't start

- Check that `config.yaml` exists at the specified path
- Ensure all dependencies are installed: `uv sync`
- Check stderr output for error messages

### Tools not responding

- Verify worker agents are configured correctly in `config.yaml`
- Check that MCP tool servers (filesystem, etc.) are installed
- Use `list_agents()` to see what's configured

### Shared session confusion

- Always pass `agent_name` when multiple agents use the same session
- Each agent should use a unique, descriptive name
- Check session participants with `list_sessions()`

### Connection refused (SSE/HTTP)

- Check your firewall settings
- Verify `--host 0.0.0.0` is set for remote access (not `127.0.0.1`)
- Confirm the port is not already in use
