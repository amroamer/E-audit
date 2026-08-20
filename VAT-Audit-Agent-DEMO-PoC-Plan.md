# DEMO POC PLAN — AI VAT Audit Agent
### KPMG × ZATCA | React + FastAPI + PostgreSQL | Claude-powered stakeholder demo

> **Superseded in part — historical planning record.** The reconciliation framing below
> ("apparent gap", "explained by rules", the bridge/waterfall) was **retired**: rules decide
> *which documents qualify*, and the expected figure is the sum of the ones that do. There is
> no pre-qualification total and nothing is "explained away". See **Qualify, then sum** in
> `CLAUDE.md` for what the build actually does. The stage-by-stage demo choreography and the
> attribution claim below still hold.

**The one sentence this build proves:** a business viewer watches a single flagged case — *Al-Faisaliah Trading* — walk from Intake to Approve (steps 1→9) on screen; sees the agent decide **which of the 27 sale documents on file actually qualify** for the period (25 do; two are supplies of the next quarter), sum them to **SAR 2,075,000** against a declared **SAR 2,000,000**, and put the **SAR 75,000 difference** in front of the auditor; watches **Claude write the audit report live**; and sees, at four clearly-labelled points, that *Python computed every number and Claude only wrote the words* — with **no AI-produced figure ever touching the difference**.

Storytelling and tie-out beat edge-case coverage. Every mocked part is labelled on screen — honesty is a feature, not an apology. The binary attribution claim (**violet = Claude wrote it · slate ∑ = Python computed it**) is now literally true everywhere on screen, because no Claude call in the demo emits a number that moves a total.

---

## 1. What changes vs. the existing plan

The existing `VAT-Audit-Agent-Build-Plan.md` is an excellent **production** architecture and a poor **demo** plan: it optimizes for defensibility under litigation (hash-chained logs, 4-schema PDPL segregation, real-data validation gates, party-link sockets) — none of which a non-technical exec sees — while the three things a stakeholder demo lives on (a scripted narrative, an animated "gap collapses to residual" moment, visible AI attribution) are absent or buried. The fix is **additive UX + seed-data staging on top of a ~40% thinner backend**, not a rebuild.

