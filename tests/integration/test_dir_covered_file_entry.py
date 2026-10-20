"""A FILE-valued ``dir-covered`` entry is attributed by the deepest-ancestor rule.

The deploy unit (``config/cdmon/deploy.yaml``) claims one module by listing the
file itself under ``dir-covered``, nested under a parent unit that covers the
package. This pins that engine behaviour on a fixture tree, independent of this
repo's own config: the file equal to the entry goes to the nested unit, while a
sibling in the same directory and a path that merely shares the file name as a
string prefix stay with the parent.

Features: FEAT-QUALITY-010
"""

from __future__ import annotations

from pathlib import Path

from custodex.config import load_bundle, unit_for_path
from tests.integration.test_config_v2 import _AGENT_YAML, _FOUNDATION_YAML, _write_tree

# The parent unit covers the whole package; the nested unit lists ONE file.
_PARENT = _FOUNDATION_YAML.replace("  - custodex/config.py", "  - custodex", 1)
_FILE_ENTRY = _AGENT_YAML.replace(
    "  - custodex/agent\n", "  - custodex/agent/backend.py\n", 1
)


def _owners(tmp_path: Path, *paths: str) -> list[str | None]:
    bundle = load_bundle(_write_tree(tmp_path, foundation=_PARENT, agent=_FILE_ENTRY))
    units = [unit_for_path(bundle, p) for p in paths]
    return [None if u is None else u.frontmatter.unit for u in units]


def test_the_fixture_really_uses_a_file_valued_entry(tmp_path: Path) -> None:
    bundle = load_bundle(_write_tree(tmp_path, foundation=_PARENT, agent=_FILE_ENTRY))
    covered = {u.frontmatter.unit: tuple(u.dir_covered) for u in bundle.units}
    assert covered["agent-workflow"] == ("custodex/agent/backend.py",)
    assert covered["foundation"] == ("custodex",)


def test_the_file_equal_to_the_entry_belongs_to_the_nested_unit(
    tmp_path: Path,
) -> None:
    assert _owners(tmp_path, "custodex/agent/backend.py") == ["agent-workflow"]


def test_a_sibling_in_the_same_directory_stays_with_the_parent(
    tmp_path: Path,
) -> None:
    assert _owners(tmp_path, "custodex/agent/graph.py") == ["foundation"]


def test_a_string_prefix_of_the_entry_is_not_a_match(tmp_path: Path) -> None:
    got = _owners(
        tmp_path, "custodex/agent/backend.py.bak", "custodex/agent/backend.pyi"
    )
    assert got == ["foundation", "foundation"]
