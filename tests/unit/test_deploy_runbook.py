"""DEPLOY-MANAGED: the operator runbook (DEPLOY.md) agrees with the code it describes.

The config side (``config/cdmon/deploy.yaml``) makes a settings-model change drift
the runbook. The checks here pin the runbook's CONTENT against the code, deriving
every expectation from the code rather than restating it, so neither a code change
nor a prose edit can quietly break a claim the runbook makes:

* the settings block is the complete ``config/settings.yaml`` at its built-in
  defaults (every key, nothing unknown, every value the default), walked against
  the pydantic models so a dict-typed or digit-bearing key is handled too;
* each ``# env:`` comment names exactly the variable the loader reads for that
  key, and every variable the loader reads (by any access path) has one;
* the parse bullets put each override in the bullet of its field kind, and the
  boolean tokens / integer / list rules hold for near-miss values;
* every ``CDMON_*`` the page names is read by the server or the compose file, and
  the secrets table is exactly the presence-checked secrets plus the compose-only
  ones;
* every port the page states is the default port, the stated precedence is the
  loader's, every ``server.*`` key the prose names exists, and every settings
  model is named;
* the upgrade block fetches and checks out a release BEFORE any install or
  console build (the gitignored ``frontend/dist`` is rebuilt every upgrade), and
  the image builds the console and copies it to the directory the server serves;
  the checkout carries local settings edits (``--merge``) and ``cdx settings``
  gates the build (``tests/integration/test_deploy_shell_blocks.py`` runs it);
* the compose claims (database URL, read-only mount, refuse-to-start secrets,
  the data volume and user the reuse paragraph names), the KEK claim, the
  compose-aware hardening items, and every prose port naming **server.port**.

Pure reads of checked-in files, no network, no clock (K4, K10).

Features: FEAT-QUALITY-011
"""

from __future__ import annotations

import ast
import re
import shlex
import typing
from collections.abc import Iterator, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
import yaml
from pydantic import BaseModel

from custodex.errors import ConfigError
from custodex.settings import (
    DEFAULT_SETTINGS_PATH,
    Settings,
    resolve_settings,
    secret_presence,
    settings_from_env,
)
from tests._repo import REPO_ROOT

_DOC = REPO_ROOT / "DEPLOY.md"
_COMPOSE = REPO_ROOT / "docker-compose.yml"
_DOCKERFILE = REPO_ROOT / "Dockerfile"
_DOCKERIGNORE = REPO_ROOT / ".dockerignore"

_ENV_COMMENT = re.compile(r"#\s*env:\s*([A-Z][A-Z0-9_]*)")
_CDMON_NAME = re.compile(r"\bCDMON_[A-Z0-9_]*[A-Z0-9]\b")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})\s*([\w+-]*)\s*$")
_BACKTICK = re.compile(r"`([^`\n]+)`")


# ── document readers ─────────────────────────────────────────────────────────


def _body(text: str) -> str:
    """The document without its leading ``---`` front-matter block."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        assert end != -1, "unterminated front matter"
        return text[end + len("\n---\n") :]
    return text


def _sections(text: str, level: int) -> dict[str, str]:
    """Split ``text`` on headings of exactly ``level`` ``#``s, ignoring fences.

    A ``#`` line inside a fenced block (a bash comment, a YAML comment) is
    content, never a heading.
    """
    marker = "#" * level + " "
    out: dict[str, list[str]] = {}
    current: str | None = None
    in_fence = False
    for line in text.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence and line.startswith(marker):
            current = line[len(marker) :].strip()
            assert current not in out, f"duplicate heading {current!r}"
            out[current] = []
            continue
        if current is not None:
            out[current].append(line)
    return {k: "\n".join(v) for k, v in out.items()}


def _section(text: str, prefix: str, level: int = 2) -> str:
    hits = [v for k, v in _sections(text, level).items() if k.startswith(prefix)]
    assert len(hits) == 1, f"expected one {'#' * level} {prefix!r} section"
    return hits[0]


def _fenced(text: str, lang: str) -> list[str]:
    """The bodies of the fenced blocks tagged ``lang`` in ``text``."""
    blocks: list[str] = []
    buf: list[str] | None = None
    for line in text.split("\n"):
        m = _FENCE.match(line)
        if m and buf is None:
            buf = [] if m.group(2) == lang else None
            if m.group(2) != lang:
                buf = ["\0skip"]
            continue
        if m and buf is not None:
            if buf[:1] != ["\0skip"]:
                blocks.append("\n".join(buf))
            buf = None
            continue
        if buf is not None:
            buf.append(line)
    assert buf is None, "unterminated fence"
    return blocks


def _prose(text: str) -> str:
    """``text`` with every fenced block blanked out."""
    out: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)


def _doc() -> str:
    return _body(_DOC.read_text(encoding="utf-8"))


def _config_section() -> str:
    return _section(_doc(), "Configuration")


def _settings_block() -> str:
    blocks = _fenced(_config_section(), "yaml")
    assert len(blocks) == 1, "the Configuration section carries one yaml block"
    return blocks[0]


# ── the settings model graph ─────────────────────────────────────────────────


def _nested_model(annotation: Any) -> type[BaseModel] | None:
    """The model a field nests DIRECTLY (its mapping recurses), else ``None``."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None


def _models_in(annotation: Any) -> set[type[BaseModel]]:
    """Every model named anywhere in ``annotation`` (``X | None``, containers)."""
    found: set[type[BaseModel]] = set()
    model = _nested_model(annotation)
    if model is not None:
        found.add(model)
    for arg in typing.get_args(annotation):
        found |= _models_in(arg)
    return found


def _reachable_models(root: type[BaseModel]) -> set[type[BaseModel]]:
    seen: set[type[BaseModel]] = set()
    todo = [root]
    while todo:
        model = todo.pop()
        if model in seen:
            continue
        seen.add(model)
        for field in model.model_fields.values():
            todo.extend(_models_in(field.annotation))
    return seen


def _model_leaves(model: type[BaseModel], prefix: str = "") -> dict[str, Any]:
    """Dotted leaf key -> field annotation (nested models recurse)."""
    out: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        sub = _nested_model(field.annotation)
        if sub is not None:
            out.update(_model_leaves(sub, f"{prefix}{name}."))
        else:
            out[f"{prefix}{name}"] = field.annotation
    return out


