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
