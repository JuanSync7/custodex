"""The hard-coded-values audit is frozen, owned and well-formed (HC-INVENTORY).

``.project/problems/HC-AUDIT.md`` lists every adopter-tunable literal that the
W0 sweep found in ``custodex/`` and ``templates/ci/``. Each row names the slice
that turns it into a config knob, or is a ``keep`` row with a reason.

Rows are frozen in batches (``FROZEN_BATCHES``). A batch pins its rows' cells by
a digest, so a frozen slice cannot quietly gain, lose or reword a row (critique
M7: a new row becomes a new XS slice, never scope growth), and names the commit
its rows' line numbers refer to. A frozen row's cited lines are checked at that
commit with ``git show``, so the code moving on (an owner slice landing and
removing the literal) never breaks the audit. The roster entries of the frozen
owners are pinned too (``FROZEN_ROSTER``): a status may only move to ``done``.

A row added after the last batch is a late row. It must be a ``keep`` row, or
the only row of a fresh ``HC-<TOPIC>`` owner with status ``new XS``, and its
cited lines are checked in the working tree. ``test_every_row_is_frozen`` then
asks for the batch that freezes it, so a late row never stays late.

The lint is pure functions (``audit_problems``, ``base_problems``). The real file
must give no problems; every known-bad edit must give the expected problem;
every legitimate edit must give none.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests._repo import REPO_ROOT

AUDIT_PATH = REPO_ROOT / ".project" / "problems" / "HC-AUDIT.md"


@dataclass(frozen=True)
class Batch:
    """Rows HC-``first``..HC-``last``, frozen at commit ``base``."""

    first: int
    last: int
    base: str
    rows_sha256: str


#: The freeze batches, in order. Changing one is a reviewed edit, visible in
#: this file's diff; ``test_every_row_is_frozen`` prints the next one to add.
FROZEN_BATCHES: tuple[Batch, ...] = (
    Batch(
        first=1,
        last=76,
        base="ddc368d",
        rows_sha256="8f64b8160676275dbba696cf1114ca6afde79978678cc9ef2b8e9fc49acc9fcc",
    ),
)

#: The status each owner of a frozen row had when it was frozen. A status may
#: stay or move to ``done``; nothing else.
FROZEN_ROSTER: Mapping[str, str] = {
    "HC-SWEEP-SERVER": "scheduled W36",
    "HC-SWEEP-ENGINE": "scheduled W35",
    "REC-RECIPE": "scheduled W6",
    "X-FORGE-CFG": "scheduled W12",
    "X-TPLROOT": "scheduled W13",
    "X-FORGE-SITES": "scheduled W16",
    "CI-OPEN": "scheduled W18",
    "CI-TEMPLATES": "scheduled W22",
    "FPW-CFG-1": "scheduled W23",
    "HC-FORGE": "scheduled W27",
    "HC-PROVENANCE": "scheduled W28",
    "REL-0.2.0": "scheduled W39",
    "DEFER-COVLANG": "deferred",
    "HC-FORGE-TIMEOUT": "new XS",
    "HC-BACKEND": "new XS",
    "HC-SINGLE-SOURCE": "new XS",
    "HC-PROMO-MIN": "new XS",
    "HC-ENTITIES": "new XS",
    "HC-WORKLIST-SEVERITY": "new XS",
    "HC-ISSUE-TEXT": "new XS",
    "HC-DOCS-ROOT": "new XS",
}
#: The frozen owners' roster notes, pinned by a digest (``_notes_digest``).
FROZEN_ROSTER_NOTES_SHA256 = (
    "bdfffa7bc95740dec519c9050e379e484f71f5c4d54bc77a2ddbe8504a8ebd9e"
)

#: Plan slice names a late row may never use as its owner.
RESERVED_OWNERS = frozenset(
    {
        "HC-INVENTORY",
        "HC-SCAFFOLD",
        "HC-FORGE",
        "HC-PROVENANCE",
        "HC-SWEEP-ENGINE",
        "HC-SWEEP-SERVER",
    }
)

#: The plan's row count per sweep slice (PLAN.md, HC-SWEEP-ENGINE/-SERVER).
PLAN_SWEEP_ROWS = {"HC-SWEEP-ENGINE": 3, "HC-SWEEP-SERVER": 2}

ROWS_HEADER = "| id | literal | sites | owner | knob or keep reason |"
OWNERS_HEADER = "| owner | status | note |"
LATE_STATUS = "new XS"
DONE_STATUS = "done"

_STATUS = re.compile(r"scheduled W[1-9][0-9]*|new XS|deferred|done")
_OWNER_NAME = re.compile(r"[A-Z][A-Z0-9]*(?:-[A-Z0-9][A-Z0-9.]*)*")
_LATE_OWNER = re.compile(r"HC-[A-Z0-9]+(?:-[A-Z0-9]+)*")
_ROW_LIKE = re.compile(r"^\s*\|?\s*HC-\d+\s*\|")
_ROW_ID = re.compile(r"HC-\d{3}")
_SITES_CELL = re.compile(r"`[^`]+`(?:, `[^`]+`)*")
_SITE = re.compile(r"(?P<path>[^:]+):(?P<lo>\d+)(?:-(?P<hi>\d+))?")
_IN_SCOPE = re.compile(
    r"custodex/(?:[a-z_][a-z0-9_]*/)*[a-z_][a-z0-9_]*\.py"
    r"|templates/ci/[A-Za-z0-9_.-]+\.yml"
)
#: A knob: a dotted YAML path (`learning.exemplar_top_n`) or a CI template
#: variable / field (`CDX_GIT_BOOTSTRAP`, `fetch-depth`).
_KNOB = re.compile(r"`[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*`")
_SEPARATOR = re.compile(r"\|(?:\s*:?-{3,}:?\s*\|)+")
_TICKED = re.compile(r"`([^`]+)`")
_MIN_KEEP_REASON = 20

#: Reads ``path`` (repo-relative) as lines, or None when it does not exist.
Reader = Callable[[str], "list[str] | None"]
#: Reads ``path`` at commit ``base`` as lines, or None when it does not exist.
BaseReader = Callable[[str, str], "list[str] | None"]


@dataclass(frozen=True)
class Row:
    """One parsed table row of the audit."""

    lineno: int
    cells: tuple[str, ...]

    @property
    def id(self) -> str:
        return self.cells[0]

    @property
    def number(self) -> int:
        return int(self.id.split("-")[1])

    @property
    def owner(self) -> str:
        return self.cells[3]


@dataclass(frozen=True)
class Freeze:
    """The edit that freezes the late rows: a batch and the roster pins."""

    batch: Batch
    roster: dict[str, str]
    notes_sha256: str


def _cells(line: str) -> tuple[str, ...]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return tuple(cell.strip() for cell in body.split("|"))


def _norm(cell: str) -> str:
    return " ".join(cell.split())


def _table(
    lines: list[tuple[int, str]], header: str, width: int, name: str
) -> tuple[list[tuple[int, tuple[str, ...]]], list[str]]:
    """Parse one section that must be exactly one table; return its body rows."""
    problems: list[str] = []
    body: list[tuple[int, tuple[str, ...]]] = []
    content = [(n, line) for n, line in lines if line.strip()]
    if len(content) < 2 or content[0][1] != header:
        return body, [f"## {name}: the table must start with `{header}`"]
    if not _SEPARATOR.fullmatch(content[1][1]):
        problems.append(f"## {name}: line {content[1][0]} is not the table separator")
    last = content[-1][0]
    first = content[0][0]
    for n, line in lines:
        if first < n < last and not line.strip():
            problems.append(
                f"## {name}: a blank line at {n} splits the table; rows after it "
                "would render outside the table"
            )
    for n, line in content[2:]:
        if not line.startswith("|"):
            problems.append(
                f"## {name}: line {n} must start at column 0 with `|` "
                f"(got {line[:40]!r})"
            )
            continue
        cells = _cells(line)
        if len(cells) != width:
            problems.append(f"## {name}: line {n} has {len(cells)} cells, not {width}")
            continue
        body.append((n, cells))
    return body, problems


def _parse_sites(cell: str) -> tuple[list[tuple[str, int, int]], list[str]]:
    if not _SITES_CELL.fullmatch(cell):
        return [], [f"malformed site list {cell!r}; use `path:N` or `path:N-M`"]
    sites: list[tuple[str, int, int]] = []
    problems: list[str] = []
    for ref in _TICKED.findall(cell):
        m = _SITE.fullmatch(ref)
        if m is None:
            problems.append(f"malformed site `{ref}`; use `path:N` or `path:N-M`")
            continue
        path, lo = m.group("path"), int(m.group("lo"))
        hi = int(m.group("hi")) if m.group("hi") else lo
        if not _IN_SCOPE.fullmatch(path):
            problems.append(
                f"site `{ref}` is out of scope (custodex/**/*.py, templates/ci/*.yml)"
            )
        if lo < 1:
            problems.append(f"site `{ref}`: line numbers start at 1")
        if m.group("hi") and hi <= lo:
            problems.append(f"site `{ref}`: a range must run from low to high")
        if (path, lo, hi) in sites:
            problems.append(f"site `{ref}` is cited twice")
        sites.append((path, lo, hi))
    return sites, problems


def _digest(rows: list[Row]) -> str:
    norm = "\n".join("\x1f".join(_norm(cell) for cell in row.cells) for row in rows)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _notes_digest(notes: Mapping[str, str]) -> str:
    norm = "\n".join(f"{owner}\x1f{_norm(notes[owner])}" for owner in sorted(notes))
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _sections(
    text: str,
) -> tuple[list[tuple[int, str]], dict[str, list[tuple[int, str]]], list[str]]:
    header: list[tuple[int, str]] = []
    sections: dict[str, list[tuple[int, str]]] = {}
    order: list[str] = []
    current: list[tuple[int, str]] | None = None
    for n, line in enumerate(text.splitlines(), start=1):
        if line.startswith("## "):
            name = line[3:].strip()
            order.append(name)
            current = sections.setdefault(name, [])
            continue
        (header if current is None else current).append((n, line))
    return header, sections, order


def parse_rows(text: str) -> list[Row]:
    """The well-formed rows of the ``## Rows`` table."""
    _, sections, _ = _sections(text)
    body, _ = _table(sections.get("Rows", []), ROWS_HEADER, 5, "Rows")
    return [Row(n, cells) for n, cells in body if _ROW_ID.fullmatch(cells[0])]


