# Plan: On-Demand Agent Configuration Sets (Isolated Worker Paradigm)

Using the `Agent_head` orchestrator template, we can create tailored configurations for different product lines. 

### 🛡️ Security & Reliability Philosophy
To prevent the Orchestrator from hallucinating due to tool overload and to ensure strict security, these configurations rely heavily on **Worker Agent Isolation**. 
- The Orchestrator acts purely as a fast router and communicator.
- Tools and RAG collections are **only** given to the specialized Worker Agents (Planner, Auditor, Researcher, Coder).
- Different LLMs are allocated based on expertise (e.g., `qwen-coder` for the Coder worker, `gemini-2.5-pro` for the Thinker/Planner).

---

## 1. Domain Expert Agent
*Goal*: Deep specialized knowledge retrieval and synthesis without needing to execute arbitrary actions.
* **Orchestrator Model**: Fast router (e.g., `gemini-2.0-flash`).
* **Worker Agents**: 
  - `thinker_worker`: High-reasoning model (`gpt-4o`, temp `0.0`). Given the Domain-Specific RAG tool.
  - `researcher_worker`: Fast searcher. Given `@modelcontextprotocol/server-brave-search` and `server-puppeteer`.
* **MCP Tools (Main)**: `agent-rag-mcp` (RAG system given to the orchestrator to fetch extra domain knowledge quickly).
* **RAG System**: Active on the orchestrator and `thinker_worker`, strictly watching domain `docs`.
* **Sessions**: Continuous memory enabled with `auto_feed_top_k: 5` to maintain deep context.

## 2. Personal Agent (Unlimited Capability)
*Goal*: A highly capable assistant with file access, code execution, web browsing, and communication abilities.
* **Orchestrator Model**: Fast communicative model (e.g., `kimi-k2.5:cloud`).
* **Worker Agents**: 
  - `planner_worker`: Breaks down goals. Uses `@modelcontextprotocol/server-sequential-thinking`.
  - `coder_worker`: Given `filesystem`, `shell-execution`, and `server-github`. Uses `qwen3-coder`.
  - `auditor_worker`: Verifies files/code safely.
* **MCP Tools (Main)**: 
  - `tele_bot_mcp` (for direct telegram interaction).
  - `@modelcontextprotocol/server-google-drive` or `server-slack` for fetching personal communications.
  - `filesystem` (for file management tasks).
  - DuckDuckGo MCP and `@modelcontextprotocol/server-brave-search` (for web browsing and searching).
* **RAG System**: Attached to orchestrator or specific workers to retrieve personal facts.
* **Sessions**: SQLite backend for long persistent sessions.

