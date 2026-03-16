from mcp.server.fastmcp import FastMCP

mcp = FastMCP("HttpTestServer", port=8005)

@mcp.tool()
def ping() -> str:
    """A simple test tool to verify HTTP connectivity."""
    return "Pong! The HTTP connection is successfully established."

if __name__ == "__main__":
    # Updated to reflect the standard HTTP endpoint
    print("Starting MCP HTTP Server on http://localhost:8005/mcp") 
    
    # Changed from "sse" to "http" (or "streamable-http" if using the newest SDK)
    mcp.run(transport="streamable-http")