def parse_roster(text: str) -> dict[str, tuple[str, str]]:
    """owner -> (status, note) from the ``## Owners`` table."""
    _, sections, _ = _sections(text)
    body, _ = _table(sections.get("Owners", []), OWNERS_HEADER, 3, "Owners")
    return {owner: (status, note) for _, (owner, status, note) in body}


def _batch_of(row: Row, batches: tuple[Batch, ...]) -> Batch | None:
    return next((b for b in batches if b.first <= row.number <= b.last), None)


def site_problems(row: Row, read: Reader, where: str) -> list[str]:
    """Each cited site must exist and hold one of the row's backticked spans."""
    sites, malformed = _parse_sites(row.cells[2])
    if malformed:
        return []  # reported by the lint
    spans = _TICKED.findall(row.cells[1])
    if not spans:
        return ["its literal must quote the code in backticks"]
    problems: list[str] = []
    for path, lo, hi in sites:
        lines = read(path)
        if lines is None:
            problems.append(f"cited file {path} does not exist {where}")
            continue
        if hi > len(lines):
            problems.append(
                f"site {path}:{hi} is past the end ({len(lines)} lines {where})"
            )
            continue
        if not any(span in line for span in spans for line in lines[lo - 1 : hi]):
            problems.append(
                f"no span of its literal is found at {path}:{lo}-{hi} {where}"
            )
    return problems


def _working_tree(repo_root: Path) -> Reader:
    def read(path: str) -> list[str] | None:
        file = repo_root / path
        return file.read_text(encoding="utf-8").splitlines() if file.is_file() else None

    return read