def _leaf_values(obj: BaseModel, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in type(obj).model_fields:
        value = getattr(obj, name)
        if isinstance(value, BaseModel):
            out.update(_leaf_values(value, f"{prefix}{name}."))
        else:
            out[f"{prefix}{name}"] = value
    return out


def _field_kind(annotation: Any) -> str:
    """``list`` / ``int`` / ``bool`` / ``str`` for a leaf annotation."""
    args = [a for a in typing.get_args(annotation) if a is not type(None)]
    if typing.get_origin(annotation) is tuple:
        return "list"
    if annotation is bool:
        return "bool"
    if annotation is int or (len(args) == 1 and args[0] is int):
        return "int"
    if annotation is str:
        return "str"
    raise AssertionError(f"no env parse kind for annotation {annotation!r}")


def _block_leaves(
    model: type[BaseModel], node: yaml.Node, prefix: str = ""
) -> tuple[dict[str, int], list[str]]:
    """Walk a composed YAML mapping against ``model``.

    Returns (dotted leaf -> 0-based line of its key, unknown/mis-shaped keys).
    A key is a leaf exactly when the model says so, so a dict-typed field is ONE
    leaf compared whole, never flattened into its entries.
    """
    assert isinstance(node, yaml.MappingNode), f"{prefix or 'top level'}: not a map"
    leaves: dict[str, int] = {}
    unknown: list[str] = []
    for key_node, value_node in node.value:
        dotted = f"{prefix}{key_node.value}"
        field = model.model_fields.get(key_node.value)
        if field is None:
            unknown.append(dotted)
            continue
        sub = _nested_model(field.annotation)
        if sub is None:
            leaves[dotted] = key_node.start_mark.line
        elif isinstance(value_node, yaml.MappingNode):
            sub_leaves, sub_unknown = _block_leaves(sub, value_node, f"{dotted}.")
            leaves.update(sub_leaves)
            unknown.extend(sub_unknown)
        else:
            unknown.append(f"{dotted} (expected a mapping)")
    return leaves, unknown


def _block_env_overrides(model: type[BaseModel], block: str) -> dict[str, str]:
    """``# env:`` name -> the dotted leaf whose key sits on the same line."""
    leaves, _ = _block_leaves(model, yaml.compose(block))
    by_line = {line: key for key, line in leaves.items()}
    out: dict[str, str] = {}
    for lineno, line in enumerate(block.split("\n")):
        for name in _ENV_COMMENT.findall(line):
            assert lineno in by_line, f"`# env: {name}` is not on a settings key line"
            assert name not in out, f"{name} named twice in the block"
            out[name] = by_line[lineno]
    return out


# ── the env loader, observed ─────────────────────────────────────────────────


class _RecordingEnv(Mapping[str, str]):
    """An env that records every name read, by ANY access path.

    Enumerating the environment is refused, so a loader that discovers variables
    by iteration (instead of naming them) fails loudly here.
    """

    def __init__(self, values: Mapping[str, str] | None = None) -> None:
        self._values = dict(values or {})
        self.read: list[str] = []

    def __getitem__(self, key: str) -> str:
        self.read.append(key)
        return self._values[key]

    def get(self, key: str, default: Any = None) -> Any:
        self.read.append(key)
        return self._values.get(key, default)

    def __contains__(self, key: object) -> bool:
        self.read.append(str(key))
        return key in self._values

    def __iter__(self) -> Iterator[str]:
        raise AssertionError("the env must be read by name, never enumerated")

    def __len__(self) -> int:
        raise AssertionError("the env must be read by name, never enumerated")


def _loader_reads() -> set[str]:
    env = _RecordingEnv()
    settings_from_env(Settings(), env)
    return set(env.read)


def _presence_reads() -> set[str]:
    env = _RecordingEnv()
    secret_presence(env)
    return set(env.read)


def _compose_names() -> set[str]:
    """``CDMON_*`` the compose file interpolates (``${CDMON_X...}``)."""
    return set(re.findall(r"\$\{(CDMON_[A-Z0-9_]+)", _COMPOSE.read_text("utf-8")))


def _candidates() -> tuple[str, ...]:
    """Sample env values: two generic ones plus every string default (sorted).

    Derived from the defaults so a field whose validator only accepts its own
    vocabulary (e.g. a ``kinds`` tuple) still finds a value that moves it.
    """
    strings: set[str] = set()
    for value in _leaf_values(Settings()).values():
        items = value if isinstance(value, tuple) else (value,)
        strings |= {v for v in items if isinstance(v, str)}
    return ("7", "on", *sorted(strings))


def _moves(name: str, value: str) -> dict[str, Any] | None:
    """The leaves ``name=value`` moves off their defaults (``None`` if refused)."""
    try:
        got = settings_from_env(Settings(), {name: value})
    except ConfigError:
        return None
    base = _leaf_values(Settings())
    return {k: v for k, v in _leaf_values(got).items() if base[k] != v}


def _override_target(name: str) -> tuple[str, str]:
    """(the one leaf ``name`` moves, a sample value that moves it)."""
    for sample in _candidates():
        moved = _moves(name, sample)
        if moved:
            assert len(moved) == 1, f"{name} moved several keys: {sorted(moved)}"
            return next(iter(moved)), sample
    raise AssertionError(f"no sample value moves any setting for {name}")


def _bullets(section: str) -> dict[str, str]:
    """Top-level ``- **Word**`` bullets (with continuation lines), by word."""
    out: dict[str, list[str]] = {}
    current: str | None = None
    for line in _prose(section).split("\n"):
        m = re.match(r"^- \*\*(\w+)\*\*", line)
        if m:
            current = m.group(1).lower()
            out[current] = [line]
        elif current is not None and line.startswith("  ") and line.strip():
            out[current].append(line)
        else:
            current = None
    return {k: " ".join(v) for k, v in out.items()}


_KIND_BULLET = {"list": "lists", "int": "integers", "bool": "booleans"}


# ── helper self-tests (so the readers above cannot pass vacuously) ───────────


class _Leaf(BaseModel):
    x: int = 1


class _Holder(BaseModel):
    a: _Leaf | None = None
    b: tuple[_Leaf, ...] = ()
    c: dict[str, _Leaf] = {}


class _Probe(BaseModel):
    http2_enabled: bool = False
    extra: dict[str, str] = {}
    leaf: _Leaf = _Leaf()


def test_the_section_reader_ignores_hash_lines_inside_fences() -> None:
    text = "## A\nx\n```bash\n## not a heading\n# nor this\n```\ny\n## B\nz\n"
    sections = _sections(text, 2)
    assert list(sections) == ["A", "B"]
    assert "## not a heading" in sections["A"] and "y" in sections["A"]


def test_the_model_graph_walks_optional_and_container_annotations() -> None:
    assert _reachable_models(_Holder) == {_Holder, _Leaf}


def test_the_block_walker_keeps_dict_fields_whole_and_reads_digit_keys() -> None:
    block = "http2_enabled: false  # env: P_H2\nextra: {}\nleaf:\n  x: 1  # env: P_X\n"
    leaves, unknown = _block_leaves(_Probe, yaml.compose(block))
    assert unknown == []
    assert (
        set(leaves)
        == set(_model_leaves(_Probe))
        == {
            "http2_enabled",
            "extra",
            "leaf.x",
        }
    )
    assert _block_env_overrides(_Probe, block) == {
        "P_H2": "http2_enabled",
        "P_X": "leaf.x",
    }
    _, bad = _block_leaves(_Probe, yaml.compose("leaf: 3\nnope: 1\n"))
    assert bad == ["leaf (expected a mapping)", "nope"]


def test_the_recording_env_sees_every_access_path() -> None:
    env = _RecordingEnv({"A": "1"})
    _ = env.get("A"), env["A"], "B" in env
    assert env.read == ["A", "A", "B"]
    with pytest.raises(AssertionError):
        list(env)


# ── the settings block ───────────────────────────────────────────────────────


def test_settings_block_is_the_complete_file_at_its_built_in_defaults() -> None:
    block = _settings_block()
    leaves, unknown = _block_leaves(Settings, yaml.compose(block))
    assert unknown == [], f"keys DEPLOY.md names that Settings lacks: {unknown}"
    missing = sorted(set(_model_leaves(Settings)) - set(leaves))
    assert missing == [], f"settings keys missing from DEPLOY.md: {missing}"
    loaded = Settings(**(yaml.safe_load(block) or {}))
    assert _leaf_values(loaded) == _leaf_values(Settings())


def test_every_env_override_is_named_on_the_line_of_the_key_it_sets() -> None:
    declared = _block_env_overrides(Settings, _settings_block())
    read = _loader_reads()
    assert read, "the env loader read nothing — the probe is broken"
    assert set(declared) == read, (
        f"undocumented overrides: {sorted(read - set(declared))}; "
        f"documented but never read: {sorted(set(declared) - read)}"
    )
    for name, key in declared.items():
        assert _override_target(name)[0] == key, f"{name} does not set {key}"


def test_each_override_is_in_the_parse_bullet_of_its_field_kind() -> None:
    bullets = _bullets(_config_section())
    assert set(_KIND_BULLET.values()) <= set(bullets), sorted(bullets)
    leaves = _model_leaves(Settings)
    checked = 0
    for name in sorted(_loader_reads()):
        key, _ = _override_target(name)
        kind = _field_kind(leaves[key])
        holders = {b for b, text in bullets.items() if f"`{name}`" in text}
        expected = {_KIND_BULLET[kind]} if kind in _KIND_BULLET else set()
        assert holders == expected, f"{name} ({kind}) is in bullets {sorted(holders)}"
        checked += 1
    assert checked >= len(_KIND_BULLET)


def test_the_parse_bullets_hold_for_near_miss_values() -> None:
    bullets = _bullets(_config_section())
    tokens = [t for t in _BACKTICK.findall(bullets["booleans"]) if "CDMON_" not in t]
    assert tokens, "the booleans bullet lists no accepted tokens"
    leaves = _model_leaves(Settings)
    kinds_seen: set[str] = set()
    for name in sorted(_loader_reads()):
        key, sample = _override_target(name)
        kind = _field_kind(leaves[key])
        kinds_seen.add(kind)
        if kind == "bool":
            for token in tokens:
                for form in (token, token.upper(), token.title()):
                    got = settings_from_env(Settings(), {name: form})
                    assert _leaf_values(got)[key] is True, (name, form)
            near = {t[:i] for t in tokens for i in range(1, len(t))} - set(tokens)
            for miss in sorted(near | {"2", "enable", "0", "false", "off", "no"}):
                got = settings_from_env(Settings(), {name: miss})
                assert _leaf_values(got)[key] is False, (name, miss)
        elif kind == "int":
            for miss in ("1.5", "1e3", "seven"):
                with pytest.raises(ConfigError):
                    settings_from_env(Settings(), {name: miss})
        elif kind == "list":
            with pytest.raises(ConfigError):
                settings_from_env(Settings(), {name: ","})
            got = settings_from_env(Settings(), {name: f"{sample} , {sample}"})
            assert _leaf_values(got)[key] == (sample, sample), name
        # Any kind: an empty variable is ignored (the file or default stands).
        assert settings_from_env(Settings(), {name: ""}) == Settings(), name
    assert set(_KIND_BULLET) <= kinds_seen


def test_runbook_names_only_env_vars_that_are_read() -> None:
    named = set(_CDMON_NAME.findall(_doc()))
    assert named, "the runbook names no CDMON_* variable"
    known = _loader_reads() | _presence_reads() | _compose_names()
    assert named <= known, f"CDMON_* names nothing reads: {sorted(named - known)}"


def test_the_secrets_table_is_the_presence_checked_and_compose_only_secrets() -> None:
    table = _section(_config_section(), "Secrets", level=3)
    rows = set(re.findall(r"^\|\s*`(CDMON_[A-Z0-9_]+)`", table, re.MULTILINE))
    compose_only = _compose_names() - _loader_reads() - _presence_reads()
    assert rows == _presence_reads() | compose_only


def test_every_port_the_runbook_states_is_the_default_port() -> None:
    text = _doc()
    found = (
        re.findall(r"(?<![\w.]):(\d{2,5})\b", text)
        + re.findall(r"(?<!\w)localhost:(\d{2,5})\b", text)
        + re.findall(r"\b(\d{2,5}):\d{2,5}\b", text)
        + re.findall(r"\bport\s+(\d{2,5})\b", text, re.IGNORECASE)
        + re.findall(r"\bport:\s*(\d{2,5})\b", text)
    )
    assert found, "the runbook states no port"
    assert set(found) == {str(Settings().server.port)}


def test_the_stated_precedence_is_the_loaders(tmp_path: Path) -> None:
    m = re.search(r"\*\*([a-z -]+(?: > [a-z -]+)+)\*\*", _prose(_config_section()))
    assert m, "no bolded `a > b > c` precedence in the Configuration section"
    order = [part.strip() for part in m.group(1).split(">")]
    default = Settings().server.port
    path = tmp_path / "settings.yaml"
    path.write_text(f"server:\n  port: {default + 1}\n", encoding="utf-8")
    env = {"CDMON_SERVER_PORT": str(default + 2)}
    absent = tmp_path / "absent.yaml"
    layer_port = {
        "environment variable": default + 2,
        "file": default + 1,
        "built-in default": default,
    }
    assert sorted(order) == sorted(layer_port), order
    observed = [
        resolve_settings(path, env).server.port,
        resolve_settings(path, {}).server.port,
        resolve_settings(absent, {}).server.port,
    ]
    assert [layer_port[layer] for layer in order] == observed


def test_every_settings_key_the_prose_names_exists() -> None:
    leaves = set(_model_leaves(Settings))
    sections = {k.rsplit(".", 1)[0] for k in leaves} | {
        ".".join(k.split(".")[:i]) for k in leaves for i in range(1, k.count(".") + 1)
    }
    named = set(re.findall(r"\bserver(?:\.[a-z_][a-z0-9_]*)+", _prose(_doc())))
    assert named, "the prose names no server.* key"
    assert named <= leaves | sections, sorted(named - leaves - sections)


def test_every_settings_model_is_named_in_the_runbook() -> None:
    named = set(_BACKTICK.findall(_prose(_doc())))
    missing = sorted(m.__name__ for m in _reachable_models(Settings))
    assert [n for n in missing if n not in named] == []


# ── upgrading and the image ──────────────────────────────────────────────────


def _upgrade_lines() -> list[str]:
    """The upgrade block's commands, one per line, without comments or ``&&``."""
    blocks = _fenced(_section(_doc(), "Upgrading"), "bash")
    assert len(blocks) == 1, "the Upgrading section carries one bash block"
    lines = [ln.split("#", 1)[0].strip() for ln in blocks[0].split("\n")]
    lines = [ln.removesuffix("&&").strip() for ln in lines]
    return [ln for ln in lines if ln]


def test_upgrade_block_checks_out_a_fetched_release_before_any_build() -> None:
    section = _section(_doc(), "Upgrading")
    lines = _upgrade_lines()
    assert not any("git pull" in ln for ln in lines), "upgrade to a release, not main"

    def first(pred: Any, what: str) -> int:
        hits = [i for i, ln in enumerate(lines) if pred(ln)]
        assert hits, f"the upgrade block has no {what}"
        return hits[0]

    fetch = first(lambda ln: ln.startswith("git fetch") and "--tags" in ln, "fetch")
    checkout = first(lambda ln: ln.startswith("git checkout"), "checkout")
    target = lines[checkout].split()[-1]
    assert re.fullmatch(r"v(\d+|[A-Z])\.(\d+|[A-Z])\.(\d+|[A-Z])", target), target
    builds = [
        first(lambda ln: "pip install" in ln, "pip install"),
        first(lambda ln: "npm ci" in ln, "npm ci"),
        first(lambda ln: "npm run build" in ln, "console build"),
    ]
    assert fetch < checkout < min(builds)
    assert "frontend/dist" in _prose(section), "say why the console is rebuilt"


def _docker_instructions() -> list[tuple[str, str]]:
    """(stage, instruction line) for every non-comment Dockerfile line."""
    out: list[tuple[str, str]] = []
    stage = ""
    for raw in _DOCKERFILE.read_text("utf-8").split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"FROM\s+\S+\s+AS\s+(\S+)", line, re.IGNORECASE)
        if m:
            stage = m.group(1)
        out.append((stage, line))
    return out


