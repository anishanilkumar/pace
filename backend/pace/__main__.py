"""python -m pace web [--port 8778]  |  worker  |  fetch [--headed]

web     the API for the web and Android apps
worker  reads Time Doctor on a schedule and makes nudges (long-running)
fetch   one read now, then the nudge rules; for checking the setup
        (--headed shows the browser, to watch the login)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if len(sys.argv) < 2 or sys.argv[1] not in ("web", "worker", "fetch"):
        sys.exit(__doc__)
    cmd, rest = sys.argv[1], sys.argv[2:]

    if cmd == "web":
        import uvicorn

        from .web import create_app

        p = argparse.ArgumentParser(prog="pace web")
        p.add_argument("--host", default="127.0.0.1")
        p.add_argument("--port", type=int, default=8778)
        a = p.parse_args(rest)
        # proxy_headers: nginx sets X-Forwarded-For, and only loopback is trusted.
        uvicorn.run(create_app(), host=a.host, port=a.port, proxy_headers=True, forwarded_allow_ips="127.0.0.1")
        return

    from . import db, worker

    db.init()
    if cmd == "worker":
        asyncio.run(worker.run())
        return

    p = argparse.ArgumentParser(prog="pace fetch")
    p.add_argument("--headed", action="store_true")
    a = p.parse_args(rest)
    asyncio.run(worker.fetch_once(headed=a.headed))
    last = db.last_fetch()
    if last and not last["ok"]:
        sys.exit(f"Fetch failed: {last['error']}")
    today = datetime.now(db.get_prefs().zone).date()
    print(f"Fetched. Today: {db.hours(today, today).get(today, 0):.2f} h")


if __name__ == "__main__":
    main()