def audit_problems(
    text: str,
    repo_root: Path,
    *,
    batches: tuple[Batch, ...] = FROZEN_BATCHES,
    roster_pin: Mapping[str, str] = FROZEN_ROSTER,
    notes_sha256: str = FROZEN_ROSTER_NOTES_SHA256,
) -> list[str]:
    """Every problem with the audit text, or ``[]``. Pure apart from reading the
    working-tree files that late rows cite; frozen rows are checked at their
    base by ``base_problems``."""
    problems: list[str] = []
    if "<!--" in text:
        problems.append("the audit must not contain an HTML comment (it hides rows)")
    header, sections, order = _sections(text)
    for name in ("Owners", "Rows"):
        if order.count(name) != 1:
            problems.append(f"the audit needs exactly one `## {name}` section")
    if "Rows" not in order:
        return problems
    if "Owners" in order and order.index("Rows") < order.index("Owners"):
        problems.append("`## Owners` must come before `## Rows`")
    sweep_base = batches[0].base if batches else ""
    if sweep_base not in "\n".join(line for _, line in header):
        problems.append(f"the header must name the sweep's base commit {sweep_base}")

    for name, lines in sections.items():
        if name == "Rows":
            continue
        for n, line in lines:
            if _ROW_LIKE.match(line):
                problems.append(f"line {n} is a row outside ## Rows (in ## {name})")
    for n, line in header:
        if _ROW_LIKE.match(line):
            problems.append(f"line {n} is a row outside ## Rows (in the header)")

    owner_body, owner_problems = _table(
        sections.get("Owners", []), OWNERS_HEADER, 3, "Owners"
    )
    row_body, row_problems = _table(sections.get("Rows", []), ROWS_HEADER, 5, "Rows")
    problems += owner_problems + row_problems

    rows: list[Row] = []
    for n, cells in row_body:
        if not _ROW_ID.fullmatch(cells[0]):
            problems.append(f"line {n} is not a row: malformed id {cells[0]!r}")
            continue
        rows.append(Row(n, cells))
    if not rows:
        return [*problems, "the audit has no rows"]

    expected = [f"HC-{i:03d}" for i in range(1, len(rows) + 1)]
    ids = [row.id for row in rows]
    dupes = sorted(i for i, c in Counter(ids).items() if c > 1)
    if dupes:
        problems.append(f"duplicate row ids {dupes}")
    if ids != expected:
        problems.append("row ids must run HC-001, HC-002, ... in order with no gap")

    roster: dict[str, str] = {}
    notes: dict[str, str] = {}
    for n, (owner, status, note) in owner_body:
        if owner in roster:
            problems.append(f"owner {owner} is listed twice on the roster")
        if not _OWNER_NAME.fullmatch(owner):
            problems.append(f"line {n}: {owner!r} is not a valid roster owner name")
        if not _STATUS.fullmatch(status):
            problems.append(
                f"line {n}: status {status!r} must be one of `scheduled W<n>`, "
                "`new XS`, `deferred`, `done`"
            )
        roster[owner] = status
        notes[owner] = note

    owned = Counter(row.owner for row in rows)
    for owner in roster:
        if owned[owner] == 0:
            problems.append(f"roster owner {owner} owns no row")

    for row in rows:
        _, literal, sites_cell, owner, reason = row.cells
        tag = f"{row.id} (line {row.lineno})"
        if not literal:
            problems.append(f"{tag}: the literal cell is empty")
        problems += [f"{tag}: {p}" for p in _parse_sites(sites_cell)[1]]
        if owner == "keep":
            if len(reason) < _MIN_KEEP_REASON:
                problems.append(f"{tag}: a keep row needs a keep reason")
        else:
            if owner not in roster:
                problems.append(
                    f"{tag}: owner {owner!r} is not on the ## Owners roster"
                )
            if not _KNOB.search(reason):
                problems.append(f"{tag}: an owned row must name its knob in backticks")

    problems += _batch_problems(rows, batches)
    frozen = [row for row in rows if _batch_of(row, batches) is not None]
    frozen_owners = {row.owner for row in frozen} - {"keep"}
    problems += _roster_pin_problems(
        roster, notes, frozen_owners, roster_pin, notes_sha256
    )

    read = _working_tree(repo_root)
    for row in rows:
        if _batch_of(row, batches) is not None:
            continue
        tag = f"{row.id} (line {row.lineno})"
        problems += [f"{tag}: {p}" for p in site_problems(row, read, "here")]
        if row.owner == "keep":
            continue
        if not _LATE_OWNER.fullmatch(row.owner):
            problems.append(f"{tag}: a late owner must be named `HC-<TOPIC>`")
        if row.owner in frozen_owners:
            problems.append(
                f"{tag}: {row.owner} already owns frozen rows; a new row is a new "
                "XS slice, never scope growth"
            )
        if row.owner in RESERVED_OWNERS:
            problems.append(f"{tag}: {row.owner} is a reserved plan slice name")
        if owned[row.owner] != 1:
            problems.append(f"{tag}: a late owner must own exactly one row")
        status = roster.get(row.owner, LATE_STATUS)
        if status != LATE_STATUS:
            problems.append(
                f"{tag}: a late owner's roster status must be `{LATE_STATUS}` "
                f"(got {status!r})"
            )
    return problems


def _batch_problems(rows: list[Row], batches: tuple[Batch, ...]) -> list[str]:
    problems: list[str] = []
    expected_first = 1
    for batch in batches:
        name = f"frozen rows HC-{batch.first:03d}..HC-{batch.last:03d}"
        if batch.first != expected_first or batch.last < batch.first:
            problems.append(
                f"{name}: batches must be contiguous from HC-001 "
                f"(this one should start at HC-{expected_first:03d})"
            )
        expected_first = batch.last + 1
        members = [r for r in rows if batch.first <= r.number <= batch.last]
        if [r.number for r in members] != list(range(batch.first, batch.last + 1)):
            problems.append(f"{name} are missing rows")
        elif _digest(members) != batch.rows_sha256:
            problems.append(
                f"{name} changed; a frozen row changes only with a reviewed "
                "update of its batch digest"
            )
    return problems


def _roster_pin_problems(
    roster: Mapping[str, str],
    notes: Mapping[str, str],
    frozen_owners: set[str],
    roster_pin: Mapping[str, str],
    notes_sha256: str,
) -> list[str]:
    problems: list[str] = []
    if frozen_owners != set(roster_pin):
        problems.append(
            "the owners of frozen rows and FROZEN_ROSTER disagree: "
            f"{sorted(frozen_owners ^ set(roster_pin))}"
        )
    for owner, pinned in sorted(roster_pin.items()):
        status = roster.get(owner)
        if status is None:
            problems.append(f"frozen roster owner {owner} is missing from ## Owners")
        elif status not in (pinned, DONE_STATUS):
            problems.append(
                f"frozen roster owner {owner}: status {status!r} is pinned to "
                f"{pinned!r} (it may only move to `{DONE_STATUS}`)"
            )
    if set(roster_pin) <= set(notes) and (
        _notes_digest({o: notes[o] for o in roster_pin}) != notes_sha256
    ):
        problems.append(
            "frozen roster notes changed; a frozen note changes only with a "
            "reviewed update of FROZEN_ROSTER_NOTES_SHA256"
        )
    return problems


def base_problems(
    text: str, batches: tuple[Batch, ...], read_at: BaseReader
) -> list[str]:
    """Every frozen row's cited sites hold its literal at its batch's base."""
    problems: list[str] = []
    for row in parse_rows(text):
        batch = _batch_of(row, batches)
        if batch is None:
            continue
        base = batch.base

        def read(path: str, base: str = base) -> list[str] | None:
            return read_at(base, path)

        problems += [
            f"{row.id} (line {row.lineno}): {p}"
            for p in site_problems(row, read, f"at {base}")
        ]
    return problems


