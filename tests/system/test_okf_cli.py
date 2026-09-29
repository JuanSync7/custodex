"""OKF-01 — `cdx okf` end-to-end (offline, via CliRunner).

Default writes the bundle (the `cdx wiki` precedent); `--check` gates.

Features: FEAT-OKF-001
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from custodex.backends import BackendResult, FixRequest, MockBackend
from custodex.cli import app
from custodex.config import MonitorConfig, load_config
from custodex.drift import DriftKind
from custodex.mcp.tools import RemediationItem, remediate_drift, resolve_drift
from custodex.reviewlog import read_all

runner = CliRunner()

_DOC = """# Guide

> One line of purpose.

Prose.
"""


def _fixture(tmp_path: Path) -> None:
    (tmp_path / "guide.md").write_text(_DOC, encoding="utf-8")
    (tmp_path / "code.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "cdmon.yaml").write_text(
        'version: "1.0.0"\n'
        'root: "."\n'
        "documents:\n"
        '  - id: "guide"\n'
        '    path: "guide.md"\n'
        '    audience: "user-guide"\n'
        "    code_refs:\n"
        '      - path: "code.py"\n',
        encoding="utf-8",
    )


def test_default_writes_then_unchanged_then_check(tmp_path: Path, monkeypatch) -> None:
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)

    first = runner.invoke(app, ["okf"])
    assert first.exit_code == 0, first.output
    assert "wrote 2 file(s), 0 unchanged" in first.output

    bundle_doc = tmp_path / ".cdmon" / "okf" / "guide.md"
    front = yaml.safe_load(bundle_doc.read_text(encoding="utf-8").split("---\n")[1])
    assert front["type"] == "User Guide"
    assert front["generated"] == {"by": front["generated"]["by"]}  # no `at`
    assert front["custodex"]["doc_id"] == "guide"
    assert front["sources"] == [{"resource": "code.py"}]

    second = runner.invoke(app, ["okf"])
    assert "wrote 0 file(s), 2 unchanged" in second.output

    clean = runner.invoke(app, ["okf", "--check"])
    assert clean.exit_code == 0, clean.output
    assert "in sync" in clean.output

    (tmp_path / "guide.md").write_text(_DOC + "\nMore prose.\n", encoding="utf-8")
    stale = runner.invoke(app, ["okf", "--check"])
    assert stale.exit_code == 1
    assert "STALE" in stale.output


def test_out_override_and_json(tmp_path: Path, monkeypatch) -> None:
    _fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "elsewhere"
    result = runner.invoke(app, ["okf", "--out", str(out_dir), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert sorted(payload["written"]) == ["guide.md", "index.md"]
    assert (
        (out_dir / "index.md")
        .read_text(encoding="utf-8")
        .startswith('---\nokf_version: "0.2"\n---\n')
    )


# --- `verified` binding end-to-end (idea 11 / critic 2.5) ---------------------

_MANAGED_CONFIG = (
    'version: "1.0.0"\n'
    'root: "."\n'
    "documents:\n"
    "  - id: guide\n"
    "    path: docs/guide.md\n"
    "    audience: user-guide\n"
    "    region_keys: [symbols]\n"
    "    code_refs: [{path: src/lib.py}]\n"
)


def _unhealed_fixture(tmp_path: Path, config: str = _MANAGED_CONFIG) -> Path:
    """A managed doc with an empty region and no fingerprint yet (drifted);
    writes the config at ``tmp_path / "cdmon.yaml"`` unless a caller moves it.
    Returns the config path."""
    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "src" / "lib.py").write_text(
        'def connect(host: str) -> None:\n    """Open."""\n', encoding="utf-8"
    )
    (tmp_path / "docs" / "guide.md").write_text(
        "# Guide\n\n> How to connect.\n\n"
        "<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n",
        encoding="utf-8",
    )
    cfg = tmp_path / "cdmon.yaml"
    cfg.write_text(config, encoding="utf-8")
    return cfg


def _managed_fixture(tmp_path: Path) -> str:
    """A managed doc healed by `cdx monitor --apply`; returns its HASH record id.

    After the heal the record's surface_hash IS the doc's stored fingerprint,
    so a verifying resolution of that record binds to the current surface.
    """
    _unhealed_fixture(tmp_path)
    healed = runner.invoke(app, ["monitor", "--apply"])
    assert healed.exit_code == 0, healed.output
    records = read_all(tmp_path / ".cdmon" / "review-log.jsonl")
    return next(r.record_id for r in records if r.drift_kind == "HASH")


def _verified(tmp_path: Path) -> list[dict[str, str]] | None:
    exported = runner.invoke(app, ["okf"])
    assert exported.exit_code == 0, exported.output
    text = (tmp_path / ".cdmon" / "okf" / "docs" / "guide.md").read_text(
        encoding="utf-8"
    )
    return yaml.safe_load(text.split("---\n")[1]).get("verified")


def _resolve(record_id: str, resolution: str, *by: str) -> None:
    args = ["resolve", record_id, "--resolution", resolution]
    if by:
        args += ["--by", by[0]]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output


def test_rejected_resolution_is_never_a_human_verified_event(
    tmp_path: Path, monkeypatch
) -> None:
    """Bug repro (wf-next/ba_okf): `cdx resolve --resolution rejected --by
    alice` made the bundle say `verified: human:alice` over the very fix she
    rejected. A rejection is not a verification."""
    # Feature: FEAT-OKF-001
    monkeypatch.chdir(tmp_path)
    record_id = _managed_fixture(tmp_path)
    _resolve(record_id, "rejected", "alice")
    assert _verified(tmp_path) is None


def test_accept_verifies_and_a_later_reject_retracts_it(
    tmp_path: Path, monkeypatch
) -> None:
    """An ACCEPT of the record bound to the current fingerprint verifies the
    doc; a later REJECT of the same record is a correction (last-write-wins)
    and withdraws the claim — `okf --check` then reports the bundle STALE
    instead of "in sync" over a withdrawn attestation."""
    # Feature: FEAT-OKF-001
    monkeypatch.chdir(tmp_path)
    record_id = _managed_fixture(tmp_path)
    _resolve(record_id, "accepted", "bob")
    verified = _verified(tmp_path)
    assert verified is not None and [e["by"] for e in verified] == ["human:bob"]

    _resolve(record_id, "rejected", "bob")
    stale = runner.invoke(app, ["okf", "--check"])
    assert stale.exit_code == 1
    assert "STALE" in stale.output
    assert _verified(tmp_path) is None


def test_resolution_without_a_resolver_emits_no_verified_event(
    tmp_path: Path, monkeypatch
) -> None:
    """Bug: an ACCEPT with no `--by` became `human:unrecorded` — a human
    attestation with no human. An unknown resolver emits no event at all."""
    # Feature: FEAT-OKF-001
    monkeypatch.chdir(tmp_path)
    record_id = _managed_fixture(tmp_path)
    _resolve(record_id, "accepted")
    assert _verified(tmp_path) is None
    bundle_doc = tmp_path / ".cdmon" / "okf" / "docs" / "guide.md"
    assert "unrecorded" not in bundle_doc.read_text(encoding="utf-8")


def test_code_change_and_reheal_drop_a_stale_verification(
    tmp_path: Path, monkeypatch
) -> None:
    """Bug repro: after a code change and a MACHINE reheal the bundle still
    said `verified: human:<who>` beside the new fingerprint. The accept was
    for the old code surface, so it no longer binds; re-running the export
    with nothing changed is a no-op (K7)."""
    # Feature: FEAT-OKF-001
    monkeypatch.chdir(tmp_path)
    record_id = _managed_fixture(tmp_path)
    _resolve(record_id, "accepted", "alice")
    assert _verified(tmp_path) is not None

    (tmp_path / "src" / "lib.py").write_text(
        'def connect(host: str, port: int = 443) -> None:\n    """Open."""\n',
        encoding="utf-8",
    )
    reheal = runner.invoke(app, ["monitor", "--apply"])
    assert reheal.exit_code == 0, reheal.output
    assert _verified(tmp_path) is None

    again = runner.invoke(app, ["okf"])
    assert "wrote 0 file(s)" in again.output


# --- review round 1: the claim needs a RESOLVED doc and no later drift --------

_LIB_S1 = 'def connect(host: str) -> None:\n    """Open."""\n'
_LIB_S2 = 'def connect(host: str, port: int = 443) -> None:\n    """Open."""\n'


def _records_of(tmp_path: Path, kind: str, doc_id: str = "guide") -> list[str]:
    """Record ids of ``kind`` on ``doc_id``, in log (append) order."""
    return [
        r.record_id
        for r in read_all(tmp_path / ".cdmon" / "review-log.jsonl")
        if r.drift_kind == kind and r.doc_id == doc_id
    ]


def test_accepting_an_unapplied_region_fix_does_not_verify_drifted_content(
    tmp_path: Path, monkeypatch
) -> None:
    """Bug repro (review r1, rev-r1/region): a REGION record's surface_hash
    equals the stored fingerprint BEFORE its fix is applied, so accepting
    the proposal published `verified` over the very content `cdx check`
    still reports as drifted — and `okf --check` said "in sync"."""
    # Feature: FEAT-OKF-001
    monkeypatch.chdir(tmp_path)
    _managed_fixture(tmp_path)
    doc = tmp_path / "docs" / "guide.md"
    doc.write_text(
        doc.read_text(encoding="utf-8").replace(
            "def connect(host: str) -> None",
            "def connect(host: str, retries: int = 99) -> None  # WRONG",
        ),
        encoding="utf-8",
    )
    proposed = runner.invoke(app, ["monitor"])  # proposal only, not applied
    assert proposed.exit_code == 1, proposed.output
    _resolve(_records_of(tmp_path, "REGION")[-1], "accepted", "alice")
    assert runner.invoke(app, ["check"]).exit_code == 1  # the drift still stands
    assert _verified(tmp_path) is None


_TWO_DOC_CONFIG = (
    'version: "1.0.0"\n'
    'root: "."\n'
    "documents:\n"
    "  - id: api\n"
    "    path: docs/api.md\n"
    "    audience: eng-guide\n"
    "    region_keys: [symbols]\n"
    "    code_refs: [{path: src/lib.py}]\n"
    "  - id: guide\n"
    "    path: docs/guide.md\n"
    "    audience: user-guide\n"
    "    region_keys: [symbols]\n"
    "    code_refs: [{path: src/lib.py}]\n"
    "    depends_on: [{doc: api}]\n"
)


def test_an_escalated_suspect_link_verifies_only_once_the_link_is_cleared(
    tmp_path: Path, monkeypatch
) -> None:
    """Bug repro (review r1, rev-r1/suspect): an upstream edit makes the
    downstream doc SUSPECT; accepting that ESCALATE record (no fix, surface
    unchanged) published `verified` while `cdx check` still failed on the
    link. The claim holds only after the human re-confirms the edge."""
    # Feature: FEAT-OKF-001
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "src" / "lib.py").write_text(_LIB_S1, encoding="utf-8")
    region = "<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n"
    (tmp_path / "docs" / "api.md").write_text(f"# API\n\n{region}", encoding="utf-8")
    (tmp_path / "docs" / "guide.md").write_text(
        f"# Guide\n\n> How to connect.\n\n{region}", encoding="utf-8"
    )
    (tmp_path / "cdmon.yaml").write_text(_TWO_DOC_CONFIG, encoding="utf-8")
    assert runner.invoke(app, ["monitor", "--apply"]).exit_code == 0

    api = tmp_path / "docs" / "api.md"
    api.write_text(
        api.read_text(encoding="utf-8") + "\nThe API now says port 8443.\n",
        encoding="utf-8",
    )
    runner.invoke(app, ["monitor"])
    _resolve(_records_of(tmp_path, "SUSPECT_LINK")[-1], "accepted", "carol")
    assert runner.invoke(app, ["check"]).exit_code == 1  # the link still stands
    assert _verified(tmp_path) is None

    cleared = runner.invoke(app, ["resolve", "--edge", "guide", "api"])
    assert cleared.exit_code == 0, cleared.output
    assert runner.invoke(app, ["check"]).exit_code == 0
    verified = _verified(tmp_path)
    assert verified is not None and [e["by"] for e in verified] == ["human:carol"]


def test_an_accept_before_a_later_machine_heal_does_not_vouch_for_it(
    tmp_path: Path, monkeypatch
) -> None:
    """Bug repro (review r1, rev-r1/preapply): an ACCEPT of an unapplied HASH
    proposal bound to the LATER machine heal at the same surface — text the
    human never saw (with a real LLM backend, not the text accepted), dated
    before the rewrite it vouched for. The heal is a later record, so it
    supersedes; only accepting the heal's own record verifies the doc."""
    # Feature: FEAT-OKF-001
    monkeypatch.chdir(tmp_path)
    _managed_fixture(tmp_path)
    (tmp_path / "src" / "lib.py").write_text(_LIB_S2, encoding="utf-8")
    runner.invoke(app, ["monitor"])  # proposal only, not applied
    _resolve(_records_of(tmp_path, "HASH")[-1], "accepted", "alice")
    assert _verified(tmp_path) is None  # the doc still carries the old surface

    healed = runner.invoke(app, ["monitor", "--apply"])
    assert healed.exit_code == 0, healed.output
    assert _verified(tmp_path) is None  # the machine rewrite is not reviewed

    _resolve(_records_of(tmp_path, "HASH")[-1], "accepted", "alice")
    verified = _verified(tmp_path)
    assert verified is not None and [e["by"] for e in verified] == ["human:alice"]


