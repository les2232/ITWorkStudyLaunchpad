from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTENT_ROOT = PROJECT_ROOT / "content"
DATA_ROOT = CONTENT_ROOT / "data"


def load_json(name: str) -> Any:
    path = DATA_ROOT / name
    return json.loads(path.read_text(encoding="utf-8"))


def list_modules() -> list[dict[str, Any]]:
    return load_json("modules.json")


def list_checklists() -> list[dict[str, Any]]:
    return load_json("checklists.json")


def get_module(slug: str) -> dict[str, Any] | None:
    return _find_by_slug(list_modules(), slug)


def get_checklist(slug: str) -> dict[str, Any] | None:
    return _find_by_slug(list_checklists(), slug)


def read_content_file(relative_path: str) -> str:
    path = PROJECT_ROOT / relative_path
    return path.read_text(encoding="utf-8")


def read_module_markdown(slug: str) -> str:
    module = get_module(slug)
    if module is None:
        raise KeyError(f"Unknown module: {slug}")
    return read_content_file(module["path"])


def read_checklist_markdown(slug: str) -> str:
    checklist = get_checklist(slug)
    if checklist is None:
        raise KeyError(f"Unknown checklist: {slug}")
    return read_content_file(checklist["path"])


def extract_checklist_items(markdown: str) -> list[str]:
    items = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("- [ ]"):
            items.append(stripped[5:].strip())
    return items


def render_markdown(markdown: str) -> str:
    """Render enough Markdown for the prototype without adding another dependency."""

    html_lines: list[str] = []
    in_ul = False
    in_ol = False
    in_code = False
    code_lines: list[str] = []

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            html_lines.append("</ul>")
            in_ul = False
        if in_ol:
            html_lines.append("</ol>")
            in_ol = False

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                html_lines.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
                code_lines = []
                in_code = False
            else:
                close_lists()
                in_code = True
            continue

        if in_code:
            code_lines.append(line)
            continue

        if not stripped:
            close_lists()
            continue

        if stripped == "---":
            close_lists()
            html_lines.append("<hr>")
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            close_lists()
            level = len(heading.group(1))
            html_lines.append(f"<h{level}>{_inline_markup(heading.group(2))}</h{level}>")
            continue

        if stripped.startswith("> "):
            close_lists()
            html_lines.append(f"<blockquote>{_inline_markup(stripped[2:])}</blockquote>")
            continue

        checklist = re.match(r"^-\s+\[\s\]\s+(.*)$", stripped)
        if checklist:
            if in_ol:
                html_lines.append("</ol>")
                in_ol = False
            if not in_ul:
                html_lines.append('<ul class="checklist-rendered">')
                in_ul = True
            item = _inline_markup(checklist.group(1))
            html_lines.append(f'<li><label><input type="checkbox"> <span>{item}</span></label></li>')
            continue

        unordered = re.match(r"^-\s+(.*)$", stripped)
        if unordered:
            if in_ol:
                html_lines.append("</ol>")
                in_ol = False
            if not in_ul:
                html_lines.append("<ul>")
                in_ul = True
            html_lines.append(f"<li>{_inline_markup(unordered.group(1))}</li>")
            continue

        ordered = re.match(r"^\d+\.\s+(.*)$", stripped)
        if ordered:
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            if not in_ol:
                html_lines.append("<ol>")
                in_ol = True
            html_lines.append(f"<li>{_inline_markup(ordered.group(1))}</li>")
            continue

        close_lists()
        html_lines.append(f"<p>{_inline_markup(stripped)}</p>")

    close_lists()
    if in_code:
        html_lines.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")

    return "\n".join(html_lines)


def _inline_markup(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    return escaped


def _find_by_slug(items: list[dict[str, Any]], slug: str) -> dict[str, Any] | None:
    for item in items:
        if item.get("slug") == slug:
            return item
    return None
