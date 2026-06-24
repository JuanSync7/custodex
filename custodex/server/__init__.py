"""The central monitoring server (optional ``[server]`` extra — E-03).

A FastAPI app that ingests repo registrations (:class:`RegistrationPayload`) +
review records (:class:`IngestEnvelope`) over the SHARED, versioned schemas — no
hand-written DTOs (K6) — behind an in-memory :class:`Store` Protocol that E-04
swaps for a SQLAlchemy/Postgres store.

Importing THIS subpackage requires ``fastapi`` (the ``[server]`` extra); the core
engine never imports it (``import custodex`` pulls in nothing from here),
keeping the core dependency surface minimal (K0, mirrors the ``[agent]`` extra).
The pure :class:`Store`/:class:`InMemoryStore`/:class:`RegisteredRepo` live in
``store.py`` and need no fastapi; only ``app.create_app`` does.
"""

from __future__ import annotations

from .app import create_app, store_from_env
from .store import InMemoryStore, RegisteredRepo, Store

__all__ = [
    "create_app",
    "store_from_env",
    "Store",
    "InMemoryStore",
    "RegisteredRepo",
]
