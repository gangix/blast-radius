# tests/test_comment_golden.py
from __future__ import annotations

import os
import pathlib

import pytest
import scenarios

from blast_radius.comment import CommentContext, render_comment

GOLDEN = pathlib.Path(__file__).parent / "golden"
CTX = CommentContext(link_base="https://datahub.example.com")

CASES = {
    "hard_break_discount_amount.md": [scenarios.hard_break()],
    "warning_warehouse_name.md": [scenarios.warning()],
    "clean_pass_gift_wrap.md": [scenarios.clean_pass()],
    "multi_change_pr.md": [scenarios.hard_break(), scenarios.warning(), scenarios.clean_pass()],
}


@pytest.mark.parametrize("name, assessments", list(CASES.items()))
def test_golden(name, assessments):
    actual = render_comment(assessments, ctx=CTX)
    path = GOLDEN / name
    if os.getenv("BLAST_RADIUS_UPDATE_GOLDEN"):
        path.parent.mkdir(exist_ok=True)
        path.write_text(actual, encoding="utf-8")
    assert actual == path.read_text(encoding="utf-8"), (
        f"{name} drifted; re-run with BLAST_RADIUS_UPDATE_GOLDEN=1 to update"
    )
