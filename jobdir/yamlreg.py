"""Restricted YAML reader and writer for the flat board registry.

The file is a document of scalar maps under `boards:`. Values are strings.
This avoids a third-party YAML dependency for a format we fully control.
"""

from __future__ import annotations

from jobdir.models import Board

FIELDS = (
    "company",
    "source",
    "board_id",
    "sector",
    "careers_url",
    "api_base",
    "workday_host",
    "workday_tenant",
    "workday_site",
)


def _quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        body = value[1:-1]
        return body.replace('\\"', '"').replace("\\\\", "\\")
    if value in {"", "null", "~"}:
        return ""
    return value


def dump_boards(boards: list[Board]) -> str:
    lines = [
        "# Company to public ATS board registry.",
        "# Regenerate with: python3 scripts/build_registry.py",
        "version: 1",
        "boards:",
    ]
    for board in boards:
        first = True
        for field in FIELDS:
            value = getattr(board, field) or ""
            if field not in {"company", "source", "board_id", "sector"} and not value:
                continue
            prefix = "- " if first else "  "
            lines.append(f"{prefix}{field}: {_quote(str(value))}")
            first = False
    lines.append("")
    return "\n".join(lines)


def load_boards(text: str) -> list[Board]:
    boards: list[Board] = []
    current: dict[str, str] | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.startswith("version:") or line.startswith("boards:"):
            continue
        if line.startswith("- "):
            if current:
                boards.append(_board_from(current))
            current = {}
            _assign(current, line[2:].strip())
            continue
        if current is not None and ":" in line:
            _assign(current, line.strip())
    if current:
        boards.append(_board_from(current))
    return boards


def _assign(current: dict[str, str], item: str) -> None:
    key, _, value = item.partition(":")
    key = key.strip()
    if key:
        current[key] = _unquote(value)


def _board_from(data: dict[str, str]) -> Board:
    return Board(
        company=data.get("company") or data.get("board_id") or "",
        source=(data.get("source") or "").strip().lower(),
        board_id=data.get("board_id") or "",
        sector=data.get("sector") or "other",
        careers_url=data.get("careers_url") or "",
        api_base=data.get("api_base") or "",
        workday_host=data.get("workday_host") or "",
        workday_tenant=data.get("workday_tenant") or "",
        workday_site=data.get("workday_site") or "",
    )


def load_boards_file(path: str) -> list[Board]:
    with open(path, encoding="utf-8") as handle:
        return load_boards(handle.read())
