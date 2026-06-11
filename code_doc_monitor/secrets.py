"""At-rest sealing of per-repo provider credentials (GIT-01, PHASE 1).

A git provider credential (a PAT / project token / minted App token) must be
**replayed** to the provider, so — unlike the E-06 per-repo bearer token, which
the server keeps only as a one-way sha256 hash — it cannot be hashed. It is
SEALED with authenticated encryption (AES-256-GCM) under a single key-encryption
key (the KEK) read from ``$CDMON_SECRET_KEY``. This is a conscious, documented
weakening of the "nothing reversible at rest" invariant — unavoidable for ANY
approach that replays a credential; PHASE 2's short-lived minted tokens recover
most of it.

K0 asterisk: this module is the ONE place that uses ``cryptography`` (declared in
the ``[server]`` extra only). The import is LAZY — done inside :meth:`SecretBox.seal`
/ :meth:`SecretBox.open_secret`, not at module load — and the engine core never
imports this module (only ``server/app.py`` and tests do), so a core-only install
never pulls ``cryptography`` (proven by ``tests/unit/test_secrets.py``).

K8: every malformed-KEK / tampered-ciphertext path raises a loud
:class:`~code_doc_monitor.errors.SecretError`; the plaintext is never logged.
"""

from __future__ import annotations

import base64
import binascii
import os
from collections.abc import Mapping

from .errors import SecretError

__all__ = ["SecretBox", "secret_box_from_env"]

# AES-256-GCM: a 32-byte key + a 12-byte (96-bit) nonce, the standard GCM nonce.
_KEY_BYTES = 32
_NONCE_BYTES = 12
_ENV_VAR = "CDMON_SECRET_KEY"


class SecretBox:
    """Seal/open a short secret with AES-256-GCM under a fixed 32-byte key.

    :meth:`seal` prepends a fresh random 12-byte nonce to the GCM ciphertext+tag
    (so sealing the same plaintext twice yields different bytes, both openable);
    :meth:`open_secret` splits the nonce back off and authenticates. A wrong key,
    a too-short blob, or a tampered ciphertext is a loud :class:`SecretError`.
    """

    def __init__(self, key: bytes) -> None:
        if len(key) != _KEY_BYTES:
            raise SecretError(
                f"the secret key must be exactly {_KEY_BYTES} bytes "
                f"(AES-256), got {len(key)}"
            )
        self._key = key

    def seal(self, plaintext: str) -> bytes:
        """Encrypt ``plaintext`` → ``nonce ‖ ciphertext+tag`` (opaque, replayable)."""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = AESGCM(self._key).encrypt(nonce, plaintext.encode("utf-8"), None)
        return nonce + ciphertext

    def open_secret(self, sealed: bytes) -> str:
        """Authenticate + decrypt a value produced by :meth:`seal` (loud on tamper)."""
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        if len(sealed) <= _NONCE_BYTES:
            raise SecretError("sealed secret is too short to contain a nonce")
        nonce, ciphertext = sealed[:_NONCE_BYTES], sealed[_NONCE_BYTES:]
        try:
            plaintext = AESGCM(self._key).decrypt(nonce, ciphertext, None)
        except InvalidTag as exc:
            raise SecretError(
                "sealed secret failed authentication (tampered or wrong key)"
            ) from exc
        return plaintext.decode("utf-8")


def secret_box_from_env(env: Mapping[str, str] | None = None) -> SecretBox:
    """Build a :class:`SecretBox` from the base64 KEK in ``$CDMON_SECRET_KEY``.

    ``env`` defaults to ``os.environ``; tests pass a plain mapping so no real
    environment is mutated (deterministic, K10). A missing/empty value, a
    non-base64 value, or a decoded length other than 32 bytes is a loud
    :class:`SecretError` (K8) — the server refuses to seal/open with a bad KEK
    rather than silently weakening the credential at rest.
    """
    source = os.environ if env is None else env
    raw = source.get(_ENV_VAR)
    if not raw:
        raise SecretError(
            f"${_ENV_VAR} is unset — a base64-encoded 32-byte key is required to "
            "seal/open per-repo provider credentials"
        )
    try:
        key = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SecretError(f"${_ENV_VAR} is not valid base64") from exc
    return SecretBox(key)  # SecretBox enforces the 32-byte length (K8)
