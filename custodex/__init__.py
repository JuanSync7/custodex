"""custodex — a standardized code→documentation drift monitor.

Given a config that groups code files (with function / line / variable
granularity) into *logical documents*, each tagged with an **audience**
(``user-guide`` vs ``eng-guide``), this package:

* extracts the code surface relevant to each document (audience-aware),
* detects drift between that surface and the document,
* invokes a pluggable **LLM backend** (a deterministic mock for tests; a
  single-shot headless Claude Code / Anthropic API call; or the deterministic
  **LangGraph agent** in :mod:`custodex.agent`, whose prompt is composed
  from separated Markdown artifacts and whose model runtime is config-chosen) to
  either **fix** the drift or **invalidate** it (a change irrelevant to the
  document's audience — e.g. a comment edit for a user guide),
* logs every drift + verdict + fix for human review, and
* emits a standardized public schema payload to a central monitoring system.

The engine itself never calls a real LLM in tests: the backend is selected by
config and defaults to a mock, so the whole pipeline runs offline.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
