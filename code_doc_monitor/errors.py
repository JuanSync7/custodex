"""Typed error hierarchy for code-doc-monitor (K8).

Every failure mode in the engine raises a :class:`CodeDocMonitorError`
subclass carrying a clear, human-readable message — never a silent pass.
All subclasses are defined here so the hierarchy lives in one place, even
though individual slices only raise a subset of them.
"""

from __future__ import annotations

__all__ = [
    "CodeDocMonitorError",
    "ConfigError",
    "ExtractionError",
    "DriftError",
    "BackendError",
    "SchemaError",
    "InventoryError",
    "TransportError",
    "SyncError",
    "CatalogError",
    "SecretError",
]


class CodeDocMonitorError(Exception):
    """Base class for all code-doc-monitor errors. Carries a human message."""


class ConfigError(CodeDocMonitorError):
    """A config file is missing, malformed, or fails validation (K8)."""


class ExtractionError(CodeDocMonitorError):
    """A code reference could not be read or parsed (K8)."""


class DriftError(CodeDocMonitorError):
    """Drift detection hit an inconsistency (e.g. an unknown region id) (K8)."""


class BackendError(CodeDocMonitorError):
    """A backend failed to produce a usable verdict (K8)."""


class SchemaError(CodeDocMonitorError):
    """A review record failed to serialize/validate against the schema (K8)."""


class InventoryError(CodeDocMonitorError):
    """A repo root could not be inventoried (missing or not a directory) (K8)."""


class TransportError(CodeDocMonitorError):
    """A PR transport could not be built or a provider call failed (K8)."""


class SyncError(CodeDocMonitorError):
    """A config-sync run could not be performed (Y-02, K8).

    Raised for a missing ``local_path``, an unknown sync ``mode``, or a failed
    git subprocess (the working tree could not be materialized / inspected). The
    user's working tree is NEVER mutated on the failure path (K1).
    """


class CatalogError(CodeDocMonitorError):
    """The golden feature catalog is missing, malformed, or inconsistent (EPIC R, K8).

    Raised for a missing/empty catalog dir, malformed yaml, a bad feature id,
    a duplicate id across files, or a feature naming a non-existent module.
    """


class SecretError(CodeDocMonitorError):
    """A provider secret could not be sealed/opened (GIT-01, K8).

    Raised for a missing/empty/non-base64/wrong-length ``$CDMON_SECRET_KEY`` (the
    KEK that seals per-repo provider credentials at rest) or a sealed value that
    fails authentication (tampered ciphertext or the wrong key). The plaintext
    credential is NEVER included in the message.
    """
