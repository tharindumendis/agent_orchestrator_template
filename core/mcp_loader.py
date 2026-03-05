import logging
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from langchain_mcp_adapters.tools import load_mcp_tools

logger = logging.getLogger(__name__)


async def load_mcp_server_tools(
    stack: AsyncExitStack,
    # ── stdio args ──────────────────────────────────────────
    command: str = "",
    args: list[str] | None = None,
    env: dict | None = None,
    # ── network transports (sse / http) ─────────────────────
    transport: str = "stdio",
    url: str | None = None,
    # ── shared ──────────────────────────────────────────────
    description_override: str | None = None,
):
    """
    Connects to an MCP server and loads LangChain tools.

    transport="stdio"  → spawns a subprocess via command/args  (default)
    transport="sse"    → legacy SSE endpoint  (url ending in /sse)
    transport="http"   → modern Streamable HTTP endpoint  (url ending in /mcp)
    """
    try:
        if transport == "sse":
            if not url:
                raise ValueError("transport='sse' requires 'url' to be set.")
            logger.info("[MCP Loader] Connecting via SSE to %s", url)
            read, write = await stack.enter_async_context(sse_client(url))

        elif transport == "http":
            if not url:
                raise ValueError("transport='http' requires 'url' to be set.")
            logger.info("[MCP Loader] Connecting via Streamable HTTP to %s", url)
            # streamablehttp_client returns (read, write, _get_session_id)
            read, write, _ = await stack.enter_async_context(streamablehttp_client(url))

        else:
            # Default: stdio subprocess
            import os
            merged_env = dict(os.environ)
            if env:
                merged_env.update(env)
            params = StdioServerParameters(command=command, args=args or [], env=merged_env)
            logger.info("[MCP Loader] Spawning stdio process: %s %s", command, args)
            read, write = await stack.enter_async_context(stdio_client(params))

        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()

        tools = await load_mcp_tools(session)

        if description_override:
            for t in tools:
                t.description = f"{description_override.strip()}\n\nTool specific details: {t.description}"

        return tools

    except Exception as exc:
        label = url if transport in ("sse", "http") else command
        logger.error(
            "[MCP Loader] Failed to connect to '%s' (transport=%s): %s",
            label, transport, exc
        )
        raise