### The one contradiction to resolve first
The plan mandates an **in-tenant/self-hosted LLM** and *forbids* the cloud SDK (§3, §7.2, §7.6-#3). The confirmed pivot locks us to the **hosted Anthropic Claude API** (`claude-opus-5`) on synthetic data. **Resolution:** the demo calls the hosted API on synthetic data only; the in-tenant runtime is deferred to production and stated honestly on the PDPL slide. Every plan sentence mandating in-tenant hosting is re-scoped to "production requirement." This is the highest-leverage correction — it silently unblocks all four AI features.

### The AI boundary is now architecturally clean (the biggest correction to the draft)
An earlier draft had Claude *read a filing note and extract SAR 45,000 of VAT that moved the residual 75k→30k* — a fifth, PII-touching capability that directly contradicted "Claude never introduces a number." **That is removed.** The deterministic rules take the residual to its true value (**SAR 75,000**) with no AI arithmetic; Claude's four features remain purely linguistic. The Evidence-viewer beat now shows the **deterministic source documents** behind the bridge lines (credit notes, delivery-date metadata, export evidence) — no AI extraction, no residual movement. Result: "94% explained" becomes an honest **84% ((480−75)/480)**, and the violet/slate legend survives an SME grilling because it is now factually exact.

### What we ADD (the demo layer)
| Add | Why |
|---|---|
| **Hero-case narrative + presenter script** (Al-Faisaliah = scenario E, one taxpayer) | Without a story there is no demo; everything hangs off this |
| **Two new screens:** N1 Executive Overview / "Command Deck" + N2 Case Cockpit / Flow Map | Frame the whole 9-step journey and the AI story in 20 seconds; give execs a closing "so what" |
| **Animated bridge waterfall + shrinking-residual counter** | The single most persuasive visual — the emotional payoff, now driven entirely by deterministic lines |
| **Step-3 tie-out card + Step-7 conclusion beat** (on the main path, not buried in a drill) | Give the load-bearing deterministic steps visible on-screen substance |
| **AI-attribution system:** the "AI Lens" toggle + violet "AI" chips vs slate "∑ computed" chips + a fixed legend | Makes "Python computes, Claude writes" literally visible — and now literally true |
| **`verify_claims()` surface applied to ALL prose** + provenance-on-click | Strongest "the AI can't lie" proof, extended beyond the report |
| **Real-vs-Simulated honesty badges** (`● Real` / `◐ Simulated`) | Converts the party-link/notes liabilities into SME trust |
| **Depth toggle** (Business view ↔ Auditor view) | One build serves execs *and* survives an SME grilling |
| **Value tiles on N1** (auditor-hours saved, % cleared zero-contact, contacts avoided) | The ROI-to-ZATCA question an exec asks in the first 60 seconds |
| **Arabic UI chrome + one bilingual report section** | Zero Arabic in front of a ZATCA/KSA audience is a needless credibility gap |
| **Guided/presenter mode + Reset control + pre-validated offline stream fixture** | De-risks the live run |

### What we CUT or DEFER (production hardening no viewer perceives)
| Cut/defer | Disposition |
|---|---|
| In-tenant LLM runtime | **Defer** (production); keep only the honesty slide |
| Immutable hash-chained `audit.action_log` + insert-only triggers | **Simplify** → plain append-only `recon.event_log` |
| 4-schema separation (`stg`/`core`/`config`/`audit`) | **Simplify** → **2 schemas** (`core`, `recon`) |
| Full Phase-8 validation harness, 7-metric scorecard, Gold/Silver/Bronze, bootstrap CIs | **Cut**; keep one `verify` self-check that reconstruction + **each bridge line** ties to seed |
| Process mining (PM4Py) + learned family→`ROOT_CAUSE_CODE` crosswalk | **Cut**; mock the `nba_prior` benchmark strip with seeded numbers |
| Config-driven JSONB rule engine + full 12-rule pack + precedence tiers | **Simplify** → **8 real deterministic rules + hygiene checks** (see §4) |
| Party-link resolver / `DirectionResolver` abstraction | **Mock** — seed `direction` directly onto invoices |
| Celery/RQ workers + `202 + job_id` polling + durable `AWAIT_TAXPAYER` waits | **Cut** — synchronous FastAPI; SSE only for streamed prose |
| Idempotent ingest envelope (`source_row_hash`, `ingest_batch_id`) | **Cut** — plain truncate-and-reload seed script |
| **Evidence/notes AI extraction** | **Cut from demo** (was the boundary-violating fifth feature); deferred, PII-gated in production |
| **Two-breakpoint prompt cache + silent-invalidator discipline** | **Demote** → a single optional breakpoint kept only for the slide claim; off the critical path (§6.2) |
| PII segregation tables + column grants | **Cut**; show `BP_CONTACT_*` masked as a design signal only |
| 14-section report | **Simplify** → ~6 sections |
| Docker stack (`api`,`worker`,`postgres`,`redis`,`react`,`model-runtime`) | **Simplify** → `api` + `postgres` + `react` |

**Net:** keep the load-bearing spine — reconstruction, the bridge, the 4 Claude features, the workbench screens. Delete the litigation-grade backend. Every cut maps to a labelled socket in the production plan, so the demo promotes cleanly toward production without rework.

---

## 2. The demo PoC in one picture

```
                 THE HERO CASE — Al-Faisaliah Trading Co.  (= scenario E)
   Reconstructed output VAT (Σ from e-invoices)   SAR 2,480,000   [Rebuilt]
   Declared (as-filed-at-referral)                SAR 2,000,000   [Declared]
   ────────────────────────────────────────────────────────────
   APPARENT GAP  (Rebuilt − Declared)             SAR   480,000   ← "looks like evasion"

   Reconciliation identity shown live:
        Rebuilt − Declared  =  Σ(reconciling items)  +  Residual
        480,000             =  405,000               +  75,000

        │  each line labelled by SIDE, so it cannot double-count:
        │  −210,000  COR-01  credit notes      [Declared-side]  prior-period / UNLINKED
        │                                        CNs applied to the return, NOT in Rebuilt
        │   −95,000  TIM-04  clearance lag      [Rebuilt-side]   issued in-period,
        │                                        delivered/cleared Q+1 → belong to next period
        │   −40,000  TIM-05  prepayments (386)  [Rebuilt-side]   VAT already declared prior period
        │   −60,000  TRT-04  export reclass     [Rebuilt-side]   reconstructed at 15%,
        ▼                                        valid export evidence = 0%
   TRUE RESIDUAL (deterministic)                  SAR    75,000   ← POTENTIAL-FINDING, DIFF_TAX_AMT
   84% of the flagged gap was legitimate — proven from data the taxpayer already gave us,
   with zero AI arithmetic. Every line above is a Python rule; Claude never touched a number.
```

**Why the SIDE labels matter (the SME's first question):** credit notes of type 381 that are in-period and linked are *already netted inside* the 2,480,000 Rebuilt figure and therefore are **not** a bridge line — netting them again would double-count. The COR-01 bridge line is deliberately seeded from **prior-period / UNLINKED credit notes** that the taxpayer legitimately applied to *this* return but that reconstruction does **not** capture (Rebuilt only sums this-period linked invoices). Subtracting them is a **Declared-side** correction and is provably not a double-count. TIM-04, TIM-05 and TRT-04 are **Rebuilt-side** over-inclusions removed from the reconstruction. The Box-by-box drill states each line's side explicitly so the identity defends live.

**Scope that is REAL:** the seed generator (tie-out oracle, now asserting *each line* not just the residual), reconstruction (`recon.rebuilt_box` — one `GROUP BY` over `invoice_taxsubtotal`), the bridge/residual, the 8-rule library, the 4 Claude calls, `verify_claims` (applied to all prose), and the polished React workbench.
**Scope that is MOCK (labelled):** invoice→party direction (seeded column), the "send request" action, the immutable log (plain append-only). No synthetic-notes-content is read by Claude in the demo — that path is deferred.

The full-flow story we show: **five of six flagged cases resolve with zero taxpayer contact; only the hero (E) generates a single, precisely-scoped request** — a live, per-case demonstration of the "minimize taxpayer requests" objective, backed by real `nba_recommendation` rows, not assertion. Because the hero **is** one of the six scenarios, the N1 "5 of 6 avoided" stat counts the exact case on screen.

---

## 3. Screen inventory + demo script

### Screen inventory (8 workbench screens re-ranked; 2 new demo-first surfaces; 1 demoted)
⭐⭐⭐ hero stop · ⭐⭐ supporting · ⭐ on-demand SME proof

| # | Screen | Flow step | Status | The ONE thing it makes obvious | AI touchpoint |
|---|---|---|---|---|---|
| **N1** | **Executive Overview / "Command Deck"** | portfolio | ⭐⭐⭐ NEW | "The agent triages the whole book — X auditor-hours saved, Y% cleared with zero contact, Z contacts avoided; AI runs at ~$0.20/case." | Aggregate AI stats |
| **N2** | **Case Cockpit / Flow Map** | all 9 | ⭐⭐⭐ NEW | "The entire lifecycle on one screen; here's where we are." 9-node rail + `480k→75k` hero band + 4 AI pins | Shows all 4 AI markers |
| 1 | **Case Queue / Inbox** | 1 INTAKE | ⭐⭐ | "A flagged case just arrived, with a machine reason." | — |
| 2 | **Taxpayer-360** | 2 ASSEMBLE | ⭐⭐⭐ | "In 3 seconds the agent read years of history." | **AI #4** taxpayer brief |
| **3a** | **Reconstruct tie-out card** | 3 RECONSTRUCT | ⭐⭐⭐ | "12 invoices → Σ TAXSUBTOTAL = SAR X = Box 6. The machine computed it, in the open." | — (deterministic proof, on main path) |
| 3 | **Reconciliation Bridge (waterfall)** | 4 RECONCILE | ⭐⭐⭐ **HERO** | "The scary gap dissolves into named, legitimate reasons — watch it shrink." | **AI #2** bridge narration (qualitative only) |
| 4 | **Box-by-box drilldown** | 4 RECONCILE | ⭐ drill-tab | "Every number ties out, box by box — and each bridge line's side is labelled." | — (deterministic proof) |
| 5 | **Evidence viewer** | 5 INVESTIGATE | ⭐⭐ | "Here are the taxpayer's own source documents behind each line." | **None in demo** (AI note-read deferred) |
| 6 | **NBA panel** | 5–6 INFO REQUEST | ⭐⭐⭐ | "Exhausted internal evidence first, then asks for exactly ONE document — human-gated." | **AI #3** request phrasing (qualitative only) |
| 7 | **Draft-report review** | 8 DRAFT | ⭐⭐⭐ **HERO** | "Watch the agent write the report live — it cannot invent a number." | **AI #1** streamed report + `verify_claims` |
| 8 | **Action-trail timeline** | 9 APPROVE | ⭐⭐ | "Every step — AI, math, human — is logged and replayable." | AI-call rows |

**Demoted/folded:** Box-by-box is a "Prove it ▸" drill inside the Bridge. Process-mined variant graph → Auditor-view-only tab. **For the MVD, the Evidence viewer folds into the Bridge segment-click and Box-by-box folds into the Bridge from day one** (see §8) — they are cut-candidates, the two HERO screens are not.

### The presenter script (hero case, ~6–8 min, click-by-click)

**Beat 1 — INTAKE (Case Queue).** One row pulses "Just referred," showing `CASE_REASON_CODE`, `RISK_CATEGORY = output-under-declaration`, `VAT_PRIORITY`. *"A risk engine upstream flagged this taxpayer. The agent's job begins after the flag."* → click into **Case Cockpit**.

**Beat 2 — the map (Case Cockpit).** The 9-node rail animates in; only step 1 is green; hero band reads **Apparent gap SAR 480,000**. *"This is the whole audit on one screen. Watch it fill in."*

**Beat 3 — ASSEMBLE + AI #4 (Taxpayer-360).** Structured `tp` fields (`ACCOUNTING_METHODE`, `BP_RESIDENT_FLAG`, `IND_SECTOR`, `BUSINESS_SIZE`) snap in; the **AI Brief** types itself in 4 sentences. **Turn the AI Lens ON here** — the brief glows violet, the fields stay slate. *"Everything violet is Claude; everything grey is math. Keep that split — it's the whole safety story, and you will not see it broken once."*

**Beat 4 — RECONSTRUCT + tie-out card (Cockpit step 3, screen 3a).** Not a spinner: a compact card animates in — **"12 invoices → Σ TAXSUBTOTAL = SAR 2,480,000 = Box 6 (Rebuilt)"** — with the invoice count, the summed taxable/VAT, and the box it lands in. Honesty badge: `◐ direction simulated`. *"This is the load-bearing step. The machine rebuilt Box 6 straight from the e-invoices, in the open — no taxpayer involved, no AI involved. That grey ∑ has substance."*

**Beat 5 — THE BRIDGE (hero #1).** The waterfall builds left-to-right; each reconciling item drops a step (credit notes, timing lag, prepayment, export reclass), each tagged with its **side** ([Declared-side] / [Rebuilt-side]). A corner **Residual counter** ticks `480k → 270k → 175k → 135k → 75k`. The AI #2 narration writes itself alongside — **explaining *why each difference is legitimate and what the auditor should conclude*, not restating the printed numbers**. *"That 480,000 looked like evasion. It isn't — and the agent explained 405,000 of it, from data in hand, without asking the taxpayer for anything, and without an AI ever computing a figure."*

**Beat 6 — the evidence behind the lines (Evidence viewer, deterministic).** Click any bridge segment → the source documents open: the type-381 credit notes, the `ActualDeliveryDate`/`STATUSCODE` metadata proving the timing lag, the export evidence behind the reclass. **No AI, no number moves.** *"Every line you just saw is backed by the taxpayer's own documents. The agent read them deterministically — this is evidence, not inference."*

**Beat 7 — CONCLUDE (Cockpit step 7 beat).** A one-line beat, on the main path: **residual SAR 75,000 → POTENTIAL-FINDING → Proposed Adjustment `DIFF_TAX_AMT` SAR 75,000**; penalty shown as human-entered. Cockpit hero band updates: **Apparent 480,000 → True residual 75,000 (84% explained)**. *"So 1→9 never skips: here's exactly how the residual becomes a proposed number."*

**Beat 8 — NBA + AI #3 (NBA panel).** For the surviving **SAR 75,000**, the internal-first ladder shows green checks (prior returns ✓, e-invoices ✓, filing comments ✓). One terminal rung: Claude phrases the single scoped request — **qualitative wording only; the SAR 75,000 and any figure are rendered by the frontend from the deterministic struct, never from model text** (*"Provide the VAT control-account reconciliation for [period] supporting the SAR 75,000 residual difference…"*), with a benchmark strip (*"historically requested in 68% of similar cases; yield 71%"*). Presenter clicks **Approve & Send** (human gate). Badge: `◐ send simulated`.

**Beat 9 — DRAFT REPORT + AI #1 (hero #2).** The report **streams in live** into §2/§7 with a typing cursor. Because `claude-opus-5` runs adaptive thinking on by default at high effort, the call sets `display:"summarized"` so a short reasoning summary streams **first** as visible progress — the flagship moment never opens on a silent pause. Click any sentence → its `claim(rule_id, number, evidence_ref)` draws back to the source invoice/rule. Green seal: **"✓ verify_claims: every number traced."** *(Optional: flip the "adversarial" toggle to show one fabricated sentence caught and stripped — this is a **separate canned artifact**, not computed live.)*

**Beat 10 — APPROVE (Timeline).** Presenter clicks **Approve** (human gate). The run replays as a vertical timeline: deterministic (slate ∑), AI (violet), human (green gate). *"Three human gates. Nothing left the building without an auditor. That's the product."* End on the Cockpit, all 9 green, or on N1 Executive Overview for the "so what."

**Reset demo** re-seeds to step 1.

---

## 4. Seed-data package

**Governing invariant:** author invoices first → derive the return from them → perturb the *return only* (never the invoices) to manufacture each scenario's gap. This guarantees `Σ TAXSUBTOTAL` ties to the reconstructed boxes *by construction*, and the residual is exactly what we designed. **Fixed `SEED=42`**; Faker fills only cosmetic fields. The generator's self-consistency **is** the test oracle.

**Each reconciling driver is a separately quantified perturbation.** The waterfall shows *specific* magnitudes (−210,000 / −95,000 / −40,000 / −60,000), so the oracle must pin **each line**, not just the terminal residual. The seeder injects the credit-note total, the timing-lag total, the prepayment total and the reclass total as **independent, individually parameterised** perturbations, and the `manifest` records each expected bridge-line value alongside the expected residual. `verify` asserts **every bridge line == manifest AND residual == manifest** — so if a rule change shifts any single line, the build fails, and the on-screen numbers can never silently drift.

**Exact-sum "remainder trick"** (`tieout.split_exact(total_taxable, total_vat, rate, n)`): draw `n−1` plausible taxable amounts, the n-th absorbs all rounding residue, then `assert Σ == target` (fail-closed). The reconstructor reads only `invoice_taxsubtotal.TaxableAmount`/`TaxAmount` — that flat table is the linchpin the seeder must land exactly.

**Volumes (demo-scale):** 6 scenario taxpayers (A–F, one of which is the hero E) + 6 background (queue variety) + **30 historical closed cases** (labelled outcomes — these power both the `nba_prior` benchmark strip **and** the N1 value tiles, so their aggregate hours-saved / contacts-avoided numbers are non-trivial); ~100 returns; ~450 invoice docs (only hero current periods fully modelled to tie); 42 audit cases (6 open + 6 in-flight + 30 closed). Low thousands of physical rows — seeds in seconds.

### The six scenarios (each a story the flow tells on screen)

| # | Taxpayer (sector/size) | Story | Rules fired | Terminal state | Request? | Objective-2 lesson |
|---|---|---|---|---|---|---|
| **A Clean** | Al-Rawabi Retail (Retail/Med) | Margin-outlier flag; reconstructed == declared | — | **No Adjustment** | No | Risk-engine false positive cleared, zero contact |
| **B Timing** | Bina'a Contracting (Construction/Large) | 8 straddle invoices issued 27–31 Mar, cleared 2–5 Apr, belong to Q2 | TIM-04 + TIM-01 | **No Adjustment** | No | Resolved from `STATUSCODE`/`ActualDeliveryDate` metadata |
| **C Rate error** | Noor Medical (Pharma/Med) | SAR 800k keyed at 5% instead of 15% (invalid 2024 tax point) | TRT-09 + DAT-05 | **Adjustment +80k** | No | Real finding, caught internally *before* invoice work — **core, not LLM, finds it** |
| **D Credit note** | Jazeera Electronics (Retail/Med) | 14 type-381 credit notes (−75k VAT) explain the whole gap; 1 orphan CN shown, not netted | COR-01 (+UNLINKED_NOTE) | **No Adjustment** | No | Explained by evidence in hand; honest UNLINKED_NOTE handling |
| **E — HERO — Al-Faisaliah** | **Al-Faisaliah Trading (General/Med)** | **The composite hero of §2/§3.** Apparent 480k gap; COR-01 credit notes (Declared-side, prior-period/UNLINKED) −210k, TIM-04 lag −95k, TIM-05 prepayment −40k, TRT-04 export reclass −60k explain 405k; genuine **75k** survives; amendment chain (v1 as-filed vs v2 `Current_Flag='Y'`) | COR-01, TIM-04, TIM-05, TRT-04, COR-05, DAT-02, VersionResolver | **Potential Finding +75k** | **Yes — exactly 1** | The ladder proven: request reachable **only** after internal exhaustion; the one contact in the whole book |
| **F Import** | Gulf Industrial (Mfg/Large) | Sales side ties (residual 0); Box8/Box9 declared pass-throughs, `partial=true` | — | **Coverage-limited** | No (deferred) | Agent won't request on boxes it structurally can't reconstruct |

**One taxpayer, one row, one number:** the hero **is** scenario E (renamed to Al-Faisaliah Trading) — not a seventh composite. This makes the headline "**5 of 6 resolve with zero contact; only one generates a request**" match the case actually demoed on screen exactly. E is the spine of the full 1→9 walk (all four AI features converge); A shows business value (avoided contact); C shows SME credibility (the deterministic core owns the number).

**The 8 deterministic rules + hygiene checks (reconciled to the scenarios above — every rule the scripts fire is in this set):**
- **Reconciling rules** (produce bridge lines): **COR-01** credit notes · **TIM-04** clearance/reporting lag · **TIM-05** prepayments (type 386) · **TRT-04** export reclassification · **TRT-09** rate / tax-point error.
- **Classification / support:** **COR-05** amendment correction (with the `VersionResolver`) · **TIM-01** period-boundary straddle · **DAT-05** invalid tax-point validation.
- **Data-hygiene deterministic checks** (not bridge lines): **DAT-01** duplicate detection · **DAT-02** version/amendment data · **UNLINKED / UNLINKED_NOTE** handling.

This is the true minimum the flagship and the six scenarios require — the earlier "5 rules" list could not run the hero (which alone fires COR-01, TIM-04, TIM-05, TRT-04 plus the amendment path).

**Amendment trap (E):** two rows share `Form_Number`, differ on `Data_Version`. `v1 (Current_Flag='N')` matches `OLD_TAX_AMT`, pre-`AUD_DATE_G` — the row `VersionResolver.as_filed_at_referral()` must pick. Naive `Current_Flag='Y'` selection would understate the finding. One clean beat that shows we audit the *right* return.

**Global noise** (injected *outside* the six tie-outs): 2 duplicate invoices (exercises DAT-01 dedup), 3 UNLINKED invoices (roster-external VATs), 1 orphan 381 credit note (UNLINKED_NOTE) — all light up honest-handling machinery without disturbing headline numbers.

### How it's generated
```
seeder/  cli.py · rng.py(seed=42) · keys.py · tieout.py · ubl.py
         builders/{clean,timing,rate_error,credit_note,under_declaration,import_passthrough,background,historical}.py
         manifest.py   # scenario → intended ROOT_CAUSE_CODE + expected PER-LINE magnitudes + expected residual (the oracle)
         load.py       # write to core.* tables
```
```bash
make demo-reset                                  # fresh schemas
python -m seeder.cli seed --scenario all         # 6 scenarios + background + 30 closed
python -m seeder.cli verify                       # reconstruct every case; assert EACH bridge line == manifest AND residual == manifest
```
`seed` prints a per-case tie-out report (declared / reconstructed / **each expected line** / expected residual / PASS-FAIL). `verify` is the single regression gate: any rule change that breaks a scenario **or shifts any bridge-line magnitude** fails the build.

---

## 5. Where AI is used — the AI-usage table

Ordered by ROI (High first), then implementation complexity (Low first). The four SELECTED features light up steps **2, 4, 5–6, 8** — deliberately the language-heavy moments, never steps 3, 4-recon and 7 where numbers are decided. **All four consume deterministic outputs and emit only language; none introduces a figure that moves a total, and the two mid-demo prose calls (#2, #3) are constrained to qualitative text with numerals rendered from the struct (§6).**

| Flow step | AI feature | Screen | User-facing value | ROI | Complexity | Status |
|---|---|---|---|---|---|---|
| **4 RECONCILE** | **Bridge narration** | Reconciliation Bridge | Explains *why each difference is legitimate and what the auditor should conclude* — synthesis the printed labels don't give; the money-shot sentence a non-technical exec instantly gets | High | **Low** | ✅ **SELECTED (Claude)** — `draft_prose`, `effort` mid, **qualitative-only** |
| **2 ASSEMBLE** | **Taxpayer-history auto-summary** | Taxpayer-360 | Replaces minutes of scrolling amendment/audit history with a 4-line brief | High | **Low** | ✅ **SELECTED (Claude)** — `messages.parse`, `effort` low (cheapest) |
| **5–6 INFO REQUEST** | **NBA phrasing + justification** | NBA panel | Ready-to-send, defensible single request bound to the exhausted ladder | High | Med | ✅ **SELECTED (Claude)** — `messages.parse`, `effort` high, **qualitative-only** |
| **8 DRAFT REPORT** | **AI-drafted audit report** | Draft-report review | The headline deliverable, written live — the streaming WOW | High | Med | ✅ **SELECTED (Claude)** — `messages.stream` + `verify_claims`, `effort` high |
| 8 | Bilingual Arabic↔English report | Draft-report review | Native-language report for ZATCA leadership | High | Med | **Partially shipped** — Arabic UI chrome + one bilingual §; full bilingual report deferred; re-run `verify_claims` on translation |
| 4 | Notes/COMMENTS/`LETTER_*` gap auto-explanation | Evidence viewer | Auto-close gap from evidence taxpayer already gave | High | High | **Deferred** — was the boundary-violating "fifth feature"; content sourcing unconfirmed; needs `hold_unconfirmed_netting()`; real notes = PII. **Not in demo.** |
| 1 | Referral-reason plain-language explainer | Case Queue | Context on intake | Med | Low | **Deferred** — code lists undecoded; nothing real to say |
| 7 | Residual root-cause classification | Draft-report | Speeds labeling (soft suggestion) | Med | Med | **Deferred** — classical ML crosswalk, not Claude; needs real closed cases |
| 3/7 | Peer/anomaly vs sector norms | Box-by-box | "Ratio 2× sector median" context | Med | Med | **Deferred** — Tier-4 signal only; classical ML |
| 9 | Conversational "Ask the case" | Timeline | Demo-flashy NL Q&A | Med | High | **Deferred** — boundary risk: open chat could pull the LLM back across the number line |
| 3 | Invoice anomaly / duplicate flags | Box-by-box | Cleaner reconstructed side | Low | Low | **Deferred** — already handled deterministically (DAT-01/DAT-05) |
| 2/5 | OCR document extraction | Evidence viewer | Unlocks scanned attachments | Low | High | **Deferred** — synthetic attachments already structured; zero demo payoff |
| 1 | Case triage / priority ranking | Case Queue | Prioritized inbox | Low | Med | **Out of scope** — that's the upstream risk engine |

**Quick wins (High ROI + Low complexity):** bridge narration and taxpayer summary — both SELECTED, ship first. **Honesty note on the bridge narration:** its value is *synthesis* (legitimacy reasoning + auditor conclusion), explicitly **not** paraphrasing the printed "−210,000 credit notes" labels; scoped that way it earns High ROI, scoped as a restatement it would be filler. NBA phrasing and the report are High ROI at Med complexity; their Med rating is *entirely the guardrails* (binding to the ladder; `verify_claims` + streaming), and that guardrail cost **is** the defensibility story, so it's worth paying.

**Why exactly these four:** they sit in the top-left quadrant, span the flow's four language-heavy moments, and — structurally — **consume deterministic outputs and emit only language**. None can invent a number, and the demo now proves that with `verify_claims` applied to all three prose outputs, not just the report.

---

## 6. The Claude AI layer

### 6.1 The `LLMService` boundary
```
services/llm/  client.py · schemas.py · prompts.py · guardrail.py · service.py
```
**One import rule (CI-enforced):** the build fails if `import anthropic` appears anywhere except `services/llm/`. This is the physical realization of "the LLM is fenced to language behind exactly one boundary."

Public surface = **two primitives + one guardrail**, with four thin feature methods:
```python
class LLMService:
    MODEL = "claude-opus-5"
    def draft_prose(self, *, context, task, effort, max_tokens) -> Iterator[str]         # streamed
    def parse_structured(self, *, context, task, effort, schema, max_tokens) -> BaseModel # typed (messages.parse)
    def verify_claims(self, draft, claims) -> VerifyResult                              # applied to ALL prose
    # features:
    def summarize_taxpayer(ctx) -> TaxpayerBrief      # parse_structured, effort low
    def narrate_bridge(ctx)     -> Iterator[str]      # draft_prose, effort mid,  QUALITATIVE-only + verify
    def phrase_nba(ctx)         -> NBAPhrasing        # parse_structured, effort high, QUALITATIVE-only + verify
    def draft_report(ctx,claims)-> Iterator[str]      # draft_prose + verify_claims, effort high
```

**SDK correctness (verified against the current `claude-api` skill):**
- **`messages.parse` takes `output_format=<PydanticModel>`** (returns a typed, parsed object) — *not* `output_config={"format": <json_schema>}`, which is the `messages.create` form. The two structured calls (taxpayer summary, NBA) use `parse` + Pydantic model; do not mix the two shapes.
- **`thinking:{type:"adaptive", display:"summarized"}` on all four calls** — this is deliberate, not cosmetic: `claude-opus-5` runs adaptive thinking **on by default**, and at `effort:"high"` the model thinks before emitting text. With the default `display:"omitted"` the streamed report would open on a **silent pause**; `display:"summarized"` streams the reasoning summary first as visible progress, so the flagship "types itself live" moment never stalls on stage.

| Endpoint | Feature | SDK mode | Returns |
|---|---|---|---|
| `POST /cases/{id}/summary` | Taxpayer brief | `messages.parse` (`output_format=TaxpayerBrief`) | typed JSON |
| `POST /cases/{id}/bridge/narrate` | Bridge narration | `messages.stream` | SSE text (qualitative), then `verify_claims` |
| `POST /cases/{id}/nba` | NBA phrasing | `messages.parse` (`output_format=NBAPhrasing`) | typed JSON, then `verify_claims` |
| `POST /cases/{id}/report/draft` | Report | `messages.stream` → `get_final_message()` → `verify_claims` | SSE text, then gate |

No Celery — four short synchronous calls.

### 6.2 Context assembly (caching demoted to a production note)
Over ~6 cases at ~$0.20 each the dollar saving from prompt caching is nil, and the two-breakpoint design added a whole failure mode (silent invalidation) to a build that is **frontend-constrained**, not cost-constrained. **Prompt caching is therefore demoted to a production note.** For the demo, each call assembles its context inline from deterministic structs; **at most one** `cache_control:{type:"ephemeral"}` breakpoint is kept — on the frozen preamble only — purely so the slide can show `cache_read_input_tokens > 0`, and it is **off the critical path** (nothing breaks if it is removed).
```
system = [
  block 0 — FROZEN preamble (role, boundary, guardrails)   cache_control:{type:"ephemeral"}  # optional, slide-only
  block A — TAXPAYER FACTS (feature #4 sends only [preamble, A]; the bridge doesn't exist yet at step 2)
  block B — THIS-PERIOD CASE (declared boxes, rebuilt_box, bridge_line[], residual, rule_firing[],
            conclusion, claim[], nba_recommendation)
]
```
**Discipline (still worth stating):** `BP_CONTACT_*` PII is *never* serialized into the context; no `datetime.now()`/UUIDs/unsorted `json.dumps` where a cache breakpoint sits. Production reinstates the full two-breakpoint prefix behind the identical interface.

### 6.3 The four feature specs
- **#1 Report** — inputs: taxpayer + case context; narrates only §2 (executive conclusion) + §7 (explained differences/findings) — the numeric skeleton is filled by deterministic `ReportService`. Output: streamed prose → `verify_claims` before it becomes approvable. Render: Draft-report review with provenance-on-click. **WOW:** the report types itself live (reasoning summary first, then prose), then each sentence gets a green "✓ CLM-xxx" badge.
- **#2 Bridge narration** — inputs: `bridge_line[]` (ordered, each with `side`), `rule_id`, signed `amount`, `root_cause_code`. Task: **"explain why each difference is *legitimate* and what the auditor should conclude, walking the lines in order — do not restate the figures."** Output: short streamed **qualitative** prose; any numeral in the panel is rendered by the frontend from the struct. Passes `verify_claims` before render. Render: panel beside the waterfall, each segment clickable to `rule_id`+`evidence_refs`.
- **#3 NBA phrasing** — inputs: `residual`, the winning `nba_recommendation` rung (selection is deterministic), `nba_prior` yield. Output: structured `NBAPhrasing{request_title, request_body, justification, what_it_would_resolve, rule_ids}` — **the request text is qualitative; the SAR figures are injected by the frontend from the struct**, and the struct is run through the same number-allowlist check. Render: NBA panel above the ticked internal ladder, `Approve & Send` gated below.
- **#4 Taxpayer brief** — inputs: **block A only**. Output: structured `TaxpayerBrief{one_line, prior_audit_history, amendment_pattern, why_flagged, watch_items}`. Render: Taxpayer-360 header cards.

**Governance:** no Claude call in the demo emits a figure that moves the residual (the boundary-violating note-extraction is deferred). The narration and NBA describe the deterministic residual; they never mutate or compute it.

### 6.4 The `verify_claims()` guardrail — now applied to ALL prose, not just the report
The core writes one `claim{claim_id, rule_id, box, number, unit, evidence_refs[], assertion}` per assertable fact. `verify_claims(draft, claims)` splits prose into sentences, extracts every monetary figure and `rule_id` token, and: a sentence is **backed** iff every figure matches some `claim.number` within materiality tolerance *and* its box/rule context is consistent; qualitative sentences (no number) pass; **any number with no backing claim is rejected**. Example rejection: *"…under-reported roughly SAR 42,000 of cash sales"* → no claim with `number ≈ −42000` → `VerifyResult(ok=False, rejected=[…])`.

**Scope fix:** the same check runs on **bridge narration (#2) and NBA phrasing (#3)** before they render — not only on the report (#1). This closes the gap where an unbacked number could sit under a violet chip *earlier* in the demo than the report. Combined with the qualitative-only prompting (numerals rendered from the struct), the two mid-demo prose calls are guarded twice over.

**Brittleness insurance (so it never misfires live):** figure extraction normalises thousands separators, `k`-suffixes (`405k` ≡ `405,000`) and Arabic-Indic numerals before matching, so formatting variance cannot cause a spurious rejection. The recorded stream **fixture is pre-run through `verify_claims` in CI with an assertion that it passes** (see §6.5 and §8-DoD-14) — a live run can never show an accidental block. The adversarial "caught bad number" demo is a **separate canned artifact**, deliberately failing, never computed live.

### 6.5 Streaming, cost, stage insurance
Report + narration stream over SSE (`stream.text_stream` → `StreamingResponse`); on completion the server runs `stream.get_final_message()` → `verify_claims` → flips "drafting…" to "verified ✓". **Stage insurance:** one good stream is recorded as a fixture and replayed deterministically, with a "use live API" switch; that fixture is CI-asserted to pass `verify_claims`.

**Per-case cost** (`claude-opus-5`: in $5 / out $25 / cache-write $6.25 / cache-read $0.50 per MTok — verified current):

| Call | ≈ Cost |
|---|---|
| Taxpayer summary (low) | $0.028 |
| Bridge narration (mid) | $0.055 |
| NBA phrasing (high) | $0.031 |
| Report draft (high) | $0.082 |
| **Total** | **≈ $0.20/case** |

**Quote $0.15–0.25/case** (caching now a production optimization, not load-bearing to this number). Latency: structured calls in a few seconds; report streams a reasoning summary first (~1–2s), then §2/§7 in ~10–20s — perceived latency near-zero because it streams. *(Confirm against current `claude-opus-5` list pricing before a slide.)*

### 6.6 In-tenant production swap
Production PDPL requires an in-tenant/self-hosted (or ZATCA-approved) endpoint. The swap happens **behind the identical `LLMService` interface** — repoint `client.py`'s base URL/credentials; the four feature methods, Pydantic schemas, `verify_claims`, and the (re-enabled) cached prefix are unchanged. Slide states plainly: *"Demo uses the hosted Claude API on synthetic ZATCA-shaped data. No real taxpayer data — and specifically no real filing notes — are sent. Production runs an in-tenant model behind the same interface."* (The note-extraction path stays deferred precisely because real notes are PII — which is why cutting it from the demo also keeps the "synthetic, no PII" line airtight.)

---

## 7. Simplified architecture (real vs mock)
```
React Auditor Workbench (Vite + TS + shadcn/ui + Tailwind + Framer Motion) — bilingual-ready (Arabic chrome + RTL)
  fetch/JSON  +  EventSource(SSE) for streaming prose
        │  HTTP (single hardcoded token)
ONE FastAPI app (uvicorn, synchronous)
  ReconEngine → rebuild + bridge + residual (set-based SQL)          [REAL]
  RuleEngine  → 8 rules + hygiene checks → rule_firing → bridge lines [REAL, subset]
  ConclusionSvc → 4 states + DIFF_TAX_AMT                             [REAL]
  NBAService  → 2-rung internal-first ladder                          [REAL, simplified]
  LLMService  → the SINGLE Claude boundary (4 methods) ──────────────► Anthropic API
  verify_claims → guardrail before ANY prose renders                     (claude-opus-5,
  event_log   → append-only trail (no hash chain)                         SYNTHETIC only)
        │  SQLAlchemy
PostgreSQL — TWO schemas
  core.*  taxpayer, vat_return(+history), invoice, invoice_taxsubtotal (linchpin grain),
          audit_case, case(assembled_doc JSONB), rule_library, box_mapping, materiality, code_dictionary
  recon.* rebuilt_box, bridge_line(+side), residual, rule_firing, conclusion, claim,
          nba_recommendation, draft_report, case_state, event_log, llm_call
        ▲  python seed.py (deterministic; truncate + reload)
```
- Reconstruction reads only the flat `invoice_taxsubtotal` (`invoice_uuid, direction, category_id, rate_pct, taxable_amount, tax_amount, invoice_type_code, issue_date, status_code`) — a single `GROUP BY`, on-screen tie-out trivial (screen 3a). Raw UBL lives in `invoice.raw JSONB` for the Evidence viewer.
- `bridge_line.side` (`Rebuilt` | `Declared`) is stored so the Box-by-box drill can label each line and defend the no-double-count identity live.
- `llm_call` stores `{method, prompt_hash, response, effort, cost_est}` — feeds the live "AI activity"/cost strip.

**Frontend stack:** Vite + React 18 + TS · shadcn/ui + Tailwind (bespoke KPMG-blue + violet-AI system) · **Framer Motion** for the hero animation (count-ups via `useMotionValue`, staggered waterfall reveals, one shared "demo timeline" reducer so "advance step" drives waterfall + counter + narration together) · **hand-built SVG + `@visx/scale`** for the waterfall (float offsets/connectors/segment-drill need control no chart lib gives) · **Recharts** for box-by-box + portfolio charts · streamed prose via `ReadableStream` + `react-markdown` with Radix popovers for provenance · **Zustand** (demo state: current step, AI Lens, Depth toggle, language) + **TanStack Query** · **i18n + RTL** for Arabic chrome · a **demo-fixtures adapter** so every screen runs with the backend fully offline · presenter mode as a small reducer/XState (keyboard-driven beats, autoplay, Reset). Load the `frontend-design` skill before building — the bridge waterfall and streaming-report screen must feel finished.

**Bilingual (ZATCA/KSA audience):** ship **Arabic UI chrome** (labels, the hero band, the 9-node rail, buttons) with RTL, plus **one bilingual report section behind a toggle** (re-run through `verify_claims` on the Arabic text). Full bilingual report stays deferred — but no screen is English-only in front of a Saudi audience.

**Deployment:** `docker compose up` (`postgres` + `api` + `react-static`) then `python seed.py`. Runs on a presenter's laptop, offline except the Anthropic call (with the pre-validated offline stream fallback).

---

## 8. Build plan

### Workstreams + 6-week timeline
| WS | Workstream | W1 | W2 | W3 | W4 | W5 | W6 |
|---|---|---|---|---|---|---|---|
| **A** | Seed data & scenarios (`core` tables, `seed.py`, **per-line** tie-out oracle) | ███ | ██ | | | | |
| **B** | Backend: reconstruction + bridge(+side) + 8 rules + conclusion + NBA + endpoints | | ███ | ███ | ██ | | |
| **C** | AI layer: `LLMService`, 4 features, structured outputs, streaming, `verify_claims`-on-all-prose | | | ██ | ███ | ██ | |
| **D1** | React — **two HERO screens** (Bridge waterfall + streaming report) — PROTECTED | | ██ | ███ | ███ | ██ | ██ |
| **D2** | React — remaining screens, tie-out card, N1/N2, AI-Lens, Arabic chrome | | ██ | ██ | ███ | ███ | ██ |
| **E** | Demo polish: honesty labels, "where AI" map, value tiles, scripted walkthrough, dry runs | | | | | ██ | ███ |

**Critical path (tighter than it looks):** `seed.py` **per-line** tie-out → reconstruction + bridge with the **no-double-count side logic** (B) → Bridge screen + AI narration (C/D1) → streaming report (C/D1). Seed data is the pacing item and it now carries the double-count subtlety, so **WS-A ships the first golden case (E/Al-Faisaliah) end-to-end in Week 1, with each bridge line asserted**, or the whole chain slips.

**Frontend is resourced for the "must feel finished" bar:** the two HERO screens (waterfall + streamed report with per-sentence provenance) are ~2–3 weeks of polished work on their own, so they get a **dedicated frontend hand (D1)** and are named **protected deliverables**; a second frontend-weighted hand (D2, the reweighted full-stack floater) owns everything else. For the MVD, **Evidence viewer and Box-by-box fold into the Bridge from day one and N1 is deferred** — these are the explicit cut-candidates, the two HERO screens are not.

**Minimum-Viable-Demo — end of Week 3:** one case runs Intake → Reconstruct tie-out card → Bridge → Draft report, with a real reconstructed waterfall (every line asserted) and the report streaming from Claude, on the two HERO screens. Everything after is breadth (more cases, more screens, NBA gate, N1/N2, Arabic chrome, polish), not new risk.

**Scope-cut order if compressed:** defer N1 → fold Evidence viewer + Box-by-box into the Bridge → drop scenario F/D → narrate the NBA request verbally. **Never cut:** reconstruction tie-out (with the Step-3 card), the animated Bridge waterfall, the streaming report, the AI-attribution layer, `verify_claims`.

**Team (headcount unchanged, reweighted to frontend):** 1.0 Backend/AI engineer (FastAPI, ReconEngine, RuleEngine, `LLMService`, `seed.py` — lighter now the backend is ~40% thinner); **2.0 Frontend engineers** — one owns the two HERO screens exclusively (D1), one owns the rest + seed→query wiring early (D2); 0.5 VAT SME (credibility guarantor — confirms every bridge line ties and stories are realistic); 0.5 PM/demo director (10-min script, honesty narrative, value tiles, dry runs). No ML/data/DevOps engineer needed.

### Definition of Done
A non-technical stakeholder watches a ~10-minute live walkthrough in which all are true:
1. **Full cycle on screen** — a queued case walks 1→9 to an approved report, with the human gates shown as deliberate stops, **and no step (including 3-Reconstruct and 7-Conclude) is a bare spinner or a skipped label**.
2. **Numbers tie out and are shown tying out** — the Step-3 tie-out card shows `Σ invoice_taxsubtotal = Box`, and the Box-by-box drill shows **each bridge line labelled by side** with the identity `Rebuilt − Declared = Σ items + Residual`. No hand-waving, no double-count question left unanswered.
3. **The bridge visibly closes** — declared → named reconciling lines (each with its rule and side) → **deterministic residual of SAR 75,000** matching the conclusion, with **no AI-produced figure anywhere in the chain**.
4. **AI is visible and bounded at four points**, each under a violet chip beside its slate deterministic input; the presenter states the boundary in one sentence and it holds — the violet/slate legend is never contradicted on screen.
5. **All prose is guarded** — the report streams live, `verify_claims` goes green, and the same check is shown covering narration/NBA; optionally the separate canned adversarial artifact catches an injected bad number.
6. **≥3 distinct scenarios** reach 3 different conclusions (Close / Small Adjustment / Info-request→Finding) — the agent is seen both clearing and flagging taxpayers, and the **one request case is the hero itself**, matching the "5 of 6 zero-contact" stat.
7. **Honesty labels present** — "synthetic data / no real PII (incl. no real filing notes)," "party link simulated," "immutable log simplified for demo."
8. **Value, not just cost, on N1** — auditor-hours saved per case, % of flagged cases cleared with zero contact, contacts avoided, each with a one-line extrapolation to the book (seeded from the 30 historical cases); the ~$0.20/case AI cost is shown as a footnote, not the headline.
9. **Some Arabic on screen** — Arabic UI chrome + one bilingual report section behind a toggle.
10. **Runs from a laptop** — `docker compose up` + `python seed.py`, deterministic, repeatable, with the **CI-pre-validated** offline pre-recorded stream fallback (asserted to pass `verify_claims`).
11. **A one-slide "where AI is used" map** ties each of the four features to its screen, ROI, and the ~$0.20/case cost.

**The bar:** a ZATCA exec immediately gets it *and asks about ROI, which N1 answers*, and a KPMG tax SME believes it *including the no-double-count bridge and the "no AI number" boundary*. If either fails, it's not done.

---
*Supersedes the production plan's §7.4 timeline and §3 4-schema architecture for PoC purposes only; every cut maps to a labelled socket there, so the demo build promotes cleanly toward production without rework. Source of record: `C:\projects\E-AUDIT\VAT-Audit-Agent-Build-Plan.md`.*