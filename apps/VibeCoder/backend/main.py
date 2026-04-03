"""VibeCoder entry point.

Usage:
  python main.py                    # CLI mode (default)
  python main.py --server           # WebSocket server for CADEN GUI
  python main.py --workspace PATH   # Set workspace directory
"""

import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(description="CADEN VibeCoder")
    parser.add_argument("--server", action="store_true", help="Start WebSocket server for GUI mode")
    parser.add_argument("--port", type=int, default=5180, help="Server port (default: 5180)")
    parser.add_argument("--workspace", default=None, help="Workspace directory")
    args = parser.parse_args()

    if args.server:
        from server import start_server
        start_server(port=args.port, workspace=args.workspace)
    else:
        from cli import main as cli_main
        cli_main(workspace=args.workspace)


if __name__ == "__main__":
    main()