def test_the_image_builds_the_console_and_copies_it_where_it_is_served(
    tmp_path: Path,
) -> None:
    from custodex.server.app import _default_static_dir

    ins = _docker_instructions()
    copy_from = [ln for _s, ln in ins if ln.startswith("COPY --from=")]
    assert len(copy_from) == 1, copy_from
    m = re.match(r"COPY --from=(\S+)\s+(\S+)\s+(\S+)", copy_from[0])
    assert m, copy_from[0]
    src_stage, src, dest = m.groups()

    stage_lines = [ln for s, ln in ins if s == src_stage]
    builds = [
        ln for ln in stage_lines if ln.startswith("RUN") and "npm run build" in ln
    ]
    assert builds, f"stage {src_stage!r} never runs the console build"
    workdir = [ln.split()[1] for ln in stage_lines if ln.startswith("WORKDIR")][-1]
    assert PurePosixPath(src) == PurePosixPath(workdir) / "dist"

    runtime = [ln for s, ln in ins if s != src_stage]
    app_dir = PurePosixPath(
        [ln.split()[1] for ln in runtime if ln.startswith("WORKDIR")][-1]
    )
    pkg = [ln.split() for ln in runtime if re.match(r"COPY\s+custodex\s", ln)]
    assert len(pkg) == 1, "the runtime copies the package once"
    pkg_dir = app_dir / pkg[0][2]
    (tmp_path / "frontend" / "dist").mkdir(parents=True)
    (tmp_path / "frontend" / "dist" / "index.html").write_text("x", encoding="utf-8")
    served = _default_static_dir(tmp_path)
    assert served is not None
    expected = pkg_dir.parent / served.relative_to(tmp_path).as_posix()
    assert app_dir / dest == expected

    ignored = _DOCKERIGNORE.read_text("utf-8").split("\n")
    assert "frontend/dist" in [ln.strip() for ln in ignored], (
        "a checkout's stale frontend/dist must never enter the build context"
    )


