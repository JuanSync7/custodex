"""CIX-01 guard — the persisted code index must not move any fingerprint.

The K6 hash contract: `cdm.fingerprint` / `fingerprint_tiers` / `symbol_sigs`
are computed from an EXPLICIT payload field list in `extract.fingerprint()`.
Persisting the surface (codeindex.py) adds fields AROUND that payload, never
inside it — so every digest below is a golden literal captured on `main`
BEFORE the slice landed (the P-01 lesson: capture the golden hash before you
touch the code). If any assertion here fails, a change leaked into the hash
payload and every adopter's stored fingerprint would re-baseline — that is a
migration, not an additive slice (P-02).

Features: FEAT-CODEINDEX-001
"""

from __future__ import annotations

from pathlib import Path

from custodex.extract import Audience, DocumentSurface, anchor_id, extract_file

_FIXTURE = '''"""Mod docstring."""
CONST = 1

def alpha(x, y=2):
    """Alpha docs."""
    return x + y

class Widget:
    """Widget docs."""

    def run(self, verbose=False):
        """Run docs."""
        if verbose:
            return 2
        return 1

def _private_helper():
    return None
'''

# Captured on main @ 5f3f891 (pre-CIX), 2026-08-05.
_GOLDEN_USER = {
    "composite": "66bf1304f69db894",
    "signature": "66bf1304f69db894",
}
_GOLDEN_ENG = {
    "composite": "97e6ca31ae28eed8",
    "signature": "7e66c32213d568a5",
    "docstring": "7c19ce0cf292c957",
    "body": "7525c0415e2d993c",
    "composite_body": "c47e611da6c7c0ea",
}
_GOLDEN_SIGS = {
    "3b5d28caea5749e8": "fdf92662fc42959e",
    "5eae516235f7bfa8": "9e670de32d3187f1",
    "7dd7a28c2ff9e308": "10e56c211bb15307",
    "8ed3f6ad685b959e": "c29e0c4c61376c5d",
    "ac83765c2be47b3d": "53fb4e11a4b7a27d",
}


def _surface(tmp_path: Path, audience: Audience) -> DocumentSurface:
    path = tmp_path / "mod.py"
    path.write_text(_FIXTURE, encoding="utf-8")
    symbols = extract_file(path)
    if audience is Audience.USER_GUIDE:
        symbols = tuple(s for s in symbols if s.is_public)
    return DocumentSurface(
        doc_id="golden", audience=audience, symbols=symbols, records=()
    )


def test_user_guide_fingerprint_is_byte_stable(tmp_path: Path) -> None:
    fp = _surface(tmp_path, Audience.USER_GUIDE).fingerprint()
    assert fp.composite == _GOLDEN_USER["composite"]
    assert fp.signature == _GOLDEN_USER["signature"]
    assert fp.docstring is None
    assert fp.body is None


def test_eng_guide_fingerprint_is_byte_stable(tmp_path: Path) -> None:
    surface = _surface(tmp_path, Audience.ENG_GUIDE)
    fp = surface.fingerprint()
    assert fp.composite == _GOLDEN_ENG["composite"]
    assert fp.signature == _GOLDEN_ENG["signature"]
    assert fp.docstring == _GOLDEN_ENG["docstring"]
    fp_body = surface.fingerprint(include_body=True)
    assert fp_body.body == _GOLDEN_ENG["body"]
    assert fp_body.composite == _GOLDEN_ENG["composite_body"]


def test_symbol_sig_digests_are_byte_stable(tmp_path: Path) -> None:
    fp = _surface(tmp_path, Audience.ENG_GUIDE).fingerprint()
    assert fp.sig_by_anchor == _GOLDEN_SIGS
    assert anchor_id("Widget.run") == "5eae516235f7bfa8"