def test_a_reverted_code_surface_does_not_revive_an_old_attestation(
    tmp_path: Path, monkeypatch
) -> None:
    """Bug repro (review r1, rev-r1/revert): an ACCEPT at surface S1 came
    back after S1 → S2 → S1 (two machine reheals), over a prose line added
    in between that nobody reviewed."""
    # Feature: FEAT-OKF-001
    monkeypatch.chdir(tmp_path)
    record_id = _managed_fixture(tmp_path)
    _resolve(record_id, "accepted", "alice")
    assert _verified(tmp_path) is not None

    lib = tmp_path / "src" / "lib.py"
    lib.write_text(_LIB_S2, encoding="utf-8")
    assert runner.invoke(app, ["monitor", "--apply"]).exit_code == 0
    doc = tmp_path / "docs" / "guide.md"
    doc.write_text(
        doc.read_text(encoding="utf-8")
        + "\nconnect() defaults to port 8080 (text nobody reviewed).\n",
        encoding="utf-8",
    )
    lib.write_text(_LIB_S1, encoding="utf-8")
    assert runner.invoke(app, ["monitor", "--apply"]).exit_code == 0
    assert _verified(tmp_path) is None


def test_an_override_verifies_only_once_the_humans_text_is_in_the_doc(
    tmp_path: Path, monkeypatch
) -> None:
    """Bug repro (review r1, rev-r1/override): custodex never writes
    `resolved_text` to the doc, so `resolve --resolution overridden --text`
    published `verified: human:dave` over the machine text dave overrode.
    The claim holds once his text is actually in the doc."""
    # Feature: FEAT-OKF-001
    monkeypatch.chdir(tmp_path)
    record_id = _managed_fixture(tmp_path)
    text = "Connect over TLS; see the security guide."
    overridden = runner.invoke(
        app,
        [
            "resolve",
            record_id,
            "--resolution",
            "overridden",
            "--by",
            "dave",
            "--text",
            text,
        ],
    )
    assert overridden.exit_code == 0, overridden.output
    assert _verified(tmp_path) is None

    doc = tmp_path / "docs" / "guide.md"
    doc.write_text(doc.read_text(encoding="utf-8") + f"\n{text}\n", encoding="utf-8")
    assert runner.invoke(app, ["check"]).exit_code == 0  # prose is not graded
    verified = _verified(tmp_path)
    assert verified is not None and [e["by"] for e in verified] == ["human:dave"]