def next_freeze(
    text: str,
    head: str,
    batches: tuple[Batch, ...] = FROZEN_BATCHES,
    roster_pin: Mapping[str, str] = FROZEN_ROSTER,
) -> Freeze | None:
    """None when every row is frozen, else the edit that freezes the late rows
    at ``head`` (the commit whose lines they cite)."""
    late = [row for row in parse_rows(text) if _batch_of(row, batches) is None]
    if not late:
        return None
    first = batches[-1].last + 1 if batches else 1
    roster = parse_roster(text)
    owners = sorted({r.owner for r in late} - {"keep"} - set(roster_pin))
    pin = {o: roster[o][0] for o in owners if o in roster}
    notes = {o: roster[o][1] for o in [*roster_pin, *pin] if o in roster}
    return Freeze(
        Batch(first, late[-1].number, head, _digest(late)), pin, _notes_digest(notes)
    )


# ---------------------------------------------------------------------------
# git access for the base check
# ---------------------------------------------------------------------------


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def git_skip_reason() -> str | None:
    """Why the base check cannot run here, or None when it must run."""
    if shutil.which("git") is None:
        return "git is not installed (the CI image has none)"
    probe = _git("rev-parse", "--is-shallow-repository")
    if probe.returncode != 0:
        return "not a git checkout"
    if probe.stdout.strip() != "false":
        return "a shallow clone has no base commits"
    return None


def git_read_at(base: str, path: str) -> list[str] | None:
    """``path`` at commit ``base``; None when absent there; loud when the base
    commit itself is missing from a full clone (K8)."""
    if _git("cat-file", "-e", f"{base}^{{commit}}").returncode != 0:
        raise LookupError(f"base commit {base} is not in this clone")
    shown = _git("show", f"{base}:{path}")
    return shown.stdout.splitlines() if shown.returncode == 0 else None


def _head() -> str:
    if git_skip_reason() is not None:
        return "<HEAD sha>"
    return _git("rev-parse", "--short", "HEAD").stdout.strip()


# ---------------------------------------------------------------------------
# The real file
# ---------------------------------------------------------------------------


def _audit_text() -> str:
    return AUDIT_PATH.read_text(encoding="utf-8")


def test_the_audit_passes_its_lint() -> None:
    """The checked-in audit has no problems and holds every frozen row."""
    text = _audit_text()
    assert audit_problems(text, REPO_ROOT) == []
    assert len(parse_rows(text)) >= FROZEN_BATCHES[-1].last > 0


def test_every_row_is_frozen() -> None:
    """A late row is frozen in the change that adds it; the failure prints the
    batch and roster pins to add."""
    freeze = next_freeze(_audit_text(), _head())
    assert freeze is None, (
        f"append {freeze.batch!r} to FROZEN_BATCHES, add {freeze.roster!r} to "
        f"FROZEN_ROSTER and set FROZEN_ROSTER_NOTES_SHA256 = "
        f"{freeze.notes_sha256!r}"
    )


def test_frozen_rows_hold_their_literal_at_their_base() -> None:
    """Every cited site of every frozen row holds a span of its literal at the
    batch's base commit (read with git show; skipped visibly without history)."""
    reason = git_skip_reason()
    if reason is not None:
        pytest.skip(f"the base check needs a full git clone: {reason}")
    assert base_problems(_audit_text(), FROZEN_BATCHES, git_read_at) == []


def test_the_base_check_runs_in_a_full_clone() -> None:
    """Guard on the skip: in a full clone with git, the base check must run, so
    an inverted probe cannot skip it everywhere."""
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    shallow = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--is-shallow-repository"],
        capture_output=True,
        text=True,
        check=False,
    )
    if shallow.returncode != 0 or shallow.stdout.strip() != "false":
        pytest.skip("not a full git clone")
    assert git_skip_reason() is None
    lines = git_read_at(FROZEN_BATCHES[0].base, "custodex/errors.py")
    assert lines is not None
    assert any("class CodeDocMonitorError" in line for line in lines)
    assert git_read_at(FROZEN_BATCHES[0].base, "custodex/no_such_module.py") is None
    with pytest.raises(LookupError, match="not in this clone"):
        git_read_at("0" * 40, "custodex/errors.py")


def test_the_skip_names_its_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    """No git, no checkout and a shallow clone each skip with their own reason."""
    module = "tests.smoke.test_hc_audit"
    shallow = subprocess.CompletedProcess(args=[], returncode=0, stdout="true\n")
    monkeypatch.setattr(f"{module}._git", lambda *a: shallow)
    assert git_skip_reason() == "a shallow clone has no base commits"
    broken = subprocess.CompletedProcess(args=[], returncode=128, stdout="")
    monkeypatch.setattr(f"{module}._git", lambda *a: broken)
    assert git_skip_reason() == "not a git checkout"
    assert _head() == "<HEAD sha>"
    monkeypatch.setattr(f"{module}.shutil.which", lambda name: None)
    assert git_skip_reason() == "git is not installed (the CI image has none)"


def test_sweep_slices_own_exactly_the_plan_rows() -> None:
    """HC-SWEEP-ENGINE owns 3 rows and HC-SWEEP-SERVER owns 2, as the plan says."""
    owned = Counter(row.owner for row in parse_rows(_audit_text()))
    assert {name: owned[name] for name in PLAN_SWEEP_ROWS} == PLAN_SWEEP_ROWS


