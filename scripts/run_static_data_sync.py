#!/usr/bin/env python3
"""Manually run Juniper static data full sync into PostgreSQL.

Runs ``juniper_ai.app.tasks.sync_static_data.run_full_sync()`` in order:
``sync_zones`` → ``sync_hotels`` → ``sync_catalogue`` (see ``doc/development.md``).

HotelContent is **not** part of this full sync; see ``doc/todo-static-data-cache.md`` Phase D.

Prerequisites:
  - Database reachable (``DATABASE_URL`` in ``.env`` or environment).
  - For real SOAP data: ``JUNIPER_USE_MOCK=false`` plus ``JUNIPER_API_URL``, ``JUNIPER_EMAIL``, ``JUNIPER_PASSWORD``.
  - From repo root: ``python scripts/run_static_data_sync.py``
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from juniper_ai.app.config import settings
from juniper_ai.app.tasks.sync_static_data import run_full_sync


async def _main() -> int:
    print("DATABASE_URL set:", bool(settings.database_url))
    print("JUNIPER_USE_MOCK:", settings.juniper_use_mock)
    if settings.juniper_use_mock:
        print(
            "Note: Mock Juniper client is active; synced rows will reflect mock fixtures, not supplier SOAP.",
            file=sys.stderr,
        )
    elif not settings.juniper_email or not settings.juniper_password:
        print(
            "Set JUNIPER_EMAIL and JUNIPER_PASSWORD for live SOAP sync (or use JUNIPER_USE_MOCK=true for dev).",
            file=sys.stderr,
        )
        return 2

    print("Starting run_full_sync(): sync_zones → sync_hotels → sync_catalogue ...")
    try:
        summary = await run_full_sync()
    except OSError as e:
        err_txt = str(e)
        if e.errno == 61 or "Connect call failed" in err_txt or "connection refused" in err_txt.lower():
            print(
                "run_full_sync FAILED: cannot connect to PostgreSQL (connection refused).\n"
                "  If you use docker-compose, start the DB first:\n"
                "    docker compose up -d db\n"
                "  Default host mapping is localhost:5433 → container :5432 (see docker-compose.yml).\n"
                "  Or set DATABASE_URL in .env to a reachable instance.",
                file=sys.stderr,
            )
        print("run_full_sync FAILED:", repr(e), file=sys.stderr)
        return 1
    except Exception as e:
        print("run_full_sync FAILED:", repr(e), file=sys.stderr)
        return 1

    print("OK:", json.dumps(summary, indent=2, default=str))
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