def test_check_is_in_sync_right_after_exporting_a_verification(
    tmp_path: Path, monkeypatch
) -> None:
    """`cdx okf --check` renders with the SAME logs and drift report as the
    export: right after `cdx okf` writes a bundle carrying a bound `verified`
    event, the read-only gate reports "in sync" (exit 0), not a false STALE
    no re-export could clear; a second export writes nothing (K7)."""
    # Feature: FEAT-OKF-001
    monkeypatch.chdir(tmp_path)
    record_id = _managed_fixture(tmp_path)
    _resolve(record_id, "accepted", "bob")
    verified = _verified(tmp_path)
    assert verified is not None and [e["by"] for e in verified] == ["human:bob"]
    clean = runner.invoke(app, ["okf", "--check"])
    assert clean.exit_code == 0, clean.output
    assert "in sync" in clean.output
    again = runner.invoke(app, ["okf"])
    assert "wrote 0 file(s)" in again.output


def test_drift_is_detected_only_when_a_verification_is_at_stake(
    tmp_path: Path, monkeypatch
) -> None:
    """`cdx okf` needs the drift report only to decide `verified`, so a repo
    with no resolutions still exports without extracting code (an unreadable
    code ref does not break a plain export). Once a resolution is at stake,
    an unreadable ref is a loud error (K8), never a silent claim."""
    # Feature: FEAT-OKF-001
    plain = tmp_path / "plain"
    plain.mkdir()
    _fixture(plain)
    (plain / "code.py").unlink()
    monkeypatch.chdir(plain)
    exported = runner.invoke(app, ["okf"])
    assert exported.exit_code == 0, exported.output

    managed = tmp_path / "managed"
    managed.mkdir()
    monkeypatch.chdir(managed)
    _resolve(_managed_fixture(managed), "accepted", "bob")
    (managed / "src" / "lib.py").unlink()
    for args in (["okf"], ["okf", "--check"]):
        failed = runner.invoke(app, args)
        assert failed.exit_code == 1, failed.output
        assert "error:" in failed.output and "lib.py" in failed.output


