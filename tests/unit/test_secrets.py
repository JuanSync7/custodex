"""GIT-01 — at-rest secret sealing (AES-256-GCM) + the K0 lazy-extra boundary.

:mod:`code_doc_monitor.secrets` seals a per-repo provider credential at rest. A
git credential must be REPLAYED, so it is ENCRYPTED (reversible), not hashed —
the conscious fork from the E-06 token-hash model. These tests prove the
round-trip, the random-nonce property, loud failure on every malformed-KEK /
tampered-ciphertext path (K8), and — critically — that the engine core never
imports ``cryptography`` (the one K0 asterisk lives behind the ``[server]`` extra
and is lazily imported only when sealing actually happens).

The KEK is injected as a mapping (no ``os.environ`` mutation → deterministic, K10).

Features: FEAT-SERVER-006, FEAT-GITSYNC-002
"""

from __future__ import annotations

import base64
import subprocess
import sys

import pytest

from code_doc_monitor.errors import SecretError
from code_doc_monitor.secrets import SecretBox, secret_box_from_env

# A FIXED 32-byte key (deterministic, K10), base64 as $CDMON_SECRET_KEY carries it.
_KEY = bytes(range(32))
_KEY_B64 = base64.b64encode(_KEY).decode("ascii")


def _box() -> SecretBox:
    return secret_box_from_env({"CDMON_SECRET_KEY": _KEY_B64})


# --------------------------------------------------------------------------- #
# Round-trip + the random-nonce property.
# --------------------------------------------------------------------------- #


def test_seal_open_round_trips() -> None:
    box = _box()
    sealed = box.seal("ghp_realtoken")
    assert isinstance(sealed, bytes)
    assert box.open_secret(sealed) == "ghp_realtoken"


def test_seal_uses_a_random_nonce_distinct_ciphertext() -> None:
    box = _box()
    a = box.seal("same-secret")
    b = box.seal("same-secret")
    assert a != b  # random 12-byte nonce prepended → distinct ciphertext
    assert box.open_secret(a) == box.open_secret(b) == "same-secret"


def test_seal_open_round_trips_unicode_and_empty() -> None:
    box = _box()
    for plain in ("", "tøken-✓-£", "a" * 500):
        assert box.open_secret(box.seal(plain)) == plain


# --------------------------------------------------------------------------- #
# Loud failures (K8) — never a silent pass.
# --------------------------------------------------------------------------- #


def test_tampered_ciphertext_raises_secret_error() -> None:
    box = _box()
    sealed = bytearray(box.seal("ghp_realtoken"))
    sealed[-1] ^= 0x01  # flip a tag bit
    with pytest.raises(SecretError, match="authentication|tamper"):
        box.open_secret(bytes(sealed))


def test_wrong_key_cannot_open_raises_secret_error() -> None:
    sealed = _box().seal("ghp_realtoken")
    other = secret_box_from_env(
        {"CDMON_SECRET_KEY": base64.b64encode(bytes(32)).decode()}
    )
    with pytest.raises(SecretError):
        other.open_secret(sealed)


def test_too_short_sealed_raises_secret_error() -> None:
    with pytest.raises(SecretError, match="short"):
        _box().open_secret(b"\x00\x01\x02")  # shorter than the nonce


def test_missing_env_raises_secret_error() -> None:
    with pytest.raises(SecretError, match="CDMON_SECRET_KEY"):
        secret_box_from_env({})


def test_empty_env_raises_secret_error() -> None:
    with pytest.raises(SecretError, match="CDMON_SECRET_KEY"):
        secret_box_from_env({"CDMON_SECRET_KEY": ""})


def test_non_base64_env_raises_secret_error() -> None:
    with pytest.raises(SecretError, match="base64"):
        secret_box_from_env({"CDMON_SECRET_KEY": "not valid base64 !!!"})


def test_wrong_key_length_raises_secret_error() -> None:
    short = base64.b64encode(bytes(16)).decode("ascii")  # 16 bytes, not 32
    with pytest.raises(SecretError, match="32"):
        secret_box_from_env({"CDMON_SECRET_KEY": short})


def test_secret_box_ctor_rejects_wrong_length() -> None:
    with pytest.raises(SecretError, match="32"):
        SecretBox(b"too short")


# --------------------------------------------------------------------------- #
# K0 boundary — the engine core never imports `cryptography`; secrets.py is lazy.
# --------------------------------------------------------------------------- #


def test_core_engine_import_does_not_pull_cryptography() -> None:
    code = (
        "import sys, code_doc_monitor.configsync, code_doc_monitor.gitfetch, "
        "code_doc_monitor.monitor, code_doc_monitor.pr;"
        "loaded = sorted(m for m in sys.modules if 'cryptograph' in m);"
        "assert not loaded, loaded"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_importing_secrets_module_is_lazy() -> None:
    # Importing the module (without sealing) must NOT load cryptography.
    code = (
        "import sys, code_doc_monitor.secrets;assert 'cryptography' not in sys.modules"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
