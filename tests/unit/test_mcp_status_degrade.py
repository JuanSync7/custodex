"""MCP-STATUS: ``custodex_status`` degrades on an extraction error (S1-DEADSEL D16).

``custodex_status`` is the "call first" overview. One ``ExtractionError`` from the
drift detect (a code ref the extractor cannot read or parse, or a per-ref
extraction setting it rejects) must not take down the ownership / staleness /
coverage pillars with it. The drift pillar degrades to an honest partial instead:
``drift_available=False``, the extractor's message verbatim in ``drift_error``,
``-1`` for the three drift counts and ``clean=False``. Every other error stays
loud (K8), and the ``custodex_drift`` drill-down raises the same error.

Each fixture drives the REAL extractor (or the public ``register_extractor``
extension point), never a mocked ``Monitor``.

Features: FEAT-MCP-002
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from custodex import extract
from custodex.blocks import symbol_table
from custodex.config import Audience, CodeRef, DocumentSpec, MonitorConfig
from custodex.errors import ConfigError, DriftError, ExtractionError
from custodex.extract import Symbol, build_document_surface, register_extractor
from custodex.manifest import render_doc, set_fingerprint, set_region
from custodex.mcp.tools import (
    StatusSummary,
    coverage_summary,
    drift_detail,
    ownership_summary,
    staleness_summary,
    status_summary,
)

# A fixed as-of date so the staleness fold is deterministic (K10).
NOW = "2026-06-01T00:00:00+00:00"

# The wire sentinel for "unknown" (a count can never be negative). Spelled as a
# literal here on purpose: the tests pin the WIRE value, not the constant's name.
SENTINEL = -1

CODE_V1 = '''\
def greet(name: str) -> str:
    """Say hello."""
    return f"hi {name}"
'''

CODE_V2 = '''\
def greet(name: str, loud: bool) -> str:
    """Say hello."""
    return f"hi {name}"
'''

# A front matter that ``parse_doc`` rejects with a DriftError (unparseable YAML).
MALFORMED_FM = "---\n: [\n---\n# API\n"


def _synced_repo(tmp_path: Path) -> MonitorConfig:
    """A one-doc repo whose region + fingerprint match CODE_V1 (in sync)."""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "src" / "mod.py").write_text(CODE_V1, encoding="utf-8")
    spec = DocumentSpec(
        id="api",
        path="docs/api.md",
        audience=Audience.ENG_GUIDE,
        code_refs=(CodeRef(path="src/mod.py"),),
        region_keys=("symbols",),
    )
    surface = build_document_surface(spec, root)
    body = "# API\n\n<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n"
    body, _ = set_region(body, "symbols", symbol_table(surface))
    meta = set_fingerprint({}, surface.surface_hash())
    (root / spec.path).write_text(render_doc(meta, body), encoding="utf-8")
    return MonitorConfig(root="repo", documents=(spec,))


def _bare_repo(tmp_path: Path, *refs: CodeRef, doc: str = "# API\n") -> MonitorConfig:
    """A one-doc repo (no owner, never reviewed) whose doc cites ``refs``."""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "api.md").write_text(doc, encoding="utf-8")
    spec = DocumentSpec(
        id="api", path="docs/api.md", audience=Audience.ENG_GUIDE, code_refs=refs
    )
    return MonitorConfig(root="repo", documents=(spec,))


def _extraction_message(cfg: MonitorConfig, config_dir: Path) -> str:
    """The message the loud drill-down (``custodex_drift``) raises for ``cfg``."""
    with pytest.raises(ExtractionError) as exc:
        drift_detail(cfg, config_dir, repo_id="demo")
    return str(exc.value)


def _counts(summary: StatusSummary) -> tuple[int, int, int]:
    return (summary.drift_total, summary.code_doc_drift, summary.suspect_link_drift)


def _assert_degraded(summary: StatusSummary, message: str) -> None:
    """The full degraded drift-pillar shape for ``message`` (verbatim)."""
    assert summary.drift_available is False
    assert summary.drift_error == message
    assert _counts(summary) == (SENTINEL, SENTINEL, SENTINEL)
    assert summary.clean is False
    assert summary.summary == f"drift unavailable — {message}"


class _OpaqueExtractionError(ExtractionError):
    """An adopter's own ExtractionError subclass (raised with no useful text)."""


class _AdopterPlugin:
    """An adopter plugin that nests its error class (a reachable public shape)."""

    class NestedExtractionError(ExtractionError):
        """Raised with no text, so the class-name fallback is what reaches the wire."""


