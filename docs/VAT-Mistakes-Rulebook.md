# VAT Mistakes Rulebook — ZATCA AI VAT Audit Agent

**Purpose.** This rulebook is the canonical catalogue of taxpayer VAT mistakes the agent must catch when investigating a flagged case. Each rule reconstructs the *expected* KSA VAT return from cleared FATOORA e-invoices (aggregating `TAXSUBTOTAL` by tax category × rate × direction × period), plus external feeds where e-invoices cannot reach (customs/Bayan, AP/payment ledgers, counterparty master), compares that reconstruction to the declared boxes, and names the concrete explanation for every residual. Detection is deterministic; AI only reads/narrates free text; a human auditor approves every finding. These rules are the content behind `config.rule_library`, and each maps to a `ROOT_CAUSE_CODE`.

---

## Legend

**Severity** — risk × typical SAR materiality:
- **High** — direct revenue loss or strong evasion signal.
- **Medium** — material but often timing, valuation, or structural.
- **Low** — small/systematic (rounding, base-only) or self-penalising.

**explains_gap** — does the rule explain an e-invoice-vs-filing difference?
- **Yes → Box X (direction)** — the mistake moves value into/out of a named box and closes part of the reconstructed-vs-declared residual.
- **No (compliance/registration/valuation/customs)** — the residual is real but is *not* derivable from FATOORA; it must be evidenced from an external feed or is a pure compliance defect.
- **Partial** — the box reclass is e-invoice-provable but a second element (proof of export, RCM output leg) needs an external feed.

**Shared materiality gate `τ` (single source of truth in `config.rule_library`).** A residual is flagged only when `|residual| > max(SAR 1,000, 0.5% of the compared box)`, in SAR (`TaxCurrencyCode`). All families consume this one function — no per-family drift. Where a rule historically used a wider band (e.g. input-pool 1%), it now reads `τ` with a rule-level override recorded in config, not a hard-coded constant.

**Global data preconditions (apply wherever cited):**
- **CP-MASTER** — rules that classify a *counterparty* (customer/supplier residence, sector, government type, registration validity) require a **counterparty BP-master dimension** or the invoice buyer/seller-party fields. The audited taxpayer's own `NATIONALITY`/`BP_RESIDENT_FLAG`/`ZZBPTYPE`/`IND_SECTOR` describe **the taxpayer, not the counterparty** — never read them as the counterparty's attribute.
- **BUYER-SOCKET** — supplier-invoice-backed **input** reconstruction depends on **buyer-keyed FATOORA retrieval** (`PURCHASE_BUYER_UNIDENTIFIED`). ZATCA invoices are seller-submitted; until this socket is confirmed live, input-pool rules run `partial=true` and fall back to AP-ledger/registry checks. INP and COR-02 share this single dependency (see INP preamble).
- **RATE-TRANSITION** — one shared detector owns the 2020-07-01 5%→15% arithmetic; family rules call it rather than re-deriving it (see CMP-07).
- **VERSION-SELECT** — reconcile against the return version **as filed at referral** (`Box16 ≈ OLD_TAX_AMT` at `AUD_DATE_G`), not merely `Current_Flag='Y'` (see COR-05).

---

## Summary table — all rules

