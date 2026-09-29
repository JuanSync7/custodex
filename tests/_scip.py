"""Test-only minimal SCIP protobuf ENCODER (the ``tests/_gitrepo.py`` pattern).

Builds real wire-format bytes for the ``scip.py`` decoder tests with no
protobuf dependency: varints, LEN fields, packed repeated int32, nested
messages. Field numbers mirror ``scip.proto`` (Index: metadata=1,
documents=2; Document: relative_path=1, occurrences=2, language=4;
Occurrence: range=1, symbol=2, symbol_roles=3, enclosing_range=7,
single_line_range=8, multi_line_range=9; Metadata: tool_info=2;
ToolInfo: name=1, version=2).
"""

from __future__ import annotations

__all__ = [
    "document",
    "index",
    "occurrence",
    "packed_field",
    "len_field",
    "str_field",
    "varint",
    "varint_field",
]


def varint(value: int) -> bytes:
    out = bytearray()
    while True:
        bits = value & 0x7F
        value >>= 7
        if value:
            out.append(bits | 0x80)
        else:
            out.append(bits)
            return bytes(out)


def _tag(field: int, wire_type: int) -> bytes:
    return varint((field << 3) | wire_type)


def varint_field(field: int, value: int) -> bytes:
    return _tag(field, 0) + varint(value)


def len_field(field: int, payload: bytes) -> bytes:
    return _tag(field, 2) + varint(len(payload)) + payload


def str_field(field: int, value: str) -> bytes:
    return len_field(field, value.encode("utf-8"))


def packed_field(field: int, values: list[int]) -> bytes:
    return len_field(field, b"".join(varint(v) for v in values))


def occurrence(
    symbol: str,
    *,
    roles: int = 0,
    range_: list[int] | None = None,
    unpacked_range: list[int] | None = None,
    single_line: tuple[int, int, int] | None = None,
    multi_line: tuple[int, int, int, int] | None = None,
    enclosing: list[int] | None = None,
) -> bytes:
    """One Occurrence message; exactly one range form is normally passed."""
    out = b""
    if range_ is not None:
        out += packed_field(1, range_)
    if unpacked_range is not None:
        for v in unpacked_range:
            out += varint_field(1, v)
    out += str_field(2, symbol)
    if roles:
        out += varint_field(3, roles)
    if enclosing is not None:
        out += packed_field(7, enclosing)
    if single_line is not None:
        line, start, end = single_line
        payload = varint_field(1, line) + varint_field(2, start) + varint_field(3, end)
        out += len_field(8, payload)
    if multi_line is not None:
        sl, sc, el, ec = multi_line
        payload = (
            varint_field(1, sl)
            + varint_field(2, sc)
            + varint_field(3, el)
            + varint_field(4, ec)
        )
        out += len_field(9, payload)
    return out


def document(
    relative_path: str, occurrences: list[bytes], *, language: str = "python"
) -> bytes:
    out = str_field(1, relative_path)
    for occ in occurrences:
        out += len_field(2, occ)
    out += str_field(4, language)
    return out


def index(
    documents: list[bytes],
    *,
    tool_name: str = "scip-python",
    tool_version: str = "0.6.6",
    project_root: str = "file:///repo",
) -> bytes:
    tool = str_field(1, tool_name) + str_field(2, tool_version)
    metadata = len_field(2, tool) + str_field(3, project_root)
    out = len_field(1, metadata)
    for doc in documents:
        out += len_field(2, doc)
    return out
