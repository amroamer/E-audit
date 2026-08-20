# CLAUDE.md

Guidance for Claude Code (and humans) working in this repository.

## What this is

**E-AUDIT** is an AI-powered **VAT Audit Agent for ZATCA** (the Saudi Zakat, Tax
and Customs Authority), built as a stakeholder demo / proof-of-concept.

It begins **when the taxpayer's documents arrive**. Planning is deliberately out of
scope: the client does not supply risk-engine output, a pre-computed reconciliation,
a taxpayer-history feed or a corpus of similar cases, and the request has already
gone out in the auditor's own words before the app sees the case. Everything the
PoC needs is in the files the taxpayer sent.

Two jobs, in order:

1. **Did we get what we asked for?** The auditor pastes the email they sent; it is
   parsed into a checkable spec (`requests/from_email.py`) which they confirm. The
   uploaded spreadsheets are compared against it — missing items, missing columns,
   blank mandatory fields, period coverage, totals that do not foot — and the chase
   email is drafted from the gaps alone.
2. **What does it mean?** The engine decides which uploaded lines *qualify* for the
   box and the period, sums them into an **expected** return, and compares that with
   what was **declared**. Four agents then propose findings for a deterministic
   adjudicator to settle, and the verdict email and audit report are drafted from
   whatever it confirms.

Both the **output** (standard-rated sales) and **input** (standard-rated purchases)
VAT boxes are qualified and compared separately.

**Two things survived the scope cut**, because the work needs them and they live on
the Intake page rather than in the dossier: the registration's **economic activities**
(revenue matching none of them is the undisclosed secondary-activity outcome, which is
unreachable without the list) and the **audit history** (a repeat of a prior root cause
is the first thing an auditor checks).

Planning, precedent retrieval, risk-engine ingestion and the request planner are
**dormant, not deleted** — `app/precedent/`, `app/risk_indicators.py` and
`app/requests/planner.py` still work and are still tested. Scope has moved twice; they
are cheap to keep and expensive to rebuild.

## The outcome vocabulary (do not paraphrase these)

> An agent raises an outcome **code**. The Authority's own sentence is what gets
> written down.

`app/outcomes.py` holds the auditors' fifteen finding statements verbatim, de-duplicated
to **twelve** distinct outcomes (their 6 and 15 are identical; 8 and 14 differ by two
words; 1 states as non-deductibility what 8/14 state as exclusion). `client_refs` records
the mapping and `test_outcomes.py` asserts all fifteen are covered.

Nothing is phrased ad hoc at a call site. An agent's `claim` is exploratory language
written to be tested and **never goes outbound**; only the vocabulary statement reaches a
report or a taxpayer letter. Outcome statements carry no digits — the amount is computed
by the adjudicator and travels alongside, never interpolated into the sentence.

## Findings rest on evidence, not on tests

A confirmed hypothesis with an `outcome_code` becomes a `Finding` (`agents/findings.py`).
Each one carries a **basis** declared by the adjudicator: the evidence it rests on.

This is not bookkeeping. A sales listing above the return is simultaneously "higher than
declared", "not disclosed", "does not correspond" and — with no trial balance — the
fourth variant, all from **one test over one file**. Summing them reported SAR 1,854,000
against a real excess of SAR 618,000, and the taxpayer letter stated the same figure four
times. So `exposure()` counts each basis once, documentation risk excludes evidence
already producing an adjustment, and the letter states each amount once with the
alternative readings named beneath it.

The basis comes from the *adjudicator*, not the test name: `trial-balance-absent`
delegates to `listing-vs-declared` and must share its basis or the excess is counted twice.

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
  outcomes.py          # the auditors' finding statements — the ONLY outbound wording
  casefile/            # the lifecycle machine (derived, never stored)
  dossier/             # everything ZATCA already holds, assembled in one call
  precedent/           # deterministic retrieval + tally over labelled closed cases
  requests/            # the request/response loop:
                       #   catalog.py      what an auditor can ask for
                       #   from_email.py   recover the spec from the email that was sent
                       #   planner.py      DORMANT — planning is out of scope
                       #   extract.py      xlsx/csv -> columns, rows, stated totals
                       #   completeness.py requested vs received, deterministically
                       #   service.py      drives the rounds; recomputes gaps each pass
  pipeline/            # predicates.py (Python ⇄ SQL algebra) + rules.py + run.py
                       #   source.py       lines from an uploaded listing, not the feed
  recon_engine.py      # qualify -> expected -> compare with declared (output & input VAT)
  rule_taxonomy.py     # explanation/mistake/risk + precedence stage + difference reason codes
  risk_indicators.py   # the risk-engine vocabulary + which internal source to consult first
  scope.py             # what this PoC reconciles, and what it deliberately leaves out
  priority.py          # composite case prioritization (exposure/deadline/history/quick-win)
  agents/              # contracts, adjudicator, orchestrator (rounds), correspondence
                       #   roster.py          the four agents
                       #   document_tests.py  how each is settled over the rows
                       #   findings.py        confirmed -> the Authority's wording
                       #   calculation.py     the closed query algebra
                       #   calc_service.py    ask / check, persisted
  api/routes.py        # FastAPI endpoints
  models/              # core.py, dossier.py, casework.py, config_tables.py, recon.py
  llm/                 # the ONLY Claude boundary: service, prompts, verify, schemas
  seed/                # scenarios.py + dossier_seed.py + corpus.py + casework_seed.py
frontend/src/
  pages/               # Overview, Intake, Dossier, Casework, Reconciliation, Rules
  components/          # lifecycle rail, case tabs, AI panels, funnel, findings,
                       # calculations, step emails
  api.ts, ai/          # typed API + SSE streaming helpers