#: The slice entry's seed rows: (site at the base, the owner the plan gives it).
SEEDS: tuple[tuple[str, str], ...] = (
    ("custodex/workers.py:85", "HC-SWEEP-SERVER"),
    ("custodex/registry.py:111", "HC-SWEEP-SERVER"),
    ("custodex/sinks.py:148", "HC-SWEEP-SERVER"),
    ("custodex/backends.py:68", "REC-RECIPE"),
    ("custodex/agent/runtime.py:36", "REC-RECIPE"),
    ("custodex/monitor.py:53", "HC-SWEEP-ENGINE"),
    ("custodex/similar.py:36", "HC-SWEEP-ENGINE"),
    ("custodex/issues.py:43", "HC-SWEEP-ENGINE"),
    ("custodex/pr.py:122", "HC-FORGE"),
    ("custodex/pr.py:141", "HC-FORGE"),
    ("custodex/pr.py:304", "HC-FORGE"),
    ("custodex/pr.py:324", "HC-FORGE"),
    ("custodex/pr.py:430", "HC-FORGE"),
    ("custodex/pr.py:462", "HC-FORGE"),
    ("custodex/sinks.py:296", "HC-PROVENANCE"),
    ("custodex/registry.py:234", "HC-PROVENANCE"),
    ("custodex/cli.py:628", "HC-PROVENANCE"),
    ("custodex/cli.py:1507", "HC-PROVENANCE"),
    ("custodex/cli.py:2542", "HC-PROVENANCE"),
    ("custodex/extract.py:466", "FPW-CFG-1"),
    ("custodex/extract.py:982", "FPW-CFG-1"),
    ("custodex/server/app.py:1725", "X-FORGE-SITES"),
    ("custodex/server/app.py:1841", "X-FORGE-SITES"),
    ("custodex/server/app.py:2067", "X-FORGE-SITES"),
    ("custodex/server/app.py:2183", "X-FORGE-SITES"),
    ("custodex/server/standalone.py:48", "X-FORGE-SITES"),
    ("custodex/configsync.py:388", "X-FORGE-SITES"),
    ("custodex/gitfetch.py:71", "X-FORGE-SITES"),
    ("custodex/pr.py:50", "X-FORGE-SITES"),
    ("custodex/pr.py:445", "X-FORGE-SITES"),
    ("custodex/cli.py:799", "X-FORGE-SITES"),
    ("custodex/cli.py:956", "X-FORGE-SITES"),
    ("custodex/config.py:1278", "X-TPLROOT"),
    ("custodex/generate.py:323", "X-TPLROOT"),
    ("custodex/monitor.py:252", "X-TPLROOT"),
    ("custodex/templates_v2.py:287", "X-TPLROOT"),
    ("custodex/server/app.py:748", "X-TPLROOT"),
    ("templates/ci/gitlab-ci.adopter.yml:78", "CI-TEMPLATES"),
    ("templates/ci/github-actions.adopter.yml:78", "CI-TEMPLATES"),
    ("templates/ci/gitlab-ci.adopter.yml:70", "CI-TEMPLATES"),
    ("templates/ci/github-actions.adopter.yml:58", "CI-TEMPLATES"),
    ("templates/ci/gitlab-ci.adopter.yml:43", "REL-0.2.0"),
    ("templates/ci/github-actions.adopter.yml:43", "REL-0.2.0"),
    ("custodex/pr.py:447", "X-FORGE-CFG"),
    ("custodex/cli.py:847", "CI-OPEN"),
)


def test_every_seed_row_is_inventoried_under_its_plan_owner() -> None:
    """Each seed site from the slice entry is cited by a frozen row of its owner."""
    rows = [r for r in parse_rows(_audit_text()) if _batch_of(r, FROZEN_BATCHES[:1])]
    missing: list[str] = []
    for seed, owner in SEEDS:
        path, line = seed.rsplit(":", 1)
        hits = [
            row.owner
            for row in rows
            for p, lo, hi in _parse_sites(row.cells[2])[0]
            if p == path and lo <= int(line) <= hi
        ]
        if owner not in hits:
            missing.append(f"{seed} -> {owner} (cited by {hits or 'no row'})")
    assert missing == []


def test_every_frozen_cell_is_pinned() -> None:
    """Changing any single cell of any frozen row fails the lint."""
    text = _audit_text()
    rows = [r for r in parse_rows(text) if _batch_of(r, FROZEN_BATCHES)]
    assert len(rows) == FROZEN_BATCHES[-1].last
    lines = text.splitlines()
    unpinned: list[str] = []
    for row in rows:
        for idx in range(1, 5):
            cells = list(row.cells)
            cells[idx] = cells[idx] + " x"
            edited = list(lines)
            edited[row.lineno - 1] = "| " + " | ".join(cells) + " |"
            found = audit_problems("\n".join(edited) + "\n", REPO_ROOT)
            if not any("frozen rows" in p for p in found):
                unpinned.append(f"{row.id} cell {idx}")
    assert unpinned == []


# ---------------------------------------------------------------------------
# Edits: known-bad must be caught, legitimate must pass
# ---------------------------------------------------------------------------


def _lines(text: str) -> list[str]:
    return text.splitlines()


