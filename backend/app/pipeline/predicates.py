"""A restricted predicate algebra — the same test in Python now and SQL later.

Qualification rules must never be arbitrary Python. At ZATCA volumes the pipeline has to
run as set-based passes over a line table, so every rule is expressed here as data: a
comparison over named columns, combined with All/Any/Not. That buys two things:

* `evaluate(row)` runs it in-process over the demo data today;
* `to_sql()` emits the equivalent WHERE fragment, so the same registry can drive a
  batch job tomorrow. `backend/tests/test_pipeline.py` asserts the two agree.

Columns are the flattened line record built by `pipeline.run.line_records` — one row per
tax subtotal joined to its invoice and the case period.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Protocol


class Predicate(Protocol):
    def evaluate(self, row: dict) -> bool: ...
    def to_sql(self) -> str: ...


@dataclass(frozen=True)
class Col:
    """Reference to another column, so a rule can compare two fields of the same row."""
    name: str


def _sql_literal(v: Any) -> str:
    if isinstance(v, Col):
        return v.name
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, date):
        return f"DATE '{v.isoformat()}'"
    if isinstance(v, (list, tuple, set, frozenset)):
        return "(" + ", ".join(_sql_literal(x) for x in v) + ")"
    return "'" + str(v).replace("'", "''") + "'"


_SQL_OPS = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


@dataclass(frozen=True)
class Cmp:
    """One comparison: `column op value`."""

    column: str
    op: str          # eq ne gt gte lt lte in not_in is_null not_null
    value: Any = None

    def _rhs(self, row: dict) -> Any:
        return row.get(self.value.name) if isinstance(self.value, Col) else self.value

    def evaluate(self, row: dict) -> bool:
        left = row.get(self.column)
        if self.op == "is_null":
            return left is None
        if self.op == "not_null":
            return left is not None
        right = self._rhs(row)
        if self.op == "in":
            return left in right
        if self.op == "not_in":
            return left not in right
        if left is None or right is None:
            return False                      # SQL three-valued logic: NULL compares false
        return {
            "eq": left == right, "ne": left != right,
            "gt": left > right, "gte": left >= right,
            "lt": left < right, "lte": left <= right,
        }[self.op]

    def to_sql(self) -> str:
        if self.op == "is_null":
            return f"{self.column} IS NULL"
        if self.op == "not_null":
            return f"{self.column} IS NOT NULL"
        if self.op == "in":
            return f"{self.column} IN {_sql_literal(self.value)}"
        if self.op == "not_in":
            return f"{self.column} NOT IN {_sql_literal(self.value)}"
        return f"{self.column} {_SQL_OPS[self.op]} {_sql_literal(self.value)}"


@dataclass(frozen=True)
class All:
    parts: tuple[Predicate, ...]

    def __init__(self, *parts: Predicate):
        object.__setattr__(self, "parts", tuple(parts))

    def evaluate(self, row: dict) -> bool:
        return all(p.evaluate(row) for p in self.parts)

    def to_sql(self) -> str:
        return "(" + " AND ".join(p.to_sql() for p in self.parts) + ")"


@dataclass(frozen=True)
class Any_:
    parts: tuple[Predicate, ...]

    def __init__(self, *parts: Predicate):
        object.__setattr__(self, "parts", tuple(parts))

    def evaluate(self, row: dict) -> bool:
        return any(p.evaluate(row) for p in self.parts)

    def to_sql(self) -> str:
        return "(" + " OR ".join(p.to_sql() for p in self.parts) + ")"


@dataclass(frozen=True)
class Not:
    part: Predicate

    def evaluate(self, row: dict) -> bool:
        return not self.part.evaluate(row)

    def to_sql(self) -> str:
        return f"NOT {self.part.to_sql()}"


# ---- shorthand constructors, so a rule reads like a sentence
def eq(column: str, value: Any) -> Cmp: return Cmp(column, "eq", value)
def ne(column: str, value: Any) -> Cmp: return Cmp(column, "ne", value)
def gt(column: str, value: Any) -> Cmp: return Cmp(column, "gt", value)
def gte(column: str, value: Any) -> Cmp: return Cmp(column, "gte", value)
def lt(column: str, value: Any) -> Cmp: return Cmp(column, "lt", value)
def lte(column: str, value: Any) -> Cmp: return Cmp(column, "lte", value)
def is_in(column: str, values: Iterable) -> Cmp: return Cmp(column, "in", tuple(values))
def not_in(column: str, values: Iterable) -> Cmp: return Cmp(column, "not_in", tuple(values))
def is_null(column: str) -> Cmp: return Cmp(column, "is_null")
def not_null(column: str) -> Cmp: return Cmp(column, "not_null")
