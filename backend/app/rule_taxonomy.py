"""Rule taxonomy — separating the three things the rulebook conflates.

`docs/VAT-Mistakes-Rulebook.md` catalogues 66 things that can go wrong, but a
single `explains_gap` column hides the fact that those 66 entries are really
three different kinds of object:

* **explanation** — a legitimate reason a VAT return differs from the e-invoice
  population (credit notes, tax-point timing, transmission lag). It becomes a
  reason a line *qualifies differently* — it changes which documents count, and so
  changes the expected figure itself.
* **mistake** — a taxpayer error. It becomes a *finding*.
* **risk** — a behavioural or data-quality signal (late filing, rounding drift,
  broken continuity). It feeds *prioritisation*; it never changes which documents
  qualify, and so can never move the expected figure.

The same phenomenon can sit on either side of that split depending on polarity:
COR-01 is titled "Sales credit notes (381) issued but output not reduced" — a
mistake — yet the engine uses COR-01 to explain credit notes the taxpayer *did*
apply correctly. Classifying every rule makes that duality explicit instead of
leaving it implicit in the engine's `if` statements.

Alongside `kind`, each rule carries:

* **stage** — where it sits in the evaluation precedence. A difference may only be
  called non-compliant after every earlier stage has had its say.
* **reason_code** — which class of difference the rule is about. Reason codes
  describe the *phenomenon*; `kind` describes the *verdict*. A scope code on a
  `mistake` rule means "this is about imports/reverse charge", not "this is fine".

The reason-code list is our reading of the difference taxonomy, not a published
ZATCA code list, so it is seeded as a placeholder code set (see `seed.py`).
"""
from __future__ import annotations

# --------------------------------------------------------------------- kinds
KIND_EXPLANATION = "explanation"
KIND_MISTAKE = "mistake"
KIND_RISK = "risk"
KINDS = (KIND_EXPLANATION, KIND_MISTAKE, KIND_RISK)

# ------------------------------------------------------------------- stages
# Evaluation precedence: a difference is only "potentially non-compliant" once
# every earlier stage has been applied and has failed to explain it.
STAGES = (
    "population",    # is a Saudi e-invoice expected for this transaction at all?
    "identity",      # does it belong to this taxpayer / branch / tax group?
    "status",        # is the document valid, cleared, rejected, cancelled, duplicated?
    "tax-point",     # which date determines the VAT period?
    "category",      # standard / zero / exempt / reverse charge / outside scope
    "adjustment",    # credit note, debit note, bad debt, correction
    "aggregation",   # individual invoice, summary invoice, B2C batch
    "timing",        # is the difference inside an acceptable reporting window?
    "materiality",   # is the difference above the taxpayer-specific tolerance?
    "risk",          # is it persistent, unusual, or corroborated by other signals?
)