class _AdopterExtractor:
    """An adopter extractor registered through the public K0 extension point."""

    language = "boom"

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def extract(self, path: Path) -> list[Symbol]:
        raise self._exc


@pytest.fixture
def adopter_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Build a repo whose only ref goes through an adopter extractor raising ``exc``.

    The extractor registry is a monkeypatched COPY, so the registration never
    leaks into another test.
    """
    monkeypatch.setattr(extract, "_EXTRACTORS", dict(extract._EXTRACTORS))

    def _build(exc: Exception) -> MonitorConfig:
        register_extractor(_AdopterExtractor(exc))
        cfg = _bare_repo(tmp_path, CodeRef(path="src/x.boom", lang="boom"))
        (tmp_path / "repo" / "src" / "x.boom").write_text("boom\n", encoding="utf-8")
        return cfg

    return _build


# --- the degrade (DS 49) -------------------------------------------------------


def test_status_degrades_when_drift_cannot_be_extracted(tmp_path: Path) -> None:
    # DS 49: a code ref deleted mid-refactor. Drift degrades; the other three
    # pillars still answer and each agrees with its drill-down tool. Coverage
    # stays available (the two degrades are independent).
    cfg = _bare_repo(tmp_path, CodeRef(path="src/gone.py"))
    message = _extraction_message(cfg, tmp_path)
    assert message.startswith("Code reference not found")

    summary = status_summary(cfg, tmp_path, repo_id="demo", now=NOW)

    _assert_degraded(summary, message)
    assert "unavailable" in summary.summary
    assert summary.repo_id == "demo"
    assert summary.doc_count == 1
    own = ownership_summary(cfg, tmp_path, repo_id="demo")
    stale = staleness_summary(cfg, tmp_path, repo_id="demo", now=NOW)
    cov = coverage_summary(cfg, tmp_path, repo_id="demo")
    assert summary.docs_unowned == own.unowned_count == 1
    assert summary.docs_needing_review == stale.needs_review_total == 1
    assert summary.coverage_available is True
    assert summary.coverage_file_pct == cov.percent_files
    assert summary.coverage_symbol_pct == cov.percent_public_symbols


def test_status_degrades_drift_and_coverage_on_an_unparseable_ref(
    tmp_path: Path,
) -> None:
    # A syntax error in a cited module breaks BOTH the drift detect and the
    # coverage walk. Both pillars degrade, and unknown drift is still never
    # clean even though coverage is unavailable too.
    cfg = _synced_repo(tmp_path)
    (tmp_path / "repo" / "src" / "mod.py").write_text("def (:\n", encoding="utf-8")
    message = _extraction_message(cfg, tmp_path)

    summary = status_summary(cfg, tmp_path, repo_id="demo", now=NOW)

    _assert_degraded(summary, message)
    assert summary.coverage_available is False
    assert summary.coverage_file_pct == -1.0
    assert summary.coverage_symbol_pct == -1.0


def test_coverage_only_degrade_leaves_the_drift_pillar_available_and_clean(
    tmp_path: Path,
) -> None:
    # The converse direction: an unparseable file that NO doc cites breaks only
    # the coverage walk. The drift pillar must stay available, error-free, clean
    # and at real (zero) counts.
    cfg = _synced_repo(tmp_path)
    (tmp_path / "repo" / "src" / "broken.py").write_text("def (:\n", encoding="utf-8")

    summary = status_summary(cfg, tmp_path, repo_id="demo", now=NOW)

    assert summary.coverage_available is False
    assert summary.drift_available is True
    assert summary.drift_error is None
    assert summary.clean is True
    assert _counts(summary) == (0, 0, 0)
    assert "unavailable" not in summary.summary


@pytest.mark.parametrize(
    ("ref", "files", "names"),
    [
        (CodeRef(path="src/mod.py", lang="pyhton"), {"src/mod.py": CODE_V1}, "pyhton"),
        (
            CodeRef(path="src/data.json", extract="records"),
            {"src/data.json": "[]\n"},
            "json_records",
        ),
    ],
    ids=["unregistered-lang", "records-without-json-records"],
)
def test_status_degrades_on_a_per_ref_extraction_setting(
    tmp_path: Path, ref: CodeRef, files: dict[str, str], names: str
) -> None:
    # The degrade is keyed on the error CLASS. A per-ref setting the loader
    # deliberately defers to extraction time raises ExtractionError, so it
    # degrades too, and the message names the setting.
    cfg = _bare_repo(tmp_path, ref)
    for rel, text in files.items():
        (tmp_path / "repo" / rel).write_text(text, encoding="utf-8")
    message = _extraction_message(cfg, tmp_path)
    assert names in message

    summary = status_summary(cfg, tmp_path, repo_id="demo", now=NOW)

    _assert_degraded(summary, message)


@pytest.mark.parametrize("drifted", [False, True], ids=["healthy", "drifted"])
def test_status_drift_is_available_on_an_extractable_repo(
    tmp_path: Path, drifted: bool
) -> None:
    # A repo whose refs extract keeps the drift pillar available with real
    # counts, whether or not it has drift.
    cfg = _synced_repo(tmp_path)
    if drifted:
        (tmp_path / "repo" / "src" / "mod.py").write_text(CODE_V2, encoding="utf-8")
    detail = drift_detail(cfg, tmp_path, repo_id="demo")

    summary = status_summary(cfg, tmp_path, repo_id="demo", now=NOW)

    assert summary.drift_available is True
    assert summary.drift_error is None
    assert summary.drift_total == detail.total
    assert summary.clean is (not drifted)
    assert (summary.drift_total >= 1) is drifted
    assert "unavailable" not in summary.summary


# --- what stays loud (DS 50, K8) ------------------------------------------------


def test_drift_tool_still_raises_loudly(tmp_path: Path) -> None:
    # DS 50: only the overview degrades. The drill-down raises the very error
    # the overview reports.
    cfg = _bare_repo(tmp_path, CodeRef(path="src/gone.py"))
    summary = status_summary(cfg, tmp_path, repo_id="demo", now=NOW)
    with pytest.raises(ExtractionError) as exc:
        drift_detail(cfg, tmp_path, repo_id="demo")
    assert str(exc.value) == summary.drift_error


def test_status_still_raises_on_a_non_extraction_error(tmp_path: Path) -> None:
    # A malformed front matter is a DriftError from the same detect. With the
    # refs extractable, nothing masks it, so status fails loudly.
    cfg = _synced_repo(tmp_path)
    (tmp_path / "repo" / "docs" / "api.md").write_text(MALFORMED_FM, encoding="utf-8")
    with pytest.raises(DriftError):
        status_summary(cfg, tmp_path, repo_id="demo", now=NOW)


def test_status_extraction_error_comes_before_the_same_docs_front_matter(
    tmp_path: Path,
) -> None:
    # First error wins, exactly as `cdx check`: the detect extracts a doc's refs
    # BEFORE it parses that doc's front matter. A dead ref therefore masks the
    # same doc's malformed front matter, and the DriftError surfaces once the
    # ref is fixed.
    cfg = _bare_repo(tmp_path, CodeRef(path="src/gone.py"), doc=MALFORMED_FM)
    message = _extraction_message(cfg, tmp_path)

    _assert_degraded(status_summary(cfg, tmp_path, repo_id="demo", now=NOW), message)

    (tmp_path / "repo" / "src" / "gone.py").write_text(CODE_V1, encoding="utf-8")
    with pytest.raises(DriftError):
        status_summary(cfg, tmp_path, repo_id="demo", now=NOW)


def test_status_config_error_from_an_adopter_extractor_stays_loud(
    adopter_repo: Any, tmp_path: Path
) -> None:
    # The catch is NARROW: an adopter extractor (public register_extractor hook)
    # that raises a ConfigError is not an extraction failure, so it stays loud.
    cfg = adopter_repo(ConfigError("adopter extractor config is broken"))
    with pytest.raises(ConfigError, match="adopter extractor config is broken"):
        status_summary(cfg, tmp_path, repo_id="demo", now=NOW)


def test_status_config_error_from_another_pillar_stays_loud(tmp_path: Path) -> None:
    # The guard covers the drift detect only. A bad `reviewed` date raises a
    # ConfigError from the staleness fold, and status fails loudly on it.
    cfg = _synced_repo(tmp_path)
    spec = cfg.documents[0].model_copy(update={"reviewed": "last tuesday"})
    cfg = cfg.model_copy(update={"documents": (spec,)})
    with pytest.raises(ConfigError):
        status_summary(cfg, tmp_path, repo_id="demo", now=NOW)


def test_status_bad_reviewed_date_stays_loud_even_behind_a_dead_ref(
    tmp_path: Path,
) -> None:
    # First-error-wins covers ONLY errors raised inside the drift detect. A bad
    # `reviewed` date is a ConfigError from the staleness fold, and the degrade
    # branch does not return early (the folds always run), so an unextractable
    # ref never masks it. Fold ORDER relative to the detect is not the cause.
    cfg = _bare_repo(tmp_path, CodeRef(path="src/gone.py"))
    spec = cfg.documents[0].model_copy(update={"reviewed": "last tuesday"})
    cfg = cfg.model_copy(update={"documents": (spec,)})
    _extraction_message(cfg, tmp_path)  # the detect alone would degrade

    with pytest.raises(ConfigError, match="last tuesday"):
        status_summary(cfg, tmp_path, repo_id="demo", now=NOW)


# --- drift_error is verbatim ----------------------------------------------------


def test_drift_error_is_verbatim_for_a_multiline_extractor_message(
    tmp_path: Path,
) -> None:
    # The real extractor: a code-ref path with an embedded newline yields a
    # two-line message. All of it reaches drift_error, not just line one.
    cfg = _bare_repo(tmp_path, CodeRef(path="src/dead\nref.py"))
    message = _extraction_message(cfg, tmp_path)
    assert "\n" in message

    _assert_degraded(status_summary(cfg, tmp_path, repo_id="demo", now=NOW), message)


def test_drift_error_keeps_edge_whitespace_verbatim(tmp_path: Path) -> None:
    # The real extractor: a trailing space in the ref path survives into the
    # message. drift_error keeps it, byte for byte, so it equals what the loud
    # drill-down raises.
    cfg = _bare_repo(tmp_path, CodeRef(path="src/gone.py "))
    message = _extraction_message(cfg, tmp_path)
    assert message.endswith(" ")

    _assert_degraded(status_summary(cfg, tmp_path, repo_id="demo", now=NOW), message)


def test_drift_error_is_verbatim_for_an_aggregate_message(
    adopter_repo: Any, tmp_path: Path
) -> None:
    # DS 52's shape (a multi-line every-dead-ref aggregate), driven through an
    # adopter extractor until DS-INBOX ships the real one.
    aggregate = "2 dead code refs:\n  src/a.py: gone\n  src/b.py: gone"
    cfg = adopter_repo(ExtractionError(aggregate))

    summary = status_summary(cfg, tmp_path, repo_id="demo", now=NOW)

    _assert_degraded(summary, aggregate)


@pytest.mark.parametrize(
    "exc",
    [_OpaqueExtractionError(), _OpaqueExtractionError("  \n ")],
    ids=["no-message", "blank-message"],
)
def test_status_names_the_error_class_when_the_message_is_blank(
    adopter_repo: Any, tmp_path: Path, exc: ExtractionError
) -> None:
    # An adopter's bare `raise ExtractionError()` (here a subclass) still
    # degrades to a TYPED partial that says why: the error's class name. It must
    # never turn into an untyped validation crash (K8).
    cfg = adopter_repo(exc)

    summary = status_summary(cfg, tmp_path, repo_id="demo", now=NOW)

    _assert_degraded(summary, "_OpaqueExtractionError")


def test_blank_message_names_the_bare_class_name_not_the_qualname(
    adopter_repo: Any, tmp_path: Path
) -> None:
    # Deliberate wire choice: the fallback is the BARE class name (`__name__`),
    # not the dotted `__qualname__`. The two differ only for a nested class, a
    # shape an adopter can reach through the public register_extractor hook.
    cfg = adopter_repo(_AdopterPlugin.NestedExtractionError())

    summary = status_summary(cfg, tmp_path, repo_id="demo", now=NOW)

    _assert_degraded(summary, "NestedExtractionError")


# --- read-only + deterministic (K1, K7, K10) --------------------------------------


def _snapshot(root: Path) -> tuple[tuple[str, ...], dict[str, bytes]]:
    """Every path (directories included) plus every file's bytes under ``root``."""
    paths = tuple(
        sorted(
            str(p.relative_to(root)) + ("/" if p.is_dir() else "")
            for p in root.rglob("*")
        )
    )
    blobs = {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    return paths, blobs


def test_degraded_status_is_read_only_and_deterministic(tmp_path: Path) -> None:
    cfg = _bare_repo(tmp_path, CodeRef(path="src/gone.py"))
    before = _snapshot(tmp_path)

    first = status_summary(cfg, tmp_path, repo_id="demo", now=NOW)
    second = status_summary(cfg, tmp_path, repo_id="demo", now=NOW)

    assert first.drift_available is False
    assert _snapshot(tmp_path) == before  # no file, no directory (e.g. .cdmon/)
    assert first == second
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


# --- the StatusSummary contract (K6 additive; the sentinel is tied to its flag) --

_AVAILABLE_FIELDS: dict[str, Any] = {
    "repo_id": "demo",
    "clean": True,
    "doc_count": 1,
    "drift_total": 0,
    "code_doc_drift": 0,
    "suspect_link_drift": 0,
    "coverage_available": True,
    "coverage_file_pct": 100.0,
    "coverage_symbol_pct": 100.0,
    "docs_unowned": 0,
    "docs_needing_review": 0,
    "summary": "clean — no drift detected",
}

_DEGRADED_FIELDS: dict[str, Any] = {
    **_AVAILABLE_FIELDS,
    "clean": False,
    "drift_total": SENTINEL,
    "code_doc_drift": SENTINEL,
    "suspect_link_drift": SENTINEL,
    "drift_available": False,
    "drift_error": "Code reference not found: src/gone.py",
    "summary": "drift unavailable — Code reference not found: src/gone.py",
}


def test_status_summary_new_fields_default_to_available() -> None:
    # K6: a producer that predates the two fields (the MCP-01 payload) still
    # validates, and reads as an available drift pillar.
    summary = StatusSummary(**_AVAILABLE_FIELDS)
    assert summary.drift_available is True
    assert summary.drift_error is None


def test_status_summary_accepts_a_coherent_degraded_payload() -> None:
    summary = StatusSummary(**_DEGRADED_FIELDS)
    assert summary.drift_available is False
    assert _counts(summary) == (SENTINEL, SENTINEL, SENTINEL)


@pytest.mark.parametrize(
    ("base", "override", "match"),
    [
        # available side: no error (None, not merely falsy), no negative count
        (_AVAILABLE_FIELDS, {"drift_error": "boom"}, "must be None"),
        (_AVAILABLE_FIELDS, {"drift_error": ""}, "must be None"),
        (
            _AVAILABLE_FIELDS,
            {"drift_total": -1, "code_doc_drift": -1, "suspect_link_drift": -1},
            "non-negative",
        ),
        (_AVAILABLE_FIELDS, {"drift_total": -1}, "non-negative"),
        (_AVAILABLE_FIELDS, {"code_doc_drift": -1}, "non-negative"),
        (_AVAILABLE_FIELDS, {"suspect_link_drift": -1}, "non-negative"),
        # unavailable side: a non-blank error, never clean, exactly -1 counts
        (_DEGRADED_FIELDS, {"drift_error": None}, "non-blank"),
        (_DEGRADED_FIELDS, {"drift_error": ""}, "non-blank"),
        (_DEGRADED_FIELDS, {"drift_error": "  \n"}, "non-blank"),
        (_DEGRADED_FIELDS, {"clean": True}, "never clean"),
        (_DEGRADED_FIELDS, {"drift_total": 0}, "-1 sentinel"),
        (_DEGRADED_FIELDS, {"code_doc_drift": 0}, "-1 sentinel"),
        (_DEGRADED_FIELDS, {"suspect_link_drift": 0}, "-1 sentinel"),
        (_DEGRADED_FIELDS, {"drift_total": -2}, "-1 sentinel"),
        (_DEGRADED_FIELDS, {"suspect_link_drift": -7}, "-1 sentinel"),
    ],
    ids=[
        "available-with-error",
        "available-with-empty-error",
        "available-with-sentinel-counts",
        "available-with-negative-total",
        "available-with-negative-code-doc",
        "available-with-negative-suspect",
        "unavailable-no-error",
        "unavailable-empty-error",
        "unavailable-blank-error",
        "unavailable-but-clean",
        "unavailable-total-counted",
        "unavailable-code-doc-counted",
        "unavailable-suspect-counted",
        "unavailable-total-minus-2",
        "unavailable-suspect-minus-7",
    ],
)
def test_status_summary_rejects_an_incoherent_drift_pair(
    base: dict[str, Any], override: dict[str, Any], match: str
) -> None:
    # Neither a silent degrade (the sentinel without its flag) nor a
    # self-contradicting one (the flag with real counts, clean, or no reason)
    # is representable. Each case changes ONE thing in a coherent payload.
    with pytest.raises(ValidationError, match=match):
        StatusSummary(**{**base, **override})
