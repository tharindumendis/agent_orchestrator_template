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

- **Autonomous Execution**: Uses LangChain/LangGraph for active context reasoning.
- **Worker Agents (Multiple Brains)**: Define and spawn standalone specialist worker agents (e.g., search bots, payment handlers) with isolated APIs so context isn't contaminated.
- **MCP Server Mode**: Expose the orchestrator itself as an MCP server tool for parent agents or UI clients.
- **Flexible Tooling**: Pluggable interface via MCP out-of-the-box (Filesystem access, Brave Search, Telegram).

## Installation

### Prerequisites

- Python 3.10+
- `uv` package manager (recommended) or standard `pip`
- (Optional) Running Ollama server or relevant API keys for Cloud Providers.

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
```

## Quick Start & Project Initialization

Instead of managing bulky global configs, `Agent_head` lets you scaffold AI logic natively into your current project directory:

```bash
# In an empty or existing project directory
agent-head --setup
```
This command seamlessly creates the `.agents` hidden folder in your working directory and instantiates `config.yaml` alongside specialized agent configs, keeping your agent logic tightly bound to your project environment.

> **Note**: For configuring and editing the generated `.agents` files and creating new worker specializations, please reference the [Capabilities Guide](documentation.md) on how the JSON/YAML structure behaves!

### Running the Orchestrator

**Command Line Mode (REPL):**
```bash
agent-head
```

**Single-Shot Prompting:**
```bash
agent-head --task "Search standard python typing practices and format them into a markdown file in this directory."
```

**MCP Provider Mode:**
```bash
agent-mcp --transport stdio
```

## Troubleshooting & Debugging

If you're noticing crashes or silent tool failures, you can actively inspect the reasoning loop logs:
```bash
export AGENT_HEAD_DEBUG=1
agent-head
```
All system activities are comprehensively documented within the `logs/jobs/` and `logs/runs/` directories native to the current execution path.

## License
MIT License - see LICENSE file for details.
