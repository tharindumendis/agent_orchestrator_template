"""
core/config_loader.py
---------------------
Loads and validates config.yaml into typed dataclasses for the Orchestrator Agent.

Config schema adds two new sections on top of the worker template:
  worker_agents  — MCP stdio subprocesses that expose `execute_task` (Agent_a style)
  mcp_clients    — Direct MCP tool servers (filesystem, search, shell, etc.)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Dataclass models
# ---------------------------------------------------------------------------


@dataclass
class ModelConfig:
    provider: str = "ollama"          # "ollama" | "openai" | "gemini"
    model_name: str = "llama3.2"
    temperature: float = 0.0
    base_url: str = "http://localhost:11434"
    api_key: str | None = None


@dataclass
class WorkerAgentConfig:
    """
    A sub-worker that exposes itself as an MCP server (stdio).
    The orchestrator spawns it as a subprocess and discovers its tools.
    """
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict = field(default_factory=dict)
    description: str = ""            # human-readable, shown in logs


@dataclass
class MCPClientConfig:
    """A direct MCP tool server (not a worker agent) the orchestrator connects to."""
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict = field(default_factory=dict)


@dataclass
class AgentConfig:
    name: str = "OrchestratorAgent"
    version: str = "1.0.0"
    description: str = "Main orchestrator agent that coordinates sub-worker agents."
    system_prompt: str = (
        "You are a powerful autonomous orchestrator agent.\n"
        "Decompose complex goals into sub-tasks and delegate them intelligently."
    )
    max_iterations: int = 50        # safety cap for the ReAct loop


@dataclass
class MemoryConfig:
    """Long-term memory settings."""
    enabled: bool = True
    backend: str = "jsonl"          # "jsonl" | future: "sqlite" | "rag"
    memory_dir: str = "./memory"
    max_context_entries: int = 10
    max_save_length: int = 500


@dataclass
class AppConfig:
    agent: AgentConfig = field(default_factory=AgentConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    worker_agents: list[WorkerAgentConfig] = field(default_factory=list)
    mcp_clients: list[MCPClientConfig] = field(default_factory=list)
    memory: MemoryConfig = field(default_factory=MemoryConfig)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_config(config_path: str | None = None) -> AppConfig:
    """
    Load orchestrator config. Priority:
    1. config_path argument
    2. ORCHESTRATOR_CONFIG env var
    3. ./config.yaml (cwd)
    4. <package_root>/config.yaml
    """
    env_path = os.getenv("ORCHESTRATOR_CONFIG")
    cwd_path = Path.cwd() / "config.yaml"
    package_root_path = Path(__file__).parent.parent / "config.yaml"

    if config_path:
        final_path = Path(config_path)
    elif env_path:
        final_path = Path(env_path)
    elif cwd_path.exists():
        final_path = cwd_path
    else:
        final_path = package_root_path

    if not final_path.exists():
        raise FileNotFoundError(
            f"Orchestrator config not found. Checked:\n"
            f"  - Explicit path: {config_path}\n"
            f"  - Env var (ORCHESTRATOR_CONFIG): {env_path}\n"
            f"  - CWD: {cwd_path}\n"
            f"  - Package root: {package_root_path}\n"
            f"Please ensure a 'config.yaml' exists."
        )

    print(f"[*] Using config: {final_path.absolute()}")
    with open(final_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    # --- Agent ---
    agent_raw = raw.get("agent", {})
    agent = AgentConfig(
        name=agent_raw.get("name", "OrchestratorAgent"),
        version=agent_raw.get("version", "1.0.0"),
        description=agent_raw.get("description", "Main orchestrator agent."),
        system_prompt=agent_raw.get(
            "system_prompt",
            "You are a powerful autonomous orchestrator agent.",
        ),
        max_iterations=int(agent_raw.get("max_iterations", 50)),
    )

    # --- Model ---
    model_raw = raw.get("model", {})
    model = ModelConfig(
        provider=model_raw.get("provider", "ollama"),
        model_name=model_raw.get("model_name", "llama3.2"),
        temperature=float(model_raw.get("temperature", 0.0)),
        base_url=model_raw.get("base_url", "http://localhost:11434"),
        api_key=model_raw.get("api_key", os.getenv("API_KEY")),
    )

    # --- Worker Agents ---
    worker_agents: list[WorkerAgentConfig] = []
    for entry in raw.get("worker_agents", []) or []:
        worker_agents.append(
            WorkerAgentConfig(
                name=entry["name"],
                command=entry["command"],
                args=entry.get("args", []),
                env=entry.get("env", {}),
                description=entry.get("description", ""),
            )
        )

    # --- Direct MCP Clients ---
    mcp_clients: list[MCPClientConfig] = []
    for entry in raw.get("mcp_clients", []) or []:
        mcp_clients.append(
            MCPClientConfig(
                name=entry["name"],
                command=entry["command"],
                args=entry.get("args", []),
                env=entry.get("env", {}),
            )
        )

    # --- Memory ---
    mem_raw = raw.get("memory", {})
    memory = MemoryConfig(
        enabled=bool(mem_raw.get("enabled", True)),
        backend=mem_raw.get("backend", "jsonl"),
        memory_dir=mem_raw.get("memory_dir", "./memory"),
        max_context_entries=int(mem_raw.get("max_context_entries", 10)),
        max_save_length=int(mem_raw.get("max_save_length", 500)),
    )

    return AppConfig(
        agent=agent,
        model=model,
        worker_agents=worker_agents,
        mcp_clients=mcp_clients,
        memory=memory,
    )
