# ZATCA VAT Audit Agent — Demo PoC

An AI-assisted VAT audit workbench for ZATCA. It picks up a case **after** the risk engine
has flagged a taxpayer + period, reconstructs the expected VAT return from cleared e-invoices,
reconciles it against the declared return, explains every legitimate difference down to a true
unexplained residual, recommends the next best action, and drafts an evidence-backed report for
an auditor to approve.

- **Deterministic core** (Python) computes every number.
- **Claude** (`claude-opus-5`) only writes/explains language — it never introduces a figure.
- **A human auditor approves** everything that leaves the building.

## Stack
- **Frontend:** React + TypeScript (Vite), ZATCA-themed.
- **Backend:** Python / FastAPI, SQLAlchemy.
- **Database:** PostgreSQL (schemas `core` + `recon`).

## Repo layout
```
backend/     FastAPI app, data model, seed data
frontend/    React (Vite) ZATCA-themed workbench
docs/        VAT Mistakes Rulebook (markdown + rendered page)
tools/       build scripts (rulebook page generator)
portal.html  standalone no-backend build — open it in a browser, nothing to install
```

## Scope

A VAT return is **not** the e-invoice population restated. It is the
tax-point-adjusted e-invoice population *plus* populations that carry no domestic
e-invoice at all (imports, reverse charge, exempt supplies), *plus* adjustments,
prior-period corrections and timing movements. Any design resting on
`Σ invoices(period) == return(period)` is wrong by construction.

This PoC reconstructs one slice of that picture:

- **In scope** — standard-rated sales (output VAT) and standard-rated purchases
  (input VAT), one tax period, one return version, four wired explanations
  (credit notes and tax-point straddle timing on both boxes) plus
  auditor-confirmed taxpayer evidence.
- **Out of scope** — imports, reverse charge, exempt/zero-rated supplies, VAT
  groups and branches, cash accounting, prior-period corrections and amendments,
  bad debts, partial exemption, B2C aggregation, rounding tolerance, buyer-side
  supplier matching, and rolling multi-period reconciliation.

Each exclusion is tagged with the reason code that would carry it, so the boundary
is a stated design decision with a named home in the taxonomy. The live list is
served from `GET /api/scope` and shown on the Overview page — `backend/app/scope.py`
is the single source, so the README, the API and the UI cannot drift apart.

## Phase 0 — Foundation (this milestone)
Data model + config + seed data + a themed app shell. Reconstruction/bridge/AI features land in later phases.

### Run

```bash
# 1. backend — no Docker, no Postgres, seeds itself on first run
python -m venv .venv && . .venv/bin/activate    # Scripts/activate on Windows
pip install -r backend/requirements.txt
python tools/dev.py                             # http://127.0.0.1:8000  (docs at /docs)

# 2. frontend
cd frontend && npm install && npm run dev       # http://localhost:5174
```

`tools/dev.py` loads `.env`, falls back to a local SQLite file under `backend/.data/`,
seeds the demo data if the database is empty, and prints whether the AI layer is live.
Use `--reseed` to reload the demo data and `--check` to print status and exit.

### Turning the AI on

Without a key everything works — the AI panels render labelled deterministic drafts.
To see Claude write the prose:

```bash
cp .env.example .env        # then paste your key into ANTHROPIC_API_KEY
python tools/dev.py --check # should print: ai  LIVE
```

The badges then change from **∑ Deterministic (no AI)** to **✓ Figures verified**. What
does *not* change is where the numbers come from: Claude emits no digits at all, only
placeholder tokens that the engine substitutes with its own values, and every sentence is
checked before display. A draft containing a fabricated figure — or the right figures with
the wrong verdict — is rejected and replaced by the deterministic draft with a badge saying
so. `backend/tests/test_llm_path.py` proves each of those paths with the SDK stubbed.

Two things to know: the standalone `portal.html` can never show live AI, because it is a
static file with no server and no key; and the hosted model is called only while
`EAUDIT_DATA_IS_SYNTHETIC` is true. Production points `EAUDIT_ANTHROPIC_BASE_URL` at an
in-tenant gateway — the single swap point, with no call-site change.

To use Postgres instead of SQLite, run `docker compose up -d db` and set
`EAUDIT_DATABASE_URL` in `.env`.

### The Rulebook
`docs/VAT-Mistakes-Rulebook.md` is the canonical catalogue of taxpayer VAT mistakes the agent
detects (65 rules across 6 families). `tools/build_rulebook_page.py` renders it to the themed
`docs/rulebook-page.html`. The same rules seed `core.rule_library`.

> Demo note: the demo runs on **synthetic data only** and may call the hosted Claude API.
> Production requires an in-tenant / self-hosted model behind the same `LLMService` interface.
