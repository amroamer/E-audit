# CLAUDE.md

Guidance for Claude Code (and humans) working in this repository.

## What this is

**E-AUDIT** is an AI-powered **VAT Audit Agent for ZATCA** (the Saudi Zakat, Tax
and Customs Authority), built as a stakeholder demo / proof-of-concept.

It begins **after** an upstream risk engine has flagged a taxpayer + period, and
runs the case from there to a drafted conclusion. Five stages
(`backend/app/casefile/orchestrator.py`):

1. **Intake** — assemble the *dossier*: everything ZATCA already holds on this
   taxpayer and period (returns, e-invoices, imports/exports, financials, prior
   audits, filing history, the structured risk referral).
2. **Planning** — retrieve *precedent* (what comparable closed cases turned out
   to be, and which evidence actually closed them) and build a request plan.
   Anything the Authority already holds is dropped, with the reason attached.
3. **Request & response** — draft the letter, then compare what arrives against
   what was asked for: missing columns, blank mandatory fields, period coverage,
   totals that do not foot. Draft the follow-up from the gaps alone.
4. **Substantive review** — decide which FATOORA e-invoices *qualify* for the box
   and the period, sum them into an **expected** return, compare that against
   what was **declared**, account for the taxpayer's evidence, and let the
   investigation agents propose root causes for a deterministic adjudicator to
   settle whatever is left **unexplained**.
5. **Closure** — draft the audit report and the taxpayer letter for approval.

Both the **output** (standard-rated sales) and **input** (standard-rated
purchases) VAT boxes are qualified and compared separately.

The stage machine is **derived, never stored** — every state follows from the
case's own data — and **no stage advances by itself**. A case the internal
evidence settles skips stages 2 and 3 entirely and reports that the taxpayer was
never contacted, which is the product's central claim.

## Qualify, then sum (do not invert this)

> The rules decide **which documents count**. They do not subtract from a total,
> and they never "explain a gap".

Every e-invoice line is walked through the rule stages *before* anything is
added up (`pipeline/run.py`). A line either **qualifies** for this box and this
period, or it does not — and if it does not, exactly one rule is on record as
the reason. Only the survivors are summed:

```
Σ qualifying lines        = expected
expected − declared       = difference
difference − evidence     = unexplained      (evidence = what the taxpayer showed)
```

There is deliberately **no pre-qualification total**. A "reconstructed from
e-invoices" figure taken before the rules run would correspond to nothing real:
it would have to include documents the rules place in another period and exclude
documents the rules admit, purely so a waterfall could be drawn from it. A
clearance-lag invoice was never in the period, so it is not a deduction — it is
a line in the **funnel** that says why it is not there.

The funnel is therefore a *partition of the population*, not a bridge:
population → one step per rule that set documents aside (count + amount) →
qualifying count and amount. `Composition` then says what the qualifying set is
made of, by document type. `compose()` in `pipeline/run.py` builds both; the UI
shows the funnel as the hero and the three-way comparison beneath it.

## The core invariant (do not break this)

> The **deterministic Python core computes every number.** Claude writes
> **language only** and never introduces a figure.

- The engine (`backend/app/recon_engine.py`) produces every amount and count, and
  the conclusion (`state`).
- Claude emits **no digits** — only placeholder tokens, which the engine
  substitutes with its exact values. The vocabulary is deliberately short and
  lives in `_SCALAR_KEYS` / `placeholder_values()`: `{{declared}}`,
  `{{expected}}`, `{{difference}}`, `{{evidence_total}}`, `{{unexplained}}`,
  `{{materiality}}`, `{{qualifying_count}}`, `{{population_count}}`, plus
  `{{step.OUT-07}}` / `{{step.OUT-07.count}}` for each funnel step and
  `{{evidence.CODE}}` for each item of taxpayer evidence. A rule that sets no
  documents aside has **no token at all** — there is no amount for it to name.
- Every drafted sentence is checked by `verify_claims` / `verify_conclusion`
  (`backend/app/llm/verify.py`) **before display**; on failure there is a
  corrective retry, then an honest deterministic fallback with a status badge.
- **Outbound letters** (request, follow-up, verdict) quote *documents* rather
  than reconciliation scalars, so the placeholder model does not fit them.
  `verify_correspondence` enforces the same rule in substance: every numeric
  literal in the draft must already appear in the engine-authored facts block.
  Claude may repeat a figure it was handed; it may not introduce one.
- **One exception:** the taxpayer-letter reader (`llm.read_letter`) returns the
  single figure the *letter itself states*, as a **draft** the auditor confirms
  in the UI before it is committed.

All Claude access is funneled through the single boundary
`backend/app/llm/service.py`. Nothing else imports `anthropic`.