def test_every_settings_model_is_a_class_in_its_own_module_source() -> None:
    """Each model reachable from ``Settings`` is a top-level class of the module it
    is defined in, read from source (extraction never imports the target).

    The deploy unit selects each model under ITS OWN module's code_ref (the system
    test pins that mapping), so a model nested from another module, such as a
    backend config, is still tracked without that module moving into this unit.
    """
    import sys

    models = _reachable_models(Settings)
    assert Settings in models and len(models) > 1, "the model walk found no nesting"
    for model in sorted(models, key=lambda m: m.__name__):
        source = sys.modules[model.__module__].__file__
        assert source is not None, model
        tree = ast.parse(Path(source).read_text("utf-8"))
        defined = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
        assert model.__name__ in defined, f"{model.__name__} not in {source}"


# ── the parse rules, both ways ───────────────────────────────────────────────

# A probe vocabulary of plausible "truthy" spellings. It is NOT the expectation
# (that is the bullet's own token list); it only widens what is probed, so a token
# the loader accepts but the bullet omits is caught as well as the reverse.
_TRUTHY_PROBES = ("1", "2", "y", "t", "true", "yes", "on", "ok", "enable", "enabled")


def _one_line(text: str) -> str:
    return " ".join(_prose(text).split())


def test_the_booleans_bullet_is_exactly_the_tokens_the_loader_accepts() -> None:
    tokens = {
        t.lower()
        for t in _BACKTICK.findall(_bullets(_config_section())["booleans"])
        if "CDMON_" not in t
    }
    assert tokens, "the booleans bullet lists no accepted tokens"
    leaves = _model_leaves(Settings)
    checked = 0
    for name in sorted(_loader_reads()):
        key, _ = _override_target(name)
        if _field_kind(leaves[key]) != "bool":
            continue
        for probe in sorted(set(_TRUTHY_PROBES) | tokens):
            got = _leaf_values(settings_from_env(Settings(), {name: probe}))[key]
            assert got is (probe in tokens), (name, probe, got)
        checked += 1
    assert checked, "no boolean override found — the probe is broken"


