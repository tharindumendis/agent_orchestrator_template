import sys
# Import your existing main functions
from main import _cli_entry
from api.server import main as run_api
from core.mcp_server import main as run_mcp

def main():
    if len(sys.argv) < 2:
        print("Otter AI Launcher")
        print("Usage: otter-ai [head | api | mcp]")
        # Default to head if no arg provided
        _cli_entry()
        return

    mode = sys.argv[1].lower()
    
    if mode == "head":
        _cli_entry()
    elif mode == "api":
        run_api()
    elif mode == "mcp":
        run_mcp()
    else:
        print(f"Unknown mode: {mode}")

if __name__ == "__main__":
    main()