Every deterministic fallback is **complete, sendable output**, not a stub —
degrading to it costs polish, never correctness. That is why the whole app,
including the letters and the investigation, works with no API key.

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
  casefile/            # the five-stage lifecycle machine (derived, never stored)
  dossier/             # everything ZATCA already holds, assembled in one call
  precedent/           # deterministic retrieval + tally over labelled closed cases
  requests/            # the request/response loop:
                       #   catalog.py      what an auditor can ask for (+ satisfied_by)
                       #   planner.py      what to ask for — and what NOT to (§1)
                       #   extract.py      xlsx/csv -> columns, rows, stated totals
                       #   completeness.py requested vs received, deterministically
                       #   service.py      drives the rounds; recomputes gaps each pass
  pipeline/            # predicates.py (Python ⇄ SQL algebra) + rules.py + run.py
  recon_engine.py      # qualify -> expected -> compare with declared (output & input VAT)
  rule_taxonomy.py     # explanation/mistake/risk + precedence stage + difference reason codes
  risk_indicators.py   # the risk-engine vocabulary + which internal source to consult first
  scope.py             # what this PoC reconciles, and what it deliberately leaves out
  priority.py          # composite case prioritization (exposure/deadline/history/quick-win)
  agents/              # contracts, adjudicator, detectors, orchestrator (rounds),
                       # precedent_analyst, correspondence (request/follow-up/verdict)
  api/routes.py        # FastAPI endpoints
  models/              # core.py, dossier.py, casework.py, config_tables.py, recon.py
  llm/                 # the ONLY Claude boundary: service, prompts, verify, schemas
  seed/                # scenarios.py + dossier_seed.py + corpus.py + casework_seed.py
frontend/src/
  pages/               # Overview, Dossier, Casework, Reconciliation, Rules
  components/          # lifecycle rail, case tabs, precedent, AI panels, funnel, letters
  api.ts, ai/          # typed API + SSE streaming helpers
docs/                  # VAT Mistakes Rulebook (66 rules) + rendered page
portal.html            # standalone no-backend build of the workbench (see below)
```

A case is worked left to right through three tabs — **Dossier** (what we hold),
**Casework** (what we ask for and chase), **Reconciliation** (what it means) —
with the lifecycle rail on each showing where the case is and whose move it is.

## The rule taxonomy (do not collapse this back)

The rulebook's 66 entries are three different kinds of object, and the engine
depends on the distinction:

- **explanation** — a legitimate reason a document does not belong in this box or
  this period (credit notes, tax-point timing). Changes **which documents
  qualify**, and so changes the expected figure itself.
- **mistake** — a taxpayer error. Becomes a **finding**.
- **risk** — a behavioural or data-quality signal. Feeds **prioritisation only**,
  and must never change which documents qualify.

Each rule also carries a `stage` (its place in the population → identity → status
→ tax-point → category → adjustment → aggregation → timing → materiality → risk
precedence) and a `reason_code` describing *which class of difference* it is about.
Reason codes describe the phenomenon; `kind` carries the verdict.

Rules are declared in `pipeline/rules.py`, not hard-coded in the engine.
**Wiring a rule into the live engine means appending one `QualificationRule`** —
the engine, the API's `wired` flag and the UI's "● live" badge all follow from it.
Guarded by `backend/tests/test_rules.py`.

A rule may be **scoped** by `direction`, `sectors` or `counterparty_class`,
because the expected relationship is not the same for every taxpayer — a
government supply may not be recognised until it clears the procurement platform,
months after the transaction period (OUT-11). The scope lives *inside* the
predicate, so it travels into `sql_when()`: a scope applied only in Python would
mean the batch path silently ran the rule on every taxpayer, which is the one bug
the predicate algebra exists to prevent. `test_pipeline.py` asserts the two agree.

## The standalone portal

`portal.html` is a single self-contained build of the workbench — no backend, no
database, no build step. It ports `theme.css` verbatim and re-implements the
deterministic core in JavaScript over the seeded demo data, so the qualification
funnel, the rulebook toggles and the taxpayer-response loop still recompute in
the browser — toggling a rule re-runs `qualify()` and moves the expected figure.
Its AI panels show the same deterministic fallbacks the app renders with no API
key.

Its rule is **port what the user can change, embed what they cannot.** The
reconciliation, priority, investigation and the lifecycle rail all move when a
rule is toggled or a taxpayer response is recorded, so they are ported to JS. The
dossier, precedent and the seeded correspondence round cannot move without a
backend — there is nothing to upload and no corpus to re-search — so the Python
output is embedded exactly. That is precision, not a shortcut, and the split
should stay explicit.

If you change the engine, the seed data or the rule taxonomy, regenerate it — the
JS port is validated field-by-field against the Python engine's output (currently
12,639 comparisons, 0 failures).

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
- Guard tests: `pytest backend/tests` (134 at last count).
- When editing the engine, remember: **the numbers live in Python, the words
  live in Claude.** If a change would have Claude produce a figure, route the
  figure through a placeholder instead — or, for outbound letters, put it in the
  facts block so `verify_correspondence` will accept it being repeated.
- **Qualify, then sum.** If a change would introduce a total taken before the
  rules run, or word a rule as subtracting from one, it is the wrong shape — the
  rule decides which documents are in the box, and the sum follows.
- **Deterministic first, model second.** Anything checkable is a check: column
  presence, blank fields, period coverage, whether a total adds up. Only
  genuinely judgement-shaped questions go to a model, and they are checked after.

## Inputs still needed from the auditors

- The **audit report template** — the closure drafter should target the real
  layout, not ours.
- A **real (redacted) information request** — it defines `required_columns`, and
  the completeness checker is only as good as that spec.
- The **risk indicator codes** the engine actually emits. Ours in
  `risk_indicators.py` are placeholders, and the precedent corpus is generated
  against them.