def _with_leaf(key: str, value: Any) -> Settings:
    """``Settings()`` with the dotted leaf ``key`` set to ``value``."""
    data = Settings().model_dump()
    *path, leaf = key.split(".")
    node = data
    for part in path:
        node = node[part]
    node[leaf] = value
    return Settings(**data)


def test_a_list_override_replaces_a_non_empty_file_list() -> None:
    """Against a file that already lists the value, replace gives it once and an
    append would give it twice, which an empty default list could never show."""
    assert "replaces the file's list" in _bullets(_config_section())["lists"]
    leaves = _model_leaves(Settings)
    checked = 0
    for name in sorted(_loader_reads()):
        key, sample = _override_target(name)
        if _field_kind(leaves[key]) != "list":
            continue
        base = _with_leaf(key, (sample,))
        got = _leaf_values(settings_from_env(base, {name: sample}))[key]
        assert got == (sample,), (name, got)
        checked += 1
    assert checked, "no list override found — the probe is broken"


def test_the_empty_override_sentence_matches_the_loader() -> None:
    m = re.search(
        r"An override set to the empty string is ([a-z ]+?)[,.]",
        _one_line(_config_section()),
    )
    assert m, "the runbook no longer says what an empty override does"
    reads = sorted(_loader_reads())
    assert reads
    ignored = all(settings_from_env(Settings(), {n: ""}) == Settings() for n in reads)
    assert ignored == (m.group(1) == "ignored"), m.group(1)


def test_the_git_hosts_override_combines_as_the_runbook_says() -> None:
    from custodex.server.app import _allowed_git_hosts

    m = re.search(
        r"git-hosts override (are added to|replaces?) "
        r"\*\*server\.git\.allowed_hosts\*\*",
        _one_line(_config_section()),
    )
    assert m, "the runbook no longer states how the git-hosts override combines"
    name = next(
        n
        for n in sorted(_loader_reads())
        if _override_target(n)[0] == "server.git.extra_allowed_hosts"
    )
    base = Settings()
    probe = "probe.example"
    got = _allowed_git_hosts(settings_from_env(base, {name: probe}).server.git)
    additive = got == set(base.server.git.allowed_hosts) | {probe}
    assert additive == (m.group(1) == "are added to"), (m.group(1), sorted(got))


# ── what the file loader refuses ─────────────────────────────────────────────


def _nested_yaml(key: str, raw: str) -> str:
    """A settings file that sets the dotted leaf ``key`` to the YAML scalar ``raw``."""
    parts = key.split(".")
    lines = [f"{'  ' * i}{p}:" for i, p in enumerate(parts[:-1])]
    lines.append(f"{'  ' * (len(parts) - 1)}{parts[-1]}: {raw}")
    return "\n".join(lines) + "\n"


def _leaf_named(field: str) -> str:
    hits = [k for k in _model_leaves(Settings) if k.rsplit(".", 1)[-1] == field]
    assert len(hits) == 1, f"{field!r} names {hits} settings keys"
    return hits[0]


def _examples(sentence: str) -> list[tuple[str, str]]:
    """The ``key: value`` backtick examples in ``sentence``, as (dotted key, raw)."""
    out: list[tuple[str, str]] = []
    for span in _BACKTICK.findall(sentence):
        m = re.fullmatch(r"([a-z_][a-z0-9_]*): (.+)", span)
        if m:
            out.append((_leaf_named(m.group(1)), m.group(2)))
    return out


def test_the_validation_sentence_states_what_the_loader_refuses(
    tmp_path: Path,
) -> None:
    from custodex.settings import load_settings

    text = _one_line(_config_section())
    stops = re.search(r"([^.]*stops the server at startup[^.]*)\.", text)
    assert stops, "the runbook no longer says what stops the server at startup"
    assert stops.group(1).strip().startswith("An unknown key"), stops.group(1)
    path = tmp_path / "settings.yaml"
    path.write_text("server:\n  probe_unknown_key: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(path)
    refused = _examples(stops.group(1))
    assert len(refused) >= 2, "give a type example and a model-check example"
    for key, raw in refused:
        path.write_text(_nested_yaml(key, raw), encoding="utf-8")
        with pytest.raises(ConfigError):
            load_settings(path)

    converted = re.search(r"([^.]*is converted[^.]*)\.", text)
    assert converted, "the runbook no longer says a readable value is converted"
    accepted = _examples(converted.group(1))
    assert accepted
    for key, raw in accepted:
        path.write_text(_nested_yaml(key, raw), encoding="utf-8")
        got = _leaf_values(load_settings(path))[key]
        given = yaml.safe_load(raw)
        assert type(got) is not type(given) and str(got) == str(given), (key, got)

    unchecked = re.findall(r"\*\*(server\.[a-z_.]+)\*\* is not checked", text)
    assert unchecked, "say which key the loader does not check"
    for key in unchecked:
        path.write_text(_nested_yaml(key, "probe-not-a-real-value"), encoding="utf-8")
        assert _leaf_values(load_settings(path))[key] == "probe-not-a-real-value"


# ── the endpoints and the CLI summary ────────────────────────────────────────


def test_get_settings_returns_every_value_the_settings_block_shows() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from custodex.server.app import create_app

    assert "returns every value above" in _one_line(_config_section())
    # Move every leaf the env can move, so a dropped section cannot hide behind a
    # default that rebuilding the model would fill back in.
    env = {n: _override_target(n)[1] for n in sorted(_loader_reads())}
    effective = settings_from_env(Settings(), env)
    assert effective != Settings()
    host = effective.server.trusted_hosts[0]
    client = TestClient(create_app(settings=effective), base_url=f"http://{host}")
    resp = client.get("/settings")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"settings", "secrets"}
    assert body["settings"] == effective.model_dump(mode="json")
    secrets = body["secrets"]
    assert "whether each secret is configured" in _one_line(_config_section())
    assert set(secrets) == set(secret_presence({})), sorted(secrets)
    assert all(isinstance(v, bool) for v in secrets.values())


def _model_sections() -> set[str]:
    """Every dotted path at which a settings model nests (``server``, ...)."""
    return {
        ".".join(k.split(".")[:i])
        for k in _model_leaves(Settings)
        for i in range(1, k.count(".") + 1)
    }


