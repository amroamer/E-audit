from app.llm.verify import verify_claims, verify_conclusion

HERO = {
    "case_id": "C-001", "taxpayer": "Acme Trading Co.", "box": "Standard-rated sales VAT",
    "declared": 2000000, "reconstructed_gross": 2480000, "apparent_gap": 480000,
    "explained_total": 405000, "explained_pct": 0.8438, "residual": 75000,
    "materiality": 10000, "band": "material", "state": "potential-finding",
    "invoices_considered": 27,
    "bridge": [
        {"seq": 0, "kind": "anchor", "rule": None, "label": "Declared (as filed)",
         "amount": 2000000, "running": 2000000},
        {"seq": 1, "kind": "gap", "rule": None, "label": "Reconstructed from e-invoices",
         "amount": 480000, "running": 2480000},
        {"seq": 2, "kind": "explain", "rule": "COR-01",
         "label": "Credit notes (381) already applied in the return",
         "amount": -305000, "running": 2175000},
        {"seq": 3, "kind": "explain", "rule": "TIM-04",
         "label": "Clearance lag", "amount": -100000, "running": 2075000},
        {"seq": 4, "kind": "residual", "rule": None, "label": "Unexplained residual",
         "amount": 75000, "running": 2075000},
    ],
}
CLEAN = {**HERO, "residual": 0, "state": "supported", "band": "immaterial", "explained_pct": 1.0}


def test_placeholder_prose_passes():
    txt = ("Reconstructed output VAT ({{reconstructed_gross}}) exceeds declared "
           "({{declared}}) — a gap of {{apparent_gap}}. COR-01 credit notes (381) of "
           "{{bridge.COR-01}} and TIM-04 clearance lag of {{bridge.TIM-04}} explain "
           "{{explained_pct}}, leaving a residual of {{residual}}.")
    assert verify_claims(txt, HERO)["ok"] is True


def test_fabricated_literal_rejected():
    r = verify_claims("...leaving an unexplained residual of SAR 90,000.", HERO)
    assert r["ok"] is False and any("90,000" in v for v in r["violations"])


def test_true_figure_as_literal_still_rejected():
    r = verify_claims("The residual is SAR 75,000.", HERO)
    assert r["ok"] is False


def test_unknown_placeholder_rejected():
    r = verify_claims("A penalty of {{penalty}} applies.", HERO)
    assert r["ok"] is False and any("penalty" in v for v in r["violations"])


def test_spelled_out_magnitude_rejected():
    r = verify_claims("The residual is seventy-five thousand riyals.", HERO)
    assert r["ok"] is False


def test_vague_ratio_rejected():
    r = verify_claims("Rules explain about a third of the difference.", HERO)
    assert r["ok"] is False


def test_arabic_numerals_rejected():
    r = verify_claims("المبلغ المتبقي هو ٧٥٬٠٠٠", HERO)
    assert r["ok"] is False


def test_rule_and_doc_codes_allowed():
    assert verify_claims("Per COR-01, the credit notes (381) were applied.", HERO)["ok"] is True


def test_conclusion_flip_supported_to_finding():
    v = verify_conclusion("This constitutes a finding and a penalty is recommended.", CLEAN)
    assert v and "SUPPORTED" in v[0]


def test_conclusion_flip_open_to_cleared():
    v = verify_conclusion("The gap is fully explained; no further action.", HERO)
    assert v and "OPEN" in v[0]


def test_figure_free_summary_rejects_any_digit():
    assert verify_claims("Filed 3 amended returns in 2024.", None, figure_free=True)["ok"] is False
    assert verify_claims("Repeated late amendments across periods.", None, figure_free=True)["ok"] is True
