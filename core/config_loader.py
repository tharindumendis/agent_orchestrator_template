"""
core/config_loader.py
---------------------
Loads and validates config.yaml into typed dataclasses for the Orchestrator Agent.

Config schema adds two new sections on top of the worker template:
  worker_agents  — MCP stdio subprocesses that expose `execute_task` (Agent_a style)
  mcp_clients    — Direct MCP tool servers (filesystem, search, shell, etc.)

Config resolution priority
---------------------------
1. Explicit ``config_path`` argument
2. ``ORCHESTRATOR_CONFIG`` environment variable
3. OS user-config dir  (created from bundled default on first run)
       Windows : %LOCALAPPDATA%\\agent_head\\config.yaml
       macOS   : ~/Library/Application Support/agent_head/config.yaml
       Linux   : $XDG_CONFIG_HOME/agent_head/config.yaml  (~/.config/…)
4. <cwd>/config.yaml
5. Bundled package default  (Agent_head/config.yaml next to main.py)
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Bundled default sits next to main.py (package root)
_PACKAGE_DEFAULT_CONFIG = Path(__file__).parent.parent / "config.yaml"


def _resolve_relative_paths(data: dict | list | str, base_dir: Path) -> dict | list | str:
    """
    Recursively resolve relative paths (starting with './') in the config data
    to absolute paths based on the config file's directory.
    """
    if isinstance(data, str):
        if data.startswith("./"):
            return str((base_dir / data[2:]).resolve())
        return data
    elif isinstance(data, list):
        return [_resolve_relative_paths(item, base_dir) for item in data]
    elif isinstance(data, dict):
        return {key: _resolve_relative_paths(value, base_dir) for key, value in data.items()}
    else:
        return data


# ---------------------------------------------------------------------------
# OS-specific paths
# ---------------------------------------------------------------------------


def get_app_config_dir() -> Path:
    """
    Returns the OS-specific user-editable config directory for agent_head.

    - Windows : %LOCALAPPDATA%\\agent_head
    - macOS   : ~/Library/Application Support/agent_head
    - Linux   : $XDG_CONFIG_HOME/agent_head  (default ~/.config/agent_head)
    """
    if os.name == "nt":  # Windows
        base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":  # macOS
        base = Path.home() / "Library" / "Application Support"
    else:  # Linux / other POSIX
        base = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))

    config_dir = base / "agent_head"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def bootstrap_config() -> Path:
    """
    Ensures a user-editable config.yaml exists in the OS config directory.

    - If it already exists  → does nothing, returns the existing path.
    - If it doesn't exist   → copies the bundled default there and logs a
                               message so the user knows where to find it.

    Returns the path to the user config file (whether new or pre-existing).
    """
    user_config = get_app_config_dir() / "config.yaml"

    if user_config.exists():
        # Ensure service_config is also available for relative paths in the user config.
        package_service_config = _PACKAGE_DEFAULT_CONFIG.parent / "service_config"
        user_service_config = user_config.parent / "service_config"
        if package_service_config.exists() and not user_service_config.exists():
            try:
                shutil.copytree(
                    package_service_config,
                    user_service_config,
                    dirs_exist_ok=True,
                )
            except Exception as e:
                logger.warning(
                    "[agent_head] Failed to bootstrap service_config: %s",
                    e,
                )
        return user_config

    # First run — copy the bundled default config and supporting service configs
    if _PACKAGE_DEFAULT_CONFIG.exists():
        shutil.copy2(_PACKAGE_DEFAULT_CONFIG, user_config)

        # Also bootstrap the bundled service_config folder that contains
        # default config YAMLs referenced by config.yaml (e.g. notify/rag).
        package_service_config = _PACKAGE_DEFAULT_CONFIG.parent / "service_config"
        user_service_config = user_config.parent / "service_config"
        if package_service_config.exists():
            try:
                shutil.copytree(
                    package_service_config,
                    user_service_config,
                    dirs_exist_ok=True,
                )
            except Exception as e:
                logger.warning(
                    "[agent_head] Failed to bootstrap service_config: %s",
                    e,
                )

        logger.info(
            "[agent_head] First-run bootstrap: config copied to %s\n"
            "             Edit that file to customise your orchestrator settings.",
            user_config,
        )
    else:
        logger.warning(
            "[agent_head] Bundled default config not found at %s; "
            "skipping bootstrap. User config path: %s",
            _PACKAGE_DEFAULT_CONFIG,
            user_config,
        )

    return user_config


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
    """
    A direct MCP tool server (not a worker agent) the orchestrator connects to.

    transport: "stdio" (default) or "sse"
    url:       Required when transport="sse" (e.g. "http://127.0.0.1:6010/sse")
    command/args: Used only for stdio transport.
    """
    name: str
    transport: str = "stdio"          # "stdio" | "sse"
    url: str | None = None            # SSE endpoint URL (transport=sse only)
    command: str = ""                 # stdio binary (transport=stdio only)
    args: list[str] = field(default_factory=list)
    env: dict = field(default_factory=dict)


@dataclass
class AgentConfig:
    name: str = "OrchestratorAgent"
    version: str = "1.0.0"
    debug: bool = False
    description: str = "Main orchestrator agent that coordinates sub-worker agents."
    system_prompt: str = (
        "You are a powerful autonomous orchestrator agent.\n"
        "Decompose complex goals into sub-tasks and delegate them intelligently."
    )
    max_iterations: int = 50        # safety cap for the ReAct loop


@dataclass
class RagServerConfig:
    command: str = ""
    args: list[str] = field(default_factory=list)
    collection: str = "agent_memory"
    env: dict = field(default_factory=dict)


@dataclass
class MemoryConfig:
    """Long-term memory settings."""
    enabled: bool = True
    backend: str = "jsonl"          # "jsonl" | future: "sqlite" | "rag"
    memory_dir: str = "./memory"
    max_context_entries: int = 10
    max_save_length: int = 500
    auto_feed_top_k: int = 3
    auto_feed_category: str = "all"
    rag_server: RagServerConfig = field(default_factory=RagServerConfig)


@dataclass
class ChatHistoryConfig:
    backend: str = "sqlite"
    connection_string: str = "sessions.db"


@dataclass
class SummarizerModelConfig:
    """LLM settings for the summarizer (can be a lighter model than the main orchestrator)."""
    provider: str = "ollama"
    model_name: str = "llama3.2"
    temperature: float = 0.0
    base_url: str = "http://localhost:11434"
    api_key: str | None = None


@dataclass
class SummarizerConfig:
    """Controls when and how conversation history is compressed."""
    enabled: bool = True
    summarize_every_n_messages: int = 8 # Run the summarizer exactly every N messages
    keep_recent_messages: int = 6       # Leave this many recent messages untouched
    save_to_memory: bool = True         # Save summary and facts to long-term memory
    model: SummarizerModelConfig = field(default_factory=SummarizerModelConfig)


@dataclass
class NotifyServerConfig:
    """Optional Agent_notify background notification server."""
    enabled: bool = False
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict = field(default_factory=dict)


@dataclass
class ImageToolsConfig:
    """Built-in image tools (read, save, screenshot, OCR)."""
    enabled: bool = True             # master switch for all image tools
    enable_save: bool = True         # save_image tool
    enable_screenshot: bool = True   # screenshot tool
    enable_ocr: bool = True          # extract_text tool (requires pytesseract)
    screenshot_dir: str = "./screenshots"  # default dir for saved screenshots


@dataclass
class AudioToolsConfig:
    """Built-in audio tools (transcribe, TTS, save, record, play, speak)."""
    enabled: bool = True
    enable_transcribe: bool = True   # transcribe_audio (STT)
    enable_tts: bool = True          # text_to_speech
    enable_save: bool = True         # save_audio
    enable_record: bool = True       # record_audio
    enable_play: bool = True         # play_audio
    enable_speak: bool = True        # speak (TTS + play)
    audio_dir: str = "./audio"       # default dir for saved audio files


@dataclass
class MCPServerConfig:
    """Settings for running Agent_head as an MCP server."""
    name: str = "agent-orchestrator"           # MCP server name
    host: str = "127.0.0.1"                    # bind host for SSE/HTTP transport
    port: int = 8000                           # bind port for SSE/HTTP transport
    default_progress: str = "summary"          # "none" | "summary" | "full"
    log_dir: str = "./logs/mcp"                # directory for MCP server logs


@dataclass
class AppConfig:
    agent: AgentConfig = field(default_factory=AgentConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    worker_agents: list[WorkerAgentConfig] = field(default_factory=list)
    mcp_clients: list[MCPClientConfig] = field(default_factory=list)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    chat_history: ChatHistoryConfig = field(default_factory=ChatHistoryConfig)
    summarizer: SummarizerConfig = field(default_factory=SummarizerConfig)
    notify_server: NotifyServerConfig = field(default_factory=NotifyServerConfig)
    image_tools: ImageToolsConfig = field(default_factory=ImageToolsConfig)
    audio_tools: AudioToolsConfig = field(default_factory=AudioToolsConfig)
    mcp_server: MCPServerConfig = field(default_factory=MCPServerConfig)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_config(config_path: str | None = None) -> AppConfig:
    """
    Load orchestrator config.  Resolution priority:

    1. ``config_path``           — explicit path passed by the caller
    2. ``ORCHESTRATOR_CONFIG``   — environment variable
    3. OS user-config            — bootstrapped on first run from the bundled default
       ``%LOCALAPPDATA%\\agent_head\\config.yaml``  (Windows)
       ``~/Library/Application Support/agent_head/config.yaml``  (macOS)
       ``~/.config/agent_head/config.yaml``  (Linux)
    4. ``<cwd>/config.yaml``     — dev / monorepo convenience
    5. ``<package_root>/config.yaml``  — bundled package fallback
    """
    env_path = os.getenv("ORCHESTRATOR_CONFIG")
    user_config_path = bootstrap_config()
    cwd_path = Path.cwd() / "config.yaml"
    package_root_path = _PACKAGE_DEFAULT_CONFIG

    if config_path:
        final_path = Path(config_path)
    elif env_path:
        final_path = Path(env_path)
    elif user_config_path.exists():
        final_path = user_config_path
    elif cwd_path.exists():
        final_path = cwd_path
    else:
        final_path = package_root_path

    if not final_path.exists():
        raise FileNotFoundError(
            f"Orchestrator config not found. Checked:\n"
            f"  1. Explicit path              : {config_path}\n"
            f"  2. Env var ORCHESTRATOR_CONFIG: {env_path}\n"
            f"  3. OS user-config             : {user_config_path}\n"
            f"  4. CWD                        : {cwd_path}\n"
            f"  5. Package default            : {package_root_path}\n"
            f"Please ensure a 'config.yaml' exists at one of the above locations."
        )

    logger.info("[agent_head] Using config: %s", final_path.resolve())
    print(f"[*] Using config: {final_path.absolute()}")
    with open(final_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    # Resolve relative paths in the config to absolute paths based on config file's directory
    config_dir = final_path.parent
    raw = _resolve_relative_paths(raw, config_dir)

    # --- Agent ---
    agent_raw = raw.get("agent", {})
    agent = AgentConfig(
        name=agent_raw.get("name", "OrchestratorAgent"),
        version=agent_raw.get("version", "1.0.0"),
        debug=bool(agent_raw.get("debug", False)),
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
        transport = entry.get("transport", "stdio")
        mcp_clients.append(
            MCPClientConfig(
                name=entry["name"],
                transport=transport,
                url=entry.get("url"),           # only for transport=sse
                command=entry.get("command", ""),
                args=entry.get("args", []),
                env=entry.get("env", {}),
            )
        )

    # --- Memory ---
    mem_raw = raw.get("memory", {})
    rag_raw = mem_raw.get("rag_server", {})
    memory = MemoryConfig(
        enabled=bool(mem_raw.get("enabled", True)),
        backend=mem_raw.get("backend", "jsonl"),
        memory_dir=mem_raw.get("memory_dir", "./memory"),
        max_context_entries=int(mem_raw.get("max_context_entries", 10)),
        max_save_length=int(mem_raw.get("max_save_length", 500)),
        auto_feed_top_k=int(mem_raw.get("auto_feed_top_k", 3)),
        auto_feed_category=mem_raw.get("auto_feed_category", "all"),
        rag_server=RagServerConfig(
            command=rag_raw.get("command", ""),
            args=rag_raw.get("args", []),
            collection=rag_raw.get("collection", "agent_memory"),
            env=rag_raw.get("env", {}),
        )
    )

    # --- Summarizer ---
    sum_raw = raw.get("summarizer", {})
    sum_model_raw = sum_raw.get("model", {})
    # Fall back to main model config if summarizer model block is empty
    summarizer = SummarizerConfig(
        enabled=bool(sum_raw.get("enabled", True)),
        summarize_every_n_messages=int(sum_raw.get("summarize_every_n_messages", 8)),
        keep_recent_messages=int(sum_raw.get("keep_recent_messages", 6)),
        save_to_memory=bool(sum_raw.get("save_to_memory", True)),
        model=SummarizerModelConfig(
            provider=sum_model_raw.get("provider", model.provider),
            model_name=sum_model_raw.get("model_name", model.model_name),
            temperature=float(sum_model_raw.get("temperature", 0.0)),
            base_url=sum_model_raw.get("base_url", model.base_url),
            api_key=sum_model_raw.get("api_key", model.api_key),
        ),
    )

    # --- Chat History ---
    chat_raw = raw.get("chat_history", {})
    chat_history = ChatHistoryConfig(
        backend=chat_raw.get("backend", "sqlite"),
        connection_string=chat_raw.get("connection_string", "sessions.db")
    )

    # --- Notify Server ---
    notify_raw = raw.get("notify_server", {})
    notify_server = NotifyServerConfig(
        enabled=bool(notify_raw.get("enabled", False)),
        command=notify_raw.get("command", ""),
        args=notify_raw.get("args", []),
        env=notify_raw.get("env", {}),
    )

    # --- Image Tools ---
    img_raw = raw.get("image_tools", {})
    image_tools = ImageToolsConfig(
        enabled=bool(img_raw.get("enabled", True)),
        enable_save=bool(img_raw.get("enable_save", True)),
        enable_screenshot=bool(img_raw.get("enable_screenshot", True)),
        enable_ocr=bool(img_raw.get("enable_ocr", True)),
        screenshot_dir=img_raw.get("screenshot_dir", "./screenshots"),
    )

    # --- Audio Tools ---
    aud_raw = raw.get("audio_tools", {})
    audio_tools = AudioToolsConfig(
        enabled=bool(aud_raw.get("enabled", True)),
        enable_transcribe=bool(aud_raw.get("enable_transcribe", True)),
        enable_tts=bool(aud_raw.get("enable_tts", True)),
        enable_save=bool(aud_raw.get("enable_save", True)),
        enable_record=bool(aud_raw.get("enable_record", True)),
        enable_play=bool(aud_raw.get("enable_play", True)),
        enable_speak=bool(aud_raw.get("enable_speak", True)),
        audio_dir=aud_raw.get("audio_dir", "./audio"),
    )

    # --- MCP Server ---
    mcp_raw = raw.get("mcp_server", {})
    mcp_server = MCPServerConfig(
        name=mcp_raw.get("name", "agent-orchestrator"),
        host=mcp_raw.get("host", "127.0.0.1"),
        port=int(mcp_raw.get("port", 8000)),
        default_progress=mcp_raw.get("default_progress", "summary"),
        log_dir=mcp_raw.get("log_dir", "./logs/mcp"),
    )

    return AppConfig(
        agent=agent,
        model=model,
        worker_agents=worker_agents,
        mcp_clients=mcp_clients,
        memory=memory,
        chat_history=chat_history,
        summarizer=summarizer,
        notify_server=notify_server,
        image_tools=image_tools,
        audio_tools=audio_tools,
        mcp_server=mcp_server,
    )
