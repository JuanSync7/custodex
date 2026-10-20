"""Quoted config defaults in the docs must match the config model (K0, K8).

The rule (CONSTRAINTS.md K0): an install-time or tunable value comes from
config, never from a literal in code. Docs may still quote the shipped value so
they read easily, but every quote names the config key that owns it, in one of
the closed set of forms in ``QUOTE_FORMS``. ``key`` is the YAML path an adopter
writes (a field name or its alias) and ``V`` is a YAML value:

- ``default `key: V``` or ``defaults to `key: V```
- ```key: V` by default`` or ```key: V` (default)``
- ``N <up to four words> (`key`)``: a number, then the key in parentheses, as
  in "a timeout of 120 seconds (`backend.timeout_s`)". A number that follows a
  reference noun ("section 4", "step 2", ``_REFERENCE_NOUN``) is a reference,
  not a quantity, and is not read as a quote.
- ``default OFF (the `key` knob)``, for ON, OFF, true, false or null
- ```key`, default V``, ```key` (default V)`` or ```key` knob (default V)``
- ```key` is V by default`` or ```key` defaults to V``

A line break may stand wherever a form has a space. Other phrasings are not
checked, which is why the rule tells writers to use one of these forms.

This guard finds every such quote in the repo's Markdown and checks it against
the model that the key's first segment selects (``ROUTES``): ``server.*`` is
config/settings.yaml (``Settings``), ``spmirror.*`` is config/spmirror.yaml
(``SpMirrorConfig``), and any other key is the repo config (``IndexFile`` and
the ``MonitorConfig`` it lifts into). An unknown key, a key that names no single
default, or a value that differs from the model's default fails loudly, so a
quoted default cannot drift from the code.
"""

from __future__ import annotations

import os
import re
import types
import typing
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from pydantic.fields import FieldInfo

from custodex.config import IndexFile, MonitorConfig
from custodex.settings import Settings
from custodex.spmirror import SpMirrorConfig
from tests._repo import REPO_ROOT

_W = r"\s+"
_SEGMENT = r"[a-z_][a-z0-9_-]*"
_KEY = rf"(?P<key>{_SEGMENT}(?:\.{_SEGMENT})*)"
#: A value inside the key's own backticks (``key: V``).
_SPAN_VALUE = r"(?P<value>[^`]+)"
#: A value written after the key: a number, a YAML word, or a backticked span.
_WORD_VALUE = (
    r"(?P<value>-?\d+(?:\.\d+)?|true|false|True|False|ON|OFF|on|off|null|None"
    r"|`[^`]+`)"
)
_SWITCH = r"(?P<value>ON|OFF|on|off|true|false|null)"
_NUMBER = r"(?P<value>-?\d+(?:\.\d+)?)"

#: The closed set of quote forms (name, pattern). See the module docstring.
QUOTE_FORMS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "default `key: V`",
        re.compile(rf"\b[Dd]efaults?(?:{_W}to)?{_W}`{_KEY}:{_W}{_SPAN_VALUE}`"),
    ),
    (
        "`key: V` by default",
        re.compile(rf"`{_KEY}:{_W}{_SPAN_VALUE}`{_W}(?:by{_W}default\b|\(default\))"),
    ),
    (
        "N words (`key`)",
        re.compile(rf"(?<![\w.`-]){_NUMBER}(?:{_W}[A-Za-z-]+){{0,4}}{_W}\(`{_KEY}`\)"),
    ),
    (
        "default OFF (the `key` knob)",
        re.compile(
            rf"\b[Dd]efault{_W}{_SWITCH}{_W}\((?:the{_W})?`{_KEY}`(?:{_W}knob)?\)"
        ),
    ),
    (
        "`key`, default V",
        re.compile(
            rf"`{_KEY}`(?:{_W}knob)?(?:,{_W}|{_W}\()[Dd]efault{_W}{_WORD_VALUE}"
        ),
    ),
    (
        "`key` is V by default",
        re.compile(rf"`{_KEY}`{_W}is{_W}{_WORD_VALUE}{_W}by{_W}default\b"),
    ),
    (
        "`key` defaults to V",
        re.compile(rf"`{_KEY}`{_W}defaults{_W}to{_W}{_WORD_VALUE}"),
    ),
)

