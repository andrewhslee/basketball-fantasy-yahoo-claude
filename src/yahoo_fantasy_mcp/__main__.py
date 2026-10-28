"""`yahoo-fantasy-mcp login` signs in to Yahoo once; with no arguments it runs the MCP server."""

import sys


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if command == "login":
        from yahoo_fantasy_mcp.auth import login_interactive

        login_interactive()
    elif command == "serve":
        from yahoo_fantasy_mcp.server import mcp

        mcp.run()
    else:
        sys.exit(f"Unknown command '{command}'. Use `login`, or no argument to run the server.")


if __name__ == "__main__":
    main()