def test_cdx_settings_summary_is_exactly_the_sections_the_runbook_names() -> None:
    from custodex.cli import _settings_lines

    m = re.search(
        r"prints a summary of the ([^.]+?) values", _one_line(_config_section())
    )
    assert m, "the runbook no longer describes the cdx settings summary"
    by_word = {s.rsplit(".", 1)[-1]: s for s in _model_sections()}
    words = [w for w in re.split(r",\s*|\s+and\s+", m.group(1)) if w]
    named = set()
    for word in words:
        norm = word.lower().replace("-", "_")
        assert norm in by_word, f"{word!r} names no settings section"
        named.add(by_word[norm])
    leaves = set(_model_leaves(Settings))
    presence = secret_presence({})
    shown = {
        key.rsplit(".", 1)[0]
        for line in _settings_lines(Settings(), presence)
        if (key := line.split(":", 1)[0]) in leaves
    }
    assert shown, "the summary shows no settings key — the probe is broken"
    assert shown == named


# ── the hardening claims ─────────────────────────────────────────────────────


def _numbered_items(section: str) -> list[str]:
    """``1.`` / ``2.`` list items (with continuation lines), joined to one line."""
    items: list[list[str]] = []
    for line in _prose(section).split("\n"):
        if re.match(r"^\d+\. ", line):
            items.append([line])
        elif items and line.startswith("   ") and line.strip():
            items[-1].append(line)
        elif items and not line.strip():
            items.append([])
    return [" ".join(" ".join(i).split()) for i in items if i]


def _hardening_item(marker: str) -> str:
    hits = [i for i in _numbered_items(_section(_doc(), "Hardening")) if marker in i]
    assert len(hits) == 1, f"expected one hardening item naming {marker!r}"
    return hits[0]


def _secret_rows() -> dict[str, str]:
    table = _section(_config_section(), "Secrets", level=3)
    return dict(
        re.findall(r"^\|\s*`(CDMON_[A-Z0-9_]+)`\s*\|(.*)$", table, re.MULTILINE)
    )


def test_the_compose_file_refuses_to_start_without_exactly_the_secrets_named() -> None:
    item = _hardening_item("refuses to start without")
    m = re.search(r"refuses to start without ([^.]+)\.", item)
    assert m, item
    named = set(_CDMON_NAME.findall(m.group(1)))
    guarded = set(re.findall(r"\$\{(CDMON_[A-Z0-9_]+):\?", _COMPOSE.read_text("utf-8")))
    assert named, "name the variables the compose file requires"
    assert named == guarded, (sorted(named), sorted(guarded))
    assert named <= set(_secret_rows())


def test_a_secret_row_says_it_falls_back_exactly_when_compose_defaults_it() -> None:
    compose = _COMPOSE.read_text("utf-8")
    rows = _secret_rows()
    assert rows
    for name, text in sorted(rows.items()):
        # Every interpolation must carry the default: one bare or ``:?`` use of
        # the name means compose no longer falls back for it.
        uses = re.findall(rf"\$\{{{name}(:[-?])?", compose)
        defaulted = bool(uses) and all(op == ":-" for op in uses)
        assert ("falls back to a placeholder" in text) == defaulted, (name, uses)


def test_the_file_scheme_item_claims_only_what_the_flag_gates(tmp_path: Path) -> None:
    """The flag refuses ``file://`` remotes; it does not gate a local_path
    registration, and a first registration carries no token. The item must say so
    exactly as the server behaves, so the old over-claim cannot come back."""
    pytest.importorskip("fastapi")
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    from custodex.server.app import _check_remote_allowed, create_app
    from custodex.server.store import InMemoryStore
    from custodex.settings import GitSettings, ServerSettings

    item = _hardening_item("**server.git.allow_file_scheme**")
    assert "`file://`" in item
    for allowed in (True, False):
        git = GitSettings(allow_file_scheme=allowed)
        try:
            _check_remote_allowed(f"file://{tmp_path}", git=git)
            refused = False
        except HTTPException as exc:
            refused = exc.status_code == 400
        assert refused is (not allowed)

    closed = Settings(server=ServerSettings(git=GitSettings(allow_file_scheme=False)))
    client = TestClient(create_app(InMemoryStore(), settings=closed))
    resp = client.post(
        "/repos", json={"repo": {"repo_id": "probe", "local_path": str(tmp_path)}}
    )
    accepted = resp.status_code == 201
    unchecked = re.search(r"local path .* is not checked", item) is not None
    open_first = "needs no token" in item
    assert unchecked == accepted, (unchecked, resp.status_code, resp.text)
    assert open_first == accepted, (open_first, resp.status_code)


# ── the background suggesters ───────────────────────────────────────────────


def _worker_kinds_dispatched() -> set[str]:
    """The kind strings ``_run_worker_pass`` dispatches on (``"x" in kinds``)."""
    import custodex.server.app as app_mod

    assert app_mod.__file__ is not None
    tree = ast.parse(Path(app_mod.__file__).read_text("utf-8"))
    funcs = [
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_run_worker_pass"
    ]
    assert len(funcs) == 1
    out: set[str] = set()
    for node in ast.walk(funcs[0]):
        if (
            isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Constant)
            and isinstance(node.left.value, str)
            and isinstance(node.ops[0], ast.In)
            and isinstance(node.comparators[0], ast.Name)
            and node.comparators[0].id == "kinds"
        ):
            out.add(node.left.value)
    return out


