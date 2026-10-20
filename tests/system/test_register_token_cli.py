"""SRV-TOKEN — `cdx register` can set or rotate a repo token.

Before this slice `cdx register` never sent an ``auth_token``, so every
CLI-registered repo was OPEN. Now:

- ``--auth-token-env VAR`` registers the repo token-protected with ``$VAR``. That
  token must be EXACTLY the one ``$central.auth_env`` holds — the bearer this
  config's next register and http sink present — or the repo would lock out its
  own writes. When it is not, the error says why (unset / padded / different) and
  names both remedies (for a new repo, put it in ``$auth_env``; to change a
  protected repo's token, ``--rotate-to-env``).
- ``--rotate-to-env VAR`` rotates to ``$VAR`` while presenting the CURRENT token
  from ``$central.auth_env``. Re-running it once ``$central.auth_env`` holds the
  new token CONVERGES (K7): it is an ordinary protected re-register that the
  server verifies with that token, and the output says the token is already the
  one presented. The success line says what was SENT ("registered with the new
  token"), never "rotated": an open or unknown repo has no old token to check.
- The two flags are mutually exclusive; an unset/empty/padded/non-printable-ASCII
  token is a loud ``SchemaError`` (``bearer_token_problem`` / ``token_from_env``),
  never an open register; a dry run redacts the token to ``***``.
- With no flag the payload and output are byte-identical to before.

The end-to-end tests drive the real CLI against the real app over ``TestClient``
(the one urlopen leaf is bridged in-process — no socket, K4).

Features: FEAT-SERVER-021
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

import custodex.registry as registry_mod
from custodex.cli import app
from custodex.errors import SchemaError
from custodex.registry import (
    RegistrationPayload,
    bearer_token_problem,
    register_repo,
    token_from_env,
)
from custodex.sinks import RepoIdentity

runner = CliRunner()

_URL = "https://central.example"
_REPO = "acme/widget"
_ENV_VARS = ("CDM_TOKEN", "NEW_TOKEN", "OTHER")


def _write_config(tmp_path: Path, *, auth_env: str | None = "CDM_TOKEN") -> Path:
    central = f'central:\n  sink: "http"\n  url: "{_URL}"\n'
    if auth_env is not None:
        central += f'  auth_env: "{auth_env}"\n'
    central += (
        f'  repo_id: "{_REPO}"\n  repo_name: "widget"\n  repo_commit: "cafef00d"\n'
    )
    cfg = (
        'version: "1.0.0"\n'
        'root: "."\n'
        "documents:\n"
        '  - id: "guide"\n'
        '    path: "guide.md"\n'
        '    audience: "eng-guide"\n'
        "    code_refs:\n"
        '      - path: "code.py"\n'
        '    region_keys: ["symbols"]\n'
        "backend:\n"
        '  kind: "mock"\n' + central
    )
    path = tmp_path / "cdmon.yaml"
    path.write_text(cfg, encoding="utf-8")
    return path


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    return monkeypatch


Sent = list[tuple[str, str, dict | None]]


def _stub_leaf(monkeypatch: pytest.MonkeyPatch) -> Sent:
    """Record every request the default transport would send (nothing leaves)."""
    sent: Sent = []

    def fake_request(
        self: object, method: str, url: str, *, body: dict | None, token: str
    ) -> dict:
        sent.append((url, token, body))
        return {"repo_id": _REPO}

    monkeypatch.setattr(registry_mod._UrllibRegisterHttp, "request", fake_request)
    return sent


# --------------------------------------------------------------------------- #
# back-compat: no flag → unchanged
# --------------------------------------------------------------------------- #
def test_register_without_a_token_flag_stays_open_as_before(
    tmp_path: Path, env: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path)
    env.setenv("CDM_TOKEN", "cur")
    sent = _stub_leaf(env)
    result = runner.invoke(app, ["register"])
    assert result.exit_code == 0, result.output
    assert result.output == f"registered {_REPO} with {_URL}\n"
    assert len(sent) == 1
    url, token, body = sent[0]
    assert (url, token) == (f"{_URL}/repos", "cur")
    assert body is not None and body["auth_token"] is None


def test_dry_run_without_a_token_is_unchanged(
    tmp_path: Path, env: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path)
    result = runner.invoke(app, ["register", "--dry-run"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["auth_token"] is None
    assert payload["repo"]["repo_id"] == _REPO


# --------------------------------------------------------------------------- #
# --auth-token-env
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "var", ["CDM_TOKEN", "NEW_TOKEN"], ids=["same-var", "same-value"]
)
def test_register_with_auth_token_env_sends_the_token(
    tmp_path: Path, env: pytest.MonkeyPatch, var: str
) -> None:
    _write_config(tmp_path)
    env.setenv("CDM_TOKEN", "tok-1")
    env.setenv(var, "tok-1")
    sent = _stub_leaf(env)
    result = runner.invoke(app, ["register", "--auth-token-env", var])
    assert result.exit_code == 0, result.output
    assert result.output == f"registered {_REPO} with {_URL} (token-protected)\n"
    assert [(t, b["auth_token"] if b else None) for _, t, b in sent] == [
        ("tok-1", "tok-1")
    ]


@pytest.mark.parametrize("flag", ["--auth-token-env", "--rotate-to-env"])
@pytest.mark.parametrize(
    "value",
    [None, "", "   ", " padded", "tok€n"],
    ids=["unset", "empty", "blank", "padded", "non-ascii"],
)
def test_an_unusable_token_env_is_loud_and_sends_nothing(
    tmp_path: Path, env: pytest.MonkeyPatch, flag: str, value: str | None
) -> None:
    _write_config(tmp_path)
    env.setenv("CDM_TOKEN", "cur")
    if value is not None:
        env.setenv("NEW_TOKEN", value)
    sent = _stub_leaf(env)
    result = runner.invoke(app, ["register", flag, "NEW_TOKEN"])
    assert result.exit_code == 1, result.output
    assert "error:" in result.output
    assert "$NEW_TOKEN" in result.output
    assert "Traceback" not in result.output
    if value and value.strip():
        assert value.strip() not in result.output
    assert sent == []


def test_a_blank_token_env_is_reported_as_empty(
    tmp_path: Path, env: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path)
    env.setenv("NEW_TOKEN", "  ")
    result = runner.invoke(app, ["register", "--auth-token-env", "NEW_TOKEN"])
    assert result.exit_code == 1
    assert "is empty" in result.output


@pytest.mark.parametrize("dry", [False, True], ids=["submit", "dry-run"])
def test_auth_token_env_without_a_configured_auth_env_is_loud(
    tmp_path: Path, env: pytest.MonkeyPatch, dry: bool
) -> None:
    _write_config(tmp_path, auth_env=None)
    env.setenv("NEW_TOKEN", "tok-1")
    sent = _stub_leaf(env)
    args = ["register", "--auth-token-env", "NEW_TOKEN"] + (
        ["--dry-run"] if dry else []
    )
    result = runner.invoke(app, args)
    assert result.exit_code == 1, result.output
    assert "central.auth_env" in result.output
    assert "lock" in result.output
    assert sent == []


@pytest.mark.parametrize("held", [None, "other-token"], ids=["unset", "different"])
def test_auth_token_env_that_is_not_the_configured_bearer_is_loud(
    tmp_path: Path, env: pytest.MonkeyPatch, held: str | None
) -> None:
    _write_config(tmp_path)
    env.setenv("NEW_TOKEN", "tok-1")
    if held is not None:
        env.setenv("CDM_TOKEN", held)
    sent = _stub_leaf(env)
    result = runner.invoke(app, ["register", "--auth-token-env", "NEW_TOKEN"])
    assert result.exit_code == 1, result.output
    out = " ".join(result.output.split())
    assert "$CDM_TOKEN" in out
    assert ("is not set" if held is None else "different token") in out
    assert "--auth-token-env CDM_TOKEN" in out
    assert "--rotate-to-env" in out
    assert "Traceback" not in out
    assert sent == []


@pytest.mark.parametrize(
    "held", ["tok-1\n", "tok-1\r\n", " tok-1"], ids=["trail-lf", "trail-crlf", "lead"]
)
def test_a_padded_configured_bearer_is_not_the_registered_token(
    tmp_path: Path, env: pytest.MonkeyPatch, held: str
) -> None:
    _write_config(tmp_path)
    env.setenv("NEW_TOKEN", "tok-1")
    env.setenv("CDM_TOKEN", held)
    sent = _stub_leaf(env)
    result = runner.invoke(app, ["register", "--auth-token-env", "NEW_TOKEN"])
    assert result.exit_code == 1, result.output
    out = " ".join(result.output.split())
    assert "$CDM_TOKEN" in out
    assert "leading/trailing whitespace" in out
    assert "different token" not in out
    assert "Traceback" not in out
    assert sent == []


def test_dry_run_redacts_the_token(tmp_path: Path, env: pytest.MonkeyPatch) -> None:
    _write_config(tmp_path)
    env.setenv("CDM_TOKEN", "zz-distinct-tok")
    sent = _stub_leaf(env)
    result = runner.invoke(
        app, ["register", "--auth-token-env", "CDM_TOKEN", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["auth_token"] == "***"
    assert "zz-distinct-tok" not in result.output
    assert sent == []


def test_the_two_token_flags_are_mutually_exclusive(
    tmp_path: Path, env: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path)
    env.setenv("CDM_TOKEN", "a")
    env.setenv("NEW_TOKEN", "b")
    sent = _stub_leaf(env)
    result = runner.invoke(
        app,
        ["register", "--auth-token-env", "CDM_TOKEN", "--rotate-to-env", "NEW_TOKEN"],
    )
    assert result.exit_code == 1
    assert "mutually exclusive" in result.output
    assert sent == []


def test_the_auth_token_env_help_points_to_rotation() -> None:
    result = runner.invoke(app, ["register", "--help"], env={"COLUMNS": "200"})
    assert result.exit_code == 0
    flat = " ".join(result.output.replace("\u2502", " ").split())
    assert "--auth-token-env" in flat
    assert "To CHANGE a protected repo's token use --rotate-to-env instead" in flat
    assert "presenting the current token from $central.auth_env" in flat


# --------------------------------------------------------------------------- #
# --rotate-to-env
# --------------------------------------------------------------------------- #
def test_rotate_sends_the_current_bearer_and_the_new_token(
    tmp_path: Path, env: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path)
    env.setenv("CDM_TOKEN", "old-tok")
    env.setenv("NEW_TOKEN", "new-tok")
    sent = _stub_leaf(env)
    result = runner.invoke(app, ["register", "--rotate-to-env", "NEW_TOKEN"])
    assert result.exit_code == 0, result.output
    assert result.output == (
        f"registered {_REPO} with {_URL} "
        "(registered with the new token; set $CDM_TOKEN to it)\n"
    )
    assert [(t, b["auth_token"] if b else None) for _, t, b in sent] == [
        ("old-tok", "new-tok")
    ]


@pytest.mark.parametrize(
    "current",
    [None, "", " old", "old\n", "old\r\n"],
    ids=["unset", "empty", "lead", "trail-lf", "trail-crlf"],
)
def test_rotate_without_a_usable_current_bearer_is_loud(
    tmp_path: Path, env: pytest.MonkeyPatch, current: str | None
) -> None:
    _write_config(tmp_path)
    if current is not None:
        env.setenv("CDM_TOKEN", current)
    env.setenv("NEW_TOKEN", "new-tok")
    sent = _stub_leaf(env)
    result = runner.invoke(app, ["register", "--rotate-to-env", "NEW_TOKEN"])
    assert result.exit_code == 1, result.output
    assert "$CDM_TOKEN" in result.output
    assert "current" in result.output
    assert "Traceback" not in result.output
    assert sent == []


def test_rotate_without_a_configured_auth_env_is_loud(
    tmp_path: Path, env: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, auth_env=None)
    env.setenv("NEW_TOKEN", "new-tok")
    sent = _stub_leaf(env)
    result = runner.invoke(app, ["register", "--rotate-to-env", "NEW_TOKEN"])
    assert result.exit_code == 1
    assert "central.auth_env" in result.output
    assert sent == []


def test_rotate_dry_run_also_requires_the_current_bearer(
    tmp_path: Path, env: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path)
    env.setenv("NEW_TOKEN", "new-tok")
    result = runner.invoke(
        app, ["register", "--rotate-to-env", "NEW_TOKEN", "--dry-run"]
    )
    assert result.exit_code == 1
    assert "$CDM_TOKEN" in result.output


def test_rotate_dry_run_redacts_the_new_token(
    tmp_path: Path, env: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path)
    env.setenv("CDM_TOKEN", "zz-old-tok")
    env.setenv("NEW_TOKEN", "zz-new-tok")
    sent = _stub_leaf(env)
    result = runner.invoke(
        app, ["register", "--rotate-to-env", "NEW_TOKEN", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["auth_token"] == "***"
    assert "zz-old-tok" not in result.output
    assert "zz-new-tok" not in result.output
    assert sent == []


@pytest.mark.parametrize("var", ["CDM_TOKEN", "NEW_TOKEN"])
def test_re_running_a_finished_rotation_converges(
    tmp_path: Path, env: pytest.MonkeyPatch, var: str
) -> None:
    # $central.auth_env already holds the new token: the rotation is done, so the
    # re-run is an ordinary protected re-register presenting that token (K7)
    _write_config(tmp_path)
    env.setenv("CDM_TOKEN", "same")
    env.setenv("NEW_TOKEN", "same")
    sent = _stub_leaf(env)
    result = runner.invoke(app, ["register", "--rotate-to-env", var])
    assert result.exit_code == 0, result.output
    assert result.output == (
        f"registered {_REPO} with {_URL} "
        "(registered with the new token, which $CDM_TOKEN already presents)\n"
    )
    assert [(t, b["auth_token"] if b else None) for _, t, b in sent] == [
        ("same", "same")
    ]


def test_the_dry_run_help_says_a_token_flag_still_validates() -> None:
    """--dry-run needs no url, but a token flag still checks the tokens first."""
    result = runner.invoke(app, ["register", "--help"])
    flat = " ".join(result.output.replace("│", " ").split())
    assert "no url/token required" not in flat
    assert "a token flag still validates the tokens" in flat


def test_the_rotate_help_names_the_re_run() -> None:
    result = runner.invoke(app, ["register", "--help"])
    flat = " ".join(result.output.replace("│", " ").split())
    assert "re-running it" in flat


# --------------------------------------------------------------------------- #
# library-level: bearer_token_problem / token_from_env / register_repo
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("token", "fragment"),
    [
        ("", "is empty"),
        ("  ", "is empty"),
        (" x", "leading/trailing whitespace"),
        ("x\n", "leading/trailing whitespace"),
        ("a b", "whitespace, control or non-ASCII"),
        ("a\tb", "whitespace, control or non-ASCII"),
        ("a\x00b", "whitespace, control or non-ASCII"),
        ("tok€n", "whitespace, control or non-ASCII"),
        ("del\x7f", "whitespace, control or non-ASCII"),
    ],
)
def test_bearer_token_problem_names_what_is_wrong(token: str, fragment: str) -> None:
    problem = bearer_token_problem(token)
    assert problem is not None
    assert fragment in problem
    assert "printable ASCII" in problem


def test_bearer_token_problem_accepts_every_printable_ascii_char() -> None:
    assert bearer_token_problem("".join(chr(c) for c in range(0x21, 0x7F))) is None
    assert bearer_token_problem("a") is None


@pytest.mark.parametrize(
    "value", ["", " x", "x\n", "a b", "tok€n", "a\rb"], ids=lambda v: repr(v)
)
def test_token_from_env_holds_the_bearer_charset(
    env: pytest.MonkeyPatch, value: str
) -> None:
    env.setenv("NEW_TOKEN", value)
    with pytest.raises(SchemaError, match=r"\$NEW_TOKEN"):
        token_from_env("NEW_TOKEN")


def test_a_set_but_empty_token_env_is_reported_as_empty_not_unset(
    env: pytest.MonkeyPatch,
) -> None:
    env.setenv("NEW_TOKEN", "")
    with pytest.raises(SchemaError) as info:
        token_from_env("NEW_TOKEN")
    msg = str(info.value)
    assert "is empty" in msg
    assert "not set" not in msg


def test_a_set_but_empty_auth_token_env_is_reported_as_empty_on_the_cli(
    tmp_path: Path, env: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path)
    env.setenv("NEW_TOKEN", "")
    sent = _stub_leaf(env)
    result = runner.invoke(app, ["register", "--auth-token-env", "NEW_TOKEN"])
    assert result.exit_code == 1
    flat = " ".join(result.output.split())
    assert "$NEW_TOKEN is empty" in flat
    assert "not set" not in flat
    assert sent == []


def test_token_from_env_reads_and_never_echoes(env: pytest.MonkeyPatch) -> None:
    env.setenv("NEW_TOKEN", "good-tok")
    assert token_from_env("NEW_TOKEN") == "good-tok"
    with pytest.raises(SchemaError, match="not set"):
        token_from_env("OTHER", what="the widget token")
    env.setenv("NEW_TOKEN", "zz distinct zz")
    with pytest.raises(SchemaError) as info:
        token_from_env("NEW_TOKEN", what="the widget token")
    assert "zz distinct zz" not in str(info.value)
    assert "the widget token" in str(info.value)


class _FakeTransport:
    def __init__(self) -> None:
        self.payloads: list[RegistrationPayload] = []

    def register(self, payload: RegistrationPayload) -> dict:
        self.payloads.append(payload)
        return {"repo_id": payload.repo.repo_id}


def _identity() -> RepoIdentity:
    return RepoIdentity(repo_id=_REPO)


@pytest.mark.parametrize("rotate", [False, True], ids=["register", "rotate"])
@pytest.mark.parametrize(
    "token", ["", " x", "a b", "tok€n"], ids=["empty", "padded", "space", "na"]
)
def test_register_repo_refuses_an_unusable_auth_token(
    env: pytest.MonkeyPatch, rotate: bool, token: str
) -> None:
    env.setenv("CDM_TOKEN", "cur")
    transport = _FakeTransport()
    with pytest.raises(SchemaError, match="printable ASCII"):
        register_repo(
            _identity(),
            url=_URL,
            auth_env="CDM_TOKEN",
            transport=transport,
            auth_token=token,
            rotate=rotate,
        )
    assert transport.payloads == []


def test_register_repo_rotate_needs_the_new_token(env: pytest.MonkeyPatch) -> None:
    env.setenv("CDM_TOKEN", "cur")
    transport = _FakeTransport()
    with pytest.raises(SchemaError, match="new token"):
        register_repo(
            _identity(),
            url=_URL,
            auth_env="CDM_TOKEN",
            transport=transport,
            rotate=True,
        )
    assert transport.payloads == []


def test_register_repo_rotate_through_an_injected_transport(
    env: pytest.MonkeyPatch,
) -> None:
    env.setenv("CDM_TOKEN", "cur")
    transport = _FakeTransport()
    register_repo(
        _identity(),
        url=_URL,
        auth_env="CDM_TOKEN",
        transport=transport,
        auth_token="next",
        rotate=True,
    )
    assert [p.auth_token for p in transport.payloads] == ["next"]


@pytest.mark.parametrize("injected", [True, False], ids=["injected", "default"])
def test_register_repo_rotation_to_the_presented_token_converges(
    env: pytest.MonkeyPatch, injected: bool
) -> None:
    # the rotation already happened: re-sending it is a plain protected re-register
    env.setenv("CDM_TOKEN", "cur")
    if injected:
        transport = _FakeTransport()
        register_repo(
            _identity(),
            url=_URL,
            auth_env="CDM_TOKEN",
            transport=transport,
            auth_token="cur",
            rotate=True,
        )
        assert [p.auth_token for p in transport.payloads] == ["cur"]
        return
    sent = _stub_leaf(env)
    register_repo(
        _identity(), url=_URL, auth_env="CDM_TOKEN", auth_token="cur", rotate=True
    )
    assert [(t, b["auth_token"] if b else None) for _, t, b in sent] == [("cur", "cur")]


def test_an_injected_transport_owns_its_bearer(env: pytest.MonkeyPatch) -> None:
    # no auth_env, nothing in the environment: the injected transport presents
    # its own bearer, so the lock-out check (a default-transport property) is skipped
    transport = _FakeTransport()
    register_repo(_identity(), url=_URL, transport=transport, auth_token="tok")
    assert [p.auth_token for p in transport.payloads] == ["tok"]


# --------------------------------------------------------------------------- #
# end to end: the real CLI against the real app (TestClient, no socket)
# --------------------------------------------------------------------------- #
_needs_server = pytest.mark.skipif(
    importlib.util.find_spec("fastapi") is None,
    reason="the [server] extra (fastapi) is not installed",
)


def _bridge(monkeypatch: pytest.MonkeyPatch, client: object) -> Callable[[], list[int]]:
    """Route the register leaf into ``client``; a 4xx raises like urlopen does."""
    statuses: list[int] = []

    def fake_request(
        self: object, method: str, url: str, *, body: dict | None, token: str
    ) -> dict:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        resp = client.request(  # type: ignore[attr-defined]
            method, url.removeprefix(_URL), json=body, headers=headers
        )
        statuses.append(resp.status_code)
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
        return resp.json()

    monkeypatch.setattr(registry_mod._UrllibRegisterHttp, "request", fake_request)
    return lambda: statuses


def _real_app() -> tuple[object, object]:
    from fastapi.testclient import TestClient

    from custodex.server import InMemoryStore, create_app

    store = InMemoryStore()
    return store, TestClient(create_app(store, admin_token="adm"))


@_needs_server
def test_cli_set_then_rotate_against_the_real_server(
    tmp_path: Path, env: pytest.MonkeyPatch
) -> None:
    from custodex.server.store import hash_token

    store, client = _real_app()
    statuses = _bridge(env, client)
    _write_config(tmp_path)

    env.setenv("CDM_TOKEN", "first")
    assert (
        runner.invoke(app, ["register", "--auth-token-env", "CDM_TOKEN"]).exit_code == 0
    )
    assert store.repo_token_hash(_REPO) == hash_token("first")  # type: ignore[attr-defined]
    # re-running the identical command is a no-op (K7)
    assert (
        runner.invoke(app, ["register", "--auth-token-env", "CDM_TOKEN"]).exit_code == 0
    )
    assert store.repo_token_hash(_REPO) == hash_token("first")  # type: ignore[attr-defined]

    # a rotation presenting the WRONG current bearer is refused; nothing moves
    env.setenv("CDM_TOKEN", "wrong")
    env.setenv("NEW_TOKEN", "second")
    refused = runner.invoke(app, ["register", "--rotate-to-env", "NEW_TOKEN"])
    assert refused.exit_code == 1
    assert statuses()[-1] == 403
    assert store.repo_token_hash(_REPO) == hash_token("first")  # type: ignore[attr-defined]

    env.setenv("CDM_TOKEN", "first")
    rotated = runner.invoke(app, ["register", "--rotate-to-env", "NEW_TOKEN"])
    assert rotated.exit_code == 0, rotated.output
    assert "registered with the new token; set $CDM_TOKEN to it" in rotated.output
    assert store.repo_token_hash(_REPO) == hash_token("second")  # type: ignore[attr-defined]

    # following the printed next step keeps the config able to register
    env.setenv("CDM_TOKEN", "second")
    again = runner.invoke(app, ["register", "--auth-token-env", "CDM_TOKEN"])
    assert again.exit_code == 0, again.output
    assert store.repo_token_hash(_REPO) == hash_token("second")  # type: ignore[attr-defined]


@_needs_server
def test_a_protected_register_leaves_the_config_able_to_write(
    tmp_path: Path, env: pytest.MonkeyPatch
) -> None:
    from custodex.config import load_config
    from custodex.schema import ProposedFix, ReviewRecord, Verdict
    from custodex.server.store import hash_token
    from custodex.sinks import HttpSink

    store, client = _real_app()
    _bridge(env, client)
    config_path = _write_config(tmp_path)
    env.setenv("CDM_TOKEN", "tok-1")
    for _ in range(2):
        result = runner.invoke(app, ["register", "--auth-token-env", "CDM_TOKEN"])
        assert result.exit_code == 0, result.output
    assert store.repo_token_hash(_REPO) == hash_token("tok-1")  # type: ignore[attr-defined]

    class _Post:
        def post(self, url: str, *, data: bytes, headers: dict[str, str]) -> None:
            resp = client.post(  # type: ignore[attr-defined]
                url.removeprefix(_URL), content=data, headers=headers
            )
            if resp.status_code >= 400:
                raise RuntimeError(resp.text)

    cfg = load_config(config_path)
    outbox = tmp_path / "outbox.jsonl"
    sink = HttpSink(
        f"{_URL}/ingest",
        cfg.central.auth_env,
        repo=RepoIdentity(repo_id=_REPO),
        outbox=outbox,
        client=_Post(),
    )
    sink.emit(
        ReviewRecord(
            record_id="r-sink",
            doc_id="guide",
            doc_path="guide.md",
            audience="eng-guide",
            drift_kind="REGION",
            drift_detail="d",
            cause="c",
            verdict=Verdict.FIX,
            fix=ProposedFix(rationale="r"),
            surface_hash="0" * 16,
            backend_kind="mock",
            detected_at="2026-06-05T00:00:00Z",
            resolved_at="2026-06-05T00:00:00Z",
            config_snapshot={},
            source_sha="cafebabe",
        )
    )
    assert [r.record_id for r in store.records_for(_REPO)] == ["r-sink"]  # type: ignore[attr-defined]
    assert not outbox.exists() or outbox.read_text(encoding="utf-8") == ""


@_needs_server
def test_the_lock_out_hint_leads_to_a_working_rotation(
    tmp_path: Path, env: pytest.MonkeyPatch
) -> None:
    from custodex.server.store import hash_token

    store, client = _real_app()
    _bridge(env, client)
    _write_config(tmp_path)
    env.setenv("CDM_TOKEN", "old")
    assert (
        runner.invoke(app, ["register", "--auth-token-env", "CDM_TOKEN"]).exit_code == 0
    )

    env.setenv("NEW_TOKEN", "new")
    refused = runner.invoke(app, ["register", "--auth-token-env", "NEW_TOKEN"])
    assert refused.exit_code == 1
    assert "--rotate-to-env" in " ".join(refused.output.split())
    assert store.repo_token_hash(_REPO) == hash_token("old")  # type: ignore[attr-defined]

    followed = runner.invoke(app, ["register", "--rotate-to-env", "NEW_TOKEN"])
    assert followed.exit_code == 0, followed.output
    assert store.repo_token_hash(_REPO) == hash_token("new")  # type: ignore[attr-defined]


@_needs_server
def test_re_running_a_rotation_after_updating_auth_env_converges(
    tmp_path: Path, env: pytest.MonkeyPatch
) -> None:
    from custodex.server.store import hash_token

    store, client = _real_app()
    statuses = _bridge(env, client)
    _write_config(tmp_path)
    env.setenv("CDM_TOKEN", "first")
    assert (
        runner.invoke(app, ["register", "--auth-token-env", "CDM_TOKEN"]).exit_code == 0
    )
    env.setenv("NEW_TOKEN", "second")
    first = runner.invoke(app, ["register", "--rotate-to-env", "NEW_TOKEN"])
    assert first.exit_code == 0, first.output
    assert store.repo_token_hash(_REPO) == hash_token("second")  # type: ignore[attr-defined]

    # the printed next step, then the SAME rotation command again: it converges
    env.setenv("CDM_TOKEN", "second")
    for _ in range(2):
        again = runner.invoke(app, ["register", "--rotate-to-env", "NEW_TOKEN"])
        assert again.exit_code == 0, again.output
        assert "already presents" in again.output
        assert statuses()[-1] == 201
        assert store.repo_token_hash(_REPO) == hash_token("second")  # type: ignore[attr-defined]


@_needs_server
def test_a_rotation_on_an_unknown_repo_does_not_claim_a_rotation(
    tmp_path: Path, env: pytest.MonkeyPatch
) -> None:
    # an unknown repo has no old token: the $central.auth_env bearer is never
    # checked, so the output says what was sent, never "rotated"
    from custodex.server.store import hash_token

    store, client = _real_app()
    _bridge(env, client)
    _write_config(tmp_path)
    env.setenv("CDM_TOKEN", "x1")
    env.setenv("NEW_TOKEN", "x2")
    result = runner.invoke(app, ["register", "--rotate-to-env", "NEW_TOKEN"])
    assert result.exit_code == 0, result.output
    assert "rotated" not in result.output
    assert "registered with the new token" in result.output
    assert store.repo_token_hash(_REPO) == hash_token("x2")  # type: ignore[attr-defined]
