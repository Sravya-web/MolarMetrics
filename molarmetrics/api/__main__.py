"""Run the MolarMetrics web API on this computer only.

    python -m molarmetrics.api [--port 8000] [--reload]

The server binds to 127.0.0.1. The app has no login, so it refuses to listen
on other network interfaces.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    parser = argparse.ArgumentParser(description="Run the MolarMetrics web API (local only).")
    parser.add_argument("--host", default=os.environ.get("MOLARMETRICS_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MOLARMETRICS_API_PORT", "8000")))
    parser.add_argument("--reload", action="store_true", help="restart on code changes (development)")
    args = parser.parse_args(argv)
    if args.host not in LOCAL_HOSTS:
        print(f"Refusing to listen on {args.host}: MolarMetrics has no login, so it only runs on this "
              "computer (127.0.0.1).", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per local model call is just noise
    # access_log=False: uvicorn's access log prints full URLs; our middleware logs
    # request IDs, route templates, status codes and timings instead.
    uvicorn.run("molarmetrics.api.app:create_app", factory=True, host=args.host, port=args.port,
                reload=args.reload, reload_dirs=["molarmetrics"] if args.reload else None,
                access_log=False, log_config=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
