"""Leaf primitives shared by :mod:`config` and :mod:`docstyle` (cycle-break, K0).

:mod:`docstyle` needs four CONFIG-V2 parsing primitives that historically lived
in :mod:`config` — the version constant, the shared pydantic ``model_config``,
and the front-matter/body split+parse helpers. But :mod:`config` now wants to
import the concrete ``DocStyleMap`` from :mod:`docstyle` so its
:class:`~custodex.config.ConfigBundle.doc_style` field is typed
precisely. That would be a cycle (``config -> docstyle -> config``).

This module is the LEAF that breaks it: it imports nothing from either side, so
the only edges are ``config -> _v2base`` and ``docstyle -> _v2base`` plus the
one-way ``config -> docstyle``. :mod:`config` re-exports every name here under
its old path (``config._split_frontmatter`` etc.) so callers and tests that
reference them through :mod:`config` keep working unchanged (K6).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import ConfigDict

from .errors import ConfigError

__all__ = [
    "CDMON_CONFIG_VERSION",
    "_FM_RE",
    "_V2_MODEL_CONFIG",
    "_split_frontmatter",
    "_parse_v2_body",
]

#: The only accepted ``cdmon-config-version`` for the CONFIG-V2 dir layout.
CDMON_CONFIG_VERSION = "2.0.0"

# Mirror manifest.py's front-matter fence ("---\n ... \n---\n"). Inlined (not
# imported) to avoid an import cycle: manifest imports config, so config must not
# import manifest (K0).
_FM_RE = re.compile(r"\A---\n(.*?\n)?---\n", re.DOTALL)

#: Config keys the dir layout aliases to hyphenated YAML names live on these
#: models with ``populate_by_name=True`` so attrs stay snake_case (K0).
_V2_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


def _split_frontmatter(text: str, where: Path) -> tuple[dict, str]:
    """Split a leading YAML front-matter fence from a body (mirror manifest).

    Returns ``(meta, body)`` where ``meta`` is the parsed front-matter mapping
    and ``body`` is everything after the closing ``---`` fence. A missing fence,
    a malformed YAML block, or a non-mapping front matter all raise a loud,
    typed :class:`ConfigError` (K8) — a dir-layout file MUST carry a front-matter
    block (unlike the optional one in :mod:`manifest`).
    """
    match = _FM_RE.match(text)
    if match is None:
        raise ConfigError(
            f"Missing '---' front-matter fence in {where}: a config/cdmon file "
            "must begin with a '---\\n ... \\n---\\n' block"
        )
    fm_text = match.group(1) or ""
    body = text[match.end() :]
    try:
        loaded = yaml.safe_load(fm_text) if fm_text.strip() else {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Malformed YAML front matter in {where}: {exc}") from exc
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise ConfigError(
            f"Front matter in {where} must be a mapping, got {type(loaded).__name__}"
        )
    return loaded, body


def _parse_v2_body(body: str, path: Path) -> dict:
    """Parse a dir-layout file body as a YAML mapping (loud, K8)."""
    try:
        data = yaml.safe_load(body) if body.strip() else {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Malformed config file {path}: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"Config body in {path} must be a mapping, got {type(data).__name__}"
        )
    return data
