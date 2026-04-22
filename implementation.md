# Agent_head: Technical Implementation

This document dives deep into the internal mechanisms and specific file implementations of the **Agent_head** system. It is meant for developers aiming to extend, fork, or strictly debug the multi-agent orchestrator logic.

## 1. Core Components Breakdown

The system is highly modularized around the `core/` directory.

### `main.py`
The CLI gateway to the Agent_head platform. It loads environment variables, consumes `config.yaml`, parses CLI execution flags (`--setup`, `--task`, `--provider`), and initiates either the interactive console REPL or the background task processor. It orchestrates the connection to the `mcp_loader` and ties memory, tools, and the chat history into a persistent LangGraph loop.

### `core/agent.py` (The Brain)
Hosts the underlying `create_react_agent` logic utilizing `langgraph`. By parsing through the MCP configurations, it dynamically generates LangChain-compatible `ToolNode` instances. The agent relies heavily on an LLM capable of robust JSON-tool formatting to dictate looping logic until the desired goal resolves.

### `core/mcp_server.py` (The Engine Wrapper)
Allows `Agent_head` to run entirely inverted—acting as an MCP *server* instead of just a client.
It exposes eight high-level logical tools:
1. `orchestrate_task`
2. `create_session`
3. `chat`
4. `list_sessions`
5. `get_session_history`
6. `list_agents`
7. `get_status`
8. `close_session`
It hosts an event loop that accepts connections via either `stdio` pipes, `sse` over local bind network, or `http` fast routing. 

### `core/memory.py` & `core/memory_rag.py`
Handles persistence. If the system is connected to a Vector Database (e.g., ChromaDB via `agent-rag-mcp`), `memory_rag` connects over MCP to offload JSON document storage and queries. Before every LangGraph call, the RAG similarity search attempts to pull `k` relevant texts to inject directly into the context padding, drastically augmenting the intelligence of standalone inference steps.

### `core/conversation_summarizer.py`
Monitors the `chat_history`. Rather than infinitely appending the message array, the summarizer spins up an asynchronous parallel LLM call utilizing a (potentially lighter/cheaper) LLM model. It computes a unified state summary and extracts discrete factual objects to store persistently, dramatically reducing token-count bloats during prolonged debugging scenarios.

## 2. Communication Flows

Agent_head thrives heavily on process boundary communication. 

- **Worker Agent Delegation**: Worker agents are spawned as subprocesses. The orchestrator links to them primarily via `mcp stdio` transports. When a user queries the head orchestrator, LangGraph realizes a sub-agent's skillset applies. It packages the context bounds into a formatted JSON and invokes the Worker's `execute_task` tool. The main process halts its graph until the subprocess emits its JSON completion packet, and subsequently validates the response formatting.
- **Background Loading (`_run_stack`)**: Loading dozens of local models and tools dynamically can block resources. The `mcp_loader` operates a heavily guarded asynchronous `ExceptionGroup` stack to prevent one misconfigured MCP script from aborting the entire orchestrator startup logic. This creates a flexible tolerance grid for external crashes.

## 3. The Skills System

The skills system is a read-only dependency injector. Rather than explicitly hardcoding thousands of lines of prompt text, Agent_head looks into globally linked skills directories (typically `.agents/skills`).

It follows a precise loading pattern:
1. At startup, the loader sweeps the `skills_dirs` for valid `SKILL.md` manuals.
2. It generates a concise "Catalog" text array representing precisely *what* skills exist, leaving the actual file contents on the disk.
3. This condensed catalog is appended to the system prompt of the main agent.
4. If the agent recognizes a correlation to the prompt, it utilizes the `load_skill` tool to explicitly fetch the Markdown file buffer into context only when strictly necessary, maintaining high response agility and low token consumption at resting states.
