# Agent_head: Full Documentation

Welcome to the full documentation for the **Agent_head** orchestrator template. This document outlines the broad capabilities, diverse operational modes, and setup instructions required to integrate and deploy the orchestrator system.

## 1. System Overview & Operational Modes

**Agent_head** acts as the central autonomous node of your intelligent application architecture. Built on LangChain/LangGraph, it operates a ReAct logic loop that coordinates specialized worker agents and direct MCP tools to resolve complex, multi-step queries.

Because flexibility is paramount, the orchestrator can operate seamlessly across three different modes:

- **CLI Tool / REPL (Interactive & Batch)**: 
  Run Agent_head directly in your terminal for single-shot task execution (`agent-head --task "..."`) or initiate an interactive prompt session to converse with the orchestrator.
- **MCP Server**: 
  Expose the entire Agent_head orchestrator as an MCP server with multiple built-in tools (orchestration, chats, agents listing, status) that can be plugged into Cursor, Claude Desktop, or connected to other parent agents. It supports `stdio`, `sse`, and `http` transports.
- **REST API Server**:
  Run a fully-featured FastAPI backend exposing session creation, health checks, and SSE real-time streaming endpoint to interact programmatically across your network. 

## 2. Capabilities

### LLM Integrations
Agent_head is fundamentally model-agnostic, providing robust support for multiple LLM ecosystems:
- **Ollama**: Seamlessly connect to your local or private clouds (e.g., Qwen, Llama3 models).
- **Anthropic / OpenAI**: Direct drop-in API support for enterprise reasoning models.
- **Bedrock**: Enterprise AWS integration for secure inference over Bedrock models.
- **Google Gemini**: Support for high-context fast synthesis with Gemini Flash/Pro.

### Flexible MCP Tooling Ecosystem
Agent_head heavily leverages the Model Context Protocol (MCP). Rather than hardcoding capabilities, you have complete developer flexibility to attach the tools you want:
- Connect `@modelcontextprotocol/server-filesystem` for workspace editing.
- Bring in Brave Search, GitHub, or Telegram MCPs out of the box.
- MCP Tools can be used and mixed exactly as the developer desires, acting as the fundamental interface to external software.

### Multi-Agent Workflows & Isolated Brains
One of the core features of Agent_head is delegating work down to **Worker Agents**. 
- **Role Specialization**: You can spin up dedicated worker agents that act as separate, localized "brains." 
- **Isolated Custom Prompts**: Provide a worker agent with its own API keys, its own system prompt, and a specific toolset. For instance, define a worker specifically tailored to handle secure payments, or another worker specialized heavily for searching and organizing personal filesystem resources. 
- The orchestrator intelligently breaks down tasks and delegates execution to these specialized brains, ensuring tasks aren't cross-contaminated and context windows stay highly relevant to the problem at hand.

### Native Sensory Tooling
The orchestrator includes several native interfaces enabled by configuration:
- **Image Tooling**: Read, modify, save, OCR, and execute desktop screenshotting.
- **Audio Tooling**: Take in audio streams, generate Text-To-Speech (TTS), execute Speech-to-Text (STT) transcriptions, and execute native recording functions.

### Persistent RAG Memory System
Agent_head includes two robust persistence layers:
- **Session History**: Ongoing REPL/Stream conversations are maintained permanently in a SQLite backend.
- **Rolling Conversational Summarization**: Long threads are actively compressed to prevent blowing up the LLM context window while selectively committing "facts" into memory.
- **RAG Backend**: A vector similarity search engine (e.g., ChromaDB optionally driven by `agent-rag-mcp`) stores long-term memory data and automatically pulls highly relevant context into the prompt before the model evaluates its next action.

### Asynchronous Notification System
Agent_head can stay aware of external environmental changes via the **notify_server** (`agent-notification-mcp`). By running in the background, this server:
- Polls predefined MCP servers for state changes or events.
- Automatically streams events as push notifications back to the orchestrator.
- Injects changes intelligently into the REPL loop or alerts the busy agent when spontaneous action or reaction is required.

## 3. Setup and Initialization

To bootstrap a new intelligent environment, you no longer need to manually copy code or configs. The Agent_head suite introduces a powerful automated setup command that provisions hidden project configurations in the current directory.

```bash
# Example setup workflow inside an empty directory
mkdir my-ai-project
cd my-ai-project

# Initialize the configuration space
agent-head --setup
```

This command automatically generates a localized `.agents` hidden folder containing your `config.yaml` and default `service_config/` setups. By doing so, you can easily version control your configurations locally while utilizing the identical global binary of Agent_head.

## 4. Configuration Schema (`config.yaml`)

Your localized `config.yaml` dictates the operational limits and tooling of that specific project space. 

Key nodes in the configuration:
- `agent`: Dictates fundamental metadata and the master system prompt given to the orchestrator.
- `model`: Defines the LLM provider, API keys, endpoints, and generation parameters.
- `worker_agents`: A list of specialized sub-agent definitions (e.g., payment handlers, research handlers), identifying them by their respective startup commands and specific config YAMLs.
- `mcp_clients`: The list of direct Model Context Protocol tool servers that the main agent can natively interact with.
- `notify_server`: Configurations linking the orchestrator to a background service that parses real-time push events from MCP polling.
- `memory` & `summarizer`: Rules determining when the context is shortened, when memory facts are injected into the context window (`auto_feed_top_k`), and the specific RAG storage location.
- `skills`: Indicates the directories containing `.md` operational manuals that teach the agent complex recurring tasks.
