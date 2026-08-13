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
backend/    FastAPI app, data model, seed data
frontend/   React (Vite) ZATCA-themed workbench
docs/       VAT Mistakes Rulebook (markdown + rendered page)
tools/      build scripts (rulebook page generator)
```

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
