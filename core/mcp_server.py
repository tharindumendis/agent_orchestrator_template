"""
core/mcp_server.py
-------------------
MCP Server implementation for the Agent Orchestrator.

This exposes the orchestrator agent as an MCP server that can be accessed
via stdio, HTTP, or SSE transports.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent
from pydantic import BaseModel

from core.agent import run_orchestrator
from core.config_loader import load_config

logger = logging.getLogger(__name__)

# Create FastMCP server
app = FastMCP("agent-orchestrator")


class OrchestrateTaskArgs(BaseModel):
    """Arguments for the orchestrate_task tool."""
    task: str
    session_id: str | None = None


@app.tool()
async def orchestrate_task(args: OrchestrateTaskArgs) -> str:
    """
    Execute a high-level task using the agent orchestrator.

    This tool connects to all configured worker agents and MCP tool servers,
    then runs a ReAct loop to accomplish the given task.

    Args:
        task: The natural-language description of the task to perform
        session_id: Optional session ID for memory continuity

    Returns:
        The final result from the orchestrator agent
    """
    try:
        # Load configuration
        config = load_config()

        # Run the orchestrator
        result = await run_orchestrator(
            task=args.task,
            config=config,
            session_id=args.session_id
        )

        return result

    except Exception as e:
        logger.error(f"Error in orchestrate_task: {e}")
        return f"Error: {str(e)}"


def main():
    """Main entry point for the MCP server."""
    import argparse

    parser = argparse.ArgumentParser(description="Agent Orchestrator MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "http"],
        default="stdio",
        help="Transport to use (default: stdio)"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to for network transports (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind to for network transports (default: 8000)"
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(level=logging.INFO)

    if args.transport == "stdio":
        print("Starting MCP server with stdio transport...", file=sys.stderr)
        # For stdio, we need to use the low-level API
        from mcp.server.stdio import stdio_server
        from mcp.server import Server
        
        server = Server("agent-orchestrator")
        
        @server.tool()
        async def orchestrate_task_stdio(task: str, session_id: str | None = None) -> list[TextContent]:
            try:
                config = load_config()
                result = await run_orchestrator(task=task, config=config, session_id=session_id)
                return [TextContent(type="text", text=result)]
            except Exception as e:
                logger.error(f"Error in orchestrate_task: {e}")
                return [TextContent(type="text", text=f"Error: {str(e)}")]
        
        async def run_stdio():
            async with stdio_server() as (read_stream, write_stream):
                await server.run(read_stream, write_stream, server.create_initialization_options())
        
        asyncio.run(run_stdio())
        
    elif args.transport == "sse":
        print(f"Starting MCP server with SSE transport on {args.host}:{args.port}...", file=sys.stderr)
        app.run(transport="sse", host=args.host, port=args.port)
    elif args.transport == "http":
        print(f"Starting MCP server with HTTP transport on {args.host}:{args.port}...", file=sys.stderr)
        app.run(transport="streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