# --- review round 2: one verdict per doc, the presumption, detect-at-stake ----


@pytest.mark.parametrize("reject_first", [False, True], ids=["after", "before"])
def test_a_rejected_sibling_record_withholds_the_docs_verification(
    tmp_path: Path, monkeypatch, reject_first: bool
) -> None:
    """Bug repro (review r2, rev-r2/r1_sibling + r2_order): one `monitor
    --apply` run writes a HASH and a REGION record for the doc. alice
    accepted the HASH record and bob REJECTED the REGION record — the
    symbols table now on disk — yet the bundle kept `verified: human:alice`
    and `okf --check` said "in sync". A current dispute withholds the doc's
    verification in either order, and `--check` flags the old bundle."""
    # Feature: FEAT-OKF-001
    monkeypatch.chdir(tmp_path)
    hash_id = _managed_fixture(tmp_path)
    (region_id,) = _records_of(tmp_path, "REGION")
    if reject_first:
        _resolve(region_id, "rejected", "bob")
        _resolve(hash_id, "accepted", "alice")
    else:
        _resolve(hash_id, "accepted", "alice")
        verified = _verified(tmp_path)
        assert verified is not None and [e["by"] for e in verified] == ["human:alice"]
        _resolve(region_id, "rejected", "bob")
        stale = runner.invoke(app, ["okf", "--check"])
        assert stale.exit_code == 1, stale.output
        assert "STALE" in stale.output
    assert _verified(tmp_path) is None
    again = runner.invoke(app, ["okf"])  # K7: the vetoed bundle is stable
    assert "wrote 0 file(s)" in again.output, again.output
    assert runner.invoke(app, ["okf", "--check"]).exit_code == 0


def test_a_resolution_after_the_newest_record_is_presumed_to_review_the_doc(
    tmp_path: Path, monkeypatch
) -> None:
    """Honest scope (review r2, rev-r2/r3), pinned in ship shape. A record
    carries no run id and no applied flag, so the engine cannot tell WHICH
    same-surface record a human looked at: a verifying resolution recorded
    at or after the doc's newest record is PRESUMED to review the doc as it
    stands.
    Accepting the OLD dry-run proposal after `monitor --apply` healed the doc
    therefore verifies the heal. Here (mock backend) the proposal and the
    heal carry byte-identical fixes; with an LLM backend they need not —
    closing that needs a run id plus an applied marker on the record
    (additive K6, follow-up OKF-02). Flips deliberately when it lands."""
    # Feature: FEAT-OKF-001
    monkeypatch.chdir(tmp_path)
    _unhealed_fixture(tmp_path)
    runner.invoke(app, ["monitor"])  # a dry-run preview: proposals only
    (proposal,) = _records_of(tmp_path, "HASH")
    healed = runner.invoke(app, ["monitor", "--apply"])
    assert healed.exit_code == 0, healed.output
    by_id = {r.record_id: r for r in read_all(tmp_path / ".cdmon" / "review-log.jsonl")}
    heal = by_id[_records_of(tmp_path, "HASH")[-1]]
    assert heal.record_id != proposal
    assert by_id[proposal].fix == heal.fix  # what alice reviewed IS on disk here
    _resolve(proposal, "accepted", "alice")
    verified = _verified(tmp_path)
    assert verified is not None and [e["by"] for e in verified] == ["human:alice"]


def test_a_dry_run_preview_supersedes_until_a_current_record_is_re_resolved(
    tmp_path: Path, monkeypatch
) -> None:
    """Review r2 (rev-r2/r5): the corrected supersession rationale, pinned in
    ship shape. A dry `cdx monitor` preview at surface S2 writes records and
    touches no doc; after the code reverts to S1 the doc never moved and
    `cdx check` is clean, yet the preview still supersedes alice's accept (a
    safe under-claim). Accepting the preview records cannot restore it —
    their surface no longer exists — while re-accepting a record bound to the
    CURRENT surface, at or after the newest record, does."""
    # Feature: FEAT-OKF-001
    monkeypatch.chdir(tmp_path)
    record_id = _managed_fixture(tmp_path)
    _resolve(record_id, "accepted", "alice")
    assert _verified(tmp_path) is not None

    lib = tmp_path / "src" / "lib.py"
    lib.write_text(_LIB_S2, encoding="utf-8")
    before = {r.record_id for r in read_all(tmp_path / ".cdmon" / "review-log.jsonl")}
    runner.invoke(app, ["monitor"])  # preview at S2 — no doc is touched
    preview = [
        r.record_id
        for r in read_all(tmp_path / ".cdmon" / "review-log.jsonl")
        if r.record_id not in before
    ]
    assert preview
    lib.write_text(_LIB_S1, encoding="utf-8")
    assert runner.invoke(app, ["check"]).exit_code == 0  # the doc never moved
    assert _verified(tmp_path) is None

    for newer in preview:
        _resolve(newer, "accepted", "bob")
    assert _verified(tmp_path) is None  # S2 is not the doc's surface

    _resolve(record_id, "accepted", "alice")
    verified = _verified(tmp_path)
    assert verified is not None and [e["by"] for e in verified] == ["human:alice"]