docs/                  # VAT Mistakes Rulebook (66 rules) + rendered page
portal.html            # standalone no-backend build of the workbench (see below)
```

A case is worked left to right through four tabs — **Intake** (who they are, what
arrived), **Dossier** (what ZATCA holds), **Casework** (the request/response loop),
**Reconciliation** (what it means) — with the lifecycle rail on each showing where the
case is and whose move it is. Under the current scope Intake and Reconciliation carry
the work; Dossier and Casework are the dormant planning-era screens.

## The four agents (and what they may not do)

`app/agents/roster.py`. The auditors named three and left the fourth to us; the fourth is
**Evidence & Coverage**, because five of their fifteen statements are its territory.

| Agent | Owns |
|---|---|
| **Regulations** | not entitled to deduct · valid tax invoice conditions · valid credit note conditions |
| **Data Entry** | decimal shift, transposition, out-of-character magnitude |
| **Calculation** | listing exceeds declared · POS/bank exceeds declared · undisclosed sales · unreproduced auditor figures |
| **Evidence & Coverage** | missing supporting documentation · lack of cooperation · documents do not correspond · no trial balance · **undisclosed secondary activity** |

Every one obeys the original contract: it returns a `Hypothesis` carrying **language only**
plus a typed `TestSpec`, and `agents/document_tests.py` settles it deterministically over the
uploaded rows. **No agent states a figure and no agent reaches a conclusion.**

Two fields carry weight:

- **`why`** — the observation that triggered the hypothesis. An auditor has to defend a finding
  to a taxpayer, and "an agent proposed it" is not a defence, so the trigger is recorded next to
  the claim and shown beside the verdict.
- **`outcome_code`** — the vocabulary entry this becomes *if confirmed*. The only route from an
  agent to the words in a report.

**An agent proposes nothing when its preconditions are absent.** Silence is correct behaviour:
a hypothesis that can only ever return "insufficient evidence" wastes the auditor's attention.
"Insufficient evidence" is itself a real verdict — a column that is not there cannot be tested,
and saying so beats a confident answer computed from nothing.

**There is one keying specialist.** `detectors.data_entry_forensics` is out of the roster
because the new Data Entry agent is the same specialist under the name the auditors gave it;
running both put duplicate DE-01s on the case file. `test_roster.py` checks the *combined*
roster for id collisions — each roster was unique on its own, which is how that got through.

## The auditor's own arithmetic

`app/agents/calculation.py` answers questions off the uploaded documents and checks figures the
auditor worked out by hand. **The model never does arithmetic**: it translates a described
method into a `CalcQuery` from a closed algebra, and Python executes it. A misread method
therefore surfaces as a visible wrong query, never as a wrong number wearing the engine's
authority.

- A method outside the algebra is reported **not-checkable** rather than approximated by a query
  that answers something else.
- With several documents on a case and none named, the agent **asks which** rather than
  defaulting to the largest table. Answering a sales question off the purchase listing is
  precisely the error this agent exists to catch.
- An auditor-supplied query is used verbatim and never sent to a model — there is nothing to
  interpret, and interpreting it anyway would only add a way to get it wrong.

## Where the lines come from

`app/pipeline/source.py`. The taxpayer's uploaded listing **is** the population; the e-invoice
feed is the fallback for cases with no upload. What a spreadsheet cannot say is stated rather
than assumed:

- **No clearance status** — every row is `reported`, never `cleared`.
- **Usually no delivery date**, so the tax-point rules simply never match. They are not assumed
  satisfied; the funnel shows no timing step, which is the honest reading. A listing that *does*
  carry delivery dates fires them normally.
- **No counterparty class**, so the government-platform rule cannot fire.

Fewer rules can act on a listing than on an e-invoice feed, so the expected figure sits closer
to the raw total. That is a property of the evidence, not a weakness in the engine.

A row with no readable VAT amount is **skipped, not summed as zero** — a blank cell is a
completeness defect the checker already reports, and counting it as nothing would quietly shrink
the expected figure. The UI names the document the figures came from, and when the response
still has blocking gaps the figure is labelled a **floor** rather than a settled expected
return.

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
funnel, the rulebook toggles, the four agents, the findings and the taxpayer-response
loop all still recompute in the browser — toggling a rule re-runs `qualify()` and moves
the expected figure, and a figure you record is recomputed from the embedded rows the
same way Python recomputes it.
Its AI panels show the same deterministic fallbacks the app renders with no API
key.

Uploading is the one thing a static file cannot do, so the received documents are embedded
**with their rows** — which is what lets the source seam, the agents and the calculation
panel all work offline.

Its rule is **port what the user can change, embed what they cannot.** The
reconciliation, priority, investigation and the lifecycle rail all move when a
rule is toggled or a taxpayer response is recorded, so they are ported to JS. The
dossier, precedent and the seeded correspondence round cannot move without a
backend — there is nothing to upload and no corpus to re-search — so the Python
output is embedded exactly. That is precision, not a shortcut, and the split
should stay explicit.

If you change the engine, the seed data or the rule taxonomy, regenerate it — the
JS port is validated field-by-field against the Python engine's output (currently
12,713 comparisons, 0 failures).

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
- Guard tests: `pytest backend/tests` (238 at last count).
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
- **The regulations articles.** The Regulations agent is cite-or-drop: it may not assert a
  condition without an article behind it. It currently runs the *conditions* checks (field
  presence, which is deterministic) and a small explicit list of blocked expense categories in
  `agents/document_tests.py:BLOCKED_TERMS`. That list is a placeholder for the real corpus —
  when the articles land it becomes a lookup against them, which is data, not code.
- A **real (redacted) request email.** `requests/from_email.py` is written against a
  conventional one; the cue table is only as good as the phrasing auditors actually use.
