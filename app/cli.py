"""
AI Burst Cloud CLI — start the routing server from the command line.

Usage:
    aiburstcloud                          # start on 0.0.0.0:8000
    aiburstcloud --port 9000              # custom port
    aiburstcloud --burst-mode cloud_burst # override default mode
"""

import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="aiburstcloud",
        description="Dual-mode cloud burst LLM router",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument("--burst-mode", choices=["edge_burst", "cloud_burst"],
                        help="Override BURST_MODE env var")
    parser.add_argument("--workers", type=int, default=1, help="Number of workers (default: 1)")
    parser.add_argument("--version", action="store_true", help="Show version and exit")

    args = parser.parse_args()

    if args.version:
        from app import __version__
        print(f"aiburstcloud {__version__}")
        sys.exit(0)

    if args.burst_mode:
        os.environ["BURST_MODE"] = args.burst_mode

    import uvicorn
    uvicorn.run(
        "app.router:app",
        host=args.host,
        port=args.port,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
