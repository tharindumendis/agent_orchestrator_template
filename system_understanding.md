# Agent Orchestrator Template - System Understanding

## 1. RAG System
The RAG (Retrieval-Augmented Generation) system provides long-term memory and contextual document retrieval.
- **Architecture**: It is implemented as an independent MCP server (`agent-rag-mcp`) communicating via `stdio` or [sse](file:///D:/DEV/mcp/universai/agent_orchestrator_template/api/server.py#463-466).
- **Configuration**: Managed via [service_config/rag_config.yaml](file:///D:/DEV/mcp/universai/agent_orchestrator_template/service_config/rag_config.yaml). It supports setting embedding providers (ONNX or Ollama with configurable models) and storing data in ChromaDB (`chroma_db` directory).
- **Directory Watching**: The RAG server can automatically watch specified directories (e.g., `./docs`) and re-ingest documents when they change, using the folder name as the collection name.
- **Integration**: The orchestrator (`Agent_head`) enables memory in [config.yaml](file:///D:/DEV/mcp/universai/agent_orchestrator_template/config.yaml) (`memory: backend: "rag"`). During an agent session, it dynamically registers [memory_search](file:///D:/DEV/mcp/universai/agent_orchestrator_template/main.py#281-293) and [memory_save](file:///D:/DEV/mcp/universai/agent_orchestrator_template/main.py#294-306) tools for the orchestrator to query and persist long-term facts.
- **Auto-Feed**: In the session chat generation, if the user message comes in, the orchestrator automatically searches the RAG backend and injects top K context chunks before the prompt.

## 2. Notification System
The notification system acts as a background relay for external events into the agent loop.
- **Architecture**: Implemented as the `agent-notification-mcp` service.
- **Configuration**: Configured via [service_config/notify_config.yaml](file:///D:/DEV/mcp/universai/agent_orchestrator_template/service_config/notify_config.yaml).
- **Operation**: The notification server connects to various MCP tool servers (like Telegram, GitHub, etc.) identically to how the standard orchestrator does. It then polls specific configured tools (e.g., `telegram_get_updates` or `list_issues`) at a set `poll_interval`.
- **Change Detection**: It maintains state between polls and compares the new result with the old result. When a diff is found, it streams the change as a JSON notification.
- **Integration**: The orchestrator connects to the notification server on startup. Detected changes are dynamically injected into the running REPL conversation as autonomous tasks for the agent to resolve without user prompting.

## 3. Session Management
Sessions provide persistence of the multi-turn agent interaction state.
- **Architecture**: The REST/SSE Server ([api/server.py](file:///D:/DEV/mcp/universai/agent_orchestrator_template/api/server.py)) maps each concurrent request to a dedicated [AgentSession](file:///D:/DEV/mcp/universai/agent_orchestrator_template/api/server.py#69-320) instance based on `session_id`.
- **Persistence**: Managed by [SessionManager](file:///D:/DEV/mcp/universai/agent_orchestrator_template/core/session_manager.py#10-66) ([core/session_manager.py](file:///D:/DEV/mcp/universai/agent_orchestrator_template/core/session_manager.py)) storing conversations as JSON-serialized Langchain message strings in SQLite (`sessions.db`). 
- **Graph and Tools**: For every session booted, a full connection to all Worker Agents and Direct MCP Clients is created. A unique Langgraph ReAct agent is created. 
- **Summarization**: To prevent the context window from overfilling, `ConversationSummarizer` compresses conversations every N messages, saving the new summary and derived facts (global or private) back to the session state and the RAG memory store. 
- **Concurrency**: Calling [chat](file:///D:/DEV/mcp/universai/agent_orchestrator_template/api/server.py#430-457) locks the specific session while the generation yields a real-time event stream (SSE) back to the caller.

## 4. Default Session
- The default session runs via a CLI REPL loop (typically in [main.py](file:///D:/DEV/mcp/universai/agent_orchestrator_template/main.py)). If no specific `session_id` is supplied by an API client, the orchestrator sets up a local interactive loop for testing and direct interaction. 
