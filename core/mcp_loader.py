import logging
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools

logger = logging.getLogger(__name__)

async def load_mcp_server_tools(
    stack: AsyncExitStack, 
    command: str, 
    args: list[str], 
    env: dict | None = None,
    description_override: str | None = None
):
    """
    Connects to an MCP stdio server, initializes a session, loads LangChain tools,
    and applies an optional description override to the tools for the Orchestrator LLM.
    
    Returns the list of loaded LangChain tools.
    """
    try:
        import os
        merged_env = dict(os.environ)
        if env:
            merged_env.update(env)
            
        params = StdioServerParameters(command=command, args=args, env=merged_env)
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        
        tools = await load_mcp_tools(session)
        
        if description_override:
            for t in tools:
                t.description = f"{description_override.strip()}\n\nTool specific details: {t.description}"
                
        return tools
    except Exception as exc:
        logger.error(f"[MCP Loader] Failed to connect and load tools for '{command}': {exc}")
        raise