@pytest.mark.parametrize(
    "resolve",
    [
        pytest.param((), id="review-log-without-resolutions"),
        pytest.param((("HASH", "rejected", "bob"),), id="rejected-only"),
        pytest.param((("HASH", "accepted"),), id="unnamed-accept"),
        pytest.param(
            (("HASH", "accepted", "alice"), ("REGION", "rejected", "bob")),
            id="accept-vetoed-by-a-sibling-reject",
        ),
    ],
)
def test_nothing_at_stake_means_no_drift_detection(
    tmp_path: Path, monkeypatch, resolve: tuple[tuple[str, ...], ...]
) -> None:
    """Bug repro (review r2, rev-r2/r4 + gap R2-16): once the resolutions log
    had ANY entry, `cdx okf` ran whole-config drift detection, so a log
    holding only a REJECT — which can verify nothing — made an unreadable
    code ref fail the export. Detection now runs only when some doc would
    carry `verified` if drift-free; with nothing at stake, `okf` and `okf
    --check` never extract code (the loud half is pinned by
    test_drift_is_detected_only_when_a_verification_is_at_stake)."""
    # Feature: FEAT-OKF-001
    monkeypatch.chdir(tmp_path)
    _managed_fixture(tmp_path)
    for kind, *outcome in resolve:
        (record_id,) = _records_of(tmp_path, kind)
        _resolve(record_id, *outcome)
    (tmp_path / "src" / "lib.py").unlink()
    exported = runner.invoke(app, ["okf"])
    assert exported.exit_code == 0, exported.output
    checked = runner.invoke(app, ["okf", "--check"])
    assert checked.exit_code == 0, checked.output


def test_okf_detects_drift_from_the_config_dir_when_root_differs(
    tmp_path: Path, monkeypatch
) -> None:
    """Review r2 gap R2-15: `cdx okf` detects drift the way `cdx check` does —
    from the CONFIG dir, whose `root` it resolves — never from the resolved
    repo root. With the config in a subdirectory and `root: ".."` (the
    shipped config/cdmon layout is `root: "../.."`) a bound accept
    verifies."""
    # Feature: FEAT-OKF-001
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cfg").mkdir()
    cfg = tmp_path / "cfg" / "cdmon.yaml"
    _unhealed_fixture(tmp_path).rename(cfg)
    cfg.write_text(
        cfg.read_text(encoding="utf-8").replace('root: "."', 'root: ".."'),
        encoding="utf-8",
    )
    healed = runner.invoke(app, ["monitor", "--apply", "--config", str(cfg)])
    assert healed.exit_code == 0, healed.output
    records = read_all(tmp_path / "cfg" / ".cdmon" / "review-log.jsonl")
    record_id = next(r.record_id for r in records if r.drift_kind == "HASH")
    resolved = runner.invoke(
        app,
        ["resolve", record_id, "--resolution", "accepted", "--by", "bob"]
        + ["--config", str(cfg)],
    )
    assert resolved.exit_code == 0, resolved.output
    exported = runner.invoke(app, ["okf", "--config", str(cfg)])
    assert exported.exit_code == 0, exported.output
    bundle_doc = tmp_path / "cfg" / ".cdmon" / "okf" / "docs" / "guide.md"
    front = yaml.safe_load(bundle_doc.read_text(encoding="utf-8").split("---\n")[1])
    assert [e["by"] for e in front.get("verified") or ()] == ["human:bob"]


@pytest.mark.parametrize(
    ("old", "new"),
    [
        pytest.param(
            "path: docs/guide.md", "path: nope/../docs/guide.md", id="unnormalized"
        ),
        pytest.param(
            "code_refs: [{path: src/lib.py}]\n",
            "code_refs: [{path: src/lib.py}]\n"
            "  - id: guide\n    path: docs/gone.md\n    audience: user-guide\n",
            id="duplicate-id",
        ),
    ],
)
def test_a_missing_doc_drift_on_the_id_blocks_its_verification(
    tmp_path: Path, monkeypatch, old: str, new: str
) -> None:
    """Review r2 gap R2-08: the MISSING_DOC arm of the drift gate is live. Two
    configs the single-file loader accepts render a doc that `cdx check`
    reports MISSING: a non-normalized path (`detect` tests the raw
    `root / spec.path`, the bundle normalizes it) and a duplicate doc id
    whose twin is missing. `cdx check` failing must keep the claim off."""
    # Feature: FEAT-OKF-001
    monkeypatch.chdir(tmp_path)
    record_id = _managed_fixture(tmp_path)
    cfg = tmp_path / "cdmon.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    _resolve(record_id, "accepted", "alice")
    checked = runner.invoke(app, ["check"])
    assert checked.exit_code == 1, checked.output
    assert "MISSING_DOC" in checked.output
    assert _verified(tmp_path) is None


