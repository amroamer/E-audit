"""The outcome vocabulary is the only wording allowed to reach a report or an email.

These guards exist because the vocabulary is the auditors' own list. If a statement of theirs
ends up with no code, or a code drifts away from their wording, the report starts saying
something the Authority did not sanction — which is exactly what a controlled vocabulary is
there to prevent.
"""
import re

import pytest

from app import outcomes as oc


def test_every_client_statement_is_covered():
    """All fifteen of the auditors' statements map to a code. None silently dropped."""
    assert oc.covered_client_refs() == frozenset(range(1, 16))


def test_codes_are_unique():
    codes = [o.code for o in oc.OUTCOMES]
    assert len(codes) == len(set(codes))


def test_no_client_statement_is_claimed_twice():
    """Two codes covering the same source statement would make the report ambiguous."""
    seen: dict[int, str] = {}
    for o in oc.OUTCOMES:
        for ref in o.client_refs:
            assert ref not in seen, f"statement {ref} claimed by {seen.get(ref)} and {o.code}"
            seen[ref] = o.code


def test_statements_carry_no_figures():
    """An outcome names what was found. The amount is computed and carried alongside it,
    never interpolated into the sentence — otherwise a model could word a figure into a
    finding and bypass the placeholder guard entirely."""
    for o in oc.OUTCOMES:
        assert not re.search(r"\d", o.statement), f"{o.code} states a figure"
        assert "{" not in o.statement, f"{o.code} carries a placeholder"


def test_every_outcome_has_an_owning_agent():
    valid = {oc.REGULATIONS, oc.DATA_ENTRY, oc.CALCULATION, oc.EVIDENCE}
    for o in oc.OUTCOMES:
        assert o.agent in valid, f"{o.code} has no valid owner"
        assert o.direction in ("sale", "purchase", "both")
        assert o.effect in (oc.DISALLOWS_INPUT, oc.INCREASES_OUTPUT, oc.DOCUMENTATION)


def test_statement_of_unknown_code_is_empty_not_invented():
    assert oc.statement("NOPE-99") == ""
    assert oc.short("NOPE-99") == "NOPE-99"


@pytest.mark.parametrize("code,fragment", [
    ("PUR-BLOCKED", "not entitled to deduct input VAT"),
    ("DOC-INVOICE", "requirements of a valid tax invoice"),
    ("SAL-SECONDARY", "secondary business activities"),
    ("PUR-NOCOOP", "lack of cooperation"),
])
def test_wording_is_the_authoritys_not_ours(code, fragment):
    assert fragment in oc.statement(code)
