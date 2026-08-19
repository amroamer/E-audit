"""The case dossier — everything ZATCA already holds, assembled in one place.

`collect(db, case_id)` is the single entry point; see `collect.py`.
"""
from .collect import collect, held_sources  # noqa: F401