def test_a_corrupt_review_log_stamp_is_loud_only_when_a_resolution_joins_it(
    tmp_path: Path, monkeypatch
) -> None:
    """K8 scope (review r2 gap R2-10), pinned at the CLI: `cdx okf` reads the
    review log's instants only when a resolution joins one of its records.
    A plain export with no resolutions never reads them; once one joins,
    every stamp is parsed (any record may supersede) and a corrupt one fails
    loudly, naming the field."""
    # Feature: FEAT-OKF-001
    monkeypatch.chdir(tmp_path)
    record_id = _managed_fixture(tmp_path)
    log = tmp_path / ".cdmon" / "review-log.jsonl"
    lines = []
    for line in log.read_text(encoding="utf-8").splitlines():
        payload = json.loads(line)
        if payload["drift_kind"] == "REGION":
            payload["detected_at"] = "yesterday"
        lines.append(json.dumps(payload))
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    quiet = runner.invoke(app, ["okf"])
    assert quiet.exit_code == 0, quiet.output

    _resolve(record_id, "accepted", "bob")
    for args in (["okf"], ["okf", "--check"]):
        loud = runner.invoke(app, args)
        assert loud.exit_code == 1, loud.output
        assert "error:" in loud.output and "detected_at" in loud.output


# --- review round 3: the code-surface limit covers record-less MACHINE writes -


def test_a_record_less_whole_doc_rewrite_keeps_the_claim(
    tmp_path: Path, monkeypatch
) -> None:
    """Honest scope (review r3), pinned in ship shape so the docstring cannot
    over-claim: `verified` is bound to the CODE surface, and only a review
    RECORD supersedes. ANY content change that moves no code surface and
    writes no ReviewRecord keeps the claim — not only a human prose edit.
    custodex's own `cdx new-doc --force` replaces the whole reviewed body
    with a TODO scaffold stamped at the SAME surface, writes no record, and
    `cdx check` stays clean, so alice's accept still reads as `verified`
    over text she never saw. Closing it needs a doc digest captured at
    resolve time (additive K6, follow-up OKF-03). Flips deliberately when it
    lands."""
    # Feature: FEAT-OKF-001
    monkeypatch.chdir(tmp_path)
    record_id = _managed_fixture(tmp_path)
    doc = tmp_path / "docs" / "guide.md"
    doc.write_text(
        doc.read_text(encoding="utf-8") + "\nAlice-reviewed prose: use TLS.\n",
        encoding="utf-8",
    )
    _resolve(record_id, "accepted", "alice")
    before = _verified(tmp_path)
    assert before is not None and [e["by"] for e in before] == ["human:alice"]
    log = tmp_path / ".cdmon" / "review-log.jsonl"
    records_before = len(read_all(log))

    rewritten = runner.invoke(app, ["new-doc", "guide", "--force"])
    assert rewritten.exit_code == 0, rewritten.output
    assert "Alice-reviewed prose" not in doc.read_text(encoding="utf-8")
    assert len(read_all(log)) == records_before  # no record: nothing supersedes
    assert runner.invoke(app, ["check"]).exit_code == 0  # same code surface
    assert _verified(tmp_path) == before


# --- review round 4: supersession by any verdict, per doc; the MCP limits -----


def test_a_later_escalation_supersedes_even_once_the_link_is_cleared(
    tmp_path: Path, monkeypatch
) -> None:
    """Mutation r4 gap N08 in ship shape: alice accepts guide's heal; an
    upstream api.md edit then escalates guide (a SUSPECT_LINK record, verdict
    ESCALATE, no fix). Clearing the link with `resolve --edge` writes no
    record and `cdx check` is clean, so the escalation stays guide's newest
    record and alice's accept — of text written before an upstream change she
    never saw — stays superseded. `verified` returns only once someone
    resolves the escalation itself."""
    # Feature: FEAT-OKF-001
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "src" / "lib.py").write_text(_LIB_S1, encoding="utf-8")
    region = "<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n"
    (tmp_path / "docs" / "api.md").write_text(f"# API\n\n{region}", encoding="utf-8")
    (tmp_path / "docs" / "guide.md").write_text(
        f"# Guide\n\n> How to connect.\n\n{region}", encoding="utf-8"
    )
    (tmp_path / "cdmon.yaml").write_text(_TWO_DOC_CONFIG, encoding="utf-8")
    assert runner.invoke(app, ["monitor", "--apply"]).exit_code == 0
    _resolve(_records_of(tmp_path, "HASH")[-1], "accepted", "alice")
    assert [e["by"] for e in _verified(tmp_path) or ()] == ["human:alice"]

    api = tmp_path / "docs" / "api.md"
    api.write_text(
        api.read_text(encoding="utf-8") + "\nPort 8443 now.\n", encoding="utf-8"
    )
    runner.invoke(app, ["monitor"])
    log = tmp_path / ".cdmon" / "review-log.jsonl"
    escalation = [
        r
        for r in read_all(log)
        if r.doc_id == "guide" and r.drift_kind == "SUSPECT_LINK"
    ][-1]
    assert escalation.verdict.value == "ESCALATE" and escalation.fix is None
    n_records = len(read_all(log))
    cleared = runner.invoke(app, ["resolve", "--edge", "guide", "api"])
    assert cleared.exit_code == 0, cleared.output
    assert len(read_all(log)) == n_records  # clearing the link writes no record
    assert runner.invoke(app, ["check"]).exit_code == 0
    assert _verified(tmp_path) is None  # alice never saw the upstream change

    _resolve(escalation.record_id, "accepted", "carol")
    assert [e["by"] for e in _verified(tmp_path) or ()] == ["human:carol"]


_SPLIT_CONFIG = (
    'version: "1.0.0"\n'
    'root: "."\n'
    "documents:\n"
    "  - id: api\n"
    "    path: docs/api.md\n"
    "    audience: eng-guide\n"
    "    region_keys: [symbols]\n"
    "    code_refs: [{path: src/api.py}]\n"
    "  - id: guide\n"
    "    path: docs/guide.md\n"
    "    audience: user-guide\n"
    "    region_keys: [symbols]\n"
    "    code_refs: [{path: src/lib.py}]\n"
)


