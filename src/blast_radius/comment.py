"""Render Assessments into a GitHub PR comment (pure Markdown, no I/O).

The severity layer has already written senior-grade, fact-grounded ``reasons``;
this module only structures them. It performs no DataHub calls and never
invents a fact, so the output is deterministic and golden-file testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from .diff_parser import Change, ChangeKind
from .severity import Assessment, Verdict

# Column-scoped change kinds — Fix #1 forbids table-level counts in their phrasing.
_COLUMN_KINDS = frozenset(
    {
        ChangeKind.DROP_COLUMN,
        ChangeKind.RENAME_COLUMN,
        ChangeKind.ALTER_COLUMN_TYPE,
        ChangeKind.ADD_COLUMN,
    }
)

_VERDICT_RANK = {Verdict.PASS: 0, Verdict.WARN: 1, Verdict.BREAK: 2}

# DataHub frontend path segment per entity type (Fix #4).
_ENTITY_PATH = {"DATASET": "dataset", "CHART": "chart", "DASHBOARD": "dashboard"}


@dataclass(frozen=True)
class CommentContext:
    """Presentation settings for :func:`render_comment`.

    ``link_base`` is the DataHub *frontend* host (the UI, e.g. ``:9002``), NOT
    the GMS/API host (``:8080``) — that distinction is Fix #4.
    """

    link_base: str = "https://datahub.example.com"
    marker: str = "<!-- blast-radius:v1 -->"


def _worst_of(assessments: list[Assessment]) -> Verdict:
    if not assessments:
        return Verdict.PASS
    return max((a.verdict for a in assessments), key=lambda v: _VERDICT_RANK[v])


def _summary_line(assessments: list[Assessment], all_pass: bool) -> str:
    k = len(assessments)
    if not assessments:
        return "No data-model changes detected."
    if all_pass:
        return f"No downstream impact detected across {k} change{'' if k == 1 else 's'}. Safe to merge."
    nb = sum(a.verdict is Verdict.BREAK for a in assessments)
    nw = sum(a.verdict is Verdict.WARN for a in assessments)
    segs: list[str] = []
    if nb:
        segs.append(f"{nb} breaking")
    if nw:
        segs.append(f"{nw} warning{'' if nw == 1 else 's'}")
    return f"**{', '.join(segs)}** across {k} change{'' if k == 1 else 's'}."


def _entity_url(link_base: str, entity_type: str, urn: str) -> str:
    seg = _ENTITY_PATH.get(entity_type.upper(), "entity")
    return f"{link_base.rstrip('/')}/{seg}/{quote(urn, safe='')}"


def _change_title(change: Change) -> str:
    c, t, k = change.column, change.table, change.kind
    if k is ChangeKind.DROP_COLUMN:
        return f"Drop column `{c}`"
    if k is ChangeKind.RENAME_COLUMN:
        return f"Rename column `{change.old or c}` → `{change.new}`"
    if k is ChangeKind.ALTER_COLUMN_TYPE:
        tail = f" → `{change.new}`" if change.new else ""
        return f"Alter type of column `{c}`{tail}"
    if k is ChangeKind.ADD_COLUMN:
        return f"Add column `{c}`"
    if k is ChangeKind.DROP_TABLE:
        return f"Drop table `{t}`"
    if k is ChangeKind.RENAME_TABLE:
        return f"Rename table `{change.old or t}` → `{change.new}`"
    if k is ChangeKind.CREATE_TABLE:
        return f"Create table `{t}`"
    if k is ChangeKind.LOGIC_CHANGE:
        return f"Logic change in `{t}`"
    return f"Change `{t}`"


_FOOTER = "_Deterministic analysis from DataHub lineage + 30-day query history._"


def _ranked(assessments: list[Assessment]) -> list[Assessment]:
    # Highest blast-radius score first; stable for equal scores.
    return sorted(assessments, key=lambda a: a.score, reverse=True)


def _section(a: Assessment) -> list[str]:
    lines = [f"### {a.emoji} {_change_title(a.change)}", ""]
    lines += [f"- {r}" for r in a.reasons]
    return lines


def render_comment(
    assessments: list[Assessment],
    *,
    ctx: CommentContext | None = None,
) -> str:
    ctx = ctx or CommentContext()
    verdict = _worst_of(assessments)
    all_pass = all(a.verdict is Verdict.PASS for a in assessments)

    lines: list[str] = [ctx.marker, ""]
    lines += [f"## {verdict.emoji} Blast Radius — {verdict.label}", ""]
    lines += [_summary_line(assessments, all_pass), ""]

    for a in _ranked(assessments):
        lines += _section(a)
        lines.append("")

    lines += ["---", _FOOTER]
    return "\n".join(lines).rstrip() + "\n"