# -------------------------------------------------------------- reason codes
# code -> (group, label)
REASON_CODES: dict[str, tuple[str, str]] = {
    # timing
    "T01": ("timing", "Invoice issued after the tax point"),
    "T02": ("timing", "Invoice issued before the tax point"),
    "T03": ("timing", "FATOORA transmission delay"),
    "T04": ("timing", "Return filed before the late invoice was received"),
    "T05": ("timing", "Payment-basis (cash accounting) timing"),
    "T06": ("timing", "Continuous-supply timing"),
    "T07": ("timing", "Advance-payment timing"),
    "T08": ("timing", "Prior-period correction reported in the current return"),
    # scope — populations with no domestic e-invoice
    "S01": ("scope", "Exempt supply"),
    "S02": ("scope", "Zero-rated supply"),
    "S03": ("scope", "Outside-scope transaction"),
    "S04": ("scope", "Import of goods"),
    "S05": ("scope", "Reverse charge"),
    "S06": ("scope", "Tax-group internal transaction"),
    "S07": ("scope", "Non-resident / intra-GCC transaction"),
    "S08": ("scope", "Compensation or voucher"),
    "S09": ("scope", "Deemed supply"),
    # document structure
    "D01": ("document", "Simplified (B2C) invoice aggregation"),
    "D02": ("document", "Summary invoice"),
    "D03": ("document", "Credit note"),
    "D04": ("document", "Debit note"),
    "D05": ("document", "Replacement invoice"),
    "D06": ("document", "Technical rejection / resubmission"),
    "D07": ("document", "Duplicate extraction"),
    "D08": ("document", "Missing original-invoice reference"),
    # accounting & tax treatment
    "A01": ("accounting", "Input tax claimed in a later period"),
    "A02": ("accounting", "Partial input-tax recovery"),
    "A03": ("accounting", "Bad debt"),
    "A04": ("accounting", "Error below the statutory threshold"),
    "A05": ("accounting", "Amended return"),
    "A06": ("accounting", "Tax-inclusive pricing"),
    "A07": ("accounting", "Rounding"),
    "A08": ("accounting", "Currency conversion"),
    "A09": ("accounting", "Unallocated accounting adjustment"),
    # risk indicators
    "R01": ("risk", "E-invoice taxable value exceeds the return"),
    "R02": ("risk", "Return taxable value exceeds the explainable e-invoices"),
    "R03": ("risk", "Missing invoice sequence"),
    "R04": ("risk", "Unusually high credit-note ratio"),
    "R05": ("risk", "Excessive late reporting or filing"),
    "R06": ("risk", "Repeated prior-period corrections"),
    "R07": ("risk", "Inconsistent tax-category coding"),
    "R08": ("risk", "Buyer–supplier mismatch"),
    "R09": ("risk", "E-invoices issued after the filing cut-off"),
    "R10": ("risk", "Return inconsistent with the sector or historical profile"),
}

