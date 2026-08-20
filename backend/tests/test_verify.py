from app.llm.verify import verify_claims, verify_conclusion

HERO = {
    "case_id": "C-001", "taxpayer": "Acme Trading Co.", "box": "Standard-rated sales VAT",
    "declared": 2000000, "expected_vat": 2075000, "expected_base": 13833333.33,
    "difference": 75000, "evidence_total": 0, "evidence": [], "unexplained": 75000,
    "materiality": 10000, "band": "material", "state": "potential-finding",
    "invoices_considered": 27, "population_lines": 27, "counted_lines": 25,
    "funnel": [
        {"seq": 0, "kind": "population", "rule": None, "label": "Sale e-invoices on file",
         "count": 27, "amount": 2175000},
        {"seq": 1, "kind": "defer", "rule": "OUT-07",
         "label": "Clearance lag — invoices delivered in the next period",
         "count": 2, "amount": 100000},
        {"seq": 2, "kind": "qualified", "rule": None, "label": "Qualify for Jan – Mar 2025",
         "count": 25, "amount": 2075000},
    ],
    "composition": [
        {"type_code": 388, "label": "Tax invoices", "count": 20, "amount": 2380000},
        {"type_code": 381, "label": "Credit notes", "count": 5, "amount": -305000},
    ],
}
CLEAN = {**HERO, "difference": 0, "unexplained": 0, "state": "supported", "band": "immaterial"}


def test_placeholder_prose_passes():
    txt = ("Of {{population_count}} sale lines on file, OUT-07 places {{step.OUT-07.count}} "
           "carrying {{step.OUT-07}} in the next period. The {{qualifying_count}} that qualify "
           "total {{expected}} against {{declared}} declared — a difference of {{difference}}, "
           "of which {{unexplained}} is unaccounted for.")
    assert verify_claims(txt, HERO)["ok"] is True


def test_fabricated_literal_rejected():
    r = verify_claims("...leaving SAR 90,000 unexplained.", HERO)
    assert r["ok"] is False and any("90,000" in v for v in r["violations"])


def test_true_figure_as_literal_still_rejected():
    r = verify_claims("The unexplained amount is SAR 75,000.", HERO)
    assert r["ok"] is False


def test_unknown_placeholder_rejected():
    r = verify_claims("A penalty of {{penalty}} applies.", HERO)
    assert r["ok"] is False and any("penalty" in v for v in r["violations"])


def test_spelled_out_magnitude_rejected():
    r = verify_claims("The unexplained amount is seventy-five thousand riyals.", HERO)
    assert r["ok"] is False


def test_vague_ratio_rejected():
    r = verify_claims("About a third of the documents fail to qualify.", HERO)
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