#: Words that make the number after them a reference ("section 4", "step 2"),
#: so the "N words (`key`)" form does not read it as a quoted value. No other
#: form's value can follow such a word (it follows `default`, `to`, `is` or
#: `key:`), so the check needs no per-form gate.
_REFERENCE_NOUN = re.compile(
    r"(?:^|[^\w-])(?:step|section|phase|part|item|slice|wave|round|stage|chapter"
    r"|page|line|row|figure|table|rule|issue|ticket|PR|MR)\s*$",
    re.IGNORECASE,
)

#: A backticked name ending in a file suffix is a file, not a config key,
#: unless it resolves to a real field (``documents.html`` is one).
_FILE_NAME = re.compile(
    r".*\.(?:py|pyi|md|ya?ml|json|toml|txt|ini|cfg|sh|js|ts|tsx|astro|html|css)"
)


class _SpMirrorFile(BaseModel):
    """config/spmirror.yaml: one top-level ``spmirror:`` block
    (``load_spmirror_config`` reads ``loaded["spmirror"]``)."""

    spmirror: SpMirrorConfig | None = None


#: The config file a key's first segment selects, as the models that hold it.
ROUTES: dict[str, tuple[type[BaseModel], ...]] = {
    "server": (Settings,),
    "spmirror": (_SpMirrorFile,),
}
#: Every other key belongs to the repo config (config/cdmon or cdmon.yaml).
REPO_CONFIG: tuple[type[BaseModel], ...] = (IndexFile, MonitorConfig)

#: Directories never scanned: VCS, environments, caches, build output, runtime
#: state, and the planning substrate (it quotes keys that are planned but not
#: built yet). CONSTRAINTS.md is the one planning file scanned, because it
#: states the rule and must obey it.
_PRUNE = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".astro",
        ".cdmon",
        ".project",
    }
)
_ALSO_SCAN = (Path(".project") / "spec" / "CONSTRAINTS.md",)


@dataclass(frozen=True)
class Quote:
    """One quote of a config default found in a Markdown file."""

    path: str
    line: int
    key: str
    value: str
    form: str


def _normalise_value(raw: str) -> str:
    value = raw.strip("`")
    return "null" if value == "None" else value


def find_quotes(text: str, path: str) -> list[Quote]:
    """Every quote in ``text`` in any accepted form, with the 1-based line it
    starts on (sorted, de-duplicated, K10)."""
    found: set[tuple[int, int, str, str, str]] = set()
    for form, pattern in QUOTE_FORMS:
        for m in pattern.finditer(text):
            key = m.group("key")
            if _FILE_NAME.fullmatch(key) and not _resolves(key):
                continue
            if _REFERENCE_NOUN.search(text, 0, m.start("value")):
                continue  # "section 4 (`key`)" is a reference, not a value
            line = text.count("\n", 0, m.start()) + 1
            found.add((line, m.start(), key, _normalise_value(m.group("value")), form))
    return [
        Quote(path, line, key, value, form)
        for line, _, key, value, form in sorted(found)
    ]


def iter_markdown(root: Path) -> Iterator[Path]:
    """Repo Markdown, pruned of vendored, cached and planning trees (sorted, K10).

    A set, because an ``_ALSO_SCAN`` file outside a pruned tree is also found by
    the walk and must be read once."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _PRUNE)
        found.extend(Path(dirpath) / f for f in filenames if f.endswith(".md"))
    found.extend(root / extra for extra in _ALSO_SCAN if (root / extra).is_file())
    yield from sorted(set(found))


def _strip_optional(annotation: Any) -> list[Any]:
    """The non-None members of an Optional/Union annotation (else the annotation)."""
    origin = typing.get_origin(annotation)
    if origin is typing.Union or origin is types.UnionType:
        return [a for a in typing.get_args(annotation) if a is not type(None)]
    return [annotation]


def _sub_model(annotation: Any) -> type[BaseModel] | None:
    """The single BaseModel a field descends into, through Optional and sequences."""
    models: list[type[BaseModel]] = []
    for member in _strip_optional(annotation):
        origin = typing.get_origin(member)
        if origin in (tuple, list):
            args = [a for a in typing.get_args(member) if a is not Ellipsis]
            if len(args) == 1:
                member = args[0]
        if isinstance(member, type) and issubclass(member, BaseModel):
            models.append(member)
    return models[0] if len(models) == 1 else None


def _field_named(model: type[BaseModel], segment: str) -> FieldInfo | None:
    """The field an adopter writes as ``segment``: its name or its YAML alias."""
    for name, field in model.model_fields.items():
        if segment in (name, field.alias):
            return field
    return None


def resolve_field(root: type[BaseModel], key: str) -> FieldInfo:
    """Walk ``key`` (dotted) down ``root``; loud on any segment that does not exist."""
    model: type[BaseModel] | None = root
    field: FieldInfo | None = None
    walked: list[str] = []
    for segment in key.split("."):
        if model is None:
            raise LookupError(
                f"`{'.'.join(walked)}` is not a nested model, so `{key}` cannot "
                f"descend into `{segment}`"
            )
        field = _field_named(model, segment)
        if field is None:
            raise LookupError(
                f"`{key}`: `{segment}` is not a field of {model.__name__}"
            )
        walked.append(segment)
        model = _sub_model(field.annotation)
    assert field is not None
    return field


def field_default(field: FieldInfo, key: str) -> Any:
    """The field's shipped default; loud when the field is required."""
    if field.is_required():
        raise LookupError(f"`{key}` is required: it has no shipped default to quote")
    return field.get_default(call_default_factory=True, validated_data={})


