from __future__ import annotations

from blast_radius import Change, ChangeKind, Verdict
from blast_radius.comment import (
    CommentContext,
    _change_title,
    _entity_url,
    _summary_line,
    _worst_of,
)
from blast_radius.severity import ImpactFacts, assess


def _assess(kind: ChangeKind, **change_kw):
    # resolved=None keeps these pure/offline; verdict is driven below by kind only
    return assess(ImpactFacts(change=Change(kind, "t", **change_kw), resolved=None))


def test_context_defaults():
    ctx = CommentContext()
    assert ctx.link_base == "https://datahub.example.com"
    assert ctx.marker == "<!-- blast-radius:v1 -->"


def test_worst_of_empty_is_pass():
    assert _worst_of([]) is Verdict.PASS


def test_summary_all_pass_message():
    line = _summary_line([_assess(ChangeKind.ADD_COLUMN, column="x")], all_pass=True)
    assert "No downstream impact" in line
    assert "Safe to merge" in line


def test_summary_rollup_grammar():
    # two fake assessments: one BREAK, one WARN — build via dataclasses.replace
    import dataclasses
    a = _assess(ChangeKind.ADD_COLUMN, column="x")
    brk = dataclasses.replace(a, verdict=Verdict.BREAK)
    wrn = dataclasses.replace(a, verdict=Verdict.WARN)
    line = _summary_line([brk, wrn], all_pass=False)
    assert "**1 breaking, 1 warning**" in line
    assert "across 2 changes" in line


def test_entity_url_encodes_urn_and_maps_type():
    url = _entity_url("https://dh.example.com/", "DASHBOARD",
                      "urn:li:dashboard:(tableau,d0)")
    assert url == "https://dh.example.com/dashboard/urn%3Ali%3Adashboard%3A%28tableau%2Cd0%29"


def test_change_title_variants():
    assert _change_title(Change(ChangeKind.DROP_COLUMN, "t", column="c")) == "Drop column `c`"
    assert _change_title(Change(ChangeKind.RENAME_COLUMN, "t", column="c", old="c", new="d")) \
        == "Rename column `c` → `d`"
    assert _change_title(Change(ChangeKind.DROP_TABLE, "orders")) == "Drop table `orders`"