# --------------------------------------------------- per-rule classification
# code -> (kind, stage, reason_code)
RULE_TAXONOMY: dict[str, tuple[str, str, str]] = {
    # ---- Output
    "OUT-01": (KIND_MISTAKE, "materiality", "R01"),
    "OUT-02": (KIND_MISTAKE, "category", "R07"),
    "OUT-03": (KIND_MISTAKE, "category", "R07"),
    "OUT-04": (KIND_MISTAKE, "category", "S02"),
    "OUT-05": (KIND_MISTAKE, "category", "S07"),
    "OUT-06": (KIND_MISTAKE, "category", "R07"),
    "OUT-07": (KIND_EXPLANATION, "tax-point", "T02"),
    "OUT-08": (KIND_MISTAKE, "population", "S09"),
    "OUT-09": (KIND_MISTAKE, "adjustment", "R04"),
    "OUT-10": (KIND_MISTAKE, "category", "R10"),
    # from the auditor session: government supplies recognised on Etimad approval, which can
    # fall months after the transaction period. A timing explanation, not a taxpayer error.
    "OUT-11": (KIND_EXPLANATION, "tax-point", "T02"),
    # ---- Input
    "INP-01": (KIND_MISTAKE, "status", "R08"),
    "INP-02": (KIND_MISTAKE, "category", "A02"),
    "INP-03": (KIND_MISTAKE, "category", "A02"),
    "INP-04": (KIND_MISTAKE, "status", "D07"),
    "INP-05": (KIND_MISTAKE, "category", "R07"),
    "INP-06": (KIND_MISTAKE, "category", "S01"),
    "INP-07": (KIND_MISTAKE, "tax-point", "T07"),
    "INP-08": (KIND_MISTAKE, "identity", "R08"),
    "INP-09": (KIND_EXPLANATION, "tax-point", "T02"),
    "INP-10": (KIND_MISTAKE, "adjustment", "A09"),
    "INP-11": (KIND_MISTAKE, "adjustment", "A03"),
    # ---- Reverse-charge / imports (the out-of-e-invoice populations)
    "RCM-01": (KIND_MISTAKE, "population", "S05"),
    "RCM-02": (KIND_MISTAKE, "population", "S04"),
    "RCM-03": (KIND_MISTAKE, "population", "S04"),
    "RCM-04": (KIND_MISTAKE, "population", "S05"),
    "RCM-05": (KIND_MISTAKE, "category", "S05"),
    "RCM-06": (KIND_MISTAKE, "category", "S05"),
    "RCM-07": (KIND_MISTAKE, "category", "S05"),
    "RCM-08": (KIND_MISTAKE, "population", "S07"),
    "RCM-09": (KIND_MISTAKE, "timing", "T05"),
    "RCM-10": (KIND_MISTAKE, "identity", "S05"),
    # ---- Corrections
    "COR-01": (KIND_EXPLANATION, "adjustment", "D03"),
    "COR-02": (KIND_EXPLANATION, "adjustment", "D03"),
    "COR-03": (KIND_MISTAKE, "adjustment", "D04"),
    "COR-04": (KIND_MISTAKE, "adjustment", "A03"),
    "COR-05": (KIND_MISTAKE, "identity", "A05"),
    "COR-06": (KIND_MISTAKE, "adjustment", "A04"),
    "COR-07": (KIND_MISTAKE, "adjustment", "D07"),
    "COR-08": (KIND_RISK, "adjustment", "A09"),
    "COR-09": (KIND_MISTAKE, "adjustment", "A09"),
    "COR-10": (KIND_RISK, "identity", "A05"),
    # ---- Compliance (behavioural signals)
    "CMP-01": (KIND_RISK, "risk", "R05"),
    "CMP-02": (KIND_RISK, "risk", "R05"),
    "CMP-03": (KIND_MISTAKE, "materiality", "R01"),
    "CMP-04": (KIND_RISK, "identity", "R10"),
    "CMP-05": (KIND_MISTAKE, "identity", "R10"),
    "CMP-06": (KIND_RISK, "identity", "S06"),
    "CMP-07": (KIND_MISTAKE, "category", "R07"),
    "CMP-08": (KIND_RISK, "identity", "R10"),
    "CMP-09": (KIND_RISK, "category", "R10"),
    "CMP-10": (KIND_RISK, "risk", "R06"),
    "CMP-11": (KIND_MISTAKE, "category", "S01"),
    "CMP-12": (KIND_RISK, "population", "R05"),
    # ---- Data quality
    "DAT-01": (KIND_MISTAKE, "materiality", "R01"),
    "DAT-02": (KIND_MISTAKE, "materiality", "R02"),
    "DAT-03": (KIND_EXPLANATION, "timing", "T03"),
    "DAT-04": (KIND_MISTAKE, "status", "D06"),
    "DAT-05": (KIND_MISTAKE, "status", "D07"),
    "DAT-06": (KIND_MISTAKE, "identity", "R08"),
    "DAT-07": (KIND_MISTAKE, "aggregation", "D01"),
    "DAT-08": (KIND_MISTAKE, "category", "A08"),
    "DAT-09": (KIND_RISK, "materiality", "A07"),
    "DAT-10": (KIND_MISTAKE, "category", "A09"),
    "DAT-11": (KIND_MISTAKE, "adjustment", "T07"),
    "DAT-12": (KIND_RISK, "materiality", "A09"),
}

# families whose rules are behavioural signals rather than reconciling items
_RISK_FAMILIES = {"Compliance", "Data"}
_FAMILY_STAGE = {
    "Output": "category",
    "Input": "category",
    "Reverse-charge": "population",
    "Corrections": "adjustment",
    "Compliance": "risk",
    "Data": "status",
}


def classify(code: str, family: str = "", gap_band: str = "") -> dict:
    """Return {rule_kind, stage, reason_code} for a rule.

    Explicit entries in RULE_TAXONOMY win. Anything not yet classified falls back
    to a derivation from its family and gap band, so a rule added to the rulebook
    is still usable before someone hand-classifies it.
    """
    explicit = RULE_TAXONOMY.get(code)
    if explicit:
        kind, stage, reason = explicit
        return {"rule_kind": kind, "stage": stage, "reason_code": reason}

    if family in _RISK_FAMILIES or gap_band == "no":
        kind = KIND_RISK
    else:
        kind = KIND_MISTAKE
    return {"rule_kind": kind, "stage": _FAMILY_STAGE.get(family, "category"), "reason_code": ""}


def reason_code_label(code: str) -> str:
    entry = REASON_CODES.get(code)
    return entry[1] if entry else ""


def reason_code_group(code: str) -> str:
    entry = REASON_CODES.get(code)
    return entry[0] if entry else ""