def _default_on(root: type[BaseModel], key: str) -> tuple[Any, FieldInfo] | None:
    try:
        field = resolve_field(root, key)
    except LookupError:
        return None
    return field_default(field, key), field


def _resolves(key: str) -> bool:
    return any(_default_on(root, key) for root in roots_for(key))


def roots_for(key: str) -> tuple[type[BaseModel], ...]:
    """The models of the config file that owns ``key`` (see ``ROUTES``)."""
    return ROUTES.get(key.split(".", 1)[0], REPO_CONFIG)


def check_quote(quote: Quote) -> str | None:
    """None when the quote matches its model default, else the problem (K8)."""
    where = f"{quote.path}:{quote.line}"
    roots = roots_for(quote.key)
    try:
        found = [(r, hit) for r in roots if (hit := _default_on(r, quote.key))]
        if not found:
            # Re-resolve on the first root to surface the precise reason.
            resolve_field(roots[0], quote.key)
            raise LookupError(f"`{quote.key}`: no field")  # pragma: no cover
        defaults = {repr(hit[0]) for _, hit in found}
        if len(defaults) > 1:
            names = ", ".join(f"{r.__name__}={hit[0]!r}" for r, hit in found)
            return (
                f"{where}: `{quote.key}` has different defaults per model ({names}); "
                "the quote is ambiguous"
            )
        default, field = found[0][1]
    except LookupError as exc:
        return (
            f"{where}: {exc} (read as a quoted default in the form "
            f"{quote.form!r}; name a real key, or rephrase if it is not one)"
        )
    try:
        parsed = yaml.safe_load(quote.value)
    except yaml.YAMLError as exc:
        return f"{where}: `{quote.key}: {quote.value}` is not valid YAML ({exc})"
    try:
        value: Any = TypeAdapter(field.annotation).validate_python(parsed)
    except ValidationError as exc:
        return (
            f"{where}: `{quote.key}: {quote.value}` is not a valid value for the "
            f"field ({exc.error_count()} error(s))"
        )
    if value != default:
        return (
            f"{where}: quoted `{quote.key}: {quote.value}` but the model default "
            f"is {default!r}"
        )
    return None


def _corpus() -> list[Quote]:
    quotes: list[Quote] = []
    for path in iter_markdown(REPO_ROOT):
        rel = path.relative_to(REPO_ROOT).as_posix()
        quotes.extend(find_quotes(path.read_text(encoding="utf-8"), rel))
    return quotes


def test_every_quoted_config_default_matches_the_model() -> None:
    """Each docs quote of a config default names a real key and its real default."""
    quotes = _corpus()
    assert quotes, (
        "no `default `key: value`` quote found in the docs; the rule's own "
        "examples (CLAUDE.md, CONSTRAINTS.md) should be there"
    )
    problems = [p for q in quotes if (p := check_quote(q)) is not None]
    assert problems == []


def test_the_rule_documents_quote_real_defaults() -> None:
    """The two files that state the rule carry quotes, so the guard is never empty."""
    quoted = {q.path for q in _corpus()}
    assert "CLAUDE.md" in quoted
    assert ".project/spec/CONSTRAINTS.md" in quoted


def test_the_corpus_skips_vendored_and_planning_trees(tmp_path: Path) -> None:
    """Only shipped docs are scanned; CONSTRAINTS.md is the one planning file read."""
    for rel in (
        "README.md",
        "docs/a.md",
        "node_modules/x/README.md",
        ".venv/lib/x.md",
        ".project/slices/S.md",
        ".project/spec/CONSTRAINTS.md",
        ".project/spec/SPEC.md",
    ):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x\n", encoding="utf-8")
    got = [p.relative_to(tmp_path).as_posix() for p in iter_markdown(tmp_path)]
    assert got == [".project/spec/CONSTRAINTS.md", "README.md", "docs/a.md"]


