# CLAUDE.md

Guidance for Claude Code (and humans) working in this repository.

## What this is

**E-AUDIT** is an AI-powered **VAT Audit Agent for ZATCA** (the Saudi Zakat, Tax
and Customs Authority), built as a stakeholder demo / proof-of-concept.

It begins **after** an upstream risk engine has flagged a taxpayer + period. From
there it:

1. **Reconstructs** the expected VAT return from the taxpayer's FATOORA
   e-invoices (aggregating `InvoiceTaxSubtotal` by tax category × rate ×
   direction × period).
2. **Reconciles** the reconstruction against the declared return.
3. **Explains** legitimate differences with deterministic rules (credit notes,
   clearance-lag timing, taxpayer-supplied evidence) down to a true **residual**.
4. **Recommends** the next best action and **drafts an auditor report** for a
   human to approve.

Both the **output** (standard-rated sales) and **input** (standard-rated
purchases) VAT boxes are reconstructed as separate reconciliation bridges.

## The core invariant (do not break this)

> The **deterministic Python core computes every number.** Claude writes
> **language only** and never introduces a figure.

- The engine (`backend/app/recon_engine.py`) produces all amounts, residuals,
  and the conclusion (`state`).
- Claude emits **no digits** — only placeholder tokens like `{{residual}}` or
  `{{bridge.COR-01}}`, which the engine substitutes with its exact values.
- Every drafted sentence is checked by `verify_claims` / `verify_conclusion`
  (`backend/app/llm/verify.py`) **before display**; on failure there is a
  corrective retry, then an honest deterministic fallback with a status badge.
- **One exception:** the taxpayer-letter reader (`llm.read_letter`) returns the
  single figure the *letter itself states*, as a **draft** the auditor confirms
  in the UI before it is committed.

All Claude access is funneled through the single boundary
`backend/app/llm/service.py`. Nothing else imports `anthropic`.

## Privacy / safety

- **Synthetic demo data only.** The hosted model is called only when
  `settings.data_is_synthetic` is true (see `availability()` in `service.py`).
- The real taxpayer name is pseudonymized (`"Taxpayer A"`) before egress and
  restored for display. The `purchase` and `combined` sub-results are excluded
  from the model context.
- **Never commit real secrets.** `.env` is git-ignored; `.env.example` holds a
  placeholder key. Put your real `ANTHROPIC_API_KEY` in `.env`.

## Stack & layout

React + TypeScript (Vite) · FastAPI · PostgreSQL (schemas `core` + `recon`).

```
backend/app/
  recon_engine.py     # deterministic reconstruction + bridge (output & input VAT)
  priority.py         # composite case prioritization (exposure/deadline/history/quick-win)
  api/routes.py       # FastAPI endpoints
  models/             # SQLAlchemy models: core.py, config_tables.py, recon.py
  llm/                # the ONLY Claude boundary: service, prompts, verify, schemas
  seed/               # scenarios.py (demo taxpayers) + seed.py (drop/create/load)
frontend/src/
  pages/              # Overview, Reconciliation, Rules
  components/         # AI panels, bridge, taxpayer-response + letter reader
  api.ts, ai/         # typed API + SSE streaming helpers
docs/                 # VAT Mistakes Rulebook (65 rules) + rendered page
```

## Running locally

**1. Database** (Postgres on port **5433**):

```bash
docker compose up -d
```

**2. Backend** (FastAPI on port **8000**):

```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate   # Windows; use bin/activate on macOS/Linux
pip install -r requirements.txt
python -m app.seed.seed                            # drop, create, load 65 rules + demo cases
# The Anthropic SDK reads ANTHROPIC_API_KEY from the environment for AI features:
export $(grep -v '^#' ../.env | xargs)             # or set the vars however you prefer
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Config comes from environment variables (`EAUDIT_` prefix, see
`app/config.py`); the defaults already match `docker-compose.yml`, so only
`ANTHROPIC_API_KEY` needs to be supplied for the AI layer. Without it, the AI
features degrade gracefully to deterministic drafts.

**3. Frontend** (Vite on port **5174**):

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5174.

### Gotchas

- Ports **5433** (Postgres), **8000** (API), **5174** (Vite) are chosen to avoid
  common local collisions (5432/5173).
- The Vite dev proxy targets **`http://127.0.0.1:8000`**, not `localhost`, to
  avoid a Windows IPv6 (`::1`) resolution issue — keep it that way.
- Re-seeding (`python -m app.seed.seed`, or the in-app **Reset demo** button)
  drops and recreates all tables. Synthetic data only.

## Conventions

- Branding is **ZATCA**. Keep the app ZATCA-themed; do not introduce other
  brands.
- Frontend build check: `npm run build` (runs `tsc --noEmit` + Vite build).
- Backend syntax check: `python -m compileall -q app`.
- Guard tests: `pytest backend/tests`.
- When editing the engine, remember: **the numbers live in Python, the words
  live in Claude.** If a change would have Claude produce a figure, route the
  figure through a placeholder instead.
