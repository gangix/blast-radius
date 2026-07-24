from __future__ import annotations

import dataclasses

from blast_radius import Change, ChangeKind, Verdict
from blast_radius.comment import render_comment
from blast_radius.severity import ImpactFacts, assess


def pass_assessment(column="gift_wrap"):
    return assess(ImpactFacts(change=Change(ChangeKind.ADD_COLUMN, "orders", column=column),
                              resolved=None))


def test_render_has_marker_header_and_footer():
    out = render_comment([pass_assessment()])
    assert out.startswith("<!-- blast-radius:v1 -->")
    assert "## ✅ Blast Radius — No downstream impact" in out
    assert out.rstrip().endswith(
        "_Deterministic analysis from DataHub lineage + 30-day query history._"
    )


def test_render_section_lists_reasons_as_bullets():
    a = pass_assessment()
    out = render_comment([a])
    assert "### ✅ Add column `gift_wrap`" in out
    for reason in a.reasons:
        assert f"- {reason}" in out


def test_overall_verdict_is_worst_of():
    a = pass_assessment()
    brk = dataclasses.replace(a, verdict=Verdict.BREAK)
    out = render_comment([a, brk])
    assert "## ❌ Blast Radius — Breaking change" in out