@pytest.mark.parametrize(
    ("line", "match"),
    [
        ("(default `no_such_key: 1`)", "`no_such_key` is not a field of IndexFile"),
        ("(default `apply_tiered: true`)", "but the model default is False"),
        ("(default `apply_tiered: maybe`)", "is not a valid value"),
        ("(default `apply_tiered: [1`)", "is not valid YAML"),
        ("(default `units: []`)", "`units` is required"),
        ("(default `documents.id: x`)", "`documents.id` is required"),
        ("(default `root: .`)", "different defaults per model"),
        ("(default `backend.extra.x: 1`)", "is not a nested model"),
        ("(default `backend.nope: 1`)", "`nope` is not a field of BackendConfig"),
        ("(default `server.git.clone_timeout_seconds: 5`)", "model default is None"),
        ("(default `server.nope: 1`)", "`nope` is not a field of ServerSettings"),
        (
            "(default `server.git.allowed_hosts: [github.com]`)",
            "but the model default is ('github.com', 'gitlab.com')",
        ),
        ("defaults to `backend.kind: api`", "but the model default is 'mock'"),
    ],
)
def test_a_wrong_quote_is_loud(line: str, match: str) -> None:
    """Unknown keys, wrong values, required fields and ambiguous keys all fail."""
    quotes = find_quotes(line, "x.md")
    assert len(quotes) == 1
    problem = check_quote(quotes[0])
    assert problem is not None
    assert match in problem


@pytest.mark.parametrize(
    "line",
    [
        "(default `apply_tiered: false`)",
        "Defaults to `backend.kind: mock`.",
        "(default `backend.timeout_s: 120`)",
        "(default `server.git.clone_timeout_seconds: null`)",
        "(default `server.git.allowed_hosts: [github.com, gitlab.com]`)",
        "(default `server.port: 33333`)",
        "(default `staleness.default_days: 90`)",
        "(default `documents.html: false`)",
        "`documents.html` (default false)",
    ],
)
def test_a_right_quote_passes(line: str) -> None:
    """Correct quotes pass, through nesting, Optional, tuples and both roots."""
    quotes = find_quotes(line, "x.md")
    assert len(quotes) == 1
    assert check_quote(quotes[0]) is None


def test_prose_that_is_not_the_grammar_is_ignored() -> None:
    """Plain prose such as a default `mock` without a key is not a quote."""
    assert find_quotes("the default `mock` path; default `.cdmon/x.json`", "x") == []


# --- round-1 additions (red first) -----------------------------------------


@pytest.mark.parametrize(
    ("text", "match"),
    [
        # The user's own form: a number, a few words, then the key in parentheses.
        ("top 7 exemplars (`apply_tiered`)", "is not a valid value"),
        ("a timeout of 60 seconds (`backend.timeout_s`)", "model default is 120"),
        # The plan's illustrative key: no `monitor` section exists (HC-AUDIT
        # names the planned knob `learning.exemplar_top_n`, pending ratification).
        ("top 3 exemplars (`monitor.exemplar_top_n`)", "`monitor` is not a field"),
        # The value first, then "by default".
        ("`apply_tiered: true` by default", "but the model default is False"),
        ("`apply_tiered: true` (default)", "but the model default is False"),
        # The key first, then its default.
        ("`staleness.default_days` is 30 by default", "model default is 90"),
        ("`staleness.default_days` defaults to 30", "model default is 90"),
        ("`apply_tiered`, default ON", "but the model default is False"),
        ("the `docdeps.transitive` knob (default ON)", "but the model default"),
        ("Default ON (the `docdeps.transitive` knob)", "but the model default"),
        # A quote wrapped across a line break is still one quote.
        (
            "the backend (default\n`backend.kind: api`)",
            "but the model default is 'mock'",
        ),
        # Up to four words between the number and the key.
        (
            "a timeout of 60 seconds per backend call (`backend.timeout_s`)",
            "model default is 120",
        ),
        # A reference noun only counts as a whole word ("deadline" is not "line").
        ("a deadline 60 seconds (`backend.timeout_s`)", "model default is 120"),
        # Only the words right before the VALUE can make it a reference; a key
        # that follows a reference noun is still a quote.
        ("as in step `apply_tiered`, default ON", "but the model default is False"),
        # A decimal number is found and checked, not skipped.
        ("a timeout of 1.5 seconds (`backend.timeout_s`)", "is not a valid value"),
        # The switch form takes true/false/null as well as ON/OFF.
        ("default true (the `docdeps.transitive` knob)", "but the model default"),
        # config/spmirror.yaml keys route to SpMirrorConfig.
        ("(default `spmirror.timeout_seconds: 60`)", "model default is 120"),
        ("(default `spmirror.nope: 1`)", "`nope` is not a field of SpMirrorConfig"),
    ],
)
def test_every_quote_form_is_checked(text: str, match: str) -> None:
    """Each accepted phrasing of a default is found and checked, not skipped."""
    quotes = find_quotes(text, "x.md")
    assert len(quotes) == 1, quotes
    problem = check_quote(quotes[0])
    assert problem is not None
    assert match in problem


