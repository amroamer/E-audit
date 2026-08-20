# AI VAT Audit Agent — Regenerated Build Plan (PoC)
### KPMG × ZATCA | Lead Solution Architect Consolidation — Final

> **Superseded in part — historical planning record.** Where this plan describes a
> reconstruction that is later adjusted by "explaining" rules (bridge lines, residuals,
> apparent gaps), the build no longer works that way: rules run *during* aggregation and
> decide which documents belong in the box and the period, so the expected figure is the sum
> of what qualified. See **Qualify, then sum** in `CLAUDE.md`.

---

## 1. Solution recap & PoC scope boundary

**What this agent is.** A decision-support audit agent that begins *after* ZATCA's upstream risk engine (out of scope) flags a `taxpayer + period`. For that flagged case it: reconstructs the declared VAT return from e-invoicing and other internal data, explains every legitimate difference with a rule and a number, isolates the **true unexplained residual**, recommends the next best action, and produces an evidence-backed **draft** audit report — which a human auditor approves or returns. It is **not** a risk-detection engine and **never** auto-issues an assessment.

**Two objectives, structurally enforced.**
1. Reconcile → explain → isolate residual → recommend → draft report, with mandatory human sign-off.
2. **Minimize taxpayer information requests** — exhaust internally-held evidence first. This is guaranteed by the *shape* of the Next-Best-Action ladder (§5, §8) and proven per-case by a first-class `case_evidence_ledger`, not by policy or LLM discretion.

**Two design decisions that drive the whole architecture** (everything else is standard hygiene — audit logging, in-tenant residency, traced assertions — assumed throughout, not restated as "invariants"):
- **The deterministic core owns 100% of VAT math** — Python + set-based SQL over PostgreSQL. Reproducible and defensible, because the number gets litigated in the legal-dept/committee path. Every assertion traces to `rule_id + number + evidence_ref`.
- **The LLM is fenced to language behind exactly one service boundary (`LLMService`)** — it reads unstructured evidence and drafts prose from an already-decided conclusion. It never computes VAT, picks a state, or selects an action. (Standing constraints inherited: append-only hash-chained audit log; data stays in-tenant for PDPL; every known data gap is a labelled socket swapped with zero rework.)

**PoC scope boundary (explicit).**