## 3. Domain Expert Chatbot
*Goal*: A customer-facing Q&A chatbot focused strictly on a knowledge base.
* **Architecture**: The [api/server.py](file:///D:/DEV/mcp/universai/agent_orchestrator_template/api/server.py) exposes endpoints, allowing integration into any custom frontend or chat widget.
* **Orchestrator Model**: Fast, low-latency model.
* **Worker Agents**: None needed (simple passthrough).
* **MCP Tools (Main)**: `tele_bot_mcp` (for Telegram), purely REST endpoints, and `agent-rag-mcp` (to fetch extra domain knowledge). No shell/filesystem allowed.
* **RAG System**: Active, strictly pointing to curated PDFs/documents.
* **Notifications**: Telegram webhook/polling via notification server.
* **Sessions**: Simple session management isolated per-user via `session_id`.

## 4. Session Base Agent
*Goal*: An agent spun up temporarily for a specific context/task and terminated afterward.
* **Orchestrator Model**: Task-dependent.
* **Worker Agents**: Spun up based on the job template.
* **MCP Tools (Main)**: Ephemeral state tools (`@modelcontextprotocol/server-memory`).
* **RAG System**: Enabled securely per session. RAG retains context and user nuances specific to that session, dropped or archived post-task.
* **Sessions**: In-memory or explicitly deleted SQLite records (`DELETE /sessions/{session_id}`) after completion.

## 5. Security Expert (Kali OS)
*Goal*: Vulnerability scanning, infrastructure review, and network discovery.
* **Orchestrator Model**: High-reasoning logic model.
* **Worker Agents**: 
  - `auditor_worker`: Reviews exploit paths securely. Uses `claude-3.5-sonnet`.
  - `scanner_worker`: Dedicated to running networking scans (Nmap, etc).
* **MCP Tools**: 
  - `kalimcp` (Kali Linux MCP server for security tools) attached specifically to the `scanner_worker`.
  - `filesystem` (attached to an isolated sandbox directory to create reports). *Note: Prompt must aggressively instruct the agent to clean up unnecessary temporary files.*
* **RAG System**: Pointed to a CVE collection and internal compliance policies.
* **Sessions**: Persistent for long audits, highly structured outputs.

## 6. Coding Agent
*Goal*: Software development, debugging, and file manipulation.
* **Orchestrator Model**: Fast communicator.
* **Worker Agents**: 
  - `architect_worker`: Uses `@modelcontextprotocol/server-sequential-thinking` to plan logic. Pointed to a codebase RAG.
  - `coder_worker`: Given `filesystem` (write) and `shell-execution` to compile/test.
* **MCP Tools (Main)**: `@modelcontextprotocol/server-github` or `@modelcontextprotocol/server-gitlab` to manage PRs.
* **Notifications**: Polling local filesystem or `list_issues` on Git to trigger autonomous fixes.
* **Sessions**: Persistent based on sprint/project scope.

## 7. Data Analysis Agent
*Goal*: Explore datasets, generate charts, and summarize data insights.
* **Orchestrator Model**: Presentation/Communication model.
* **Worker Agents**: 
  - `analyst_worker`: Expert math/statistical model (`claude-3.5-sonnet`).
* **MCP Tools (Main)**: 
  - `@modelcontextprotocol/server-sqlite` or `@modelcontextprotocol/server-postgres`
  - `@modelcontextprotocol/server-google-drive` (to export CSVs/Sheets).
* **RAG System**: Used to store schema definitions and query optimization rules.

## 8. IT Support / Helpdesk Agent
*Goal*: Internal IT support tier 1 responder, triage tickets, and user assistance.
* **Orchestrator Model**: Friendly, general-purpose (`gpt-4o-mini`).
* **Worker Agents**: 
  - `knowledge_worker`: RAG-enabled to search internal manuals.
  - `action_worker`: Safely scoped to execute password resets or AD tasks securely.
* **MCP Tools (Main)**: 
  - Issue tracker MCP (Jira/Zendesk) or `@modelcontextprotocol/server-gitlab`.
  - `@modelcontextprotocol/server-slack` / `tele_bot_mcp` for direct engagement.

## 9. DevOps / SRE Automation Agent
*Goal*: Monitor infrastructure, review alerts, and run safe deployment playbooks.
* **Orchestrator Model**: Analytical, low-hallucination model.
* **Worker Agents**: 
  - `monitor_worker`: Observes logs constantly.
  - `operator_worker`: Proposes playbooks to human admins.
* **MCP Tools**: 
  - `@modelcontextprotocol/server-sentry` or Datadog equivalents.
  - `@modelcontextprotocol/server-aws` (or GCP bindings) attached strictly to the `operator_worker`.
* **Notifications**: Alerting endpoints ping the orchestrator directly to initiate investigations automatically.

---
### Next Steps for Implementation
1. **Dynamic Config Factory**: Build a python script (`create_agent.py --profile personal_agent`) that fuses [config.yaml](file:///D:/DEV/mcp/universai/agent_orchestrator_template/config.yaml) with the chosen toolsets and sub-agent workers.
2. **Worker Prompt Isolation**: Build strict, isolated system prompts for the Planner/Auditor/Researcher worker configurations to ensure they stick perfectly to their role.