@pytest.mark.parametrize(
    ("text", "line"),
    [
        ("a timeout of 120 seconds (`backend.timeout_s`)", 1),
        ("`apply_tiered: false` by default", 1),
        ("`staleness.default_days` is 90 by default", 1),
        ("`staleness.default_days` defaults to 90", 1),
        ("(overriding `apply_tiered`, default OFF)", 1),
        ("the additive `docdeps.transitive` knob (default OFF);", 1),
        ("Default OFF (the `docdeps.transitive` knob)", 1),
        ("intro\nthe backend (default\n`backend.kind: mock`)", 2),
        ("(default `spmirror.timeout_seconds: 120`)", 1),
        ("(default `doc-style: doc-style.yaml`)", 1),
        ("(default `doc_style: doc-style.yaml`)", 1),
        ("(default `server.git.clone_timeout_seconds: None`)", 1),
        # A backticked value after the key is unquoted before it is parsed.
        ("`backend.kind`, default `mock`", 1),
        ("`backend.kind` defaults to `mock`", 1),
        ("default false (the `docdeps.transitive` knob)", 1),
        ("a timeout of 120 seconds per backend call (`backend.timeout_s`)", 1),
    ],
)
def test_every_quote_form_passes_when_right(text: str, line: int) -> None:
    """A right quote in any accepted form passes, and reports its first line."""
    quotes = find_quotes(text, "x.md")
    assert len(quotes) == 1, quotes
    assert quotes[0].line == line
    assert check_quote(quotes[0]) is None


@pytest.mark.parametrize(
    "text",
    [
        "it reads 2 files (`custodex/cli.py`)",
        "it reads 2 files (`cli.py`)",
        "turns on (`db`)",
        "a config with `staleness.default_days: 30` set",
        "the default `body` baseline",
        # A section or step number before a key is a reference, not a quantity.
        "see section 4 (`backend.timeout_s`)",
        "Monitor switches it on in step 2 (`apply_tiered`) of the rollout.",
        "Phase 3 of the plan (`docdeps.transitive`) ships later",
        "wave\n12 (`apply_tiered`)",
    ],
)
def test_text_that_is_not_a_quote_is_ignored(text: str) -> None:
    """File names, prose words and plain settings are not quotes of a default."""
    assert find_quotes(text, "x.md") == []


def test_the_shipped_prose_quotes_are_checked() -> None:
    """The guard reads the real default statements in the shipped docs, not just
    the rule's own examples (reviewer: FEATURES.md and DEMOS.md state defaults)."""
    quoted = {q.path for q in _corpus()}
    assert {"feature-doc/FEATURES.md", "demo/DEMOS.md"} <= quoted


class _Leaf(BaseModel):
    n: int = 3


class _Root(BaseModel):
    opt: _Leaf | None = None
    hosts: list[str] = Field(default_factory=lambda: ["a"])


def test_the_resolver_descends_optionals_and_calls_factories() -> None:
    """An Optional sub-model is descended and a default factory is called, so a
    future config field of either shape is checked, not misread."""
    assert field_default(resolve_field(_Root, "opt.n"), "opt.n") == 3
    assert field_default(resolve_field(_Root, "hosts"), "hosts") == ["a"]


def test_a_file_scanned_twice_is_read_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An extra scan target that the walk also finds is listed once."""
    (tmp_path / "README.md").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(
        "tests.smoke.test_config_quotes._ALSO_SCAN", (Path("README.md"),)
    )
    assert [p.name for p in iter_markdown(tmp_path)] == ["README.md"]