def _worker_kinds_accepted(extra: set[str]) -> set[str]:
    """The kinds ``WorkerSettings`` accepts, probed over every string literal in
    its class source plus ``extra`` (the validator keeps its vocabulary private)."""
    import sys

    from pydantic import ValidationError

    from custodex.settings import WorkerSettings

    source = sys.modules[WorkerSettings.__module__].__file__
    assert source is not None
    tree = ast.parse(Path(source).read_text("utf-8"))
    cls = [
        n
        for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == WorkerSettings.__name__
    ]
    assert len(cls) == 1
    probes = set(extra) | {
        n.value
        for n in ast.walk(cls[0])
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    accepted: set[str] = set()
    for probe in sorted(probes):
        try:
            WorkerSettings(kinds=(probe,))
        except ValidationError:
            continue
        accepted.add(probe)
    return accepted


def test_the_worker_kinds_the_runbook_lists_are_the_ones_accepted_and_run() -> None:
    m = re.search(
        r"\*\*server\.workers\.kinds\*\* picks which ones run \(([^)]*)\)",
        _one_line(_section(_doc(), "Health")),
    )
    assert m, "the runbook no longer lists the worker kinds"
    named = {w for w in re.split(r",\s*|\s+or\s+", m.group(1)) if w and w != "both"}
    dispatched = _worker_kinds_dispatched()
    accepted = _worker_kinds_accepted(named | dispatched)
    assert dispatched, "the worker pass dispatches no kind — the probe is broken"
    assert named == accepted == dispatched, (named, accepted, dispatched)


# ── the install the upgrade uses ─────────────────────────────────────────────


def test_the_upgrade_installs_the_checkout_in_place_like_the_image() -> None:
    """The server finds its console (``frontend/dist``) and migrations (``alembic``)
    two levels above the package, which only a source checkout has; a plain
    ``pip install .`` into site-packages would lose both. So the upgrade must be
    an editable install, the same one the image runs."""
    import custodex.server.app as app_mod

    assert app_mod.__file__ is not None
    checkout = Path(app_mod.__file__).resolve().parents[2]
    assert checkout == REPO_ROOT.resolve()
    assert (checkout / "alembic.ini").is_file() and (checkout / "frontend").is_dir()

    def install(line: str) -> tuple[bool, str]:
        words = line.split()
        i = words.index("install")
        args = words[i + 1 :]
        return ("-e" in args or "--editable" in args, args[-1])

    doc_lines = [ln for ln in _upgrade_lines() if ln.startswith("pip install")]
    image = [
        ln.strip()[len("RUN ") :]
        for _s, ln in _docker_instructions()
        if ln.startswith("RUN") and "pip install" in ln
    ]
    assert len(doc_lines) == 1 and len(image) == 1, (doc_lines, image)
    doc_install, image_install = install(doc_lines[0]), install(image[0])
    assert image_install[0], "the image itself must install editable"
    assert doc_install == image_install, (doc_lines[0], image[0])


# ── the upgrade commands, word by word ───────────────────────────────────────
# (tests/integration/test_deploy_shell_blocks.py runs the whole block for real.)


def test_the_upgrade_checkout_moves_to_the_tag_carrying_local_edits() -> None:
    """One ref and only ``--merge``: ``-b vX.Y.Z`` (a new branch at the OLD head)
    or ``-- vX.Y.Z`` (a path) would both keep the tag as the last word."""
    hits = [ln for ln in _upgrade_lines() if ln.startswith("git checkout")]
    assert len(hits) == 1, hits
    args = shlex.split(hits[0])[2:]
    refs = [a for a in args if not a.startswith("-")]
    flags = [a for a in args if a.startswith("-")]
    assert len(refs) == 1, args
    assert flags == ["--merge"], args


def test_the_console_build_runs_in_the_directory_that_holds_package_json() -> None:
    from custodex.server.app import _default_static_dir

    probe = REPO_ROOT / "frontend" / "dist"
    served = _default_static_dir(REPO_ROOT)
    front = (served if served is not None else probe).parent.relative_to(REPO_ROOT)
    assert (REPO_ROOT / front / "package.json").is_file()
    assert not (REPO_ROOT / "package.json").exists()
    npm = [ln for ln in _upgrade_lines() if "npm " in ln]
    assert npm, "the upgrade block runs no npm command"
    for ln in npm:
        cd = re.search(r"\bcd\s+(\S+)\s*&&", ln)
        assert cd and ln.index(cd.group(0)) < ln.index("npm "), ln
        assert PurePosixPath(cd.group(1)) == PurePosixPath(front.as_posix()), ln


def test_the_upgrade_checks_the_settings_file_after_install_before_the_build() -> None:
    lines = _upgrade_lines()
    checks = [
        i for i, ln in enumerate(lines) if shlex.split(ln)[:2] == ["cdx", "settings"]
    ]
    installs = [i for i, ln in enumerate(lines) if ln.startswith("pip install")]
    builds = [i for i, ln in enumerate(lines) if "npm " in ln]
    assert len(checks) == 1 and installs and builds, lines
    assert max(installs) < checks[0] < min(builds)
    text = _one_line(_section(_doc(), "Upgrading"))
    assert "`cdx settings`" in text and "stops" in text


def test_every_compose_up_in_the_upgrade_section_rebuilds_the_image() -> None:
    text = _one_line(_section(_doc(), "Upgrading"))
    ups = re.findall(r"`(docker compose up[^`]*)`", text)
    assert ups, "the upgrade section no longer says how to upgrade with Docker"
    assert all("--build" in u.split() for u in ups), ups


# ── the compose file, as the runbook describes it ────────────────────────────


def _compose() -> dict[str, Any]:
    data = yaml.safe_load(_COMPOSE.read_text("utf-8"))
    assert isinstance(data, dict)
    return data


def test_the_compose_file_sets_the_database_url_from_the_db_password() -> None:
    rows = _secret_rows()
    env = _compose()["services"]["server"]["environment"]
    url_row, pw_row = rows["CDMON_DATABASE_URL"], rows["CDMON_DB_PASSWORD"]
    assert ("The compose file sets it for you" in url_row) == (
        "CDMON_DATABASE_URL" in env
    )
    url = env.get("CDMON_DATABASE_URL", "")
    assert ("writes into the database URL" in pw_row) == (
        "${CDMON_DB_PASSWORD" in url
    ), url


def test_the_settings_file_is_mounted_read_only_where_the_server_reads_it() -> None:
    assert "mounted read-only in the" in _one_line(_config_section())
    workdir = [
        ln.split()[1] for _s, ln in _docker_instructions() if ln.startswith("WORKDIR")
    ][-1]
    target = (PurePosixPath(workdir) / DEFAULT_SETTINGS_PATH.as_posix()).as_posix()
    mounts = [
        v
        for v in _compose()["services"]["server"].get("volumes", [])
        if v.split(":")[1] == target
    ]
    assert len(mounts) == 1, mounts
    assert mounts[0].split(":")[2:] == ["ro"], mounts[0]


def _db_volume() -> str:
    """The named compose volume that holds the bundled Postgres data directory."""
    compose = _compose()
    named = set(compose.get("volumes") or {})
    vols = [v.split(":")[0] for v in compose["services"]["db"].get("volumes", [])]
    held = [v for v in vols if v in named]
    assert len(held) == 1, (vols, sorted(named))
    return held[0]


def test_the_reuse_paragraph_names_the_volume_and_user_compose_creates() -> None:
    """Postgres applies its password only when its data volume is first created
    (postgres-image behaviour, not run here); the paragraph must name the volume
    and the user the compose file actually uses, and that password must be the
    same variable the server's URL carries."""
    db_env = _compose()["services"]["db"]["environment"]
    url = _compose()["services"]["server"]["environment"]["CDMON_DATABASE_URL"]
    var = re.fullmatch(
        r"\$\{(CDMON_[A-Z0-9_]+)(:-[^}]*)?\}", db_env["POSTGRES_PASSWORD"]
    )
    assert var, db_env["POSTGRES_PASSWORD"]
    assert "${" + var.group(1) in url
    text = _one_line(_section(_config_section(), "Secrets", level=3))
    assert f"(`{_db_volume()}`) is first created" in text, text
    assert f"`ALTER USER {db_env['POSTGRES_USER']} PASSWORD" in text
    assert f"a new `{var.group(1)}`" in text


def test_a_new_kek_cannot_open_what_the_old_one_sealed() -> None:
    pytest.importorskip("cryptography")
    from custodex.errors import SecretError
    from custodex.secrets import SecretBox

    sealed = SecretBox(b"\x01" * 32).seal("probe-not-a-real-credential")
    try:
        SecretBox(b"\x02" * 32).open_secret(sealed)
        opened = True
    except SecretError:
        opened = False
    text = _one_line(_section(_config_section(), "Secrets", level=3))
    says = re.search(
        r"[Aa] new `CDMON_SECRET_KEY` cannot open .* sealed with the old one", text
    )
    assert (says is None) == opened, text
    assert "registered again" in text


def test_the_tldr_keeps_the_secrets_in_a_file_the_image_never_copies() -> None:
    """The TL;DR writes the secrets to ``.env``; no Dockerfile COPY may pick it up
    (a whole-context ``COPY .`` would bake the secrets into the image)."""
    tldr = _fenced(_section(_doc(), "TL;DR"), "bash")
    assert len(tldr) == 1 and "> .env" in tldr[0], tldr
    sources: list[str] = []
    for _stage, ln in _docker_instructions():
        if not ln.startswith("COPY "):
            continue
        words = shlex.split(ln)
        if words[0] == "COPY" and not any(w.startswith("--from") for w in words):
            sources += [w for w in words[1:-1] if not w.startswith("--")]
    assert sources, "the Dockerfile copies nothing — the probe is broken"
    for src in sources:
        norm = PurePosixPath(src).as_posix()
        assert norm not in (".", "./", ".env"), src
    assert "never commit it" in _one_line(_section(_doc(), "TL;DR"))


# ── the hardening items under compose ────────────────────────────────────────


def _healthcheck_url() -> str:
    test = _compose()["services"]["server"]["healthcheck"]["test"]
    found = re.findall(r"https?://[^'\"\s]+/health", " ".join(test))
    assert len(found) == 1, test
    return str(found[0])


def test_the_trusted_hosts_item_keeps_the_compose_healthcheck_working() -> None:
    pytest.importorskip("fastapi")
    from urllib.parse import urlsplit

    from fastapi.testclient import TestClient

    from custodex.server.app import create_app

    url = urlsplit(_healthcheck_url())
    probe_host = "probe-not-a-real-host.example"
    env = {"CDMON_TRUSTED_HOSTS": probe_host}
    alone = settings_from_env(Settings(), env)
    with_hc = settings_from_env(
        Settings(), {"CDMON_TRUSTED_HOSTS": f"{probe_host},{url.hostname}"}
    )
    base = f"{url.scheme}://{url.netloc}"
    assert (
        TestClient(create_app(settings=alone), base_url=base).get(url.path).status_code
        == 400
    )
    assert (
        TestClient(create_app(settings=with_hc), base_url=base)
        .get(url.path)
        .status_code
        == 200
    )
    item = _hardening_item("**server.trusted_hosts**")
    assert f"also list `{url.hostname}`" in item, item
    assert "healthcheck" in item


def test_the_loopback_item_publishes_the_compose_container_port() -> None:
    ports = _compose()["services"]["server"]["ports"]
    assert len(ports) == 1, ports
    container_port = str(ports[0]).rsplit(":", 1)[-1]
    item = _hardening_item("**server.host**")
    m = re.search(r"`127\.0\.0\.1:(\d+):(\d+)`", item)
    assert m, item
    assert m.group(2) == container_port == str(Settings().server.port)
    assert "without docker" in item.lower() and "under compose" in item.lower()


def _prose_units(text: str) -> list[str]:
    """Paragraphs and list items of the prose, each joined to one line."""
    units: list[list[str]] = [[]]
    for line in _prose(text).split("\n"):
        if not line.strip() or re.match(r"^(\d+\.|-) ", line):
            units.append([])
        if line.strip():
            units[-1].append(line)
    return [" ".join(" ".join(u).split()) for u in units if u]


def test_every_port_in_prose_names_the_key_that_owns_it() -> None:
    port = str(Settings().server.port)
    hits = [u for u in _prose_units(_doc()) if port in u]
    assert hits, "the prose quotes no port — the probe is broken"
    for unit in hits:
        assert "**server.port**" in unit, unit


# ── secret presence and the remaining stated defaults ────────────────────────


def test_cdx_settings_shows_the_same_secret_presence() -> None:
    from custodex.cli import _settings_lines

    assert "with the same secret presence" in _one_line(_config_section())
    presence = secret_presence({})
    shown = {
        ln.strip().split(":", 1)[0] for ln in _settings_lines(Settings(), presence)
    }
    assert set(presence) <= shown, sorted(set(presence) - shown)


def test_a_padded_boolean_token_matches_what_the_bullet_says() -> None:
    bullet = _bullets(_config_section())["booleans"]
    tokens = [t for t in _BACKTICK.findall(bullet) if "CDMON_" not in t]
    assert tokens
    trims = re.search(r"spaces around the value trimmed", bullet) is not None
    leaves = _model_leaves(Settings)
    checked = 0
    for name in sorted(_loader_reads()):
        key, _ = _override_target(name)
        if _field_kind(leaves[key]) != "bool":
            continue
        for tok in tokens:
            got = _leaf_values(settings_from_env(Settings(), {name: f" {tok} "}))[key]
            assert got is trims, (name, tok, got, trims)
        checked += 1
    assert checked


def test_the_suggesters_default_stated_in_prose_is_the_model_default() -> None:
    text = _one_line(_section(_doc(), "Health"))
    m = re.search(r"\*\*Background suggesters\*\* are (on|off) by default", text)
    assert m, "the runbook no longer states the suggesters' default"
    assert (m.group(1) == "on") is Settings().server.workers.enabled
    assert "**server.workers.enabled**" in text


def test_the_liveness_probe_answers_what_the_runbook_shows() -> None:
    pytest.importorskip("fastapi")
    import json

    from fastapi.testclient import TestClient

    from custodex.server.app import create_app

    m = re.search(
        r"`GET (/\S+)` → `(\{[^`]*\})` \(unauthenticated\)", _one_line(_doc())
    )
    assert m, "the runbook no longer shows the liveness probe"
    resp = TestClient(create_app(settings=Settings())).get(m.group(1))
    assert resp.status_code == 200
    assert resp.json() == json.loads(m.group(2))