def _join(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"


def _row_index(lines: list[str], row_id: str) -> int:
    for i, line in enumerate(lines):
        if line.startswith(f"| {row_id} |"):
            return i
    raise AssertionError(f"{row_id} not in the audit")


def _last_index(lines: list[str], prefix_re: str, section: str) -> int:
    inside = False
    last = -1
    for i, line in enumerate(lines):
        if line.startswith("## "):
            inside = line[3:].strip() == section
            continue
        if inside and re.match(prefix_re, line):
            last = i
    assert last >= 0
    return last


def _next_number(text: str) -> int:
    return max(row.number for row in parse_rows(text)) + 1


def _row(number: int, literal: str, sites: str, owner: str, reason: str) -> str:
    return f"| HC-{number:03d} | {literal} | {sites} | {owner} | {reason} |"


_LIVE_FILE = "custodex/errors.py"


def _live_line() -> int:
    """The line of a literal in the working tree, so the controls never go stale."""
    text = (REPO_ROOT / _LIVE_FILE).read_text(encoding="utf-8").splitlines()
    for n, line in enumerate(text, start=1):
        if "class CodeDocMonitorError" in line:
            return n
    raise AssertionError("errors.py has no CodeDocMonitorError")  # pragma: no cover


def _live_len() -> int:
    return len((REPO_ROOT / _LIVE_FILE).read_text(encoding="utf-8").splitlines())


def _live_literal() -> tuple[str, str]:
    return f"`{_LIVE_FILE}:{_live_line()}`", "`CodeDocMonitorError`"


def add_owner(text: str, owner: str, status: str = "new XS") -> str:
    lines = _lines(text)
    at = _last_index(lines, r"\| [A-Z]", "Owners")
    lines.insert(at + 1, f"| {owner} | {status} | a late slice |")
    return _join(lines)


def add_row(text: str, row: str, *, prefix: str = "") -> str:
    lines = _lines(text)
    at = _last_index(lines, r"\| HC-\d", "Rows")
    lines.insert(at + 1, prefix + row)
    return _join(lines)


def _late(text: str, owner: str, number: int | None, kw: dict[str, str]) -> str:
    site, literal = _live_literal()
    return _row(
        number if number is not None else _next_number(text),
        kw.get("literal", literal),
        kw.get("sites", site),
        owner,
        kw.get("reason", "`errors.late_knob`"),
    )


def late_row(text: str, owner: str, *, number: int | None = None, **kw: str) -> str:
    return _late(text, owner, number, kw)


def add_late(text: str, owner: str, status: str = "new XS", **kw: str) -> str:
    return add_row(add_owner(text, owner, status), _late(text, owner, None, kw))


def set_cell(text: str, row_id: str, idx: int, value: str) -> str:
    lines = _lines(text)
    i = _row_index(lines, row_id)
    cells = list(_cells(lines[i]))
    cells[idx] = value
    lines[i] = "| " + " | ".join(cells) + " |"
    return _join(lines)


def first_row_of(text: str, owner: str) -> str:
    return next(row.id for row in parse_rows(text) if row.owner == owner)


def _set_roster(text: str, owner: str, *, status: str = "", note: str = "") -> str:
    lines = _lines(text)
    for i, line in enumerate(lines):
        if line.startswith(f"| {owner} |"):
            _, old_status, old_note = _cells(line)
            lines[i] = f"| {owner} | {status or old_status} | {note or old_note} |"
            return _join(lines)
    raise AssertionError(f"{owner} not on the roster")  # pragma: no cover


def _drop_roster(text: str, owner: str) -> str:
    return _join([ln for ln in _lines(text) if not ln.startswith(f"| {owner} |")])


def _first_roster_owner(text: str) -> str:
    return next(iter(parse_roster(text)))


def _two_late_rows(t: str) -> str:
    t = add_late(t, "HC-LATE-ONE")
    return add_late(t, "HC-LATE-TWO")


def _second_row_for_late_owner(t: str) -> str:
    t = add_late(t, "HC-LATE")
    return add_row(t, late_row(t, "HC-LATE"))


def _blank_in_table(t: str) -> str:
    lines = _lines(t)
    lines.insert(_row_index(lines, "HC-002"), "")
    return _join(lines)


def _blank_after_header(t: str) -> str:
    lines = _lines(t)
    lines.insert(lines.index(ROWS_HEADER) + 1, "")
    return _join(lines)


def _stray_pipe(t: str) -> str:
    return add_row(t, "| not | a | row | at | all |")


def _no_rows(t: str) -> str:
    return _join([line for line in _lines(t) if not line.startswith("| HC-")])


def _row_after_rows(t: str) -> str:
    keep = late_row(t, "keep", reason="a keep reason long enough here")
    return t + "\n" + keep + "\n"


def _row_in_header(t: str) -> str:
    lines = _lines(t)
    lines.insert(1, late_row(t, "keep", reason="a keep reason long enough here"))
    return _join(lines)


def _drop_last_frozen(t: str) -> str:
    lines = _lines(t)
    del lines[_row_index(lines, f"HC-{FROZEN_BATCHES[-1].last:03d}")]
    return _join(lines)


def _dup_id(t: str) -> str:
    lines = _lines(t)
    lines.insert(_row_index(lines, "HC-002"), lines[_row_index(lines, "HC-001")])
    return _join(lines)


def _swap_sections(t: str) -> str:
    return t.replace("## Owners", "## Roster", 1)


def _rows_before_owners(t: str) -> str:
    owners = t.index("## Owners")
    rows = t.index("## Rows")
    tail = t.index("## Changing this file")
    return t[:owners] + t[rows:tail] + t[owners:rows] + t[tail:]


def _break_rows_separator(t: str) -> str:
    return t.replace("| --- | --- | --- | --- | --- |", "| -- | -- | -- | -- | -- |", 1)


KNOWN_BAD: dict[str, tuple[Callable[[str], str], str]] = {
    # The frozen rows (critique M7, prior A1/A2/P1-P4)
    "frozen-literal-reworded": (
        lambda t: set_cell(t, "HC-001", 1, "a harmless literal"),
        "frozen rows",
    ),
    "frozen-site-repointed": (
        lambda t: set_cell(t, first_row_of(t, "keep"), 2, "`custodex/pr.py:1`"),
        "frozen rows",
    ),
    "frozen-owner-moved": (
        lambda t: set_cell(t, first_row_of(t, "HC-SWEEP-ENGINE"), 3, "HC-SWEEP-SERVER"),
        "frozen rows",
    ),
    "frozen-knob-grows": (
        lambda t: set_cell(
            t,
            first_row_of(t, "HC-SWEEP-ENGINE"),
            4,
            "`learning.exemplar_top_n` plus `learning.min_score`",
        ),
        "frozen rows",
    ),
    "frozen-row-deleted": (_drop_last_frozen, "are missing rows"),
    "html-comment": (lambda t: t.replace("## Rows", "<!-- x -->\n## Rows", 1), "HTML"),
    "header-loses-base": (
        lambda t: t.replace(FROZEN_BATCHES[0].base, "BASE"),
        "base commit",
    ),
    "no-owners-section": (_swap_sections, "`## Owners`"),
    "rows-before-owners": (_rows_before_owners, "`## Owners` must come before"),
    "no-rows": (_no_rows, "no rows"),
    # The frozen roster
    "frozen-status-rescheduled": (
        lambda t: _set_roster(t, "HC-SWEEP-ENGINE", status="scheduled W40"),
        "is pinned to 'scheduled W35'",
    ),
    "frozen-status-deferred": (
        lambda t: _set_roster(t, _first_roster_owner(t), status="deferred"),
        "is pinned to",
    ),
    "frozen-note-reworded": (
        lambda t: _set_roster(t, "HC-SWEEP-ENGINE", note="anything the slice wants"),
        "frozen roster notes changed",
    ),
    "frozen-owner-off-roster": (
        lambda t: _drop_roster(t, "DEFER-COVLANG"),
        "missing from ## Owners",
    ),
    # Ids
    "duplicate-id": (_dup_id, "duplicate row ids"),
    "id-gap": (
        lambda t: add_row(
            t, late_row(t, "keep", number=_next_number(t) + 1, reason="x" * 30)
        ),
        "in order with no gap",
    ),
    "malformed-id": (
        lambda t: add_row(
            t,
            late_row(t, "keep", number=0, reason="x" * 30).replace("HC-000", "HC-1000"),
        ),
        "malformed id",
    ),
    # Rows hiding outside the table (prior: indented rows)
    "row-outside-rows": (_row_after_rows, "outside ## Rows"),
    "row-in-header": (_row_in_header, "outside ## Rows (in the header)"),
    "indented-1-space": (
        lambda t: add_row(t, late_row(t, "HC-SWEEP-ENGINE"), prefix=" "),
        "column 0",
    ),
    "indented-3-no-pipe": (
        lambda t: add_row(t, late_row(t, "HC-SWEEP-ENGINE")[1:], prefix="   "),
        "column 0",
    ),
    "blank-line-splits-table": (_blank_in_table, "splits the table"),
    "blank-after-header": (_blank_after_header, "splits the table"),
    "rows-separator-missing": (_break_rows_separator, "not the table separator"),
    "stray-pipe-line": (_stray_pipe, "malformed id"),
    "four-cells": (
        lambda t: add_row(t, "| HC-999 | a | `custodex/pr.py:1` | keep |"),
        "4 cells",
    ),
    # Late rows (prior P5-P8 and the M7 rule)
    "late-on-frozen-owner": (
        lambda t: add_row(t, late_row(t, "HC-SWEEP-ENGINE")),
        "already owns frozen rows",
    ),
    "late-on-reserved-owner": (
        lambda t: add_late(t, "HC-SCAFFOLD"),
        "reserved plan slice name",
    ),
    "late-owner-two-rows": (_second_row_for_late_owner, "exactly one row"),
    "late-owner-not-on-roster": (
        lambda t: add_row(t, late_row(t, "HC-NOBODY")),
        "not on the ## Owners roster",
    ),
    "late-owner-bad-name": (lambda t: add_late(t, "XS-THING"), "`HC-<TOPIC>`"),
    "late-owner-dotted": (lambda t: add_late(t, "HC-LATE.2"), "`HC-<TOPIC>`"),
    "late-owner-scheduled-later": (
        lambda t: add_late(t, "HC-LATE", "scheduled W40"),
        "must be `new XS`",
    ),
    "late-site-past-eof": (
        lambda t: add_late(t, "HC-LATE", sites=f"`{_LIVE_FILE}:99999`"),
        "past the end",
    ),
    "late-range-one-past-eof": (
        lambda t: add_late(
            t, "HC-LATE", sites=f"`{_LIVE_FILE}:{_live_line()}-{_live_len() + 1}`"
        ),
        "past the end",
    ),
    "late-site-missing-file": (
        lambda t: add_late(t, "HC-LATE", sites="`custodex/nope.py:1`"),
        "does not exist",
    ),
    "late-literal-not-at-line": (
        lambda t: add_late(t, "HC-LATE", literal="`NotInThatFile`"),
        "no span of its literal",
    ),
    "late-literal-at-one-site-only": (
        lambda t: add_late(
            t,
            "HC-LATE",
            sites=f"`{_LIVE_FILE}:{_live_line()}`, `{_LIVE_FILE}:1`",
        ),
        f"no span of its literal is found at {_LIVE_FILE}:1-1",
    ),
    "late-literal-unquoted": (
        lambda t: add_late(t, "HC-LATE", literal="a prose literal"),
        "quote the code in backticks",
    ),
    # The roster
    "roster-owner-twice": (
        lambda t: add_owner(t, _first_roster_owner(t), "done"),
        "listed twice",
    ),
    "roster-owner-no-row": (lambda t: add_owner(t, "HC-IDLE"), "owns no row"),
    "roster-bare-scheduled": (
        lambda t: _set_roster(t, _first_roster_owner(t), status="scheduled"),
        "must be one of",
    ),
    "roster-scheduled-w0": (
        lambda t: _set_roster(t, _first_roster_owner(t), status="scheduled W0"),
        "must be one of",
    ),
    "roster-scheduled-w-bare": (
        lambda t: _set_roster(t, _first_roster_owner(t), status="scheduled W"),
        "must be one of",
    ),
    "roster-status-suffix": (
        lambda t: _set_roster(t, _first_roster_owner(t), status="new XS soon"),
        "must be one of",
    ),
    "roster-keep-owner": (lambda t: add_owner(t, "keep"), "not a valid roster owner"),
    # Sites and reasons
    "site-without-line": (
        lambda t: add_late(t, "HC-LATE", sites="`custodex/pr.py`"),
        "malformed site",
    ),
    "site-line-zero": (
        lambda t: add_late(t, "HC-LATE", sites="`custodex/pr.py:0`"),
        "start at 1",
    ),
    "site-range-reversed": (
        lambda t: add_late(t, "HC-LATE", sites="`custodex/pr.py:9-3`"),
        "low to high",
    ),
    "site-is-a-directory": (
        lambda t: add_late(t, "HC-LATE", sites="`custodex/:3`"),
        "out of scope",
    ),
    "site-out-of-scope": (
        lambda t: add_late(t, "HC-LATE", sites="`README.md:3`"),
        "out of scope",
    ),
    "site-suffix-out-of-scope": (
        lambda t: add_late(t, "HC-LATE", sites="`custodex/pr.pyc:1`"),
        "out of scope",
    ),
    "site-list-trailing-site": (
        lambda t: add_late(
            t, "HC-LATE", sites=f"`{_LIVE_FILE}:{_live_line()}`, custodex/nope.py:1"
        ),
        "malformed site list",
    ),
    "site-list-trailing-prose": (
        lambda t: add_late(
            t, "HC-LATE", sites=f"`{_LIVE_FILE}:{_live_line()}` and more"
        ),
        "malformed site list",
    ),
    "site-range-degenerate": (
        lambda t: add_late(
            t, "HC-LATE", sites=f"`{_LIVE_FILE}:{_live_line()}-{_live_line()}`"
        ),
        "low to high",
    ),
    "site-cited-twice": (
        lambda t: add_late(
            t, "HC-LATE", sites="`custodex/pr.py:3`, `custodex/pr.py:3`"
        ),
        "cited twice",
    ),
    "keep-without-reason": (
        lambda t: add_row(t, late_row(t, "keep", reason="protocol")),
        "needs a keep reason",
    ),
    "owned-without-knob": (
        lambda t: add_late(t, "HC-LATE", reason="make it a knob"),
        "name its knob",
    ),
    "empty-literal": (
        lambda t: add_late(t, "HC-LATE", literal=""),
        "literal cell is empty",
    ),
}


@pytest.mark.parametrize("name", sorted(KNOWN_BAD))
def test_a_known_bad_edit_is_caught(name: str) -> None:
    """Each known-bad edit of the real audit yields its specific problem."""
    edit, match = KNOWN_BAD[name]
    problems = audit_problems(edit(_audit_text()), REPO_ROOT)
    assert any(match in p for p in problems), problems


LEGITIMATE: dict[str, Callable[[str], str]] = {
    "late-row-on-a-fresh-new-XS-owner": lambda t: add_late(t, "HC-LATE"),
    "two-stacked-late-rows": _two_late_rows,
    "late-keep-row": lambda t: add_row(
        t, late_row(t, "keep", reason="a protocol constant of the provider API")
    ),
    "late-range-literal-on-last-line": lambda t: add_late(
        t, "HC-LATE", sites=f"`{_LIVE_FILE}:{_live_line() - 2}-{_live_line()}`"
    ),
    "a-roster-status-moves-to-done": lambda t: _set_roster(
        t, _first_roster_owner(t), status="done"
    ),
    "frozen-cell-whitespace-reflow": lambda t: t.replace(
        "`_SEVERITY` map from", "`_SEVERITY`  map   from", 1
    ),
    "prose-edit": lambda t: t.replace(
        FROZEN_BATCHES[0].base, f"{FROZEN_BATCHES[0].base} (reworded)", 1
    ),
}


@pytest.mark.parametrize("name", sorted(LEGITIMATE))
def test_a_legitimate_edit_passes(name: str) -> None:
    """Following the audit's own late-row procedure keeps the lint green."""
    edited = LEGITIMATE[name](_audit_text())
    assert edited != _audit_text()
    assert audit_problems(edited, REPO_ROOT) == []


# ---------------------------------------------------------------------------
# Freezing: a late row becomes frozen and survives its owner landing
# ---------------------------------------------------------------------------


def _frozen_late(tmp_path: Path) -> tuple[str, Freeze, dict[str, str]]:
    text = add_late(_audit_text(), "HC-LATE")
    freeze = next_freeze(text, "abc1234")
    assert freeze is not None
    return text, freeze, {**FROZEN_ROSTER, **freeze.roster}


def test_the_freeze_covers_exactly_the_late_rows(tmp_path: Path) -> None:
    """The proposed batch starts after the last batch, ends at the last row,
    and pins the new owner at its `new XS` status."""
    text, freeze, _ = _frozen_late(tmp_path)
    nxt = FROZEN_BATCHES[-1].last + 1
    assert (freeze.batch.first, freeze.batch.last) == (nxt, nxt)
    assert freeze.batch.base == "abc1234"
    assert freeze.roster == {"HC-LATE": LATE_STATUS}
    assert next_freeze(_audit_text(), "abc1234") is None


def test_two_late_rows_freeze_in_one_batch() -> None:
    """Applying the proposed freeze of two late rows makes the lint green."""
    text = _two_late_rows(_audit_text())
    freeze = next_freeze(text, "abc1234")
    assert freeze is not None
    nxt = FROZEN_BATCHES[-1].last + 1
    assert (freeze.batch.first, freeze.batch.last) == (nxt, nxt + 1)
    assert set(freeze.roster) == {"HC-LATE-ONE", "HC-LATE-TWO"}
    got = audit_problems(
        text,
        REPO_ROOT,
        batches=(*FROZEN_BATCHES, freeze.batch),
        roster_pin={**FROZEN_ROSTER, **freeze.roster},
        notes_sha256=freeze.notes_sha256,
    )
    assert got == []


def test_a_frozen_row_survives_its_owner_landing(tmp_path: Path) -> None:
    """Once frozen, a row is no longer checked in the working tree: the owner
    slice may remove the literal (here the whole file is gone) and the lint
    stays green. Unfrozen, the same text fails, so the check is live."""
    text, freeze, pin = _frozen_late(tmp_path)
    assert any("does not exist here" in p for p in audit_problems(text, tmp_path))
    frozen = audit_problems(
        text,
        tmp_path,
        batches=(*FROZEN_BATCHES, freeze.batch),
        roster_pin=pin,
        notes_sha256=freeze.notes_sha256,
    )
    assert frozen == []


def test_a_frozen_late_owner_may_only_move_to_done(tmp_path: Path) -> None:
    """After the freeze the late owner is pinned like every frozen owner."""
    text, freeze, pin = _frozen_late(tmp_path)

    def lint(edited: str) -> list[str]:
        return audit_problems(
            edited,
            REPO_ROOT,
            batches=(*FROZEN_BATCHES, freeze.batch),
            roster_pin=pin,
            notes_sha256=freeze.notes_sha256,
        )

    moved = lint(_set_roster(text, "HC-LATE", status="scheduled W50"))
    assert any("is pinned to 'new XS'" in p for p in moved), moved
    assert lint(_set_roster(text, "HC-LATE", status="done")) == []


def _reader(lines: list[str] | None) -> BaseReader:
    def read_at(base: str, path: str) -> list[str] | None:
        assert base == "abc1234"
        return lines

    return read_at


def test_the_base_check_reads_at_the_batch_base(tmp_path: Path) -> None:
    """A frozen row is checked at its batch's base: present passes; a missing
    file, a short file and moved code each fail with their own problem."""
    text, freeze, _ = _frozen_late(tmp_path)
    batch = (freeze.batch,)
    live = (REPO_ROOT / _LIVE_FILE).read_text(encoding="utf-8").splitlines()
    assert base_problems(text, batch, _reader(live)) == []
    gone = base_problems(text, batch, _reader(None))
    assert any("does not exist at abc1234" in p for p in gone), gone
    short = base_problems(text, batch, _reader(live[: _live_line() - 1]))
    assert any("past the end" in p and "at abc1234" in p for p in short), short
    moved = base_problems(text, batch, _reader(["", *live]))
    assert any("no span of its literal" in p for p in moved), moved
    up = base_problems(text, batch, _reader(live[1:]))
    assert any("no span of its literal" in p for p in up), up
    assert base_problems(text, (), _reader(None)) == []


_LAST = FROZEN_BATCHES[-1].last
_SHA = FROZEN_BATCHES[0].rows_sha256

#: (batches, roster pin, expected problem): each pin is checked against the file.
BAD_PINS: dict[str, tuple[tuple[Batch, ...], Mapping[str, str], str]] = {
    "batch-not-from-row-1": (
        (Batch(2, _LAST, "ddc368d", _SHA),),
        FROZEN_ROSTER,
        "contiguous from HC-001",
    ),
    "batch-overlaps": (
        (*FROZEN_BATCHES, Batch(_LAST, _LAST, "x", "")),
        FROZEN_ROSTER,
        "contiguous from HC-001",
    ),
    "batch-runs-backwards": (
        (*FROZEN_BATCHES, Batch(_LAST + 2, _LAST + 1, "x", "")),
        FROZEN_ROSTER,
        "contiguous from HC-001",
    ),
    "batch-past-the-rows": (
        (*FROZEN_BATCHES, Batch(_LAST + 1, 999, "x", "")),
        FROZEN_ROSTER,
        "are missing rows",
    ),
    "batch-base-not-named": (
        (Batch(1, _LAST, "feedbee", _SHA),),
        FROZEN_ROSTER,
        "base commit feedbee",
    ),
    "roster-pin-drops-an-owner": (
        FROZEN_BATCHES,
        {k: v for k, v in FROZEN_ROSTER.items() if k != "CI-OPEN"},
        "FROZEN_ROSTER disagree",
    ),
    "roster-pin-adds-an-owner": (
        FROZEN_BATCHES,
        {**FROZEN_ROSTER, "HC-GHOST": "new XS"},
        "FROZEN_ROSTER disagree",
    ),
}


@pytest.mark.parametrize("name", sorted(BAD_PINS))
def test_a_bad_pin_is_caught(name: str) -> None:
    """The batches and roster pins are themselves checked against the file."""
    batches, roster_pin, match = BAD_PINS[name]
    problems = audit_problems(
        _audit_text(), REPO_ROOT, batches=batches, roster_pin=roster_pin
    )
    assert any(match in p for p in problems), problems
