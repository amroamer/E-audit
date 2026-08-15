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
# 1. database
docker compose up -d db

# 2. backend
cd backend
python -m venv .venv && . .venv/Scripts/activate   # Windows; use bin/activate on *nix
pip install -r requirements.txt
python -m app.seed.seed            # create schemas/tables + load rules + seed demo cases
uvicorn app.main:app --reload      # http://localhost:8000  (docs at /docs)

# 3. frontend
cd ../frontend
npm install
npm run dev                        # http://localhost:5173
```

### The Rulebook
`docs/VAT-Mistakes-Rulebook.md` is the canonical catalogue of taxpayer VAT mistakes the agent
detects (65 rules across 6 families). `tools/build_rulebook_page.py` renders it to the themed
`docs/rulebook-page.html`. The same rules seed `core.rule_library`.

> Demo note: the demo runs on **synthetic data only** and may call the hosted Claude API.
> Production requires an in-tenant / self-hosted model behind the same `LLMService` interface.
