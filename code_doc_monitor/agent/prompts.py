"""Lazy loader for the agent's Markdown artifacts (K8).

The remediation agent's prompt is composed from separated artifacts —
``AGENT.md`` (the recipe), ``PROTOCOL.md`` (the wire contract), ``TOOL.md`` (the
fix shapes), and an optional ``PERSONA.md`` (voice). They live as files (the
packaged ``prompts/`` directory, or an ``agent.prompts_dir`` override) so they
can be edited, reviewed, and versioned independently of the engine — and each is
read from disk **only when a node actually needs it** (``TOOL.md`` only for a
healable drift, ``PERSONA.md`` only when enabled), then cached.

A missing required artifact is a loud, typed :class:`BackendError`, never a
silent empty prompt (K8). The YAML front matter is registry metadata, so it is
stripped before the body is composed into a prompt.
"""

from __future__ import annotations

from pathlib import Path

from ..errors import BackendError

__all__ = ["Artifact", "PromptLibrary", "PACKAGED_PROMPTS_DIR"]

#: The packaged artifacts directory (sibling ``prompts/`` of this module).
PACKAGED_PROMPTS_DIR = Path(__file__).parent / "prompts"


class Artifact:
    """The known artifact names (one file ``<NAME>.md`` each)."""

    AGENT = "AGENT"
    PROTOCOL = "PROTOCOL"
    TOOL = "TOOL"
    PERSONA = "PERSONA"


def _strip_front_matter(text: str) -> str:
    """Drop a leading ``---\\n…\\n---`` YAML front-matter block, return the body."""
    if not text.startswith("---"):
        return text.strip()
    end = text.find("\n---", 3)
    if end == -1:
        return text.strip()
    # Advance past the closing fence's line.
    rest = text[end + 1 :]
    newline = rest.find("\n")
    body = rest[newline + 1 :] if newline != -1 else ""
    return body.strip()


class PromptLibrary:
    """Loads and caches artifact bodies from a directory, only when asked."""

    def __init__(self, prompts_dir: Path | None = None) -> None:
        self._dir = prompts_dir or PACKAGED_PROMPTS_DIR
        self._cache: dict[str, str] = {}

    @property
    def directory(self) -> Path:
        return self._dir

    def exists(self, name: str) -> bool:
        """Is artifact ``name`` available (without raising if it is not)?"""
        return (self._dir / f"{name}.md").is_file()

    def get(self, name: str) -> str:
        """Return artifact ``name``'s body, reading + caching it on first use.

        Raises :class:`BackendError` if the file is absent or unreadable (K8).
        """
        if name not in self._cache:
            path = self._dir / f"{name}.md"
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise BackendError(
                    f"agent prompt artifact {name}.md not found under {self._dir}: "
                    f"{exc}"
                ) from exc
            self._cache[name] = _strip_front_matter(raw)
        return self._cache[name]