def test_a_heal_of_another_doc_never_withdraws_this_docs_claim(
    tmp_path: Path, monkeypatch
) -> None:
    """Mutation r4 thin pin N09, in ship shape: supersession is PER DOC. Two
    docs over separate code; alice accepts guide's heal, then only api's code
    moves and `cdx monitor --apply` heals api — records dated after her
    accept, none for guide. guide keeps `verified: human:alice`; the same
    run's records supersede nothing outside api."""
    # Feature: FEAT-OKF-001
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "src" / "lib.py").write_text(_LIB_S1, encoding="utf-8")
    (tmp_path / "src" / "api.py").write_text(
        "def serve() -> None:\n    pass\n", encoding="utf-8"
    )
    region = "<!-- CDM:BEGIN symbols -->\n<!-- CDM:END symbols -->\n"
    (tmp_path / "docs" / "api.md").write_text(f"# API\n\n{region}", encoding="utf-8")
    (tmp_path / "docs" / "guide.md").write_text(
        f"# Guide\n\n> How to connect.\n\n{region}", encoding="utf-8"
    )
    (tmp_path / "cdmon.yaml").write_text(_SPLIT_CONFIG, encoding="utf-8")
    assert runner.invoke(app, ["monitor", "--apply"]).exit_code == 0
    _resolve(_records_of(tmp_path, "HASH")[-1], "accepted", "alice")
    assert [e["by"] for e in _verified(tmp_path) or ()] == ["human:alice"]

    log = tmp_path / ".cdmon" / "review-log.jsonl"
    before = len(read_all(log))
    (tmp_path / "src" / "api.py").write_text(
        "def serve(port: int = 8443) -> None:\n    pass\n", encoding="utf-8"
    )
    assert runner.invoke(app, ["monitor", "--apply"]).exit_code == 0
    later = read_all(log)[before:]
    assert later and {r.doc_id for r in later} == {"api"}
    assert runner.invoke(app, ["check"]).exit_code == 0
    assert [e["by"] for e in _verified(tmp_path) or ()] == ["human:alice"]


def _mcp_fixture(tmp_path: Path, monkeypatch) -> MonitorConfig:
    """The unhealed managed doc, loaded the way an MCP server loads it (the
    tools take the config + its dir; the CLI reads the same `.cdmon` logs)."""
    monkeypatch.chdir(tmp_path)
    return load_config(_unhealed_fixture(tmp_path))


def _human_resolve_at(
    monkeypatch, instant: str, record_id: str, resolution: str, by: str
) -> None:
    """A person's `cdx resolve --by`, stamped at ``instant`` through the CLI's
    own injectable clock seam (`cli._now`, K10) — so these pins stay about
    the record grain and the recorded instants, not the writer channel."""
    monkeypatch.setattr("custodex.cli._now", lambda: instant)
    _resolve(record_id, resolution, by)


def _facet_id(items: tuple[RemediationItem, ...], kind: str) -> str:
    """The record id MCP reports for the doc's ``kind`` facet."""
    return next(item.record_id for item in items if item.drift_kind == kind)


@pytest.mark.parametrize(
    ("steps", "expected"),
    [
        pytest.param(
            (("bob", "REGION", "rejected"), ("alice", "HASH", "accepted")),
            ["human:alice"],
            id="reject-then-accept",
        ),
        pytest.param(
            (("alice", "HASH", "accepted"), ("bob", "REGION", "rejected")),
            None,
            id="accept-then-reject",
        ),
    ],
)
def test_an_mcp_runs_simultaneous_drifts_on_a_doc_are_one_review(
    tmp_path: Path,
    monkeypatch,
    steps: tuple[tuple[str, str, str], ...],
    expected: list[str] | None,
) -> None:
    """Honest scope (review r4), pinned in ship shape: the record GRAIN. MCP
    `remediate_drift` stamps every record with the call-start instant, so a
    doc's HASH and REGION records from one call share ONE record_id (the id
    hashes doc, surface and stamp) — exactly the grain MCP documents
    ("resolving it covers all of that doc's simultaneous drifts"). They are
    then ONE review under last-write-wins, not two: the later resolution of
    that id, from either facet, corrects the earlier one. So the doc-level
    veto of a sibling REJECT holds "in either order" only for records with
    distinct ids, as `cdx monitor` writes them
    (test_a_rejected_sibling_record_withholds_the_docs_verification). A
    STANDING limit: MCP keeps its documented doc grain (the known limitation
    in .project/problems/MCP-02-record-id-grain.md). Flips only if that grain
    decision is revisited."""
    # Feature: FEAT-OKF-001
    cfg = _mcp_fixture(tmp_path, monkeypatch)
    healed = remediate_drift(
        cfg, tmp_path, repo_id="r", now="2026-09-27T10:00:00+00:00", apply=True
    )
    assert healed.applied_count >= 1
    ids = {kind: _facet_id(healed.items, kind) for kind in ("HASH", "REGION")}
    assert ids["HASH"] == ids["REGION"]  # one record id for the doc's facets
    for minute, (who, kind, outcome) in enumerate(steps):
        _human_resolve_at(
            monkeypatch, f"2026-09-27T11:0{minute}:00+00:00", ids[kind], outcome, who
        )
    assert runner.invoke(app, ["check"]).exit_code == 0
    verified = _verified(tmp_path)
    assert (None if verified is None else [e["by"] for e in verified]) == expected