| In scope | Deferred (carved out, not "evasion") |
|---|---|
| Resident standard **organizations** (`ZZBPTYPE=org`, `BP_RESIDENT_FLAG=resident`), single accounting method, Gregorian calendar | VAT groups (`VAT_GROUP_REP_FLAG`), non-residents, Hijri calendar, multi-branch consolidation |
| **Sales boxes 1–4, 6, 10 — reconstructed from self-issued invoices (high confidence).** **Purchase boxes 5, 7, 11 — reconstruction contingent** on FATOORA national-store completeness by buyer VAT number + buyer identification (see #2 below and §7.6) | Box 8 customs, Box 9 reverse charge, Box 14 prior-period, Box 15 credit c/f, Government supplies — **declared figure accepted un-reconstructed** (§14), pending real customs/RCM/contract feeds |
| ~30–50 complete historical cases (populated `DIFF_TAX_AMT`/`AUDIT_RESULT_TYPE`/`ACTION_TAKEN`) **as Phase-8 labels** + synthetic coverage | Full-scale LLM notes/letters reading (stub-tested in PoC) |
| End-to-end: flagged → assembled → reconstructed → bridge → residual → NBA → draft report → approve/return, with immutable log, on synthetic + **any available** real data | Production orchestration hardening beyond Docker Compose |

**Non-invoice boxes — honest statement of assurance.** Boxes 8, 9, 14, 15 and Government supplies are **not reconstructed and not audited** in the PoC. On a *live* flagged case the only number available for these boxes is the **taxpayer's declared figure**, which the PoC **accepts un-reconstructed** and tags `partial=true` in the bridge. The auditor's historical `IMPORT_*`/`XBRL_*` footprint is **not** a live input for these boxes — it exists only on closed cases and is used **solely as a Phase-8 label** (see §4 note and §6). Auditing these boxes is out of scope pending the customs / RCM / contract-register feeds already listed as deferred sockets.

---

## 2. Target flow (the case, end to end)

```
Upstream risk engine flags taxpayer+period   (OUT OF SCOPE)
        │
        ▼
[INTAKE]      Assemble Case Object — anchor Case.FORM_NUMBER → Return.Form_Number,
              select the AS-FILED-AT-REFERRAL version (Total_VAT_Due ≈ OLD_TAX_AMT /
              AUD_DATE_G), NOT merely Current_Flag='Y' (see §5, fix #4). Gather invoices,
              TP master, referral fields, evidence pointers (attachments, COMMENTS,
              NOTE_OID_ID, LETTER_*).
        │
        ▼
[RECONSTRUCT] Rebuild SALES boxes 1–4,6,10 (high confidence) and PURCHASE boxes 5,7,11
              (contingent on national-store completeness + buyer identity) by aggregating
              invoice TAXSUBTOTAL (TaxableAmount + TaxAmount per S/Z/E/O × 15/5).
              Boxes 8/9/14/15/gov are NOT reconstructed — declared figure carried through.
              NOTE: direction (SALE vs PURCHASE) requires the party link — real-data
              reconstruction is BLOCKED on the party-link socket (§8, fix #3).
        │
        ▼
[RECONCILE +  Internal-consistency checks FIRST (return-only, zero cost) → then
 EXPLAIN]     the bridge: Declared → each ruled reconciling line → TRUE RESIDUAL.
              Rule library attributes each residual to a cause. LLM reads notes here only;
              LLM explanations that DRAW DOWN residual annotate only until human-confirmed
              (§6, fix #7) — residual stays gross until then.
        │
        ▼
[INVESTIGATE  Per material residual, NBAService walks the internal-first evidence ladder,
 LOOP]        auto-pulling internal sources & re-reconciling. Bounded, no taxpayer contact.
        │
        ├─ residual → EXPLAINED / de-minimis → resolved
        │
        ▼
[INFO REQUEST] Only if a material residual survives internal exhaustion: ONE scoped,
 (HUMAN GATE)  minimal request, human-approved, ledger attached as proof. → AWAIT_TAXPAYER
        │
        ▼
[CONCLUDE]    Assign each residual a terminal state (SUPPORTED / EXPLAINED / UNRESOLVED /
              POTENTIAL-FINDING); quantify OLD/NEW/DIFF_TAX_AMT + penalty; roll up case.
        │
        ▼
[DRAFT REPORT] Deterministic core fills numbers/tables; LLM drafts prose bound to claims.
        │
        ▼
[HUMAN REVIEW] Auditor approves or returns-with-reason. (HUMAN GATE)
 (HUMAN GATE)  ESCALATE_LEGAL / REFER_TO_AC package only; human drives referral.
        │
        ▼
[CLOSE]       Emit labels, freeze report version, write immutable log. → Phase-8 validation
```

The state names mirror the recovered case lifecycle (`AUD_DATE_G → BRANCH_MEET_DT_G → BRANCH_DEC_DT_G → REFER_LEGAL_DEP_DTG → … → CLOSING_TIME`), which we process-mine (§6) rather than invent.

---

## 3. Architecture building blocks

**Four PostgreSQL schemas** separate concerns and physically enforce the deterministic/LLM/PII lines:

| Schema | Holds | Mutability |
|---|---|---|
| `stg` | Raw 1:1 copies of the four extracts + eServices filing evidence (subject to §9 sourcing confirmation) | Append-only per ingest batch |
| `core` | Resolved entities + the assembled Case Object | Rebuildable from `stg` |
| `config` | Assumptions register, code dictionary, party-link paths, rule library, materiality | Versioned |
| `audit` | Immutable, hash-chained action/evidence log | Insert-only; no UPDATE/DELETE grants |

**Ingest envelope** on every `stg` table (uniform, idempotent adapters): `ingest_batch_id`, `source_system`, `source_row_hash` (SHA-256 of the natural business tuple → upsert key), `ingested_at`, `raw JSONB`, plus typed columns.

**Python/FastAPI service boundaries** (each writes to `audit.action_log`):
`IngestionService → VersionResolver → PartyLinkResolver (interface) → DirectionResolver → CaseAssembler → EvidenceExhaustionOrchestrator → ReconEngine (rebuild/consistency/bridge/materiality) → RuleEngine → NBAService → ConclusionService → ReportService → OrchestrationService`. **`LLMService` is the single LLM boundary** (two functions only: `extract_claims`, `draft_prose`). **`GovernanceService`** is the single choke point that can reject a state raise **and the single gate that holds unconfirmed residual-reducing LLM explanations as annotate-only** (§6). Long work (`INVESTIGATE_LOOP`, reconstruction, LLM drafting, wait states) runs on **Celery/RQ workers**; FastAPI returns `202 + job_id`, the workbench polls.

**LLM hosting — in-tenant only (PDPL).** `LLMService` binds to an **in-tenant / self-hosted model** (or an explicitly ZATCA-approved, contractually-bounded endpoint). It must **not** call an external cloud provider SDK: taxpayer data (`NOTE_OID_ID`, `LETTER_*`, filing comments) may never leave the tenant. This is a compliance blocker, not merely an engineering choice — tracked as a top risk in §7.6.

**React (TS) Auditor Workbench** — SPA, eight screens (full inventory in §7).

**Deployment** — Docker Compose (`api`, `worker`, `postgres`, `redis`, `react-static`, **in-tenant model runtime**), single deployable stack inside ZATCA's tenant; data never leaves (PDPL).

---

## 4. The phased build plan (Phase 0–8)

### Phase 0 — Foundation
- **Canonical data model + Alembic migrations** for the four `stg` extracts, their invoice child tables, and the `core` Case Object. Relational for financial columns; JSONB for raw UBL / notes / LLM output.
- **`config.assumptions` register** — every open rule question is a flippable row (full table in §5), including the **Box-14 sign, set analytically at S0** (fix #8) and the **as-filed-at-referral version selector** (fix #4). Snapshotted per case into `core.case.assumptions_snapshot_id` so a case is always re-derivable under the assumptions it was built with.
- **`config.code_dictionary`** (`code_set, code, label, meaning, status, source, is_placeholder`) — pre-decode the *known* codes (InvoiceTypeCode 388/381/383/386; category S/Z/E/O; rate 15/5/0; rate-regime boundary 2020-07-01); stub the undecoded client lists (`CASE_REASON_CODE`, `ROOT_CAUSE_CODE`, `AUDIT_RESULT_TYPE`, `RISK_CATEGORY`, `ACTION_TAKEN`, …) with `is_placeholder=true`, rendered downstream as `UNKNOWN(code=X)` while grouping/validation still work on the raw code.
- **`config.vat_rate_calendar`** — 5% before 2020-07-01, 15% on/after; selected by `From_Date`/`IssueDate`.
- **Box-14 sign, decided up front (not deferred to Phase 8).** From a handful of historical records with all of `Box13/Box14/Box15/Box16` populated, solve the `Box16 = Box13 + Box14 − Box15` identity analytically and write `box14_sign_mode` into the assumptions register at S0. Phase 8 merely *confirms* it at population scale — no Phase-3 check is gated on a Phase-8 output.

**Synthetic seed generator — split into its own S0.5 workstream** (fix #16; its self-consistency *is* the entire test oracle). Fixed RNG seed. Produces: internally-consistent `tp` + `return` (amendment chains, triplet `_Amount`/`_VAT_Amount`/`_Adjustment`, `_15`/`_5` splits, populated 8/9/14/15/gov) + full parent-child UBL invoices that **aggregate exactly to the returns** + filing attachments/comments + `cases` with `xbrl_*`/`import_*` footprints and ground-truth labels. Includes a **labelled scenario manifest** (case → intended root cause): (a) timing/credit-note, (b) rate-column 5-vs-15 error, (c) un-reconstructable import, (d) genuine under-declaration, (e) prior-period credit tie-out — plus deliberate UNLINKED/mismatched invoices to exercise the exception queue. **The generator injects `direction` and the party link** so the sales/purchase pipeline runs end-to-end pre-socket; §5 and §6 note explicitly that this is *why* rules run on synthetic before the party link arrives.

### Phase 1 — Ingest & assemble the case
- **Adapters** (`VatReturnAdapter`, `InvoiceAdapter` fanning one UBL doc into 5 child tables by `_seq`, `TaxpayerAdapter`, `AuditCaseAdapter`, `ReturnAttachmentAdapter` — *conditional on §9 sourcing*) implementing one `SourceAdapter` protocol; base runner computes `source_row_hash` and does `INSERT … ON CONFLICT DO UPDATE` (re-runs never duplicate).
- **`VersionResolver`** — default for a case **under audit** is `as_filed_at_referral()`: the version whose `Total_VAT_Due ≈ OLD_TAX_AMT` / referral timestamp `AUD_DATE_G`, **not** `current_flag='Y'` (fix #4 — `Current_Flag='Y'` may be the *post-audit corrected* return, which would reconcile against the answer). `current_flag='Y'` remains the selector for **non-audited baseline lookups** only. Also exposes `history()` (full amendment chain, required intact for Box 14/15). Stamps `resolved_version` + `resolution_rule`; governed by ASM-03.
- **`PartyLinkResolver` interface + `DirectionResolver`** — the *only* place any seller/buyer VAT number is read (§8). Tags each invoice SALE / PURCHASE / UNLINKED, applies self-billed role-flip and 381/383/386 adjustment tagging, writes `core.case_invoice_tagged`. **On real data, direction cannot be computed until the party-link socket closes — this is a hard prerequisite for reconstruction, not graceful degradation (fix #3).**
- **PII segregation** — `bp_contact_*` lands only in `stg.audit_case_pii` with column-level grants; never in the Case Object JSONB, never at the LLM boundary.
- **Assembled Case Object** — `core.case` + children: `case_return`, `case_return_history`, `case_prior_returns`, `case_invoice_tagged`, `case_prior_audits`, `case_evidence_index`, `case_evidence_ledger`; a denormalized `assembled_doc JSONB` serves `/case/{id}` and the LLM read-context (but relational tables are authoritative).

### Phase 2 — Rebuild the return from evidence
- **Return reconstructor** — single grouped SQL scan over staged UBL at grain `(taxpayer, period, direction, category_id, rate_pct)`, reading **`TAXSUBTOTAL.TaxableAmount`/`TaxAmount`** (never re-derive tax from line prices). Signs by `InvoiceTypeCode` from `config` (388/383 `+1`, 381 `−1`, 386 handled as a **timing item** — see §5, fix #11 — not a neutral bucket). `STATUSCODE` filtered to the cleared set. Writes `recon.rebuilt_box`.
- **Category × rate × direction → box mapping table** (`config.box_mapping`), **split by confidence tier (fix #2):**
  - **Sales tier (high confidence)** — boxes 1–4, 6, 10, reconstructed from **self-issued** invoices the audited taxpayer holds.
  - **Purchase tier (contingent)** — boxes 5, 7, 11, reconstructable **only** where FATOORA is a complete national store queryable by **buyer** VAT number *and* the buyer is identified. Simplified/B2C invoices (`AttName`=simplified) frequently omit buyer identity; the un-reconstructable portion routes to an explicit **`PURCHASE_BUYER_UNIDENTIFIED` residual bucket**, never silently zeroed.
  - Validates `_15`/`_5` against the period (a 5%-rated line with a post-2020 tax point is itself a finding: `RATE_PERIOD_MISMATCH`).
- **Explicit carve-out (no reconstruction)** — Box 8 `Imports_Paid_*`, Box 9 `Import_Accounted_*`, Box 14, Box 15, `Government_Supplied_Sales_*` are **never reconstructed and never dumped into residual**; the declared figure is carried through, tagged `partial=true`. The historical `IMPORT_*`/`XBRL_*` fields are **Phase-8 labels only** and are not read here.

### Phase 3 — Compare & build the bridge
- **Internal-consistency checks FIRST** (return-only, zero taxpayer cost): the C1–C12 pack (rate-ties, totals foot, Box-13 composition, Box-16 identity **using the S0-decided `box14_sign_mode`**, RCM symmetry, adjustment-ties-to-prior-version, correction cap, rate-period, sign sanity). Catches the manual-filing data-entry family before any invoice comparison. Written to `recon.check_result`. **No Phase-3 check is gated on a Phase-8 result.**
- **The bridge** — the reconciliation identity `Declared_VAT[b] = Rebuilt_VAT[b] + Σ ReconcilingItem[b] + Residual[b]` rendered as an ordered waterfall (`recon.bridge_line`): unwind `_Adjustment` → less rebuilt → credit/debit notes (**aggregate-within-period when BillingReference absent; unmatched → `UNLINKED_NOTE` line**, fix #10) → allowances/charges → prepayments (386 timing) → rounding → FX → timing straddle → unresolved-direction → **non-invoice-box pass-throughs (8/9/14/15/gov, `partial=true`, declared accepted)** → **residual**. Every line carries `rule_id`, signed `amount`, `source_fields`, `evidence_refs`.
- **Residual isolator + materiality** — a delta is material iff `|delta| > max(box_abs_floor, box_rel_pct × base)`; bands NOISE / IMMATERIAL / MATERIAL. **All thresholds are provisional and require ZATCA de-minimis/assessment-threshold sign-off (fix #13)** — they are not settled numbers. Only MATERIAL enters `recon.residual` and drives NBA. Diagnostic (not headline) trust ratio: `explained_pct`, **bounded to [0,1]** with residual capped at the gross gap; when `declared ≈ rebuilt` the report states **"no gap"** rather than emitting an unstable ratio (fix #12).

### Phase 4 — Rule library & explanation
- **Config-driven rules engine** — rules are **data** in `config.rule_library` (`id, family, precedence, enabled, definition JSONB, root_cause_code`); firings logged to `rule_firing`, feeding both the bridge and the audit log. Loaded in precedence order, evaluated against the Case Object, appending explanation entries to a per-case ledger with an **evidence-consumption set** (each invoice UUID consumed by at most one explanation — no double-count).
- **Five families, precedence-tiered**: DAT (pre-conditioners tier 0 + residual attribution tier 90), STR (tier 10), COR (tier 20), TRT (tier 30), TIM (tier 40). Residual accounting is strictly additive and drawn down box-by-box; `TRUE_RESIDUAL = Σ_b (gap_vat[b] − Σ explained)` is the only number that reaches Phase 5.
- **Priority-12 rule pack** built first (§5).

### Phase 5 — Next Best Action
- **`NBAService`** (deterministic, ranked) — materiality gate → **ordered internal-first evidence ladder** per residual type → benchmark against historical `ACTION_TAKEN` yield → terminal rung = a single minimal, scoped, **human-gated** taxpayer request. The engine cannot skip rungs; the taxpayer request is only reachable for a material, internally-exhausted, positive-expected-yield residual.
- **Objective-2 guardrail is the algorithm shape**, evidenced by `case_evidence_ledger` + `nba_recommendation` rows showing which internal sources were exhausted.
- **Benchmark is advisory only** (`nba_prior`, learned from the process-mining/crosswalk workstream moved earlier — §6, fix #16): supplies `expected_yield` for chase-vs-conclude and renders "auditors historically did X; yield N%" beside the recommendation. Divergence is itself a review signal.

### Phase 6 — Conclude + draft report
- **`ConclusionService`** — assigns each residual one of four terminal states (**SUPPORTED / EXPLAINED / UNRESOLVED / POTENTIAL-FINDING**). Hard invariant: POTENTIAL-FINDING is reachable **only** through `has_tier1_basis()` (a rule + a number over return/invoices); taxpayer history and peer data are *not arguments* to `conclude()` and cannot raise a state. **Symmetric false-negative guard (fix #7):** an LLM-extracted explanation that would *draw down* residual (net down `DIFF_TAX_AMT`) must be **human-confirmed before it nets**; unconfirmed, it annotates only and residual stays **gross**. Quantifies `OLD_TAX_AMT`/`NEW_TAX_AMT`/`DIFF_TAX_AMT` decomposed per finding line; UNRESOLVED carries an exposure **range [0, residual]**, never a point. **`TAX_PENALTY_AMT` is a statutory calculation (fix #15):** it is either sourced to ZATCA's penalty regime with VAT-SME/legal sign-off, or rendered as a **human-only field** the engine does not assert. Case roll-up precedence: any material POTENTIAL-FINDING → *Proposed Adjustment*; else any material UNRESOLVED → *Pending Evidence*; else *No Adjustment / Close*.
- **`ReportService`** — assembles the 14-section report (header/scope → executive conclusion → declared → reconstructed → bridge → box-by-box → explained differences → unresolved & findings → evidence register → NBA → quantified impact → assumptions & limitations → agent action trail → sign-off). The report is a **tree of claims**; `LLMService.draft_prose()` narrates only §2/§7 from an already-decided conclusion, and `verify_claims()` rejects any drafted sentence not bound to an existing `claim(rule_id, number, evidence_ref)` before rendering.

### Phase 7 — Orchestrate + human sign-off + trust
- **`OrchestrationService`** state machine (states in §2), transitions append-only, guarded and idempotent; the bounded `INVESTIGATE_LOOP` and durable `AWAIT_TAXPAYER`/`HUMAN_REVIEW` wait states run on workers.
- **Exactly three mandatory human gates**: before any info request leaves the building; draft-report review (approve/return); escalate-legal / refer-to-committee (agent packages, human drives). **A fourth mandatory confirmation** (not a workflow gate but a netting gate): human confirmation of any residual-reducing LLM explanation before it nets (fix #7). A "return" spawns a new report version (prior versions immutable) and re-opens the targeted stage with the auditor's note.
- **Trust substrate** — the four-tier **evidence hierarchy** enforced by `GovernanceService` (Tier 1 proof can support a finding alone; Tier 2 LLM-read internal unstructured can only explain **and only nets after human confirmation**; Tier 3 taxpayer history orders NBA only, logged to `bias_ledger`; Tier 4 peer/sector is signal only). The **immutable hash-chained `audit.action_log`** records every transition, rule fire, evidence pull, hashed LLM call, NBA, and human decision — one provenance record rendered two ways (report §13 + React timeline).
- **Reference transition model** is supplied by the process-mining workstream run earlier (§6), not discovered in Phase 8.

### Phase 8 — Validate on historical labels
- **`IMPORT_*` / `XBRL_*` are labels here — never live features (fix #1).** These fields exist only on closed cases and encode the auditor's own answer; using them as inputs would be outcome leakage. They are consumed **exclusively** as per-box gold labels for scoring reconstruction.
- **Frozen golden set** in a `validation` schema (joined case objects + label layers, versioned, never live-queried). **Deterministic replay runner** writes `eval_run` keyed by `(case_id, engine_version, config_hash)`; the **scoring module runs as a CI regression gate** so a rule/config change that degrades reconstruction fails the build.
- **Version-selection is the first validator**: anchor each case to the return version where `Total_VAT_Due ≈ OLD_TAX_AMT` (the as-filed-at-referral position, consistent with the §5 default) — cases where no version reconciles are quarantined as keying defects before scoring.
- **Real-data box-level validation is blocked on the party-link socket (fix #3):** metric #1 (box reconstruction vs `XBRL_AMT`) needs `direction`, which needs the party link. Until the socket closes, box-level scoring runs on synthetic data only, where direction is injected — this validates plumbing, not real-data accuracy (fix #9).
- **Data-tiering** (Gold/Silver/Bronze by `MIGRATION_FLAG`, `LEGACY_*` sparsity, version reconciliation, conformance fitness) — headline metrics on Gold only; unscoreable ≠ wrong (track coverage separately).

*(Process mining and the family→`ROOT_CAUSE_CODE` crosswalk are **not** in this phase — they moved earlier; see §6 and §7.4.)*

---

## 5. Rule library approach (with the priority-12 rules)

**Mechanism.** Phase 3 emits per box a signed `gap_vat[b] = Declared_vat[b] − Reconstructed_vat[b]`. Each rule that fires posts `{rule_id, box, delta_base, delta_vat, direction, confidence, evidence_refs[], root_cause_code}`; `delta` always moves *reconstructed toward declared*, `direction` names the mechanism (`reduces_reconstructed_output`, `adds_to_reconstructed_input`, `reclassifies_base`, `shifts_to_adjacent_period`, `explained_outside_einvoice`). Rules are JSONB definitions loaded by precedence; a rule is flipped off with `enabled:false` — no redeploy. Every definition is versioned so a report re-derives against the exact ruleset that produced it. The party-link/BillingReference gaps *downgrade confidence* rather than block firing.

**Open rule questions — firm decisions as guarded config flags:**

| Question | Decision (config key) | Guard |
|---|---|---|
| `Total = Amount + Adjustment` or netted? | `return.total_is_netted = true` (Total is final; `_Adjustment` already inside) | DAT-05 verifies `Total ≈ Σcomponents (± Adjustment)` |
| Which date sets the tax point? | `timing.tax_point = IssueDate` | TIM-01 uses `ActualDeliveryDate` only for the straddle test |
| Which version is audited? | `version.selector = as_filed_at_referral` (match `OLD_TAX_AMT` / `AUD_DATE_G`) — **not** `current_flag_Y`, which may be the post-audit corrected return | COR-05 reconstructs superseded `Data_Version` to explain amendment gaps; `current_flag_Y` used only for non-audited baseline lookups |
| Sign of Box 14 in the Box-16 identity | `Box16 = Box13 + Box14 − Box15`, `box14_sign_mode` **decided analytically at S0** from records with all four boxes populated | Set in assumptions register at S0; **Phase 8 confirms only** |

**The priority-12 rules** (build order = frequency × SAR coverage ÷ join cost; pre-conditioners mandatory):

| # | Rule | Family/tier | Why first |
|---|---|---|---|
| 1 | **TRT-09** rate-period split (15/5 by `From_Date` vs 2020-07-01) | TRT, pre-cond | Without period-correct rate, *every* base×rate check is spurious. Zero joins. |
| 2 | **DAT-01** duplicate-invoice removal (`UUID`) | DAT tier-0 | Cleans reconstructed side before comparison; prevents phantom over-declaration. |
| 3 | **DAT-05** internal-consistency / manual-entry error | DAT tier-0 | Cheapest real finding, no invoice join; validates `total_is_netted`; catches the portal data-entry family directly. |
| 4 | **COR-01** sales credit notes (381) | COR tier-20 | Highest-frequency legitimate sales gap; evidence in-hand; **nets aggregate-within-period when BillingReference absent, unmatched → `UNLINKED_NOTE`** (fix #10). |
| 5 | **TIM-04** clearance/reporting lag (`STATUSCODE`+`IssueDate`) | TIM tier-40 | Very common; explains large gap chunks; sharply cuts false residual. |
| 6 | **TIM-01** tax-point issue-vs-delivery straddle | TIM tier-40 | Prevents mislabeling timing as under-declaration; `ActualDeliveryDate` present. |
| 7 | **TIM-05** prepayment (386) tax-point timing | TIM tier-40 | **Prepayments post output VAT on receipt and reverse against the final 388** (fix #11) — a timing item, not a neutral bucket; needs the same original-doc link as notes. |
| 8 | **TRT-04/05** zero/exempt/export reclass (`ItemClassifiedTaxCategoryID`+`AttName`) | TRT tier-30 | Large base reclassifications; else exempt/export-heavy taxpayers show huge false gaps. |
| 9 | **COR-05** amended-return version selection | COR tier-20 | Guarantees reconciliation against the **as-filed-at-referral** version; high correctness leverage. |
| 10 | **STR-04** GCC intra-supply mapping (`Sales_To_Customers_GCC_*`) | STR tier-10 | **Previously unmapped box** (fix #15) — GCC intra-supply ≠ export `AttName`; given an explicit mapping so it is not swept into residual. |
| 11 | **DAT-06** purchase-side buyer-unidentified bucket | DAT tier-0 | Isolates the un-reconstructable input-VAT portion (simplified/B2C, no buyer ID) into `PURCHASE_BUYER_UNIDENTIFIED` (fix #2) instead of false residual. |
| 12 | **DAT-02** missing-invoice residual (catch-all) | DAT tier-90 | The payload: whatever survives 1–11 is the true unexplained residual Phase 5 acts on and Phase 8 validates against `DIFF_TAX_AMT`. |

**Removed from the priority pack (fix #1).** TRT-02 (Box 9 RCM), TRT-03 (Box 8 customs), and COR-04 (Box 14) are **no longer framed as "closing a box invoices can't rebuild."** Their only data source (`IMPORT_*`/`XBRL_*`) is an audit-outcome field with no live equivalent. On a live case these boxes are **pass-throughs at the declared figure** (`partial=true`); the rules become **live only when a real customs / RCM feed lands** (deferred socket, §8). They remain deferred config rows, zero engine change.

**Synthetic-vs-real honesty (fix, filler §).** Rules 1–12 run end-to-end on **synthetic** data before the party-link socket arrives **only because the synthetic generator injects `direction` and the party link**. On real data, every direction-dependent rule (i.e., all reconstruction) is blocked until the party-link socket closes. This is stated plainly rather than implied as graceful degradation.

**Deferred** (blocked on a socket or lower-frequency): TRT-02/03, COR-04 (all pending real feeds), STR-01/03, DAT-03 wrong-TIN, COR-02/03, TIM-02/03, TRT-06/07/08 — each a later config row, zero engine change.

**Family → `ROOT_CAUSE_CODE`** is a *learned crosswalk* (codes undecoded), built in the **early process-mining/ML workstream** (not Phase 8): a confusion matrix of predicted family (argmax `|delta_vat|`) vs actual `ROOT_CAUSE_CODE` over closed cases, then frozen into `code_dictionary`. It is moved early because Phase-5 `nba_prior` and Phase-7's transition model consume it.

---

## 6. Validation strategy & success metrics

**Headline framing (fix, filler §): the 7-metric scorecard below is the single headline.** `explained_pct` (§3) is a **per-case diagnostic ratio**, not a headline metric — the two are no longer competing framings.

**Label layers scored against:** binary outcome (`AUDIT_RESULT_TYPE`, `sign(DIFF_TAX_AMT)`), magnitude (`DIFF_TAX_AMT`, `VAT_AMT`, `TAX_PENALTY_AMT`, `PERC_*`), reason (`ROOT_CAUSE_CODE`), next action (`ACTION_TAKEN`), and the crown-jewel **per-field gold labels** `XBRL_FIELD/XBRL_RETURN_AMT/XBRL_AMT` and `IMPORT_FIELD/IMPORT_RETURN_AMT/IMPORT_AMT` — the auditor's own per-box reconciliation footprint. **These are used strictly as Phase-8 labels, never as live features (fix #1),** letting us score reconstruction at **box granularity**, and they are the only label for the customs/reverse-charge branch invoices can't see.

**Real closed cases are a gating dependency, not an assumption (fix #9).** Synthetic metrics **validate plumbing, not accuracy** — we authored the scenarios, so any synthetic target is hittable and proves nothing about real-world performance. Metrics 3–7, and especially the business-case metrics 6–7, are **only meaningful on real closed cases**. If real cases do not arrive, the fallback reports **reconstruction/consistency plumbing only** and explicitly withholds the business-case claims.

**Where each technique belongs** (validation consequence: ML/LLM are scored as *agreement with the human label* — kappa, top-k — never as ground-truth generators; the hard targets sit on the deterministic core):
- **Deterministic core** — all VAT math, reconstruction, bridge, materiality, version selection, residual isolation. Must be reproducible.
- **Classical ML (scikit-learn)** — *suggestions only, shown beside the deterministic residual*: root-cause suggestion, NBA suggestion, peer/anomaly comparison (`IND_SECTOR`/`ACTIVITY`/`BUSINESS_SIZE`/`BP_REVENUE_TYPE`), request-avoidance predictor.
- **LLM** — reading unstructured evidence + drafting language only; residual-reducing extractions annotate-only until human-confirmed.

**Success metrics** (reported on a held-out, taxpayer-disjoint test split with bootstrap CIs). **All targets below require ZATCA authority sign-off and are meaningless on synthetic data — every synthetic-run number is labelled plumbing-only (fix #13).**

| # | Metric | Computation | PoC target (provisional, ZATCA to confirm) |
|---|---|---|---|
| 1 | Reconstruction accuracy vs auditor delta | per **sales** box + (where party link resolved) **purchase** box: share within `max(SAR 1, 0.5%)` of `XBRL_AMT` + sign agreement | ≥95% within tol; ≥90% direction |
| 2 | False-alarm side | on true-no-change cases: residual below materiality | ≥95% correctly under threshold |
| 3 | Sensitivity side | on adjustment cases: our residual vs `DIFF_TAX_AMT` | Pearson ≥0.85; MAPE ≤15% |
| 4 | Root-cause agreement | vs `ROOT_CAUSE_CODE`: top-1/top-3/macro-F1/κ | top-1 ≥0.60, top-3 ≥0.85, κ ≥0.5 |
| 5 | NBA agreement | vs `ACTION_TAKEN`: top-1, κ, escalate-recall | top-1 ≥0.70; escalate-recall ≥0.90 |
| 6 | **False-positive reduction** (Obj 1) | vs historical info-request-then-no-adjustment baseline | ≥30% relative reduction |
| 7 | **Taxpayer-request reduction** (Obj 2) | share of historical info-request cases fully explainable from internal evidence | ≥30–40% avoidable |

**Metrics 6 and 7 share a denominator (fix, filler §)** — the historical **info-request** cohort. They are **not two independent wins**: metric 7 counts requests avoidable via internal evidence; metric 6 counts the subset of those where the avoided request would have ended in no adjustment (a pure false-positive contact). They must be reported with the overlap shown, never summed.

Metrics 1–3 gate the deterministic core (must pass); 4–5 gate the suggestion layer (softer, top-k); 6–7 are the business case (real-data-gated). Every scorecard is **sliced** by `RISK_CATEGORY`, `CASE_REASON_CODE`, `AUDIT_TYPE`, `BUSINESS_SIZE`, and **pre/post 2020-07-01** (where `_15`/`_5` errors surface).

**Process mining (PM4Py) runs early, not in Phase 8 (fix #16).** Of the timestamp trail → the discovered variant graph *becomes* the Phase-7 reference transition model; per-transition cycle-times seed SLAs; variant frequency conditioned on `RISK_CATEGORY`/`ROOT_CAUSE_CODE` seeds `nba_prior`; the info-request loop (`LETTER_*` + `SUBMISSION_DAYS*` + `NO_OF_EXT_DAYS`) is the denominator for the request-reduction metric. Because Phases 5 and 7 consume these outputs, the workstream is scheduled before them, not after.

When notes and the party-link/BillingReference sockets land, only the LLM-extraction metrics and buyer/seller-directed joins are added — harness, tiers, splits unchanged.

---

## 7. Delivery

### 7.1 React Auditor Workbench (SPA, TypeScript) — screen inventory
1. **Case Queue / Inbox** — flagged cases; columns from `CASE_REASON_CODE`, `RISK_CATEGORY`, `VAT_PRIORITY`, `AUDIT_TYPE`; status from the state machine.
2. **Taxpayer-360** — TP master (`ACCOUNTING_METHODE`, `BP_RESIDENT_FLAG`, `VAT_GROUP_REP_FLAG`, `IND_SECTOR`/`BUSINESS_SIZE`, branches); `BP_CONTACT_*` **masked by default**, unmask gated + logged.
3. **Reconciliation Bridge (waterfall)** — declared → reconstructed → named reconciling items → residual; each segment clickable to its `rule_id` + `evidence_refs`; **non-invoice boxes shown as declared pass-throughs (`partial`), purchase boxes carry a confidence badge**.
4. **Box-by-box drilldown** — declared (`*_VAT_Amount`, `*_Adjustment`) vs reconstructed; **sales boxes vs contingent purchase boxes visibly distinguished**; boxes 8/9/14/15/gov visibly carved out (declared accepted un-reconstructed), not counted as residual.
5. **Evidence viewer** — raw UBL (JSONB), filing attachments + `COMMENTS`, `NOTE_OID_ID`, `LETTER_*`, with evidence tier badges; **residual-reducing LLM extractions flagged "annotate-only — confirm to net."**
6. **NBA panel** — ranked action(s), the internal ladder with checkmarks showing what was exhausted, the historical benchmark strip, and the *only* external-request control (**Approve & Send / Override**).
7. **Draft-report review** — narrative + numbers with **claim-provenance on hover** (rule + number + artifact); Approve / Return-with-note; **penalty field shown as human-entered/confirmed, not engine-asserted**.
8. **Action-trail timeline** — rendered from `audit.action_log`; states mirror the case lifecycle; includes the process-mined historical view.

### 7.2 Python/FastAPI services & endpoints
`POST /ingest/{source}` · `POST /cases/{id}/assemble` · `POST /cases/{id}/reconstruct` · `POST /cases/{id}/reconcile` (→ bridge+residual) · `POST /cases/{id}/explain` · `POST /cases/{id}/nba` · `POST /cases/{id}/report/draft` · `POST /cases/{id}/confirm-explanation` (human-confirm residual-reducing LLM extraction) · `POST /cases/{id}/approve` · `POST /cases/{id}/return` · `GET /cases/{id}/audit-log` (read-only) · `GET/PUT /config/{code-dictionary|assumptions|rules}`. Each mutating endpoint writes one immutable log row and, if long-running, returns `202 + job_id`. Services: `NBAService`, `ConclusionService`, `ReportService`, `LLMService` (sole LLM boundary, **in-tenant model**), `OrchestrationService` (+ workers), `AuditLogService`, `GovernanceService`. SQLAlchemy ORM, Alembic migrations.

### 7.3 PostgreSQL schema areas

| Area | Tables | Relational vs JSONB |
|---|---|---|
| Staging | `stg.vat_return`, `stg.invoice_header`/`_taxtotal`/`_legalmonetary`/`_line`/`_taxsubtotal`, `stg.taxpayer_master`, `stg.audit_case`, `stg.audit_case_pii`, `stg.return_attachment`/`_comment` *(conditional — §9)* | Relational financial cols; `raw JSONB` per row |
| Case Object | `core.case` (+ `case_return`, `_return_history`, `_prior_returns`, `_invoice_tagged`, `_prior_audits`, `_evidence_index`, `_evidence_ledger`) | Relational keys; `assembled_doc JSONB` |
| Config | `config.assumptions`, `config.code_dictionary`, `config.party_link`, `config.rule_library`, `config.box_mapping` (**sales/purchase confidence tiers**), `config.type_sign`, `config.materiality`, `config.vat_rate_calendar` | Relational rows; `definition JSONB` |
| Reconciliation | `recon.case_recon`, `recon.rebuilt_box`, `recon.check_result`, `recon.bridge_line`, `recon.residual`, `rule_firing`, `nba_recommendation`, `nba_prior`, `conclusion`, `claim`, `draft_report`, `case_state`, `bias_ledger` | Relational amounts + `rule_id`; `source_fields`/`evidence_refs`/`sections`/`llm_output` JSONB |
| Immutable log | `audit.action_log` (append-only, hash-chained; DB trigger blocks UPDATE/DELETE) | Relational event + `payload JSONB` |

Reconciliation math is set-based SQL over staging; JSONB is reserved for semi-structured payloads (UBL, notes, LLM output).

### 7.4 Sprint timeline (realistic: 14–16 weeks, 2-week sprints)

The original 12-week plan overloaded S0 and S5 and buried process-mining/crosswalk in the last sprint even though Phases 5 and 7 depend on them (fix #16). Corrected:

| Sprint | Weeks | Phases | Goal |
|---|---|---|---|
| S0 Foundation | 1–2 | P0 | Data model, migrations, assumptions register (incl. **Box-14 sign decided analytically**, **as-filed-at-referral selector**), code dictionary, rate calendar |
| **S0.5 Synthetic oracle** | 3–4 | P0 | **Synthetic generator as its own sprint** — amendment chains, exact-aggregating parent-child UBL, 8/9/14/15/gov, attachments, 5 labelled scenarios; its self-consistency is the whole test oracle |
| S1 Ingest & Rebuild | 5–6 | P1+P2 | Adapters stage all four sources; Case Object assembled; **sales** boxes reconstructed; purchase boxes behind confidence tier |
| S2 Bridge & Rules | 7–8 | P3+P4 | Comparator, waterfall bridge (incl. `UNLINKED_NOTE`, `partial` pass-throughs), residual isolator, priority-12 rule pack |
| **S2.5 Process-mining & crosswalk** | 9 | (feeds P5/P7) | PM4Py variant graph → transition model + SLAs; family→`ROOT_CAUSE_CODE` confusion-matrix crosswalk → `nba_prior` |
| S3 NBA & Report | 10–11 | P5+P6 | Ranked NBA with internal-first guardrail; deterministic report + isolated in-tenant LLM narrative; human-confirm-to-net |
| S4 Orchestrate & HITL | 12–13 | P7 | State machine, workbench approve/return, immutable log, async workers |
| S5 Validate & Harden | 14–15(–16) | P8 | Back-test vs labels, 7 metrics sliced 5 ways + bootstrap CIs, CI regression gate, calibration, demo + Docker packaging |

**Critical path:** data model → synthetic generator → reconstructor (P2) → bridge+residual (P3) → rule pack (P4) → validation (P8). **P2 reconstruction is the tightest dependency** — everything downstream is worthless without a trustworthy reconstructed return — **and P2 on real data is itself blocked on the party-link socket (fix #3).** **Parallelizable off-path:** React shell (from S1), in-tenant LLM narrative service (from S3, stub-testable), audit-log plumbing.

**Scope-cut fallback if timeline compresses:** ship sales-side reconstruction + consistency checks + bridge + report; defer the ML crosswalk, process-mining, and purchase-side reconstruction to a phase 2.

### 7.5 Team (RACI intent: VAT SME accountable for every VAT assertion; backend accountable for determinism/auditability; ML engineer fenced to language)

| Role | Owns |
|---|---|
| PM / Delivery lead | Sprint plan, assumptions-register cadence, dependency chasing (**party-link, code lists, attachment/comment sourcing, in-tenant model, ZATCA thresholds**) |
| VAT SME | Rule-pack correctness, box mapping, materiality, tax-point & rate-period rules, **penalty statutory sign-off**, "legitimate difference" sign-off |
| Data engineer | Ingestion adapters, join resolver, schema/migrations, synthetic generator (the test oracle) |
| Backend engineer | FastAPI services, rules-engine runtime, orchestration state machine, workers, immutable log |
| ML/LLM engineer | The one **in-tenant** LLM boundary, notes/letters reading, report/NBA narrative, prompts + guardrails, process-mining + crosswalk |
| Frontend engineer | React workbench, evidence viewer, bridge waterfall, action-trail timeline |
| Auditor liaison (ZATCA) | Ground-truth interpretation, code-list decoding, HITL realism, approve/return UX, **materiality/penalty threshold authority** |

### 7.6 Risk register (top)

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| 1 | **Party-link field missing (seller/buyer VAT no) — a HARD PREREQUISITE for direction, reconstruction, and box-level validation, not a degrade-gracefully item** | Critical | Single swappable resolver interface (§8); synthetic injects it so plumbing runs; **real-data reconstruction is blocked until it lands — #1 dependency to unblock** |
| 2 | **Purchase-side invoice availability — input VAT needs supplier-issued invoices retrievable by buyer VAT no from a complete national store; simplified/B2C omit buyer identity** | High | Split box_mapping into sales (high-conf) vs purchase (contingent); `PURCHASE_BUYER_UNIDENTIFIED` bucket; honest "cannot reconstruct where buyer unidentified" residual; own confidence tier |
| 3 | **External LLM SDK vs PDPL in-tenant residency** | High (legal/compliance blocker) | Mandate in-tenant / self-hosted model (or ZATCA-approved bounded endpoint) behind `LLMService`; no taxpayer data leaves tenant; resolve before LLM boundary ships |
| 4 | **Audit-outcome fields (`IMPORT_*`/`XBRL_*`) leaking as live inputs** | High (circularity) | Reclassified as Phase-8 labels only; boxes 8/9/14/15/gov are declared pass-throughs live; TRT-02/03/COR-04 deferred to real feeds |
| 5 | **Wrong version audited — `Current_Flag='Y'` may be post-audit corrected return** | High (reconciles against the answer) | Default selector = as-filed-at-referral (`OLD_TAX_AMT`/`AUD_DATE_G`); Phase-8 quarantines cases where no version reconciles |
| 6 | **Attachment/COMMENTS not present in SAP extract** (Objective-2 Tier-0 unconfirmed) | High (headline) | Demoted to open data-availability question with named owner (§9); fallback Tier-0 = prior returns + e-invoices |
| 7 | PDPL / PII exposure (`BP_CONTACT_*`) | High (legal) | Physically segregated table + column grants; masked by default, unmask logged; never at LLM boundary; in-tenant |
| 8 | LLM false-negative (hallucinated explanation nets down a real finding) | High (under-assessment is litigable) | Residual-reducing LLM extractions annotate-only until human-confirmed; residual stays gross; symmetric to the false-positive guard |
| 9 | LLM hallucination in narrative | High (defensibility) | LLM fenced to language; `verify_claims()` rejects unbacked sentences; core owns all numbers |
| 10 | Undecoded client code lists | Med | `code_dictionary` stub rows; degrade gracefully; decode with liaison in S1–S2 |
| 11 | Rule ambiguity (Total/adjustment, tax point, Box-14 sign) | Med | Assumptions register defaults + impact; **Box-14 sign decided analytically at S0**; VAT SME sign-off; Phase 8 confirms |
| 12 | Sparse legacy/migrated cases skew validation | Med | Gold/Silver/Bronze tiering; headline on Gold; report coverage |
| 13 | **Real closed cases may not arrive — business-case metrics 6–7 circular on synthetic** | Med-High | Synthetic validates plumbing only; real cases are an explicit gating dependency; no-real-data fallback reports reconstruction/consistency plumbing only |
| 14 | **Materiality/penalty thresholds invented** | Med (defensibility) | All thresholds marked "requires ZATCA authority sign-off"; penalty is statutory — sourced to ZATCA regime with sign-off or made a human-only field |

### 7.7 Governance
Four-tier evidence hierarchy enforced by `GovernanceService.assert_state_raise()` (the single choke point — POTENTIAL-FINDING requires a Tier-1 element) **and `GovernanceService.hold_unconfirmed_netting()`** (residual-reducing LLM explanations stay annotate-only until human-confirmed — the symmetric false-negative guard); LLM confined to `extract_claims` + `draft_prose` on an **in-tenant model**, with prompt/response hashed into the log; immutable hash-chained `audit.action_log` as the trust substrate; product positioned throughout (header, report §2, sign-off) as **decision support with mandatory human approval** — the auditor is the assessing authority.

---

## 8. Stub → swap table (known data gaps)

Every gap is a labelled socket. **Two are hard prerequisites, not graceful-degradation items** (marked ⚑) — the pipeline runs on synthetic data through them but cannot produce real-data results until they close.

| Gap | PoC stub (default) | Swap trigger | Swap cost |
|---|---|---|---|
| ⚑ **Invoice → party link** (seller/buyer VAT number field) — gates `direction` = all reconstruction + box validation | `ConfigPathPartyLinkResolver` reads `config.party_link` JSONPaths against `invoice_header.raw`; **synthetic default injects the field so plumbing runs** | Client provides `AccountingSupplier/CustomerParty` mapping | Config path (or resolver class) only; every VAT-number read already routes through this one interface — but **real-data reconstruction is blocked until it lands** |
| ⚑ **Purchase-side invoice retrieval** (supplier→taxpayer invoices by buyer VAT no) | Sales boxes reconstruct without it; purchase boxes behind a confidence tier; un-reconstructable input VAT → `PURCHASE_BUYER_UNIDENTIFIED` bucket | FATOORA national-store buyer-keyed query + buyer identification confirmed | Enable purchase-tier `box_mapping`; no engine change, but coverage genuinely limited where buyer unidentified |
| **Credit/debit note → original invoice** (BillingReference) | `NoteLinkAdapter` **nets only aggregate-within-period/category**; unmatched → explicit `UNLINKED_NOTE` bridge line, never silently consumed | BillingReference path provided | Replace matcher behind interface; refines `BR_CN`/`BR_DN` from aggregate to per-original |
| **Prepayment (386) → final invoice (388)** | 386 posts output VAT at prepayment tax point (TIM-05); reverses at aggregate against 388 within period | BillingReference/original-doc link provided | Per-original reversal behind same interface as notes |
| **Code lists** (`CASE_REASON_CODE`, `ROOT_CAUSE_CODE`, `AUDIT_RESULT_TYPE`, `RISK_CATEGORY`, `ACTION_TAKEN`) | `code_dictionary` rows `is_placeholder=true`, rendered `UNKNOWN(code=X)`; grouping/validation work on raw code | Client code lists delivered | Flip `is_placeholder`, populate `label`/`meaning`; no schema/code change |
| **Filing attachments / COMMENTS** (`stg.return_attachment`/`_comment`) — **sourcing UNCONFIRMED in SAP extract** | Modelled from the eServices manual; synthetic generator produces them | **Source-A owner confirms warehouse carries them** | If present: enable Tier-0. **If absent: Objective-2 Tier-0 falls back to prior-returns + e-invoices** (headline recalibrated) |
| **Notes/letters content** (`NOTE_OID_ID`, `LETTER_*`) | In-tenant `LLMService` reads synthetic notes | Real content delivered | Point loader at real payloads; prompts unchanged |
| **Customs/import + RCM feed** (Box 8/9) & **contract register** (gov supplies) | **No reconstruction — declared figure accepted, `partial=true`**; `IMPORT_*`/`XBRL_*` are Phase-8 labels only | Real feed provided | Implement adapter behind existing socket; only then do TRT-02/03/COR-04 become live |
| **LLM hosting** | In-tenant / self-hosted model runtime in the Compose stack | ZATCA approves a specific bounded endpoint (optional) | Repoint `LLMService` base URL; no data-flow change |
| **Rule confirmations** (`Total=Amount+Adjustment`; tax point; version selector; Box-14 sign) | Register defaults: netted / IssueDate / **as-filed-at-referral** / **Box-14 sign decided analytically at S0** | VAT SME confirms / S0 analysis | Flip register value; rules re-read config |
| **ZATCA materiality & penalty thresholds** | Provisional `max(SAR 1, 0.5%)`; penalty human-only | ZATCA authority sign-off | Populate `config.materiality`; enable statutory penalty calc under sign-off |
| **Real end-to-end closed cases** | Synthetic labels drive Phase 8 — **plumbing only, not accuracy** | Real closed cases delivered | Add to validation cohort; harness unchanged — **business-case metrics 6–7 unlock only here** |

---

## 9. What changed because of the eServices manual (and what remains unconfirmed)

The eServices "Submit VAT Return" manual reshaped the design — but one of its implications rests on **sourcing that is not yet confirmed in the SAP extract**, now flagged honestly:

1. **A potential highest-priority evidence tier before any audit contact.** Supporting documents are attached **at filing time** and a free-text **COMMENTS/clarifications** field is submitted **with** the return — internal evidence the taxpayer *already provided*. We design `stg.return_attachment` and `stg.return_comment` (keyed `(form_number, from_date, to_date)`) as **Tier-0** in the evidence-exhaustion ladder. **CAVEAT (fix #6):** the manual shows these in the *filing-service UI*; **Source A (the SAP data-warehouse extract) lists no attachment/comment fields.** This is therefore an **open data-availability question with a named Source-A owner**, not a solved socket. If the warehouse does not carry them, the Objective-2 Tier-0 lever **falls back to prior returns + e-invoices**, and the ≥30–40% request-reduction headline is recalibrated accordingly. It is not presented as built until confirmed.

2. **"Data-entry error" is a first-class exception family.** The return is a **manual 3-section form** (VAT on Sales / VAT on Purchases / Total VAT), so transposition and decimal-shift mistakes are expected. This promoted **DAT-05** (internal-consistency / manual-entry) into the priority-12 pack as a **tier-0 pre-conditioner** and the cheapest real finding — no invoice join required, no dependency on the unconfirmed attachment sourcing.

3. **The box mapping is confirmed.** The manual's three sections corroborate the sales/purchase/total box structure, hardening the Phase-2 `config.box_mapping` and the C4/C5/C6/C7 footing-and-composition checks (with C7 using the **S0-decided** Box-14 sign).

4. **The SADAD tie-point is fixed.** Submit generates a SADAD bill → `SADAD_Bill_Number`, giving a concrete cross-reference between the filing event and the return record.

5. **NBA guardrail language sharpened.** Because clarifications and attachments *may* already answer the question, the NBA internal ladder checks filing `COMMENTS`/attachments **before** the terminal taxpayer-request rung **where those sources are confirmed present** — making the "exhaust internal first" guarantee concrete. Where sourcing is unconfirmed (per #1 above), the ladder's confirmed Tier-0 is prior-returns + e-invoices, and the request-reduction target is stated as contingent, not assured.