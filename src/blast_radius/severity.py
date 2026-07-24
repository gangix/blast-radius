"""Turn blast-radius facts into a verdict — deterministic, usage-weighted.

Severity is not "how many nodes are downstream". A drop of a column nobody has
queried in 30 days is safe even if the table feeds ten dashboards; a drop of a
column read 40×/day by finance is a breaking change even if it feeds one. So
this module scores a change on the signals that actually matter:

  * how many production queries read the *specific* changed column,
  * how heavily that column is queried (per-day usage), and who runs it,
  * what BI consumers sit downstream of the table.

Crucial rule: a **column** change is judged on **column-level** signals (queries
and usage that touch that column), never on the table's total downstream — that
figure is identical for every column and would make each one look catastrophic.

This is a pure function over facts the caller has already fetched (no DataHub
calls here), so the three demo verdicts are unit-testable offline. The LLM never
decides severity; it only phrases the reasons this module produces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .diff_parser import Change, ChangeKind
from .models import LineageNode, Owner, QueryRef, Usage
from .resolver import ResolvedTable

# Escalation thresholds (documented so the scoring is auditable, not magic).
HEAVY_QUERY_VOLUME = 10   # per-day reads of a column -> heavily used
MANY_QUERIES = 3          # this many production queries read it -> broad blast
MANY_USERS = 4            # this many distinct people run the breaking queries

_ADDITIVE = frozenset({ChangeKind.ADD_COLUMN, ChangeKind.CREATE_TABLE})
_COLUMN_CHANGES = frozenset(
    {ChangeKind.DROP_COLUMN, ChangeKind.RENAME_COLUMN, ChangeKind.ALTER_COLUMN_TYPE}
)
_TABLE_CHANGES = frozenset({ChangeKind.DROP_TABLE, ChangeKind.RENAME_TABLE})


class Verdict(str, Enum):
    PASS = "pass"
    WARN = "warn"
    BREAK = "break"

    @property
    def emoji(self) -> str:
        return {"pass": "✅", "warn": "⚠️", "break": "❌"}[self.value]

    @property
    def label(self) -> str:
        return {
            "pass": "No downstream impact",
            "warn": "Review before merge",
            "break": "Breaking change",
        }[self.value]


_CONFIDENCE_ORDER = ("low", "medium", "high")


def _downgrade(confidence: str, notches: int = 1) -> str:
    i = _CONFIDENCE_ORDER.index(confidence) if confidence in _CONFIDENCE_ORDER else 2
    return _CONFIDENCE_ORDER[max(0, i - notches)]


@dataclass(frozen=True)
class ImpactSignals:
    breaking_queries: int
    query_volume_per_day: int
    dashboards: int
    charts: int
    total_downstream: int
    breaking_query_users: int


@dataclass
class ImpactFacts:
    """Everything about one change's blast radius, fetched by the orchestrator.

    ``breaking_queries`` are the queries impacted by *this* change — column-scoped
    for a column change, table-scoped for a table change. The caller decides scope.
    """

    change: Change
    resolved: ResolvedTable | None = None
    downstream: list[LineageNode] = field(default_factory=list)
    usage: Usage | None = None
    breaking_queries: list[QueryRef] = field(default_factory=list)
    owners: list[Owner] = field(default_factory=list)


@dataclass(frozen=True)
class Assessment:
    change: Change
    resolved: ResolvedTable | None
    verdict: Verdict
    score: float                 # 0..100, for ranking changes within a PR
    confidence: str              # high | medium | low
    signals: ImpactSignals
    reasons: list[str]           # factual bullets, each grounded in a signal
    breaking_queries: list[QueryRef]
    owners: list[Owner]

    @property
    def emoji(self) -> str:
        return self.verdict.emoji


def _field_volume(usage: Usage | None, column: str | None) -> int:
    if usage is None or not column:
        return 0
    return usage.field_counts.get(column) or usage.field_counts.get(column.lower()) or 0


def _consumer_counts(downstream: list[LineageNode]) -> tuple[int, int]:
    dashboards = sum(1 for n in downstream if n.entity_type == "DASHBOARD")
    charts = sum(1 for n in downstream if n.entity_type == "CHART")
    return dashboards, charts


def _confidence(facts: ImpactFacts) -> str:
    conf = facts.change.confidence if facts.change.confidence in _CONFIDENCE_ORDER else "high"
    if facts.resolved is None:
        return "low"
    if facts.resolved.ambiguous:
        conf = _downgrade(conf)
    return conf


def _score(sig: ImpactSignals) -> float:
    raw = (
        sig.breaking_queries * 15
        + sig.query_volume_per_day * 2
        + sig.dashboards * 10
        + sig.charts * 3
        + sig.breaking_query_users * 4
    )
    return float(min(100, raw))


def assess(facts: ImpactFacts) -> Assessment:
    ch = facts.change
    dashboards, charts = _consumer_counts(facts.downstream)
    users = len({q.author for q in facts.breaking_queries if q.author})
    is_table_change = ch.kind in _TABLE_CHANGES
    volume = (
        (facts.usage.total_queries if facts.usage else 0)
        if is_table_change
        else _field_volume(facts.usage, ch.column)
    )
    sig = ImpactSignals(
        breaking_queries=len(facts.breaking_queries),
        query_volume_per_day=volume,
        dashboards=dashboards,
        charts=charts,
        total_downstream=len(facts.downstream),
        breaking_query_users=users,
    )

    verdict, reasons = _classify(facts, sig)
    # Additive/unresolved verdicts carry no blast-radius score.
    score = 0.0 if verdict is Verdict.PASS and not facts.breaking_queries else _score(sig)

    return Assessment(
        change=ch,
        resolved=facts.resolved,
        verdict=verdict,
        score=score,
        confidence=_confidence(facts),
        signals=sig,
        reasons=reasons,
        breaking_queries=list(facts.breaking_queries),
        owners=list(facts.owners),
    )


def _classify(facts: ImpactFacts, sig: ImpactSignals) -> tuple[Verdict, list[str]]:
    ch = facts.change
    col = ch.column
    table = facts.resolved.matched_name if facts.resolved else ch.table

    # 1. Additive — never breaks an existing consumer.
    if ch.kind in _ADDITIVE:
        what = f"column `{col}`" if col else f"table `{table}`"
        return Verdict.PASS, [f"Additive change ({what}); no existing consumer is affected."]

    # 2. Not in the catalogue — can't compute a blast radius; don't claim safety.
    if facts.resolved is None:
        return Verdict.PASS, [
            (
                f"`{ch.table}` was not found in DataHub — no lineage or usage available, "
                "so the blast radius could not be computed. Verify the name manually."
            )
        ]

    # 3. Silent logic change — can't pin a column; never assert a break, warn if consumed.
    if ch.kind is ChangeKind.LOGIC_CHANGE:
        if sig.total_downstream == 0 and sig.query_volume_per_day == 0:
            return Verdict.PASS, [f"`{table}` output changed but has no known downstream consumers."]
        return Verdict.WARN, [
            (
                f"`{table}` output changed in a way that couldn't be pinned to a specific column; "
                "downstream values may shift silently."
            ),
            _downstream_line(table, sig),
        ]

    # 4. Table drop / rename — judged on table-level consumption.
    if ch.kind in _TABLE_CHANGES:
        return _classify_table(ch, table, sig)

    # 5. Column drop / rename / type change — judged on COLUMN-level signals.
    return _classify_column(ch, table, col, sig)


def _classify_column(ch: Change, table: str, col: str | None, sig: ImpactSignals) -> tuple[Verdict, list[str]]:
    verb = {
        ChangeKind.DROP_COLUMN: "Dropping",
        ChangeKind.RENAME_COLUMN: "Renaming",
        ChangeKind.ALTER_COLUMN_TYPE: "Changing the type of",
    }[ch.kind]

    if sig.breaking_queries == 0 and sig.query_volume_per_day == 0:
        reasons = [f"No production query or usage has referenced `{col}` in the last 30 days."]
        if sig.dashboards or sig.charts:
            reasons.append(
                f"`{table}` feeds {_consumers_phrase(sig)} downstream, but none of the tracked "
                f"queries read `{col}`. (BI field-level bindings aren't verified.)"
            )
        return Verdict.PASS, reasons

    reasons = [
        (
            f"{verb} `{col}` affects "
            f"{_count(sig.breaking_queries, 'production query', 'production queries')}"
            f"{_volume_suffix(sig)}."
        )
    ]
    if sig.breaking_query_users:
        reasons.append(f"Run by {_count(sig.breaking_query_users, 'person', 'people')} in the last 30 days.")
    if sig.dashboards or sig.charts:
        reasons.append(f"`{table}` feeds {_consumers_phrase(sig)} downstream.")

    heavily_used = (
        sig.query_volume_per_day >= HEAVY_QUERY_VOLUME
        or sig.breaking_queries >= MANY_QUERIES
        or sig.breaking_query_users >= MANY_USERS
    )
    if heavily_used:
        if ch.kind is ChangeKind.ALTER_COLUMN_TYPE:
            reasons.append("A type change can silently corrupt values in these queries — verify compatibility.")
        elif ch.kind is ChangeKind.RENAME_COLUMN:
            reasons.append("Downstream references to the old name will fail until they are updated.")
        return Verdict.BREAK, reasons

    return Verdict.WARN, reasons


def _classify_table(ch: Change, table: str, sig: ImpactSignals) -> tuple[Verdict, list[str]]:
    verb = "Dropping" if ch.kind is ChangeKind.DROP_TABLE else "Renaming"
    if sig.total_downstream == 0 and sig.query_volume_per_day == 0 and sig.breaking_queries == 0:
        return Verdict.PASS, [f"`{table}` has no known downstream consumers or query history."]

    reasons = [f"{verb} `{table}` impacts everything downstream:", _downstream_line(table, sig)]
    if sig.breaking_queries:
        reasons.append(f"{_count(sig.breaking_queries, 'production query', 'production queries')} read from it.")
    if sig.dashboards or sig.charts or sig.breaking_queries:
        return Verdict.BREAK, reasons
    return Verdict.WARN, reasons


# ------------------------------------------------------------------ phrasing
def _count(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _volume_suffix(sig: ImpactSignals) -> str:
    return f" (~{sig.query_volume_per_day} reads/day)" if sig.query_volume_per_day else ""


def _consumers_phrase(sig: ImpactSignals) -> str:
    parts = []
    if sig.dashboards:
        parts.append(_count(sig.dashboards, "dashboard", "dashboards"))
    if sig.charts:
        parts.append(_count(sig.charts, "chart", "charts"))
    return " and ".join(parts) if parts else "no BI consumers"


def _downstream_line(table: str, sig: ImpactSignals) -> str:
    return (
        f"{sig.total_downstream} downstream entities, including {_consumers_phrase(sig)}."
    )