def test_a_resolution_made_during_an_mcp_heal_vouches_for_its_write(
    tmp_path: Path, monkeypatch
) -> None:
    """Honest scope (review r4; made independent of the presumption in review
    r5), pinned in ship shape: RECORDED instants, not wall time — and only
    that. ONE MCP `remediate_drift(apply=True)` call starts at 10:02 and
    stamps every record with that instant. While the backend is still
    authoring the doc's `llm` region, alice reads the review log and accepts
    the call's OWN record at 10:05; only THEN does the call write the prose
    she never saw. Her review is at or after the call's 10:02 record, so it
    is current, and `verified: human:alice` vouches for a write made after
    she resolved. No older proposal is involved, so a run-id gate that
    closes only the presumption leaves this green. Flips deliberately when
    OKF-02's applied receipt (or OKF-03's resolve-time digest) lands."""
    # Feature: FEAT-OKF-001
    monkeypatch.chdir(tmp_path)
    cfg_path = _unhealed_fixture(
        tmp_path,
        _MANAGED_CONFIG.replace(
            "    region_keys: [symbols]\n",
            "    region_keys: [symbols, overview]\n    region_modes: {overview: llm}\n",
        ),
    )
    doc = tmp_path / "docs" / "guide.md"
    doc.write_text(
        doc.read_text(encoding="utf-8")
        + "\n<!-- CDM:BEGIN overview -->\n<!-- CDM:END overview -->\n",
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    log = tmp_path / ".cdmon" / "review-log.jsonl"
    seen: dict[str, str] = {}
    authored = MockBackend.propose

    def alice_resolves_mid_call(self: MockBackend, req: FixRequest) -> BackendResult:
        if req.drift.kind is DriftKind.REGION and req.drift.region_id == "overview":
            seen["record_id"] = read_all(log)[-1].record_id
            seen["doc"] = doc.read_text(encoding="utf-8")
            _human_resolve_at(
                monkeypatch,
                "2026-09-27T10:05:00+00:00",
                seen["record_id"],
                "accepted",
                "alice",
            )
        return authored(self, req)

    monkeypatch.setattr(MockBackend, "propose", alice_resolves_mid_call)
    healed = remediate_drift(
        cfg, tmp_path, repo_id="r", now="2026-09-27T10:02:00+00:00", apply=True
    )
    assert seen["record_id"] in {item.record_id for item in healed.items}
    assert any(i.region_id == "overview" and i.applied for i in healed.items)
    assert doc.read_text(encoding="utf-8") != seen["doc"]  # written after alice
    assert runner.invoke(app, ["check"]).exit_code == 0
    verified = _verified(tmp_path)
    assert verified == [{"by": "human:alice", "at": "2026-09-27T10:05:00+00:00"}]


def test_an_agent_supplied_resolver_still_reads_as_human(
    tmp_path: Path, monkeypatch
) -> None:
    """Honest scope (review r4), pinned in ship shape: the WRITER channel is
    not recorded. An MCP agent resolving through `resolve_drift` with
    `resolved_by="claude-agent"` is indistinguishable from a person at
    `cdx resolve --by`, so the bundle emits `human:claude-agent`. Flips
    deliberately when the `channel` field on ResolutionRecord lands
    (follow-up OKF-CHANNEL)."""
    # Feature: FEAT-OKF-001
    cfg = _mcp_fixture(tmp_path, monkeypatch)
    healed = remediate_drift(
        cfg, tmp_path, repo_id="r", now="2026-09-27T10:00:00+00:00", apply=True
    )
    resolve_drift(
        cfg,
        tmp_path,
        repo_id="r",
        record_id=_facet_id(healed.items, "HASH"),
        resolution="accepted",
        now="2026-09-27T10:30:00+00:00",
        resolved_by="claude-agent",
    )
    assert _verified(tmp_path) == [
        {"by": "human:claude-agent", "at": "2026-09-27T10:30:00+00:00"}
    ]


# --- review round 5: two ids on one path; the in-run window -------------------


def test_two_doc_ids_on_one_path_make_okf_refuse_loudly(
    tmp_path: Path, monkeypatch
) -> None:
    """Bug repro (review r5, rev-r5/f3): the config loader accepts two doc ids
    over ONE path, and `cdx monitor --apply` and `cdx check` pass. bob REJECTS
    `a`'s record and alice ACCEPTS `b`'s, yet `cdx okf` printed "wrote 2
    file(s)": `b`'s concept silently overwrote `a`'s, publishing
    `verified: human:alice` over bytes bob had rejected, with `docs/guide.md`
    listed twice in the root index. `cdx okf` and `cdx okf --check` now fail
    loudly (K8) naming both ids and the path, and no bundle is written."""
    # Feature: FEAT-OKF-001
    monkeypatch.chdir(tmp_path)
    spec = _MANAGED_CONFIG.split("  - id: guide\n", 1)[1]
    _unhealed_fixture(
        tmp_path,
        f'version: "1.0.0"\nroot: "."\ndocuments:\n  - id: a\n{spec}  - id: b\n{spec}',
    )
    assert runner.invoke(app, ["monitor", "--apply"]).exit_code == 0
    assert runner.invoke(app, ["check"]).exit_code == 0
    _resolve(_records_of(tmp_path, "HASH", "a")[-1], "rejected", "bob")
    _resolve(_records_of(tmp_path, "HASH", "b")[-1], "accepted", "alice")
    for args in (["okf"], ["okf", "--check"]):
        refused = runner.invoke(app, args)
        assert refused.exit_code == 1, refused.output
        assert "error:" in refused.output
        assert "'a'" in refused.output and "'b'" in refused.output
        assert "'docs/guide.md'" in refused.output
    assert not (tmp_path / ".cdmon" / "okf").exists()
