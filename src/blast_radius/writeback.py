"""Render an Assessment into a DataHub knowledge-base document (pure, no I/O).

The document is what gets written back to DataHub so the next person or agent
inherits the blast-radius knowledge. Kept pure/testable; AgentContextClient does
the actual save_document call.
"""

from __future__ import annotations

from .severity import Assessment, Verdict

TAGS: dict[Verdict, tuple[str, str, str]] = {
    Verdict.BREAK: ("urn:li:tag:blast-radius-breaking", "blast-radius-breaking",
                    "Blast Radius flagged a proposed change to this field as breaking downstream consumers."),
    Verdict.WARN: ("urn:li:tag:blast-radius-review", "blast-radius-review",
                   "Blast Radius flagged a proposed change to this field as needing review before merge."),
}

_FOOTER = "_Deterministic analysis from DataHub lineage + 30-day query history (Blast Radius)._"


def _subject(a: Assessment) -> str:
    c = a.change
    table = a.resolved.matched_name if a.resolved else c.table
    return f"{table}.{c.column}" if c.column else table


def render_document(assessment: Assessment, *, pr_ref: str | None = None) -> tuple[str, str]:
    a = assessment
    v = a.verdict
    title = f"Blast Radius — {v.label} — {_subject(a)}"
    lines = [f"## {v.emoji} {v.label}", "", f"**Change:** `{_subject(a)}`"]
    if pr_ref:
        lines.append(f"**Pull request:** {pr_ref}")
    lines += ["", *(f"- {r}" for r in a.reasons)]
    if a.breaking_queries:
        lines += ["", "**Breaking queries**"]
        lines += [f"- {q.name or q.urn.split(':')[-1]}"
                  + (f" — {q.author}" if q.author else "") for q in a.breaking_queries]
    if a.owners:
        seen: set[str] = set()
        names = [o.name or o.urn.split(":")[-1] for o in a.owners
                 if not (o.urn in seen or seen.add(o.urn))]
        lines += ["", f"**Owners (from DataHub):** {', '.join(names)}"]
    lines += ["", "---", _FOOTER]
    return title, "\n".join(lines)