| code | title | family | explains_gap | severity |
|---|---|---|---|---|
| OUT-01 | Under-declared / omitted standard-rated sales | Output | Yes → Standard_Rate_Sales | High |
| OUT-02 | Wrong rate 5% vs 15% (2020-07-01 transition) | Output | Yes → Standard_Rate_Sales _5↔_15 | High |
| OUT-03 | Standard sales mis-declared as zero-rated/exempt | Output | Yes → Zero/Exempt ↔ Standard | High |
| OUT-04 | Exports zero-rated without flag / proof | Output | Partial (reclass Yes; proof customs) | High |
| OUT-05 | GCC sales mislabelled | Output | Yes → GCC/Exports ↔ Standard | Medium |
| OUT-06 | Government-supplied sales mishandled (15/5) | Output | Yes → Government_Supplied_Sales | Medium |
| OUT-07 | Tax-point / period-straddle timing | Output | Yes → Standard_Rate_Sales (timing) | Medium |
| OUT-08 | Output VAT not charged on deemed/nominal supplies | Output | No (compliance/valuation) | Medium |
| OUT-09 | Excessive / fictitious credit notes suppressing output | Output | Yes → Standard_Rate_Sales (netting) | High |
| OUT-10 | Supplies to connected persons below fair market value | Output | No (valuation) | Medium |
| OUT-11 | Government supplies recognised on platform approval (Etimad) | Output | Yes → Standard_Rate_Sales_VAT (timing) | Medium |
| INP-01 | Input VAT claimed with no valid cleared tax invoice | Input | Yes → Standard_Rate_Purchase_VAT | High |
| INP-02 | Input VAT on blocked / non-deductible items | Input | Yes → Standard_Rate_Purchase_VAT | Medium (High fleet/entertainment) |
| INP-03 | No partial-exemption apportionment | Input | Yes → Standard_Rate_Purchase_VAT | High |
| INP-04 | Duplicate input claim (cross-period re-claim) | Input | Yes → Standard_Rate_Purchase_VAT | High |
| INP-05 | Input VAT claimed at the wrong rate | Input | Yes → Standard_Rate_Purchase_VAT | Medium |
| INP-06 | Input VAT on zero-rated / exempt purchases | Input | Yes → Standard_Rate_Purchase_VAT | Medium |
| INP-07 | Claiming before the tax point / on prepayments | Input | Yes → Standard_Rate_Purchase_VAT (timing) | Medium |
| INP-08 | Input VAT from non-registered/deregistered suppliers | Input | Yes → Standard_Rate_Purchase_VAT (lead compliance) | High |
| INP-09 | Input claimed in the wrong / a late period | Input | Yes → Standard_Rate_Purchase_VAT (timing) | Low–Medium |
| INP-10 | Capital-assets scheme adjustment on change of use not made | Input | No (compliance, multi-year) | Medium |
| INP-11 | Input not repaid on supplier invoices unpaid > 12 months | Input | No (compliance, AP feed) | Medium |
| RCM-01 | Imported services never reverse-charged (Box 9 empty) | Reverse-charge | No (AP feed) | High |
| RCM-02 | Goods-import VAT (Box 8) understated vs customs | Reverse-charge | No (customs feed) | High |
| RCM-03 | Import VAT claimed without actual customs payment | Reverse-charge | No (customs feed) | High |
| RCM-04 | Box 9 symmetry broken (output/input legs don't tie) | Reverse-charge | No (Box 8/9 mechanics) | Medium |
| RCM-05 | RCM/import input claimed without right to deduct | Reverse-charge | No (compliance) | High |
| RCM-06 | Wrong rate on the self-assessed amount | Reverse-charge | No (Box 9 rate check) | Medium |
| RCM-07 | RCM supply booked as ordinary domestic purchase (Box 7) | Reverse-charge | Partial → Box 9 output leg missing | Medium |
| RCM-08 | Intra-GCC supply mistreated / double-counted | Reverse-charge | No (customs/AP feed) | Medium |
| RCM-09 | Wrong-period / accounting-method mismatch on import & RCM | Reverse-charge | No (timing vs customs/AP) | Low–Medium |
| RCM-10 | RCM wrongly applied to a resident/registered supplier | Reverse-charge | Partial → belongs in Box 7 | Medium |
| COR-01 | Sales credit notes (381) issued but output not reduced | Corrections | Yes → Standard_Rate_Sales_VAT | Medium (High if reversed) |
| COR-02 | Supplier credit notes (381) not reversing input VAT | Corrections | Yes → Standard_Rate_Purchase_VAT | High |
| COR-03 | Debit notes (383) issued but extra output not added | Corrections | Yes → Standard_Rate_Sales_VAT | Medium–High |
| COR-04 | Bad-debt relief claimed without meeting conditions | Corrections | Yes → Standard_Rate_Sales_Adjustment (if valid) | High |
| COR-05 | Reconciling against the wrong return version | Corrections | Yes → Box16 (baseline selection) | High |
| COR-06 | Box-14 self-correction used above the per-error cap | Corrections | Yes → Box14 carve-out (finding = compliance) | Medium (High if concealing) |
| COR-07 | Correction double-counted (381 AND Box-14) | Corrections | Yes → Box16 (over-relief) | High |
| COR-08 | Orphan `_Adjustment` not tied to any event | Corrections | No when orphan / Yes when tied | Medium–High |
| COR-09 | VAT credit (Box15) carried forward incorrectly | Corrections | No (compliance) | High |
| COR-10 | Amended return reverses a genuine liability | Corrections | Yes → Box13/Box16 | High |
| CMP-01 | Late filing of the VAT return | Compliance | No (compliance/timing) | Medium (High if chronic) |
| CMP-02 | Late or unpaid VAT payment (SADAD) | Compliance | No (compliance/payment) | Medium (High if large) |
| CMP-03 | Nil / under-stated return while e-invoices show activity | Compliance | Yes → Standard_Rate_Sales | High |
| CMP-04 | Failure to register / late registration above threshold | Compliance | No (registration) | High |
| CMP-05 | Charging VAT after deregistration / failure to deregister | Compliance | Yes → Standard_Rate_Sales (+ registration) | High |
| CMP-06 | VAT-group changes not reflected in filings | Compliance | Yes → Standard_Rate_Sales | Medium (High if intra-group VAT) |
| CMP-07 | Ignoring the 2020 rate change (portfolio trigger) | Compliance | Yes → Standard_Rate_Sales / _Purchase _5↔_15 | High |
| CMP-08 | Wrong filing frequency for the turnover band | Compliance | No (structural) | Medium |
| CMP-09 | Business/sector/activity change not reflected | Compliance | Yes → Zero/Exempt/Exports vs Standard | Medium |
| CMP-10 | Missing period / broken filing continuity | Compliance | No (compliance) | High |
| CMP-11 | Real-estate supply still charged 15% after RETT (2020-10-04) | Compliance | Yes → Standard_Rate_Sales ↔ Exempt_Sales | High |
| CMP-12 | E-invoicing Phase-2 integration-wave non-compliance | Compliance | No (compliance) | Medium |
| DAT-01 | Cleared invoices missing from the filing (under-declared) | Data | Yes → mapped sales box | High |
| DAT-02 | Filing exceeds the e-invoice store (over-declared / under-reporting) | Data | Yes → over-declared sales box | Medium |
| DAT-03 | Invoices reported late (supply in period, clearance next) | Data | Yes → affected box (timing) | Medium |
| DAT-04 | Non-cleared / rejected invoices wrongly in/excluded | Data | Yes → affected box | High |
| DAT-05 | Duplicate invoices (same UUID / broken hash chain) | Data | Yes → inflated box | Medium (High on purchase) |
| DAT-06 | Wrong buyer/seller VRN → wrong party or direction | Data | Yes → shifts sales ↔ purchase | High |
| DAT-07 | Simplified (B2C) vs standard (B2B) invoices mishandled | Data | Yes → Standard_Rate_Sales | Medium |
| DAT-08 | Foreign-currency invoices converted wrongly | Data | Yes → affected domestic box (not imports) | Medium |
| DAT-09 | Rounding differences mis-accumulated | Data | Yes → affected VAT box (closes small residual) | Low |
| DAT-10 | Allowances/discounts not netted from the base | Data | Yes → Standard_Rate_Sales base | Low |
| DAT-11 | Prepayments (386) double-counted or mistimed | Data | Yes → Standard_Rate_Sales | Medium |
| DAT-12 | Manual portal data-entry / internal-consistency errors | Data | No (arithmetic pre-gate) | Medium (High on totals) |

**65 rules across 6 families.**

---

## Family OUT — Output VAT (sales-side)

*Where the declared output position diverges from the output VAT reconstructed by aggregating sales-direction `INVOICELINE`/`TAXSUBTOTAL` (category S/Z/E/O × rate 15/5/0) within `From_Date..To_Date`.* DAT-01/02 own the raw completeness reconciliation; OUT-01…09 are the classification/rate/timing explainers layered on that residual.

**OUT-01 — Under-declared / omitted standard-rated sales**
- **taxpayer_mistake:** Reports less standard-rated output than the issued tax invoices show — a slice of 15% sales never reaches `Standard_Rate_Sales`.
- **why_it_happens:** Manual re-keying from a sub-ledger that misses branches/POS tills; cash sales left out; deliberate suppression.
- **detection:** Reconstruct expected = Σ `TAXSUBTOTAL.TaxableAmount`/`.TaxAmount` for `INVOICELINE.ItemClassifiedTaxCategoryID='S'` AND `Percent=15`, over `INVOICES` `InvoiceTypeCode IN (388,383)` minus `381`, tax point in period. Compare Σ TaxableAmount vs `Standard_Rate_Sales_Amount_15 (+_Adjustment)` and Σ TaxAmount vs `Standard_Rate_Sales_VAT_Amount_15`. Flag if `reconstructed − declared > τ`. Internal ratio check `VAT_Amount_15 ≈ Amount_15 × 0.15`.
- **data_used:** INVOICES, INVOICELINE, TAXSUBTOTAL; `Standard_Rate_Sales_Amount_15`/`_VAT_Amount_15`/`_Adjustment`; From_Date/To_Date.
- **explains_gap:** Yes → Standard_Rate_Sales (output).
- **severity:** High.
- **confirming_evidence:** Enumerate the cleared (`STATUSCODE`) invoices inside the residual absent from the declared base; if still unexplained, request the GL sales-account reconciliation before a query letter.
- **ai_assist:** Read `Reason_For_Amendment`/`NOTE_OID_ID`/`LETTER_*` for a narrated shortfall (e.g. "excludes intercompany"); summarise the residual invoice list.

**OUT-02 — Wrong VAT rate applied (5% vs 15%, 2020-07-01 transition)** *(calls RATE-TRANSITION)*
- **taxpayer_mistake:** Charges/declares 5% on supplies with tax point ≥ 2020-07-01 (should be 15%), or 15% on genuine pre-transition supplies.
- **why_it_happens:** ERP tax-code not switched on the rate-change date; long-running contracts; transitional-rule confusion.
- **detection:** For each S-line, tax point = earlier of `IssueDate`/`ActualDeliveryDate`. Flag `Percent=5` where tax point ≥ 2020-07-01 (outside the transitional window) and `=15` where tax point < 2020-07-01. Uplift = Σ affected `TaxableAmount × (0.15−0.05)`. Corroborate: material `Standard_Rate_Sales_Amount_5` for a period wholly post-switch.
- **data_used:** INVOICELINE (Percent), INVOICES (IssueDate, ActualDeliveryDate); `Standard_Rate_Sales_*_5` vs `*_15`.
- **explains_gap:** Yes → shift Standard_Rate_Sales `_5`↔`_15` (output).
- **severity:** High.
- **confirming_evidence:** Contract/PO and delivery dates fixing the tax point; if 5% lines relate to a pre-2020 continuous-supply contract, apply transitional relief and reclassify as explained.
- **ai_assist:** Read contract-date references in filing notes/`LETTER_*` to validate transitional-relief claims.

**OUT-03 — Standard-rated sales mis-declared as zero-rated or exempt**
- **taxpayer_mistake:** Puts 15% sales into `Zero_Rated_Sales` or `Exempt_Sales`, avoiding output VAT (and, for exempt, distorting input apportionment).
- **why_it_happens:** Misreading zero-rating/exemption scope; a Z/E box used as a dumping ground.
- **detection:** Compare declared `Zero_Rated_Sales_Amount` vs reconstructed category-`Z` Σ TaxableAmount, and `Exempt_Sales_Amount` vs category `E`. Flag where declared Z or E **exceeds** invoice-reconstructed Z/E by > τ AND a matching understatement appears in `Standard_Rate_Sales_Amount_15` (paired offset). Confirm the suspect lines carry no `TaxAmount` despite not truly being Z/E.
- **data_used:** INVOICELINE (category), TAXSUBTOTAL; Zero_Rated_Sales_Amount, Exempt_Sales_Amount, Standard_Rate_Sales_Amount_15.
- **explains_gap:** Yes → offset Zero/Exempt ↔ Standard (output).
- **severity:** High.
- **confirming_evidence:** Sample invoices in the excess Z/E block for their true `ItemClassifiedTaxCategoryID=S`; taxpayer `IND_SECTOR` peer norm (a retailer at 90% zero-rated is anomalous). Next-best: request the zero-rating basis per stream.
- **ai_assist:** Classify item descriptions on suspect lines to assess whether a genuine zero-rate/exemption basis exists; read filing notes for a stated basis.

**OUT-04 — Exports zero-rated without the export flag or proof of export** *(CP-MASTER for customer residence/currency)*
- **taxpayer_mistake:** Books sales into `Exports_Amount` at 0% but the invoices are not export-flagged and/or there is no evidence of goods leaving KSA.
- **why_it_happens:** Treating any foreign customer as an export; missing customs/transport docs; local supply dressed as export.
- **detection:** Reconcile declared `Exports_Amount` to Σ invoices whose `InvoiceTypeCode` **name** carries the export marker AND category `Z`. Flag the portion with **no** export-flagged invoice, or where `DocumentCurrencyCode='SAR'` with a resident customer (counterparty master). Residual export lacking flag = treated as standard-rated; expected VAT = residual × 15%.
- **data_used:** INVOICES (InvoiceTypeCode name, DocumentCurrencyCode), INVOICELINE category Z; **counterparty** residence/nationality; Exports_Amount.
- **explains_gap:** **Partial** — box reclass Exports↔Standard = Yes (output); proof-of-export = No (customs-only).
- **severity:** High.
- **confirming_evidence:** Customs export declaration / bill of lading against the invoice; prefer internal shipping records first; absent proof, reclassify to standard-rated and quantify.
- **ai_assist:** Read attached-document references/`LETTER_*` for export proof already provided; flag customer-country vs currency mismatch.

**OUT-05 — GCC (intra-GCC) sales mislabelled** *(CP-MASTER for customer nationality/registration)*
- **taxpayer_mistake:** Reports GCC-customer supplies in the wrong box — as exports/zero-rated or in `Sales_To_Customers_GCC` — when the live transitional treatment makes them standard-rated KSA supplies.
- **why_it_happens:** Assuming all GCC is export-like; the GCC electronic-services regime not being live means most "GCC sales" are standard-rated local supplies.
- **detection:** Compare `Sales_To_Customers_GCC_Amount` to invoices where **counterparty** nationality is a GCC state. Because intra-GCC defaults to standard KSA VAT, flag GCC-box amounts carrying category `Z`/0% with no export flag; reclass to `Standard_Rate_Sales_Amount_15`, VAT = amount × 15%. Also flag GCC amounts double-counted inside `Exports_Amount`.
- **data_used:** Sales_To_Customers_GCC_*, Exports_*, Standard_Rate_Sales_*_15; INVOICES/INVOICELINE; **counterparty** nationality/residence.
- **explains_gap:** Yes → GCC/Exports ↔ Standard (output).
- **severity:** Medium.
- **confirming_evidence:** Counterparty VAT registration in the GCC state + movement evidence; absent, treat as standard-rated. Cross-check RCM-08 (purchase mirror).
- **ai_assist:** Narrate the GCC-vs-export-vs-standard determination.

**OUT-06 — Government-supplied sales mishandled (15/5 split)** *(CP-MASTER for government-customer flag)*
- **taxpayer_mistake:** Errors in `Government_Supplied_Sales_*_15`/`_5` — omitting government sales, wrong rate split, or netting retentions so the base understates output.
- **why_it_happens:** Public-sector contract terms and payment retention; rate-by-tax-point confusion; a separate government billing stream not integrated in VAT prep.
- **detection:** Identify government-customer invoices via **counterparty** master (government BP type) and reconstruct their S-category `TAXSUBTOTAL` by rate. Compare to `Government_Supplied_Sales_Amount_15/_5` and `_VAT_Amount_15/_5`. Flag if reconstructed − declared > τ, or if the 15/5 split contradicts each invoice's tax point vs 2020-07-01 (RATE-TRANSITION). Verify `_VAT_Amount ≈ _Amount × rate`.
- **data_used:** Government_Supplied_Sales_*_15/_5; INVOICES/INVOICELINE/TAXSUBTOTAL; **counterparty** government-type master.
- **explains_gap:** Yes → Government_Supplied_Sales (output).
- **severity:** Medium.
- **confirming_evidence:** Government contract + payment certificates; match retention timing to tax-point rules. Next-best: request the public-sector billing schedule.
- **ai_assist:** Read contract/notes to confirm retention treatment and rate basis.

**OUT-07 — Tax-point / period-straddle timing errors**
- **taxpayer_mistake:** Assigns a sale to the wrong period — invoice date used when delivery/payment set an earlier tax point (or vice-versa) — so output lands in the adjacent period.
- **why_it_happens:** `ACCOUNTING_METHODE` (cash vs accrual) applied inconsistently; `IssueDate` used as a proxy when `ActualDeliveryDate` or prepayment (386) triggered the tax point; quarter-end straddle.
- **detection:** For invoices where `IssueDate` and `ActualDeliveryDate` fall in different return periods, recompute the correct period (goods = delivery; prepayment 386 = payment; per `ACCOUNTING_METHODE`). Flag invoices whose declared period ≠ correct period; quantify per-period over/under-declaration.
- **data_used:** INVOICES (IssueDate, ActualDeliveryDate, 386, PrepaidAmount); TP `ACCOUNTING_METHODE`; From_Date/To_Date across adjacent returns.
- **explains_gap:** Yes → timing shift of Standard_Rate_Sales between periods (output).
- **severity:** Medium (usually timing; penalty/interest exposure).
- **confirming_evidence:** Delivery/payment dates fixing the tax point; confirm the amount surfaces in the neighbouring return before treating as a true understatement.
- **ai_assist:** Narrate whether the straddle nets to a permanent loss or pure timing.

**OUT-08 — Output VAT not charged on deemed / nominal supplies**
- **taxpayer_mistake:** No output VAT on deemed supplies — free samples/gifts above de-minimis, business assets to private use, or assets on hand at deregistration — because no ordinary sales invoice is raised.
- **why_it_happens:** "No money received = no VAT"; deregistration wind-down overlooked; give-aways not treated as supplies.
- **detection:** Weak-signal, cross-source: (a) at deregistration (`DEREG_TYPE` set, `TO_DATE` in period) expect deemed-supply output on closing assets — often absent; (b) reconcile large `AllowanceTotalAmount`/zero-value/100%-discount lines carrying no `TaxAmount`; (c) `IND_SECTOR` give-away norm. Flag deregistration or material zero-consideration outputs with **no** corresponding output VAT.
- **data_used:** TP `DEREG_TYPE`/`TO_DATE`/`IND_SECTOR`; INVOICES/INVOICELINE, LEGALMONETARYTOTAL (AllowanceTotalAmount, TaxExclusiveAmount), TAXTOTAL; sales boxes.
- **explains_gap:** No (compliance/valuation — output owed but no ordinary invoice to reconcile against).
- **severity:** Medium.
- **confirming_evidence:** Fixed-asset register / deregistration stock list; marketing spend on give-aways. Next-best: request the deemed-supply working.
- **ai_assist:** Read filing/deregistration notes and asset descriptions to identify triggers and estimate value.

**OUT-09 — Excessive / fictitious credit notes suppressing output VAT** *(cross-ref COR-01 — engine must not double-adjust the same 381 set)*
- **taxpayer_mistake:** Over-uses credit notes (`381`) to reduce declared output — without a genuine return/cancellation, or in the wrong period — so net Standard_Rate_Sales is understated.
- **why_it_happens:** Managing declared VAT down at period-end; genuine adjustment in the wrong period; credit note issued but the supply still stands.
- **detection:** Credit-note ratio = Σ `TaxAmount`[381] ÷ Σ `TaxAmount`[388] per period; flag vs `IND_SECTOR`/`BUSINESS_SIZE` peer norm or a period-on-period spike. Verify each material 381 references a valid original 388 (matching buyer, ≤ original, in-period tax point). Unmatched/over-value credit notes are added back: understated output = Σ invalid 381 `TaxAmount`. **Scope split vs COR-01:** OUT-09 = *invalid/excess* credits (added back); COR-01 = *valid* credits *not netted* (over-declaration). One 381 belongs to exactly one path.
- **data_used:** INVOICES (381/388, IssueDate), TAXTOTAL/TAXSUBTOTAL; TP IND_SECTOR/BUSINESS_SIZE; Standard_Rate_Sales boxes.
- **explains_gap:** Yes → reduces legitimate netting inside Standard_Rate_Sales (output).
- **severity:** High.
- **confirming_evidence:** Original invoice + evidence of return/cancellation (goods-return note, refund); unmatched credits escalate to a query letter.
- **ai_assist:** Read credit-note `Reason` text to judge valid adjustment vs bare reduction.

**OUT-10 — Supplies to connected persons below fair market value** *(CP-MASTER for relationship data)*
- **taxpayer_mistake:** Supplies to related parties (where the recipient can't fully recover) priced below open-market value, understating output — VAT is due on FMV.
- **why_it_happens:** Intercompany pricing set for non-VAT reasons; unaware of the FMV override.
- **detection:** Identify connected-party invoices (shared ownership, `VAT_GROUP_REP_FLAG` relationships, repeated counterparty) whose unit price is materially below the taxpayer's arm's-length norm for the same item; uplift = (FMV − charged) × 15%.
- **data_used:** INVOICES buyer party; INVOICELINE price vs peer; TP `VAT_GROUP_REP_FLAG`; `IND_SECTOR`.
- **explains_gap:** No (valuation — output owed above invoiced value; not a clean box gap).
- **severity:** Medium.
- **confirming_evidence:** Ownership/relationship data + arm's-length price. Next-best: related-party transaction listing.
- **ai_assist:** Read item descriptions for like-for-like price comparison.

**OUT-11 — Government supplies recognised on platform approval (Etimad)** *(CP-MASTER for counterparty class)*
- **taxpayer_mistake:** Not a mistake — a legitimate sector timing difference. Supplies to government bodies are commonly not recognised until the invoice is approved on the government procurement platform, which can fall months after the transaction period. The e-invoice sits in the earlier period; the return reports the supply in the later one.
- **why_it_happens:** Contractual and platform mechanics, not taxpayer behaviour. The auditors raised it directly: a generic e-invoices-total minus return-total comparison reports these as under-declarations, and they are not.
- **detection:** For invoices whose counterparty is classified as government, compare the platform approval date with the period end. Where approval falls after `Period_To`, the supply belongs to the following return: deferred output = Σ `TaxAmount` over those documents. Scope split vs OUT-07: OUT-07 is delivery-date straddle on any counterparty; OUT-11 is approval-date straddle on a government counterparty. One document belongs to exactly one path.
- **data_used:** INVOICES (buyer party, IssueDate, approval/clearance date), TAXSUBTOTAL; **CP-MASTER** counterparty classification; case `Period_From`/`Period_To`.
- **explains_gap:** Yes → Standard_Rate_Sales_VAT (timing — the supply arrives in the next return).
- **severity:** Medium.
- **confirming_evidence:** Platform approval record, or the contract and the certified payment application. Next-best: the taxpayer's own reconciliation of issued invoices to approved invoices.
- **ai_assist:** Read contract and approval correspondence to confirm the recognition trigger where the platform record is unavailable.

---

## Family INP — Input VAT (purchases-side)

*The taxpayer's "incorrect input-VAT claims."* Baseline (**BUYER-SOCKET, `partial=true`**): the app builds a **recoverable-input pool** = Σ `TAXSUBTOTAL.TaxAmount` over `INVOICES` where the taxpayer's `VAT_registration_number` = **buyer**, `InvoiceTypeCode=388`, `STATUSCODE`=cleared, netted for received 381, within period — **contingent on buyer-keyed FATOORA retrieval** (shared with COR-02). Until that socket is confirmed, INP rules that depend on the pool run `partial=true` and fall back to AP-ledger + registry + return-internal checks. INP covers **domestic supplier-invoice-backed input only**; import (Box 8) and reverse-charge (Box 9) input live in the RCM family.

**INP-01 — Input VAT claimed with no valid cleared tax invoice**
- **taxpayer_mistake:** Claims input VAT it holds no cleared 388 for — estimates, pro-forma, statements, or docs never cleared on FATOORA.
- **why_it_happens:** Honest timing (invoice not yet cleared) or evasion (inflating recoverable VAT with no document).
- **detection:** Declared `Standard_Rate_Purchase_VAT_Amount (+_Adjustment)` vs recoverable-input pool. Flag residual where declared − pool > τ. The portion with **no matching cleared 388 where taxpayer = buyer** (`STATUSCODE`≠cleared / `CLEANCEENABLED` false / no invoice) is the exposure.
- **data_used:** `Standard_Rate_Purchase_Amount`/`_VAT_Amount`/`_Adjustment`, period; INVOICES (InvoiceTypeCode, STATUSCODE, CLEANCEENABLED, buyer VRN), TAXSUBTOTAL; `TP.VAT_registration_number`.
- **explains_gap:** Yes → Standard_Rate_Purchase_VAT_Amount (input, overstated).
- **severity:** High.
- **confirming_evidence:** Request the specific cleared invoice UUIDs; if none/paper-only, disallow. Next-best: match to bank payment + supplier's own reported output.
- **ai_assist:** Read `NOTE_OID_ID`/filing comments for "invoice pending clearance" to route timing vs no-document.

**INP-02 — Input VAT on blocked / non-deductible items** *(CP-MASTER for supplier sector)*
- **taxpayer_mistake:** Recovers VAT on restricted costs — entertainment, catering/hospitality, employee private use, passenger vehicles not wholly for business.
- **why_it_happens:** Misunderstanding KSA blocking rules; treats all supplier VAT as recoverable.
- **detection:** Screen purchase lines for restricted categories via **supplier** sector (restaurants, hotels, catering, car dealers/rental) plus `INVOICELINE` descriptions. Sum VAT on flagged lines; any included in `Standard_Rate_Purchase_VAT_Amount` is disallowed.
- **data_used:** INVOICELINE (description, category/percent, line TaxAmount); **supplier** sector; declared purchase VAT box.
- **explains_gap:** Yes → Standard_Rate_Purchase_VAT_Amount (input); blocked VAT should never be in the pool, so it appears as a legitimate-looking match that is actually non-deductible.
- **severity:** Medium (High for fleet/entertainment-heavy sectors).
- **confirming_evidence:** Business-use log / fleet register; if none, disallow. Cross-check taxpayer `BUSINESS_SIZE`/sector norms for expected entertainment spend.
- **ai_assist:** Classify free-text descriptions into blocked vs allowable ("meals", "gift", "vehicle").

**INP-03 — No partial-exemption apportionment (100% input while making exempt supplies)** *(shared recovery-ratio routine with RCM-05)*
- **taxpayer_mistake:** Makes exempt supplies but recovers input in full instead of restricting residual/overhead input to the taxable-use proportion.
- **why_it_happens:** Doesn't know it is partially exempt; ignores the recovery ratio.
- **detection:** If `Exempt_Sales_Amount > 0`, recovery ratio = (Standard+Zero+Export taxable supplies) ÷ total supplies. Expected recoverable ≈ directly-attributable taxable input + (residual input × ratio). Flag if declared `Standard_Rate_Purchase_VAT_Amount` ≈ full pool with **no restriction** despite material exempt sales. Exposure ≈ residual input × exempt proportion.
- **data_used:** Exempt_Sales_Amount, Standard/Zero/Export sales; input pool; `TP.IND_SECTOR` (finance, residential real estate, healthcare/education).
- **explains_gap:** Yes → Standard_Rate_Purchase_VAT_Amount (input, overstated).
- **severity:** High (large SAR for financial/real-estate).
- **confirming_evidence:** Request the apportionment calculation; recompute annual wash-up. Exempt-heavy sector + 100% recovery → escalate.
- **ai_assist:** Read filing notes/`LETTER_*` for a claimed direct-attribution method before assuming standard method.

**INP-04 — Duplicate input-VAT claim (cross-period re-claim of one UUID)** *(scope: cross-period; DAT-05 owns within-period store dedup)*
- **taxpayer_mistake:** Recovers the same purchase invoice again in a later period.
- **why_it_happens:** Accrual + payment double-entry, catch-up bookkeeping, or a second copy (PDF vs cleared) booked.
- **detection:** Count claims of each invoice UUID/`PIH` across the taxpayer's filed periods (using only `Current_Flag`). If cumulative claimed input over periods > unique-UUID pool, or a UUID's `TaxAmount` appears in ≥2 filed periods, flag the duplicate VAT. (Same-period duplicate submissions belong to DAT-05.)
- **data_used:** INVOICES UUID/PIH/IssueDate; multiple periods' `Standard_Rate_Purchase_VAT_Amount`; `Data_Version`/`Current_Flag`.
- **explains_gap:** Yes → Standard_Rate_Purchase_VAT_Amount (input, duplicated).
- **severity:** High.
- **confirming_evidence:** Show the two periods carrying the same UUID; require reversal in the later period.
- **ai_assist:** None (deterministic key match).

**INP-05 — Input VAT claimed at the wrong rate** *(calls RATE-TRANSITION)*
- **taxpayer_mistake:** Recovers 15% when the cleared invoice carries 5% (transitional/pre-2020-07-01 continuing contract) or 0%, inflating the reclaim.
- **why_it_happens:** Applies today's 15% to old/transitional invoices; ignores the `_15`/`_5` split.
- **detection:** Per purchase invoice, compare claimed VAT to `INVOICELINE.ItemClassifiedTaxCategoryPercent` (15/5/0). Expected VAT = TaxableAmount × invoice percent. Flag where the declared VAT/base ratio implies a higher rate than invoices support; reconcile against declared `_15` vs `_5` split.
- **data_used:** TAXSUBTOTAL (TaxableAmount, TaxAmount, percent); declared `Standard_Rate_Purchase_*_15`/`_5`; invoice IssueDate vs 2020-07-01.
- **explains_gap:** Yes → Standard_Rate_Purchase_VAT_Amount (input, rate overstatement).
- **severity:** Medium.
- **confirming_evidence:** Line-level rate on the cleared invoice governs; recompute at correct percent.
- **ai_assist:** None (arithmetic).

**INP-06 — Input VAT claimed on zero-rated / exempt purchases**
- **taxpayer_mistake:** Books recoverable VAT against purchases carrying no VAT — zero-rated, exempt, or out-of-scope lines.
- **why_it_happens:** Plugs a VAT figure onto a net-only cost; miscodes Z/E purchases as standard.
- **detection:** Where declared `Standard_Rate_Purchase_VAT_Amount` maps to lines whose `ItemClassifiedTaxCategoryID = Z/E/O` (percent 0), flag — no VAT exists to recover. Cross-check that `Zero_Rated_Purchase_Amount`/`Exempt_Purchase_Amount` carry base but zero VAT.
- **data_used:** category/percent, TAXSUBTOTAL; Zero_Rated_Purchase_*, Exempt_Purchase_*, Standard_Rate_Purchase_VAT_Amount.
- **explains_gap:** Yes → Standard_Rate_Purchase_VAT_Amount (input, phantom).
- **severity:** Medium.
- **confirming_evidence:** Invoice tax category is authoritative; disallow VAT on Z/E/O lines.
- **ai_assist:** None.

**INP-07 — Claiming before the tax point / on prepayments**
- **taxpayer_mistake:** Recovers input before it is due — on a prepayment (386) or before delivery, or on cash-basis before payment.
- **why_it_happens:** Accrues the reclaim early; cash-accounting timing error.
- **detection:** Flag input tied to `InvoiceTypeCode 386` or `LEGALMONETARYTOTAL.PrepaidAmount > 0` where `ActualDeliveryDate` is after `To_Date`. For `ACCOUNTING_METHODE=cash`, require payment evidence before the claim period; if the claim precedes delivery/clearance/payment, defer.
- **data_used:** INVOICES (386, IssueDate/ActualDeliveryDate, PrepaidAmount); `TP.ACCOUNTING_METHODE`; period.
- **explains_gap:** Yes → Standard_Rate_Purchase_VAT_Amount (input, timing).
- **severity:** Medium (usually timing).
- **confirming_evidence:** Delivery/payment date; reallocate to the correct period rather than disallow.
- **ai_assist:** None.

**INP-08 — Input VAT from non-registered / deregistered suppliers** *(CP-MASTER for supplier registration)*
- **taxpayer_mistake:** Recovers "VAT" charged by a supplier not validly registered — no valid registration means no recoverable tax.
- **why_it_happens:** Accepts a non-compliant/handwritten invoice showing VAT; supplier not on FATOORA.
- **detection:** Validate the **supplier** VAT number on the purchase invoice against the registry; flag where the claim has no cleared e-invoice AND the supplier registration is absent/invalid, or the supplier's `TO_DATE`/`DEREG_TYPE` shows deregistration at `IssueDate`.
- **data_used:** supplier party VRN on INVOICES; **supplier** registration FROM_DATE/TO_DATE/DEREG_TYPE; declared purchase VAT.
- **explains_gap:** Yes → Standard_Rate_Purchase_VAT_Amount (input) — **lead compliance** (recoverability turns on registry validity).
- **severity:** High.
- **confirming_evidence:** Registry lookup at invoice date; if unregistered/deregistered, disallow.
- **ai_assist:** None.

**INP-09 — Input VAT claimed in the wrong / a late period**
- **taxpayer_mistake:** Deducts an invoice in a period other than when cleared/received — pulled forward, pushed back, or beyond the allowable window.
- **why_it_happens:** Catch-up bookkeeping; shifting reclaims to smooth cash flow or manage `Net_Due_VAT`.
- **detection:** Per claimed invoice, compare `IssueDate`/clearance date to filed period. Flag input whose invoice date sits outside the period and outside the permitted recovery window; check whether it belongs in `Corrections_From_Previous_Period` (Box14) rather than current-period input.
- **data_used:** INVOICES IssueDate/STATUSCODE; period, Box14; prior returns/amendments.
- **explains_gap:** Yes → Standard_Rate_Purchase_VAT_Amount (input, period-allocation; often nets to zero across periods).
- **severity:** Low–Medium (escalates if used to defer net VAT due).
- **confirming_evidence:** Reconcile across adjacent periods; if claimed nowhere else, reallocate rather than disallow.
- **ai_assist:** Read filing comments/`Reason_For_Amendment` to separate a genuine late-recovery correction from double-counting.

**INP-10 — Capital-assets scheme adjustment on change of use not made** *(requires AP/fixed-asset feed)*
- **taxpayer_mistake:** Recovered full input on a capital asset, then shifted its use toward exempt/non-business without the annual adjustment over the 6-year (movables) / 10-year (immovables) window.
- **why_it_happens:** Unaware of the capital-assets scheme; treats initial recovery as final.
- **detection:** Identify high-value capital lines (large `INVOICELINE.TaxableAmount`, asset descriptions), then track the taxable-use ratio (`Exempt_Sales_*` vs Standard/Zero/Export) across periods; expected annual adjustment = input × (baseline − current ratio) ÷ adjustment period. Flag absence of any matching `Standard_Rate_Purchase_Adjustment`.
- **data_used:** INVOICELINE (capital lines); sales-mix boxes over multiple periods; `Standard_Rate_Purchase_Adjustment`; `IND_SECTOR`.
- **explains_gap:** No (compliance — multi-year adjustment, not a single-period invoice gap).
- **severity:** Medium.
- **confirming_evidence:** Fixed-asset register + use-ratio history. Next-best: request the capital-assets adjustment working.
- **ai_assist:** Read asset descriptions to identify capital items.

**INP-11 — Input not repaid on supplier invoices unpaid > 12 months (bad-debt claw-back)** *(mirror of COR-04; requires AP/payment feed)*
- **taxpayer_mistake:** Deducted input VAT but never paid the supplier; KSA requires repaying that input once the debt is 12 months unpaid, and the taxpayer keeps the deduction.
- **why_it_happens:** Cash flow; unaware of the claw-back mirror of bad-debt relief.
- **detection:** Match purchase 388 to payment evidence (AP/bank feed); where `IssueDate` > 12 months before period end with no payment, expect a positive `Standard_Rate_Purchase_Adjustment`/Box14 repayment. Flag absence.
- **data_used:** purchase INVOICES IssueDate/TaxAmount; AP/payment feed; `Standard_Rate_Purchase_Adjustment`, `Corrections_From_Previous_Period`.
- **explains_gap:** No (compliance — needs AP/payment feed).
- **severity:** Medium.
- **confirming_evidence:** Aged-payables > 12 months. Next-best: request the AP aging.
- **ai_assist:** None.

---

## Family RCM — Reverse Charge & Imports

*Structural note governing the family:* **Box 8 (`Imports_Paid_*`) and Box 9 (`Import_Accounted_*`) cannot be reconstructed from FATOORA.** Non-resident suppliers are not ZATCA-registered and issue no cleared UBL; goods clear through Saudi Customs (Bayan), not FATOORA. This family ingests two external feeds — (1) a **Customs/Bayan** import feed and (2) an **AP/purchase ledger** keyed so **counterparty** residence/nationality identifies non-resident suppliers (CP-MASTER). The only e-invoice signal is the occasional **self-billed** 388. Where `explains_gap` says "No", the residual is real but must be evidenced from customs/AP, not FATOORA.

**RCM-01 — Imported services never reverse-charged (Box 9 left empty)** *(AP feed; CP-MASTER)*
- **taxpayer_mistake:** Pays a non-resident supplier for services (SaaS/licences, management & royalty fees, foreign professional/marketing) and self-assesses no VAT; Box 9 stays zero.
- **why_it_happens:** Believes no KSA VAT is due because the supplier is abroad and shows no VAT — unaware RCM shifts liability to the KSA recipient.
- **detection:** From the AP ledger, sum taxable base of purchase lines whose **counterparty** is non-resident (residence flag / nationality ≠ SA, VRN null) and the line carries no local VAT, in period. If Σbase > τ while `Import_Accounted_Amount`/`_VAT_Amount` ≈ 0 → expected self-assessment = Σbase × 15%.
- **data_used:** AP/purchase ledger; **counterparty** residence/nationality/VRN; `Import_Accounted_*` (Box 9); period.
- **explains_gap:** No — Box 9 not derivable from e-invoices; needs AP feed.
- **severity:** High.
- **confirming_evidence:** Match to foreign-supplier invoices/SWIFT payments; a self-billed cleared e-invoice for the counterparty confirms the supply was recognised but not in Box 9. Next-best: RFI for the foreign-supplier contract/invoice bundle.
- **ai_assist:** Read supplier name/line narrative and `NOTE_OID_ID`/comments to classify the service (not an exempt financial fee) and narrate.

**RCM-02 — Goods-import VAT (Box 8) understated vs customs** *(customs feed)*
- **taxpayer_mistake:** Declares less import VAT in Box 8 than Bayan assessed for the period.
- **why_it_happens:** Missed/late declarations, broker paid but not booked, or partial customs value carried in.
- **detection:** Aggregate Bayan VAT for declarations with clearance date in period for the taxpayer's VRN; compare to `Imports_Paid_VAT_Amount`. If customs Σ − Box 8 > τ → understatement (net of any approved import-VAT deferral moved to Box 9).
- **data_used:** Customs/Bayan feed (value, VAT, clearance date, importer VRN); Box 8 and Box 9 (deferral); period.
- **explains_gap:** No — customs feed required.
- **severity:** High.
- **confirming_evidence:** Line-level Bayan declarations; check for an import-VAT-deferral approval (value then legitimately in Box 9). Next-best: customs statement of account.
- **ai_assist:** None material.

**RCM-03 — Import VAT claimed without actual customs payment (Box 8 input overstated)** *(customs feed)*
- **taxpayer_mistake:** Claims Box 8 input exceeding VAT actually paid at customs, or on VAT-exempt/suspended imports.
- **why_it_happens:** Booking supplier proforma values, duplicated declarations, or claiming on suspended/exempt imports.
- **detection:** Compare `Imports_Paid_VAT_Amount` (input side) to Bayan-paid VAT; if Box 8 > customs Σ by > τ, or matched declarations show an exemption/suspension code → over-claim = difference.
- **data_used:** Customs/Bayan feed (paid VAT, exemption codes); Box 8.
- **explains_gap:** No — customs feed required.
- **severity:** High.
- **confirming_evidence:** Bayan payment receipts; duplicate detection on customs reference numbers. Next-best: RFI for customs payment proof per import line.
- **ai_assist:** None material.

**RCM-04 — Box 9 symmetry broken (output self-assessed, input omitted — or reverse)** *(form-convention caveat)*
- **taxpayer_mistake:** Reports the reverse-charge output but forgets the matching input deduction (over-pays), or claims the input without the output (under-pays), so the two legs don't tie.
- **why_it_happens:** Manual one-sided journal; misunderstanding RCM is a two-sided entry.
- **detection:** Per period, compare `Import_Accounted_VAT_Amount` (output leg) against the corresponding RCM input deduction. **Form caveat:** confirm from the live return form *where* the KSA return carries the RCM input leg (netted in `Standard_Rate_Purchase_VAT_Amount` Box 7, within Box 9 mechanics, or a dedicated field) before computing the test — do not assume Box 7. For a fully-taxable counterparty the two legs should be equal; if `|output − input| > τ` and no partial-exemption reason applies → flag broken symmetry and direction.
- **data_used:** `Import_Accounted_*` (Box 9), the confirmed RCM-input location; `IND_SECTOR` (to rule out legitimate partial exemption).
- **explains_gap:** No — internal Box 8/9 mechanics.
- **severity:** Medium (Low if over-paid; High if input taken with no output).
- **confirming_evidence:** RCM journal entries showing one-sided posting. If deliberate, check apportionment (→ RCM-05). Next-best: request the reverse-charge working paper.
- **ai_assist:** Read filing comments/`NOTE_OID_ID` for a stated partial-exemption rationale before flagging.

**RCM-05 — Reverse-charge / import input claimed without the right to deduct** *(shared recovery-ratio routine with INP-03)*
- **taxpayer_mistake:** Self-assesses RCM/import VAT and deducts in full though the supply relates to exempt activity, blocked expenditure, or non-business use — the input leg should be restricted.
- **why_it_happens:** Assumes RCM always nets to zero; ignores apportionment and blocked-input rules.
- **detection:** Where Box 9 or Box 8 input is claimed in full but the taxpayer has exempt output (`Exempt_Sales_Amount > 0`) or sits in a partial-exemption `IND_SECTOR` → recompute deductible input = RCM VAT × recovery ratio (shared routine); flag excess.
- **data_used:** `Import_Accounted_*`, `Imports_Paid_*`, `Exempt_Sales_Amount`; `IND_SECTOR`, `BUSINESS_SIZE`.
- **explains_gap:** No (compliance — input-side restriction).
- **severity:** High.
- **confirming_evidence:** Apportionment vs claimed input; nature of the imported service (blocked categories). Next-best: request the partial-exemption method and recovery ratio.
- **ai_assist:** Classify the imported service/good against blocked categories; narrate the shortfall.

**RCM-06 — Wrong rate applied to the self-assessed amount** *(calls RATE-TRANSITION)*
- **taxpayer_mistake:** Self-assesses RCM at 5% (or 0%) instead of 15%, or applies 15% to a genuinely pre-2020-07-01 supply.
- **why_it_happens:** Legacy rate hard-coded after 2020; transitional-period contracts mis-rated.
- **detection:** `Import_Accounted_VAT_Amount ÷ Import_Accounted_Amount`; if the implied rate ∉ {15%, and 5% only where service period < 2020-07-01} → recompute at 15%. Cross-check `_15`/`_5` split consistency.
- **data_used:** `Import_Accounted_Amount`/`_VAT_Amount` and `_15`/`_5` split, period; supply date from AP ledger.
- **explains_gap:** No — internal rate check on Box 9.
- **severity:** Medium.
- **confirming_evidence:** Contract service dates vs the transition; recompute. Next-best: RFI for supply period on transitional contracts.
- **ai_assist:** Read contract/invoice dates to confirm the supply falls after the change.

**RCM-07 — Reverse-charge supply booked as an ordinary domestic purchase (Box 7)** *(AP feed; CP-MASTER)*
- **taxpayer_mistake:** Records a non-resident supply as a normal standard-rated domestic purchase in Box 7 with a phantom input claim, and never raises the Box 9 output self-assessment.
- **why_it_happens:** AP clerk codes the foreign invoice like a local vendor bill; ERP has no RCM tax code for the supplier.
- **detection:** Find Box 7 purchase lines whose **counterparty** is non-resident (residence/nationality ≠ SA, no VRN) yet no matching FATOORA purchase e-invoice exists. No supporting e-invoice + foreign counterparty + input claimed + Box 9 = 0 → mis-classification; the output leg (base × 15%) is missing.
- **data_used:** AP ledger + **counterparty** residence/nationality/VRN; Box 7, Box 9; e-invoice presence check.
- **explains_gap:** **Partial** — the absent FATOORA purchase invoice behind a Box 7 line is the e-invoice signal; the RCM output leg needs the AP feed. "No → Box 9 output leg missing."
- **severity:** Medium (often net-zero, but hides non-deductible RCM and breaks reconciliation).
- **confirming_evidence:** Foreign vendor master + invoice with no VAT; absence of a cleared supplier e-invoice. Next-best: reclassify to Box 9 and test deductibility (link RCM-05).
- **ai_assist:** Read vendor name/country from the AP line to confirm non-residence when the residence flag is missing.

**RCM-08 — Intra-GCC supply mistreated (wrong RCM / wrong box)** *(customs/AP feed; CP-MASTER)*
- **taxpayer_mistake:** Treats a purchase from another GCC state as a zero-rated import or export-related item instead of applying reverse charge, or double-counts it in both Box 8 and Box 9.
- **why_it_happens:** GCC framework confusion — mutual-recognition transition not fully live, so other GCC states are effectively rest-of-world for KSA, yet taxpayers still book "GCC" specially.
- **detection:** Where a **supplier's** nationality is a GCC state and the line is reported under `Sales_To_Customers_GCC_*`/zero-rated purchase rather than as an import, or appears in both Box 8 and Box 9 → flag mistreatment/double count.
- **data_used:** **counterparty** nationality/residence; `Sales_To_Customers_GCC_*`, `Zero_Rated_Purchase_*`, Box 8, Box 9; customs feed for physical clearance.
- **explains_gap:** No — needs customs/AP feed.
- **severity:** Medium.
- **confirming_evidence:** Customs entry (goods) vs service invoice (services) to pick the right box; de-dup Box 8/Box 9 on the same reference. Next-best: RFI for GCC supplier invoices and any customs clearance.
- **ai_assist:** Narrate the current KSA treatment of intra-GCC supplies for the case memo.

**RCM-09 — Wrong-period / accounting-method mismatch on import & RCM VAT** *(customs/AP feed)*
- **taxpayer_mistake:** Recognises import VAT (Box 8) or RCM (Box 9) in a different period than the customs clearance / tax-point date — pulling a claim forward or deferring an output leg.
- **why_it_happens:** Cash-vs-accrual confusion; invoice-date vs clearance-date timing; month/quarter-end cut-off.
- **detection:** Per Bayan/RCM item, compare its tax point (customs clearance date, or service completion for RCM) to the reported period, respecting `ACCOUNTING_METHODE`. Items a period early/late → timing difference (often reversing in the adjacent period).
- **data_used:** Customs/Bayan (clearance date), AP (service date); period, Box 8, Box 9, `Corrections_From_Previous_Period` (Box 14); `ACCOUNTING_METHODE`.
- **explains_gap:** No — timing reconciliation vs customs/AP.
- **severity:** Low–Medium (higher if it straddles a rate change or year-end).
- **confirming_evidence:** Reversal in the adjacent return, or a Box 14 correction that ties out. Next-best: check the neighbouring period before an assessment.
- **ai_assist:** None material.

**RCM-10 — Reverse charge wrongly applied to a resident/registered supplier** *(CP-MASTER)*
- **taxpayer_mistake:** Self-assesses RCM (Box 9) on a supplier that is actually KSA-resident or ZATCA-registered — one who should have charged VAT on a normal cleared invoice — creating a phantom output/input pair and masking a missing supplier invoice.
- **why_it_happens:** Stale vendor master (residence flag not updated after the supplier registered), or a KSA branch/PE of a foreign group.
- **detection:** For Box 9 items, verify the **supplier** truly has no valid KSA VRN and is non-resident on the supply date. If a matching cleared FATOORA supplier e-invoice exists, or the counterparty is registered/resident → RCM mis-applied; correct treatment is a standard Box 7 purchase.
- **data_used:** **counterparty** residence/nationality/VRN and validity FROM_DATE/TO_DATE; e-invoice INVOICES (supplier VRN match); Box 9, Box 7.
- **explains_gap:** **Partial** — a cleared supplier e-invoice for a Box 9 counterparty is the tell. "No → belongs in Box 7."
- **severity:** Medium.
- **confirming_evidence:** Supplier's active KSA VRN and a cleared tax invoice. Next-best: reclassify to Box 7 and confirm the supplier remitted output VAT.
- **ai_assist:** Match supplier name/VRN across the vendor master and e-invoice header when IDs don't tie exactly.

---

## Family COR — Corrections & Amendments

*The taxpayer's "VAT amendments."* These rules police the mechanics of correcting a filing — credit/debit notes, the Box-14 self-correction channel, amended `Data_Version` returns, bad-debt relief, `_Adjustment` columns, and the Box-15 credit carry-forward. Detection is deterministic amount reconciliation; AI only reads free-text reasons. The Box-14 sign convention is decided once by S0 as `box14_sign_mode`, consumed identically here and in DAT-12.

**COR-01 — Sales credit notes (381) issued but output VAT not reduced** *(cross-ref OUT-09)*
- **taxpayer_mistake:** Issued valid 381 credit notes but keyed the return from a gross sales report, so declared output still reflects full 388 and never nets the credited VAT.
- **why_it_happens:** Timing — billing books the note but the manual return uses a gross figure, or the note post-dates prep. The inverse (a claimed reduction with no cleared 381) is evasion.
- **detection:** In the SALE direction, per `Percent` (15/5), net output = Σ`TaxAmount`[388] − Σ`TaxAmount`[381], cleared. Compare to declared `Standard_Rate_Sales_VAT_Amount (±_Adjustment)`. If declared ≈ Σ[388] (gross) and (declared − net_recon) ≈ Σ[381] within τ, credits were omitted → gap explained. Where `BillingReference` is absent, net at aggregate within period×category×rate; unmatched → `UNLINKED_NOTE` bridge line (never silently consumed). Sign check: declared < net_recon → a credit was over-claimed → escalate to OUT-09.
- **data_used:** INVOICES (InvoiceTypeCode, STATUSCODE, IssueDate, BillingReference), TAXSUBTOTAL, INVOICELINE (category/percent); `Standard_Rate_Sales_VAT_Amount`/`_Adjustment` (`_15`/`_5`).
- **explains_gap:** Yes → Standard_Rate_Sales_VAT_Amount (output; declared > reconstructed by Σ[381]).
- **severity:** Medium (High when reversed — credit claimed with no cleared 381).
- **confirming_evidence:** Matched 381→388 (`BillingReference`) and clearance status. Claimed reduction with no cleared 381 → request the note; absent → under-declared output.
- **ai_assist:** Read `NOTE_OID_ID`/comments to confirm a "sales return/discount" narrative. Language only.

**COR-02 — Received supplier credit notes (381) not reversing input VAT** *(canonical for supplier-side 381; supersedes former INP-09; BUYER-SOCKET)*
- **taxpayer_mistake:** Received 381 credit notes from suppliers (returns, rebates) but kept the full input deduction, so `Standard_Rate_Purchase_VAT_Amount` was never reduced.
- **why_it_happens:** Payables and return-preparer disconnected; sometimes deliberate over-claim.
- **detection:** In the PURCHASE direction, keyed by buyer VRN, net input = Σ`TaxAmount`[388 received] − Σ`TaxAmount`[381 received]; compare `Standard_Rate_Purchase_VAT_Amount`. If declared ≈ gross input, gap = omitted supplier credits → over-claimed input. Runs `partial=true` (`PURCHASE_BUYER_UNIDENTIFIED`) until the buyer-retrieval socket is live; AP-ledger fallback otherwise.
- **data_used:** purchase INVOICES/TAXSUBTOTAL keyed by buyer VRN; `Standard_Rate_Purchase_VAT_Amount`/`_Adjustment`.
- **explains_gap:** Yes → Standard_Rate_Purchase_VAT_Amount (input; declared > reconstructed net).
- **severity:** High.
- **confirming_evidence:** Supplier 381 linked to original 388. Next-best: purchase-ledger sample.
- **ai_assist:** None (deterministic).

**COR-03 — Debit notes (383) issued but additional output VAT not added**
- **taxpayer_mistake:** Issued 383 debit notes (price increases, undercharge corrections, additional consideration) but did not add the extra output to the return.
- **why_it_happens:** Oversight/timing; occasionally deliberate to hold output down.
- **detection:** In the SALE direction, Σ`TaxAmount`[383] signs +1 into reconstructed output. If declared `Standard_Rate_Sales_VAT_Amount` excludes it, declared < reconstructed by Σ[383] → under-declared output. Match `BillingReference`→original 388.
- **data_used:** INVOICES 383, TAXSUBTOTAL.TaxAmount, BillingReference; `Standard_Rate_Sales_VAT_Amount`.
- **explains_gap:** Yes → Standard_Rate_Sales_VAT_Amount (output).
- **severity:** Medium–High.
- **confirming_evidence:** The cleared 383 and its original; if declared already includes it, no finding.
- **ai_assist:** None.

**COR-04 — Bad-debt relief claimed without meeting the conditions** *(requires write-off/notification feed)*
- **taxpayer_mistake:** Reduced output VAT as bad-debt relief (negative `Standard_Rate_Sales_Adjustment` or a Box-14 entry) without meeting Art. 40 conditions — 12 months not elapsed, debt not written off in the books, and/or customer not notified in writing.
- **why_it_happens:** Cash-flow pressure; misreading the 12-month timing; relieving a debt actually paid.
- **detection:** Isolate a negative output adjustment with **no** corresponding 381 (a relief claim, not a cancellation). On the referenced original 388, test `From_Date − IssueDate ≥ 12 months`; shorter → fails. Cross-check write-off entry + written notification (external feed); absent → conditions unproven. No 381 + no write-off/notification → unsupported relief disallowed.
- **data_used:** `_Adjustment` or `Corrections_From_Previous_Period` (Box14); original 388 `IssueDate`; write-off ledger + notification feed.
- **explains_gap:** Yes → Standard_Rate_Sales_VAT_Amount/`_Adjustment` (output, negative) **only if conditions met**; otherwise disallowed.
- **severity:** High.
- **confirming_evidence:** Write-off date + written customer notification. AI reads `LETTER_*`/notes for the notification (language only); the 12-month and write-off tests are deterministic.
- **ai_assist:** Read `LETTER_*`/notes for the notification narrative.

**COR-05 — Reconciling against the wrong return version (amended `Data_Version`)** *(VERSION-SELECT — governs the whole engine)*
- **taxpayer_mistake:** The flagged return was later amended (new `Data_Version`, `Current_Flag` flipped), so a naive comparison reconciles e-invoices against the post-hoc corrected figure and hides the original error.
- **why_it_happens:** Normal amendment lifecycle; the trap is on the audit side — but any post-referral amendment sharpens the concern.
- **detection:** Select the audited version by period + `Net_Due_VAT/Final_VAT_Due (Box16) ≈ OLD_TAX_AMT` at `AUD_DATE_G`, **not** merely `Current_Flag='Y'`. Reconstruct against that `Data_Version`. If no version's Box16 reconciles to `OLD_TAX_AMT` within τ → quarantine. Report (as-filed version − `Current_Flag='Y'` version) as the amendment's own movement; it should equal `DIFF_TAX_AMT`.
- **data_used:** all `Data_Version` rows (Current_Flag, Submission_Date, Box13/14/15/16); audit case OLD/NEW/DIFF_TAX_AMT, AUD_DATE_G.
- **explains_gap:** Yes → Box16 (both directions) via correct baseline; the version delta explains an e-invoice-vs-current gap.
- **severity:** High.
- **confirming_evidence:** A version whose Box16 matches `OLD_TAX_AMT`; if none, escalate to manual version identification.
- **ai_assist:** None (identity math).

**COR-06 — Prior-period correction (Box14) used above the per-error self-correction cap** *(flag-for-review; per-error, not Box-14 total)*
- **taxpayer_mistake:** Corrected a prior-period error through `Corrections_From_Previous_Period` (Box14) when the **individual** net error was ≥ SAR 5,000, which legally requires a formal amendment of the original period (Art. 63) — not a current-period Box-14 adjustment. Or bundled several errors into one Box-14 line to obscure the source period.
- **why_it_happens:** A Box-14 line is faster than amending a historic return; sometimes deliberate blurring.
- **detection:** The SAR 5,000 cap is **per error**, so `|Box14| > 5,000` alone does **not** prove a breach (it may be several legitimate sub-cap corrections). Raise a **review flag**, provable as a breach only once a per-error decomposition is available: (a) `|Box14| > 5,000` AND no amended `Data_Version` exists in any prior period → self-correction channel likely misused; (b) if the underlying per-error breakdown is supplied and any single error ≥ 5,000 → confirmed breach. Confirm Box14 participates correctly in `Box16 = Box13 + Box14 − Box15` under `box14_sign_mode`.
- **data_used:** `Corrections_From_Previous_Period` (Box14), prior-period `Data_Version` set, Box13/15/16.
- **explains_gap:** Yes → Box14 is a legitimate carve-out from residual (declared pass-through); the **finding** — the cap breach — is compliance/procedure.
- **severity:** Medium (procedure); High when it conceals a large error.
- **confirming_evidence:** Presence/absence of a matching amended prior return; the per-error decomposition. AI reads `Reason_For_Amendment`/`NOTE_OID_ID`; amount vs cap is deterministic once decomposed.
- **ai_assist:** Read `Reason_For_Amendment`/`NOTE_OID_ID` to see whether the Box-14 amount is explained.

**COR-07 — Correction double-counted (a 381 credit note AND a Box-14 adjustment)**
- **taxpayer_mistake:** Recorded one correction twice — a 381 that already reduced current output, and again as a Box-14 entry — relieving the same VAT twice.
- **why_it_happens:** Gap between the billing system (auto-books the note) and the manual preparer (adds Box14 believing it was missed).
- **detection:** Compare Box14 magnitude to Σ`TaxAmount`[381] for the same original supply/prior period. If a cleared 381 already reduced reconstructed output for a `BillingReference` **and** Box14 carries an equal/overlapping amount for that same prior period → double relief, within τ. Declared Box16 then sits below reconstructed by the duplicated amount.
- **data_used:** INVOICES 381 (BillingReference, IssueDate, TaxAmount), Box14, prior `Data_Version`.
- **explains_gap:** Yes → Box16 (over-relief); declared < reconstructed → under-declaration.
- **severity:** High.
- **confirming_evidence:** The single underlying event behind both entries (one original 388). Next-best: ask which channel is intended and reverse the other.
- **ai_assist:** Match the `Reason_For_Amendment` narrative to the 381 to confirm same event.

**COR-08 — Orphan `_Adjustment` not tied to any invoice, note, or prior-version event**
- **taxpayer_mistake:** Populated a `_Adjustment` (e.g. `Standard_Rate_Sales_Adjustment`, `Standard_Rate_Purchase_Adjustment`) with a manual figure mapping to no 381/383, no 386 reversal, and no prior `Data_Version` delta — an undocumented plug.
- **why_it_happens:** Manual balancing to force Box13/Box16 to a target, or a genuine adjustment left unevidenced.
- **detection:** For each `_Adjustment ≠ 0`, search for a matching event within τ: (a) net 381/383 in the same period×category×rate; (b) a 386 prepayment reversal; (c) a delta vs the prior `Data_Version` for that box. No match → `ORPHAN_ADJUSTMENT`; the adjustment is itself the unexplained residual.
- **data_used:** all `*_Adjustment` columns; INVOICES 381/383/386 (TaxAmount, BillingReference); prior `Data_Version` box values.
- **explains_gap:** No when orphan (it *is* the residual); Yes when it ties to a note/prepayment/version event → explains the relevant box.
- **severity:** Medium → High by amount.
- **confirming_evidence:** The source document/event behind the number. AI reads filing comment/`Reason_For_Amendment` for a narration; if none, request support.
- **ai_assist:** Read `Reason_For_Amendment`/filing comment for a narrated basis.

**COR-09 — VAT credit (Box15) carried forward incorrectly** *(refund/SADAD feed, partial where absent)*
- **taxpayer_mistake:** Claimed `VAT_Credit` (Box15) not equal to the credit genuinely available from the prior period, or carried forward a credit already refunded/offset — understating `Net_Due_VAT/Final_VAT_Due`.
- **why_it_happens:** Manual tracking of the running credit; re-using a refunded credit.
- **detection:** Reconstruct the credit chain: current `VAT_Credit` should equal the prior period's carried credit minus any refund paid (`SADAD_Bill_Number`/refund feed). If current Box15 > available credit within τ → over-carried. Verify `Box16 = Box13 + Box14 − Box15` under `box14_sign_mode`.
- **data_used:** current & prior Box15, Box16, Box13, Box14; refund/SADAD feed (`partial=true` where absent).
- **explains_gap:** No (compliance) — Box15 is a declared carve-out; an over-carry understates Net Due directly.
- **severity:** High.
- **confirming_evidence:** Prior-period Box16 credit balance and refund status. Next-best: recompute the carry chain across the period sequence.
- **ai_assist:** None.

**COR-10 — Amended return reverses a genuine liability / weak or missing `Reason_For_Amendment`**
- **taxpayer_mistake:** Filed an amended return (new `Data_Version`, `Current_Flag='Y'`) lowering a correctly-declared liability — e.g. stripping output VAT — often shortly after the case was flagged, with a blank/generic/contradictory `Reason_For_Amendment`.
- **why_it_happens:** Attempt to escape an emerging assessment; or a careless amendment with no stated cause.
- **detection:** Flag amendments where the new `Data_Version` reduces `Total_VAT_Due`/`Box16` vs the prior version **and** `Submission_Date` is after referral/`AUD_DATE_G`. Test support: does reconstructed output back the LOWER figure or the ORIGINAL? If e-invoices support the original (higher) → unsupported reversal (the reduction is the residual). Also flag `Reason_For_Amendment` null/blank/placeholder or not matching any detected 381/383/`_Adjustment` event.
- **data_used:** `Data_Version` chain (Current_Flag, Submission_Date, Reason_For_Amendment, Box13/16); audit case AUD_DATE_G/OLD/NEW/DIFF_TAX_AMT; reconstructed output.
- **explains_gap:** Yes → Box13/Box16; the amendment delta must reconcile to evidence, else it is unexplained residual.
- **severity:** High.
- **confirming_evidence:** Evidence backing the reduction (matching notes/adjustments). If none and e-invoices support the original, the amendment is disallowed.
- **ai_assist:** Classify `Reason_For_Amendment` free text (blank/generic/specific) and check it against detected note/adjustment events; the deterministic amount test stays authoritative.

---

## Family CMP — Compliance & Business-Change

*"Did the taxpayer play by the calendar and the rulebook?"* — filing/paying on time, staying correctly registered, and keeping filings in step with legal changes (5%→15%, real-estate/RETT, VAT-group status, filing frequency, e-invoicing waves). Most do not reconcile against a value box; they explain *why the return exists (or doesn't)* or why it is structurally wrong. Detection leans on **dates** and **presence/absence** checks. All box references use the schema's named fields (never numeric "Box 1/6" labels).

**CMP-01 — Late filing of the VAT return**
- **taxpayer_mistake:** Files the period's return after the legal due date (last day of the month following the period end), or not at all.
- **why_it_happens:** Cash-flow avoidance, disorganisation, key-person dependency, "a nil/small period doesn't matter".
- **detection:** Statutory deadline = last calendar day of the month following `To_Date`. Flag if `Submission_Date` > deadline (or NULL for a closed period lacking a `Current_Flag='Y'` return). Days-late = `Submission_Date` − deadline; cross-check `Late_Filing_Penalty` present and ≈ statutory 5–25% of `Net_Due_VAT`; flag if penalty zero but filing late.
- **data_used:** `Submission_Date`, `From_Date`, `To_Date`, `Late_Filing_Penalty`, `Net_Due_VAT`/`Final_VAT_Due`, `Current_Flag`, `Form_Number`.
- **explains_gap:** No (compliance/timing).
- **severity:** Medium (High if chronic / large `Net_Due_VAT`).
- **confirming_evidence:** Deterministic from dates. If late with no penalty booked, escalate for penalty assessment. Next-best: check prior periods in `AUDIT_CASE` history for a pattern.
- **ai_assist:** Read `NOTE_OID_ID`/`LETTER_*`/comments for a stated reason (outage, dispute) that may justify a waiver.

**CMP-02 — Late or unpaid VAT payment (SADAD)** *(payment/collection feed)*
- **taxpayer_mistake:** Submits the return but leaves `SADAD_Bill_Number` unpaid past the payment due date (same date as filing), accruing late-payment penalties.
- **why_it_happens:** Liquidity; treating filing as the end of the obligation; filing-vs-payment deadline confusion.
- **detection:** For returns with `Net_Due_VAT > 0`, check payment status of `SADAD_Bill_Number` against the deadline. Flag if unpaid or paid late. Estimate accrued penalty = 5% × unpaid VAT × months elapsed; compare to any recorded penalty.
- **data_used:** `SADAD_Bill_Number`, `Net_Due_VAT`/`Final_VAT_Due`, `To_Date`, `Submission_Date`; payment/collection feed.
- **explains_gap:** No (compliance/payment).
- **severity:** Medium (High for large or persistently unpaid balances).
- **confirming_evidence:** SADAD settlement record is definitive. If unpaid, flag for collections and recompute cumulative penalty.
- **ai_assist:** None; may narrate the running penalty accrual.

**CMP-03 — Nil / under-stated return while e-invoices show activity** *(named trigger that calls DAT-01)*
- **taxpayer_mistake:** Files a zero/token return (all boxes ≈ 0) though FATOORA invoices were cleared/reported for the period, understating output.
- **why_it_happens:** Deliberate suppression, or "estimated" filing intending (but failing) to amend later.
- **detection:** Trigger only: where `Total_VAT_Due` (Box13) and `Standard_Rate_Sales_VAT_Amount` ≈ 0 for a period, invoke **DAT-01**'s reconstruction; if reconstructed cleared `TaxAmount` > τ → flag. Does not re-derive the reconstruction.
- **data_used:** `Standard_Rate_Sales_*`, `Total_VAT_Due`, `Net_Due_VAT`; DAT-01 reconstruction (INVOICES, TAXSUBTOTAL, LEGALMONETARYTOTAL).
- **explains_gap:** Yes → `Standard_Rate_Sales` (specific sales boxes per category; not the Box13 aggregate).
- **severity:** High.
- **confirming_evidence:** The e-invoice ledger vs a nil return. Next-best: request an amended return; if none, propose assessment for the reconstructed VAT.
- **ai_assist:** Read any note/`Reason_For_Amendment` claiming "estimated pending closure" to separate timing from suppression.

**CMP-04 — Failure to register / late registration above the mandatory threshold** *(CP-MASTER / third-party sales where pre-registration)*
- **taxpayer_mistake:** Taxable turnover exceeds the SAR 375,000 mandatory threshold (rolling 12 months) but the taxpayer has no `VAT_registration_number`, or registered late — leaving taxable periods unreported.
- **why_it_happens:** Ignorance of the threshold, informal/growing business, deliberate avoidance.
- **detection:** Aggregate reconstructed taxable sales (category S at 15%+5%) over rolling 12 months; compare to 375,000. If cumulative > threshold and there is no `VAT_registration_number` or a registration `FROM_DATE` later than the crossing month → flag with the delta period.
- **data_used:** `VAT_registration_number`, registration FROM_DATE/TO_DATE, `BUSINESS_SIZE`, `IND_SECTOR`; TAXSUBTOTAL/LEGALMONETARYTOTAL (or third-party sales pre-e-invoicing).
- **explains_gap:** No (registration) — explains why no returns exist for active periods.
- **severity:** High.
- **confirming_evidence:** Reconstructed 12-month turnover crossing the threshold with no matching registration date. Next-best: enforce backdated registration and assess the unregistered periods.
- **ai_assist:** Read business-activity descriptions/correspondence to confirm the activity is a taxable supply (avoid a false trigger on exempt activity).

**CMP-05 — Charging VAT after deregistration / failure to de-register**
- **taxpayer_mistake:** Deregistered (or validity ended) yet keeps issuing tax invoices with VAT, or ceased trading below the voluntary threshold but never de-registered — collecting VAT it may not remit.
- **why_it_happens:** ERP invoice templates not updated after status change; ceasing without notifying ZATCA; deliberate collection while unregistered.
- **detection:** Compare `INVOICES.IssueDate` against the taxpayer's `TO_DATE`/`DEREG_TYPE`. Flag any tax invoice (388, category S, 15/5) with `IssueDate` after `TO_DATE`/deregistration effective date. Conversely, flag prolonged nil activity + no e-invoices + no de-registration (`DEREG_TYPE` empty) as possible failure-to-deregister.
- **data_used:** `TO_DATE`, `DEREG_TYPE`, `VAT_registration_number`; INVOICES (IssueDate, InvoiceTypeCode, STATUSCODE), INVOICELINE.
- **explains_gap:** Yes → `Standard_Rate_Sales` (output over-collected while unregistered) + registration.
- **severity:** High.
- **confirming_evidence:** Post-`TO_DATE` cleared tax invoice. Next-best: demand remittance of VAT collected while unregistered, or correct/cancel via credit notes.
- **ai_assist:** Read `DEREG_TYPE` reason text/letters to check whether cessation was genuine or the number is misused.

**CMP-06 — VAT-group changes not reflected in filings** *(CP-MASTER for member identity)*
- **taxpayer_mistake:** A member joins/leaves a VAT group (or the representative changes) but returns are still filed under the individual member's number, or intra-group supplies are treated as taxable — causing double-counting or gaps between the group return and member e-invoices.
- **why_it_happens:** Group mechanics are complex; filing setup not updated when `VAT_GROUP_REP_FLAG` changes; intra-group supplies (out of scope) invoiced with VAT.
- **detection:** Where `VAT_GROUP_REP_FLAG` indicates membership, check that member filings are consolidated under the representative's `VAT_registration_number` (only the rep files). Flag if a non-rep member also files, if the group return's reconstructed sales exclude a member's e-invoices, or if intra-group invoices carry VAT. Compare the flag-change date to the first inconsistent `From_Date`.
- **data_used:** `VAT_GROUP_REP_FLAG`, `VAT_registration_number`, `ZZBPTYPE`, validity dates; return filer identity (`ID_Number`, `Form_Number`); INVOICES per member.
- **explains_gap:** Yes → `Standard_Rate_Sales` (group-vs-member reconciliation; not a numeric "Box 6" aggregate).
- **severity:** Medium (High if intra-group VAT double-counted at scale).
- **confirming_evidence:** Group registration record + which entity filed. Next-best: realign filings to the representative and reverse VAT wrongly charged intra-group.
- **ai_assist:** Read group-registration correspondence to confirm effective dates when master-data timing is ambiguous.

**CMP-07 — Ignoring the 2020 rate change (portfolio-level trigger)** *(owns RATE-TRANSITION detector; defers arithmetic to OUT-02/INP-05/RCM-06)*
- **taxpayer_mistake:** For supplies on/after 2020-07-01 the taxpayer applies 5% instead of 15% (invoices and/or `_5` boxes), understating output — or the input mirror.
- **why_it_happens:** ERP tax code never updated; transitional-rule misapplication; inertia.
- **detection:** Portfolio trigger: for periods with `To_Date ≥ 2020-07-01`, flag any material balance in a `_5` box (`Standard_Rate_Sales_*_5`, `Standard_Rate_Purchase_*_5`, `Government_Supplied_Sales_*_5`, `Import_Accounted_*_5`) for a period wholly after the switch. The **shared RATE-TRANSITION detector** then hands the arithmetic to OUT-02 (output), INP-05 (input), RCM-06 (RCM) — CMP-07 does not itself recompute per-line VAT, avoiding triplication.
- **data_used:** `*_15`/`*_5` split boxes across sales/purchase/import; period boundaries; RATE-TRANSITION detector output.
- **explains_gap:** Yes → `Standard_Rate_Sales` / `Standard_Rate_Purchase` `_5`↔`_15` (routed to OUT-02/INP-05/RCM-06).
- **severity:** High.
- **confirming_evidence:** A `_5` balance for a wholly-post-switch period with no transitional basis. Next-best: verify supply/contract dates; if not transitional, the family rules assess the differential.
- **ai_assist:** Read contract references/invoice notes to detect a legitimate transitional supply before flagging.

**CMP-08 — Wrong filing frequency for the turnover band**
- **taxpayer_mistake:** A large taxpayer (annual supplies > SAR 40m, required to file monthly) files quarterly, or a smaller taxpayer files on a frequency inconsistent with its band — missing periods and miscalculating deadlines.
- **why_it_happens:** Turnover grew past the SAR 40m monthly line but frequency was never switched; ERP calendar misconfigured.
- **detection:** Derive expected frequency from `BUSINESS_SIZE`/reconstructed annual turnover (>40m → monthly, else quarterly). Inspect the `From_Date→To_Date` span of filed returns: flag ~3-month spans where monthly is required, missing monthly periods, or overlapping/duplicate spans.
- **data_used:** `From_Date`, `To_Date`, `Form_Number`, `Current_Flag`; `BUSINESS_SIZE`, `IND_SECTOR`; reconstructed annual turnover.
- **explains_gap:** No (structural) — but explains period-alignment mismatches vs e-invoices.
- **severity:** Medium.
- **confirming_evidence:** Return period length vs mandated frequency. Next-best: instruct correct frequency and re-file affected periods.
- **ai_assist:** None (deterministic).

**CMP-09 — Business/sector/activity change not reflected**
- **taxpayer_mistake:** Changes or adds an activity (into exempt financial services/real estate, or into zero-rated exports) but keeps declaring under the old treatment — mis-populating the exempt/zero boxes.
- **why_it_happens:** `IND_SECTOR`/activity not updated; staff unaware the new activity has a different status; ERP still using old tax codes.
- **detection:** Compare `IND_SECTOR`/activity against the mix of `ItemClassifiedTaxCategoryID` (S/Z/E/O) actually seen in e-invoices. Flag divergence — e.g. invoices now largely E/Z while returns fill only `Standard_Rate_Sales_*`, or `Exempt_Sales_*`/`Zero_Rated_Sales_*` staying zero despite E/Z invoice lines.
- **data_used:** `IND_SECTOR`, `ZZBPTYPE`, validity dates; `Exempt_Sales_*`, `Zero_Rated_Sales_*`, `Standard_Rate_Sales_*`, `Exports_*`; `INVOICELINE.ItemClassifiedTaxCategoryID`.
- **explains_gap:** Yes → `Zero_Rated_Sales` / `Exempt_Sales` / `Exports` vs `Standard_Rate_Sales`.
- **severity:** Medium.
- **confirming_evidence:** Shift in invoice tax-category mix not mirrored in the return boxes. Next-best: update activity/sector, confirm treatment, re-map the boxes.
- **ai_assist:** Read item descriptions/activity correspondence to classify the new supply's status before concluding.

**CMP-10 — Missing period / broken filing continuity**
- **taxpayer_mistake:** Between an active registration `FROM_DATE` and `TO_DATE` (or present), one or more tax periods have no return at all — not nil, simply absent — leaving e-invoice activity wholly unreported.
- **why_it_happens:** Overlooked period, staff turnover, or deliberately dropping a high-liability month.
- **detection:** Generate the expected period sequence from registration `FROM_DATE` to period-end (per CMP-08 frequency). Flag any expected period with no `Current_Flag='Y'` return. For each missing period, check e-invoice activity to quantify unreported output/input and prioritise.
- **data_used:** `From_Date`, `To_Date`, `Current_Flag`, `Form_Number`; registration `FROM_DATE`/`TO_DATE`, `DEREG_TYPE`; INVOICES/TAXSUBTOTAL.
- **explains_gap:** No (compliance) — a missing return is the extreme case of an e-invoice-vs-filing gap.
- **severity:** High.
- **confirming_evidence:** Absent return in an active registration window. Next-best: compel filing; assess from reconstructed e-invoices if not filed.
- **ai_assist:** None; may narrate the missing-period timeline.

**CMP-11 — Real-estate supply still charged 15% VAT after the RETT reform (2020-10-04)** *(the marquee VAT-rule change; CP-MASTER for property-type context)*
- **taxpayer_mistake:** Continues charging/declaring 15% output on real-estate disposals that became VAT-exempt (and subject to 5% Real Estate Transaction Tax) from 2020-10-04, or keeps full input recovery on now-exempt property activity without apportioning.
- **why_it_happens:** ERP tax codes never updated for the RETT reform; confusion over which property supplies stay taxable (commercial leases remain standard-rated) vs exempt.
- **detection:** For `IND_SECTOR` = real-estate/construction, flag `INVOICELINE` category-S property lines with tax point ≥ 2020-10-04 landing in `Standard_Rate_Sales_*`; expected reclass to `Exempt_Sales_*` plus input restriction per INP-03. Corroborate: `Exempt_Sales_Amount ≈ 0` despite property activity.
- **data_used:** `IND_SECTOR`/`ZZBPTYPE`; INVOICELINE category/percent, IssueDate/ActualDeliveryDate; `Standard_Rate_Sales_*`, `Exempt_Sales_*`.
- **explains_gap:** Yes → `Standard_Rate_Sales` ↔ `Exempt_Sales` (output).
- **severity:** High.
- **confirming_evidence:** Property type + supply date vs the RETT effective date; contracts. Next-best: request the property-supply schedule.
- **ai_assist:** Classify item/contract text to confirm in-scope real estate vs a standard-rated facilities service.

**CMP-12 — E-invoicing Phase-2 integration-wave non-compliance** *(external mandate-wave feed)*
- **taxpayer_mistake:** A taxpayer in an assigned integration wave is still only reporting/printing rather than clearing/integrating by its mandate date.
- **why_it_happens:** Integration project not delivered on time; unaware of the wave assignment.
- **detection:** Compare the `CLEANCEENABLED`/`STATUSCODE` mix of the taxpayer's invoices against the taxpayer's assigned wave date (external mandate feed). Standard invoices not being cleared after the wave date → flag.
- **data_used:** INVOICES `CLEANCEENABLED`, `STATUSCODE`, IssueDate; external integration-wave mandate feed; `VAT_registration_number`.
- **explains_gap:** No (compliance).
- **severity:** Medium.
- **confirming_evidence:** Wave-assignment record vs clearance behaviour. Next-best: refer for e-invoicing-compliance action.
- **ai_assist:** None.

---

## Family DAT — Data / E-invoicing Integrity

*The reconciliation core.* One engine reconstructs the expected return by aggregating cleared `TAXSUBTOTAL` (TaxableAmount + TaxAmount) by category × rate × direction (seller-VRN vs buyer-VRN) × period, then names the explanation for every residual against the shared gate `τ`. All amounts reconcile in SAR (`TaxCurrencyCode`). DAT-12 is the pre-reconciliation sanity gate that must pass before any residual is trusted.

**DAT-01 — Cleared invoices missing from the filing (under-declared output)** *(the master sales-side reconciliation engine; OUT-01…09 are its explainers)*
- **taxpayer_mistake:** Some cleared 388 invoices in the period were never carried into the declared sales boxes, so output is understated.
- **why_it_happens:** Honest omission — invoices raised in a peripheral system/branch not swept into the return; sometimes deliberate suppression of a subset.
- **detection:** Aggregate `TAXSUBTOTAL.TaxAmount` for seller-VRN = TP, category S / percent 15, `IssueDate` in period, cleared, net of 381. Compare Σ to `Standard_Rate_Sales_VAT_Amount_15` (base to `Standard_Rate_Sales_Amount_15`). If store > declared beyond τ, list the missing UUIDs. Repeat per rate (`_5`), and for Zero_Rated_Sales, Exports, Government_Supplied_Sales.
- **data_used:** INVOICES, TAXSUBTOTAL, `TP.VAT_registration_number`; `Standard_Rate_Sales_Amount/_VAT_Amount_15/_5`, `Zero_Rated_Sales_*`, `Exports_*`, `Government_Supplied_Sales_*`.
- **explains_gap:** Yes → the mapped sales box (output).
- **severity:** High.
- **confirming_evidence:** The enumerated cleared UUIDs with buyer VRNs are the proof; next-best is the amendment adding them (COR family) or mapping to a legitimate exclusion rule before treating as residual.
- **ai_assist:** Read `Reason_For_Amendment`/`NOTE_OID_ID`/`LETTER_*` for a narrated omission (e.g. "billed under group rep VRN").

**DAT-02 — Filing declares more than the e-invoice store holds (over-declared / under-reporting to FATOORA)** *(purchase-side variant depends on BUYER-SOCKET)*
- **taxpayer_mistake:** The declared box exceeds cleared invoices — the return was inflated, or (more often) real sales were never issued as e-invoices, breaching the FATOORA obligation.
- **why_it_happens:** Manual top-ups/estimates on the portal; legacy non-compliant billing outside ZATCA; padding output to absorb an unsupported input claim.
- **detection:** Same reconstruction as DAT-01, sign reversed: `declared box − Σ store > τ`. Split the residual into (a) *no invoice exists* (compliance breach) vs (b) *invoice exists but wrong category*, by re-checking the same counterparties across all categories. Purchase-side variant runs `partial=true` until the buyer socket is live.
- **data_used:** sales boxes; INVOICES/TAXSUBTOTAL; `IND_SECTOR`/`BUSINESS_SIZE` for plausibility.
- **explains_gap:** Yes → whichever sales box is over-declared (output).
- **severity:** Medium (self-penalising on VAT but signals e-invoicing non-compliance).
- **confirming_evidence:** Absence of matching UUIDs for the excess; confirm against sub-ledger before concluding non-issuance.
- **ai_assist:** Narrate the two-way split for the auditor's note.

**DAT-03 — Invoices reported late (supply in period, clearance in the next)**
- **taxpayer_mistake:** Tax point falls in the period but the invoice was cleared after `To_Date`, so it lands in the wrong return.
- **why_it_happens:** End-of-period invoices cleared in the next period's first days; batch clearance runs; accrual vs clearance calendar.
- **detection:** Compare tax point (`ActualDeliveryDate` else `IssueDate`) against the `STATUSCODE` clearance timestamp. Flag invoices where tax point ≤ `To_Date` but clearance > `To_Date` (belongs here, may be missing) and the mirror (cleared this period, tax point prior). Sum crossing-boundary VAT and test whether it closes the DAT-01/DAT-02 residual.
- **data_used:** INVOICES IssueDate, ActualDeliveryDate, STATUSCODE, CLEANCEENABLED; period; `ACCOUNTING_METHODE`.
- **explains_gap:** Yes → the affected sales/purchase box (timing, both directions).
- **severity:** Medium (usually genuine timing; nets to zero across two periods).
- **confirming_evidence:** The invoice appears in the adjacent period's reconstruction; confirm by extending the window ±1 period and re-running.
- **ai_assist:** None.

**DAT-04 — Non-cleared / rejected invoices wrongly included or excluded**
- **taxpayer_mistake:** Rejected/never-cleared invoices (`STATUSCODE`≠cleared) are counted in the return, or genuinely cleared ones are dropped.
- **why_it_happens:** Misunderstanding clearance — standard invoices (`CLEANCEENABLED=Y`) are void until cleared; taxpayer books them at print time regardless of ZATCA acceptance.
- **detection:** Partition the reconstruction by `STATUSCODE`. Any non-cleared/rejected invoice whose VAT is nonetheless in the declared box is an over-inclusion; any cleared invoice absent is DAT-01. Quantify the non-cleared VAT vs the residual.
- **data_used:** INVOICES STATUSCODE, CLEANCEENABLED, PDH; TAXTOTAL TaxAmount; sales/purchase boxes.
- **explains_gap:** Yes → affected box (both directions).
- **severity:** High (rejected invoices carry no valid VAT; input claim on them is disallowed).
- **confirming_evidence:** The status flag itself; for input, a rejected seller invoice invalidates the buyer's deduction — cross-check INP-01.
- **ai_assist:** None.

**DAT-05 — Duplicate invoices inflating totals (same UUID / broken hash chain)** *(scope: within-period store dedup; INP-04 owns cross-period re-claim)*
- **taxpayer_mistake:** The same invoice counted twice — identical `UUID`, or a re-issued near-duplicate (same seller VRN, invoice number, IssueDate, total, different UUID) — inflating the reconstructed side.
- **why_it_happens:** FATOORA resubmission/retries; migration double-loads; occasionally deliberate to justify a duplicated input claim.
- **detection:** Group the store by `UUID` (exact dup: count > 1) and by natural key {seller VRN, invoice number, IssueDate, LEGALMONETARYTOTAL total} (near-dup). Test the `PDH` chain: two invoices citing the same predecessor hash indicate a fork/duplicate. Deduplicate before reconstruction; report Σ VAT removed. (Cross-period re-claim of one UUID = INP-04.)
- **data_used:** INVOICES UUID, PDH, IssueDate; LEGALMONETARYTOTAL; seller/buyer VRN.
- **explains_gap:** Yes → whichever box was inflated (both directions).
- **severity:** Medium (High on the input/purchase side).
- **confirming_evidence:** Identical hash/natural key; single copy remains after dedup and reconciles.
- **ai_assist:** None.

**DAT-06 — Wrong buyer/seller VAT number → wrong party or direction**
- **taxpayer_mistake:** An invoice carries an incorrect counterparty VRN, so it is booked to the wrong entity or flips direction (a purchase read as a sale), distorting both output and input.
- **why_it_happens:** VRN typo; confusion within a VAT group where members share billing; self-billed invoices where roles invert.
- **detection:** For every invoice, verify seller-VRN or buyer-VRN = TP's `VAT_registration_number` (or a group member under the rep). If TP's VRN appears as neither, or in the wrong role for the invoice type (e.g. self-billed 388), quarantine it. Recompute the direction split and compare to declared sales vs purchase boxes.
- **data_used:** INVOICES header (VRNs, type name, self-billed flag); `VAT_registration_number`, `VAT_GROUP_REP_FLAG`; sales & purchase boxes.
- **explains_gap:** Yes → shifts amount between a sales box and a purchase box (both directions).
- **severity:** High.
- **confirming_evidence:** VRN checksum/registry validity and role vs invoice type; a corrected VRN reconciles the pair.
- **ai_assist:** None (structured matching).

**DAT-07 — Simplified (B2C) vs standard (B2B) invoices mishandled**
- **taxpayer_mistake:** Simplified (reported) and standard (cleared) invoices are mixed, double-counted, or the wrong population builds the return — e.g. B2C summarised by daily Z-report while B2B is per-invoice, causing overlap or omission.
- **why_it_happens:** Two channels with different obligations (real-time clearance vs 24h reporting); inconsistent aggregation.
- **detection:** Read the invoice-type `name` to classify standard vs simplified and `CLEANCEENABLED`/`STATUSCODE` to confirm channel. Reconstruct each channel separately, union without double count, compare combined standard-rate output to `Standard_Rate_Sales_*`. Flag overlap (same sale in both) or a channel wholly absent.
- **data_used:** INVOICES type name, CLEANCEENABLED, STATUSCODE; TAXSUBTOTAL; `IND_SECTOR` (retail B2C expectation); sales boxes.
- **explains_gap:** Yes → Standard_Rate_Sales (output).
- **severity:** Medium.
- **confirming_evidence:** Channel counts vs sector norm; reconciliation after de-overlapping.
- **ai_assist:** Read the free-text invoice `name` to disambiguate ambiguous type labels.

**DAT-08 — Foreign-currency invoices converted wrongly (`DocumentCurrencyCode` ≠ SAR)** *(domestic-supply scope only; imports excluded — customs matter)*
- **taxpayer_mistake:** For invoices billed in a foreign currency, the VAT feeding the return must be the SAR figure (`TaxCurrencyCode`=SAR); the taxpayer used the document-currency amount or an off-market FX rate.
- **why_it_happens:** Manual FX at month-end rate instead of the tax-point rate; using `DocumentCurrencyCode` values directly.
- **detection:** Select invoices where `DocumentCurrencyCode ≠ 'SAR'`; confirm `TaxCurrencyCode='SAR'` present (missing = compliance flag). Sum the SAR `TaxAmount`/`TaxableAmount` into the reconstruction. Compute implied FX = declared ÷ document-currency base; flag deviation from the tax-point reference rate beyond tolerance. **Scope:** applies to FATOORA-cleared domestic/export sales lines only. **Box 8 imports are excluded** — non-resident supplier, cleared through Bayan customs, not reconstructable from `DocumentCurrencyCode`; FX on imports is an RCM-02/03 customs-feed matter.
- **data_used:** INVOICES DocumentCurrencyCode, TaxCurrencyCode; TAXTOTAL/TAXSUBTOTAL (SAR); domestic sales boxes and `Exports_*`.
- **explains_gap:** Yes → affected domestic sales/export box (both directions). Not imports.
- **severity:** Medium.
- **confirming_evidence:** SAR `TaxCurrencyCode` amount vs declared; reference FX at tax point.
- **ai_assist:** None.

**DAT-09 — Rounding differences mis-accumulated (`RoundingAmount`)**
- **taxpayer_mistake:** Per-invoice `RoundingAmount` is dropped, double-applied, or the return is built from rounded line totals rather than exact `TaxAmount`, producing a small systematic gap.
- **why_it_happens:** Rounding half-up per invoice then re-summing; portal fields truncating decimals.
- **detection:** Reconstruct VAT from exact `TAXSUBTOTAL.TaxAmount`; separately sum `TAXTOTAL.RoundingAmount`. If `declared − Σ exact ≈ Σ RoundingAmount` (within τ), the gap is explained and closed; if the residual exceeds Σ RoundingAmount, escalate to another DAT rule.
- **data_used:** TAXTOTAL TaxAmount, RoundingAmount; return VAT boxes.
- **explains_gap:** Yes → affected VAT box (both directions), typically closing a small residual.
- **severity:** Low.
- **confirming_evidence:** The residual matches accumulated `RoundingAmount`.
- **ai_assist:** None.

**DAT-10 — Allowances/discounts not netted from the base (`AllowanceTotalAmount`)**
- **taxpayer_mistake:** Document-level discounts are ignored, so the declared base is gross while VAT was (correctly) charged on the net — the base box overstates by Σ `AllowanceTotalAmount` and no longer ties to VAT.
- **why_it_happens:** Return built from gross order values; discount applied on the invoice but not in the summary that fed the portal.
- **detection:** Reconstruct base as Σ `LEGALMONETARYTOTAL.TaxExclusiveAmount` (already net of `AllowanceTotalAmount`) and check against `Standard_Rate_Sales_Amount`. If declared base − reconstructed base ≈ Σ `AllowanceTotalAmount`, the discount was not netted. Cross-verify base × 15% = `Standard_Rate_Sales_VAT_Amount`.
- **data_used:** LEGALMONETARYTOTAL TaxExclusiveAmount, AllowanceTotalAmount; base & VAT sales boxes.
- **explains_gap:** Yes → Standard_Rate_Sales base (output; VAT usually unaffected).
- **severity:** Low (watch the case where VAT was also charged on gross).
- **confirming_evidence:** The overstatement equals Σ allowances; the VAT box confirms whether tax followed net or gross.
- **ai_assist:** None.

**DAT-11 — Prepayments (386) double-counted or timed wrong (`PrepaidAmount`)**
- **taxpayer_mistake:** VAT on a prepayment (386) is counted at receipt AND again in full on the final 388 without deducting `PrepaidAmount`, double-counting output; or the prepayment and settlement straddle periods and are mistimed.
- **why_it_happens:** The final invoice should reduce its base by the already-taxed `PrepaidAmount`, but the return sums both gross.
- **detection:** Identify 386 invoices and their matching 388 (same buyer VRN / contract reference). Expected output = Σ VAT(386) + Σ VAT(388 on base net of `PrepaidAmount`). Compare to declared standard-rate VAT; a residual ≈ VAT on Σ `PrepaidAmount` signals double count. Separately check 386 tax point vs `To_Date` for straddle.
- **data_used:** INVOICES 386/388; LEGALMONETARYTOTAL PrepaidAmount; TAXTOTAL; sales boxes; period.
- **explains_gap:** Yes → Standard_Rate_Sales (output; over- or under-statement).
- **severity:** Medium.
- **confirming_evidence:** The 386↔388 linkage and the `PrepaidAmount`; residual equals VAT on the prepayment.
- **ai_assist:** None (uses structured references; AI only to read a contract note if the 386↔388 link is not explicit).

**DAT-12 — Manual portal data-entry errors (internal-consistency checks)** *(consumes `box14_sign_mode`; pre-reconciliation sanity gate)*
- **taxpayer_mistake:** Hand-typing the return introduces transpositions, decimal shifts, or misfooted totals — `Amount × rate ≠ VAT_Amount`, subtotals that don't add, or a wrong net line.
- **why_it_happens:** Manual keying with no e-invoice import; fat-finger and copy-paste errors.
- **detection:** Deterministic self-checks needing no e-invoice data: (a) each rated box `Amount × 0.15` (or `× 0.05` for `_5`) ≈ `VAT_Amount` — ratios near 0.015/1.5/0.05× flag a decimal shift/transposition; (b) `Total_VAT_Due` (Box13) = Σ output VAT boxes; (c) `Net_Due_VAT`/`Final_VAT_Due` (Box16) = `Total_VAT_Due` (Box13) + `Corrections_From_Previous_Period` (Box14) − `VAT_Credit` (Box15), **with the Box14 sign taken from the shared `box14_sign_mode`** (not hard-coded); (d) recompute `Standard_Rate_Purchase_VAT_Amount`; each failing beyond τ.
- **data_used:** all `_Amount`/`_VAT_Amount`/`_Adjustment` triplets, Box13/14/15/16, `_15`/`_5` splits; `box14_sign_mode`.
- **explains_gap:** No (arithmetic — flags a keying error to correct before reconciliation is meaningful).
- **severity:** Medium (High when the decimal shift is on `Total_VAT_Due`/`Final_VAT_Due`).
- **confirming_evidence:** The failing identity pinpoints the box; recompute from DAT-01 reconstruction to confirm the intended value.
- **ai_assist:** Read `NOTE_OID_ID`/comments for a flagged keying error; narrate which identity failed.

---

## How the app uses this

1. **Deterministic detection first.** Every rule's `detection` is arithmetic/date/presence logic over real fields. The engine runs DAT-12 (internal consistency) and COR-05 (correct return version) as **gates** before trusting any residual, then reconstructs the expected return (DAT-01/02) and lets the OUT/INP/RCM/COR/CMP explainers consume the residual. Shared machinery is factored once — the materiality gate `τ`, the RATE-TRANSITION detector (CMP-07), the recovery-ratio routine (INP-03 / RCM-05), and `box14_sign_mode` (COR / DAT-12) — so families that chain never disagree.
2. **AI only reads and narrates.** Claude is confined to language tasks: reading `Reason_For_Amendment` / `NOTE_OID_ID` / `LETTER_*` / item descriptions to classify a supply, surface a taxpayer's own stated explanation, or narrate a finding. AI never decides an amount; the deterministic reconciliation is always authoritative.
3. **Human approves.** Each finding carries `confirming_evidence` (internal evidence first, then a next-best RFI) so a KSA VAT auditor confirms or dismisses before any assessment. Data-availability preconditions (CP-MASTER counterparty dimension, BUYER-SOCKET buyer-keyed retrieval, customs/Bayan and AP/payment feeds) are surfaced on the rules that need them; where a feed is absent the rule runs `partial=true` and degrades to a registry/AP fallback rather than a false positive.

**Backlog (named, not yet full-schema):** margin/used-goods scheme (VAT on full value vs margin); transfer-of-going-concern treated as a taxable supply; cash-accounting scheme used above the SAR 40m eligibility ceiling.

These rules populate **`config.rule_library`** (one row per code, with its `detection`, `data_used`, `explains_gap`, `severity`, and preconditions) and each maps to a **`ROOT_CAUSE_CODE`** on the audit case, so a confirmed finding writes back a stable root cause for `AUDIT_RESULT_TYPE`, `DIFF_TAX_AMT`, and `ACTION_TAKEN`.