#!/usr/bin/env python3
"""Start the API with one command — no Docker, no Postgres, no manual exports.

    python tools/dev.py              # seed if empty, then serve on 127.0.0.1:8000
    python tools/dev.py --reseed     # drop and reload the demo data first
    python tools/dev.py --check      # print the AI status and exit

It loads `.env` from the repo root into the environment before anything imports the
config, so ANTHROPIC_API_KEY reaches the Anthropic SDK and the AI panels come alive.
Without a key nothing breaks: every panel degrades to a labelled deterministic draft.

Storage defaults to a local SQLite file under `backend/.data/`. To use the Postgres in
docker-compose.yml instead, set EAUDIT_DATABASE_URL (or put it in `.env`).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"


def load_env(path: Path) -> list[str]:
    """Minimal .env loader. Existing environment variables always win."""
    loaded: list[str] = []
    if not path.exists():
        return loaded
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the E-AUDIT API for local development.")
    ap.add_argument("--reseed", action="store_true", help="drop and reload the demo data")
    ap.add_argument("--check", action="store_true", help="report AI availability and exit")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    loaded = load_env(REPO / ".env")
    os.environ.setdefault(
        "EAUDIT_DATABASE_URL", f"sqlite:///{BACKEND / '.data' / 'eaudit.db'}")
    sys.path.insert(0, str(BACKEND))

    from app.db import IS_SQLITE, SessionLocal, engine  # noqa: E402
    from app.llm.service import availability  # noqa: E402
    from app.models import AuditCase  # noqa: E402
    from sqlalchemy import func, select  # noqa: E402

    print(f"repo      {REPO}")
    print(f"env       {'.env loaded: ' + ', '.join(loaded) if loaded else 'no .env found'}")
    print(f"database  {engine.url.render_as_string(hide_password=True)}"
          f"{'  (SQLite fallback — no Docker needed)' if IS_SQLITE else ''}")

    enabled, reason = availability()
    if enabled:
        print("ai        LIVE — Claude will write the prose; every figure still comes "
              "from the engine and is verified before display")
    else:
        hint = {
            "no-credentials": "no ANTHROPIC_API_KEY found. Copy .env.example to .env and paste "
                              "your key to switch the AI panels on.",
            "disabled": "EAUDIT_LLM_DISABLED is set.",
            "pdpl-blocked": "non-synthetic data may not be sent to a public endpoint.",
        }.get(reason, reason)
        print(f"ai        OFF ({reason}) — panels show labelled deterministic drafts. {hint}")

    if args.check:
        return 0

    # seed on first run, or when asked
    try:
        with SessionLocal() as db:
            cases = db.scalar(select(func.count()).select_from(AuditCase)) or 0
    except Exception:
        cases = 0
    if args.reseed or cases == 0:
        print(f"seed      {'reseeding' if args.reseed else 'empty database, seeding'}…")
        from app.seed.seed import run as seed_run  # noqa: E402
        seed_run()
    else:
        print(f"seed      {cases} cases already loaded (use --reseed to reload)")

    print(f"\nAPI       http://{args.host}:{args.port}/api/health")
    print("docs      http://%s:%d/docs" % (args.host, args.port))
    print("frontend  cd frontend && npm install && npm run dev   ->  http://localhost:5174\n")

    import uvicorn  # noqa: E402
    uvicorn.run("app.main:app", host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
