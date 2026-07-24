from __future__ import annotations

import json

import pytest

from blast_radius import DataHubUnavailable, FileChange, FileStatus, Report, Verdict, action
from blast_radius.action import (
    MARKER,
    check_conclusion,
    check_title,
    collect_changes,
    is_candidate,
    post_check,
    to_file_change,
    upsert_comment,
)

BASE, HEAD = "base123", "head456"


# -- pure core --------------------------------------------------------------
def test_is_candidate():
    assert is_candidate("models/x.sql") and is_candidate("m/1.DDL")
    assert not is_candidate("app.py") and not is_candidate("README.md")


def test_to_file_change_status_mapping():
    a = to_file_change("x.sql", "A", None, "new")
    assert a.status is FileStatus.ADDED and a.old_content is None and a.new_content == "new"
    d = to_file_change("x.sql", "D", "old", None)
    assert d.status is FileStatus.REMOVED and d.new_content is None
    m = to_file_change("x.sql", "M", "old", "new")
    assert m.status is FileStatus.MODIFIED
    r = to_file_change("y.sql", "R100", "old", "new", old_path="x.sql")
    assert r.status is FileStatus.RENAMED and r.old_path == "x.sql"


def test_check_conclusion():
    assert check_conclusion(Verdict.BREAK, False) == "failure"
    assert check_conclusion(Verdict.WARN, False) == "neutral"
    assert check_conclusion(Verdict.PASS, False) == "success"
    assert check_conclusion(Verdict.PASS, True) == "neutral"  # unavailable overrides


def test_check_title():
    r = Report(assessments=[0, 1], verdict=Verdict.BREAK, markdown="", warnings=[])
    assert "❌" in check_title(r, False) and "2 changes" in check_title(r, False)
    assert "unavailable" in check_title(None, True).lower()


# -- shell (fake run) -------------------------------------------------------
def make_run(diff, shows, extra=None):
    def run(args):
        if args[:3] == ["git", "diff", "--name-status"]:
            return diff
        if args[:2] == ["git", "show"]:
            ref_path = args[2]
            if ref_path not in shows:
                raise RuntimeError("path absent at ref")
            return shows[ref_path]
        if extra is not None:
            return extra(args)
        raise AssertionError(f"unexpected call {args}")
    return run


def test_collect_changes_filters_and_maps():
    diff = "A\tmodels/new.sql\nM\tmodels/edit.sql\nM\tapp.py\n"
    shows = {
        f"{HEAD}:models/new.sql": "CREATE TABLE t (id int);",
        f"{BASE}:models/edit.sql": "old",
        f"{HEAD}:models/edit.sql": "new",
    }
    changes = collect_changes(BASE, HEAD, run=make_run(diff, shows))
    assert [c.path for c in changes] == ["models/new.sql", "models/edit.sql"]  # app.py dropped
    assert changes[0].status is FileStatus.ADDED and changes[0].old_content is None
    assert changes[0].new_content.startswith("CREATE TABLE")
    assert changes[1].old_content == "old" and changes[1].new_content == "new"


def test_collect_changes_handles_rename():
    diff = "R100\tmodels/old.sql\tmodels/new.sql\n"
    shows = {f"{BASE}:models/old.sql": "a", f"{HEAD}:models/new.sql": "b"}
    (c,) = collect_changes(BASE, HEAD, run=make_run(diff, shows))
    assert c.status is FileStatus.RENAMED and c.path == "models/new.sql" and c.old_path == "models/old.sql"


def test_upsert_edits_existing_marker_comment():
    comments = json.dumps([{"id": 5, "body": "hi"}, {"id": 9, "body": MARKER + "\nx"}])
    calls = []
    upsert_comment("o/r", 3, "body", run=lambda a: (calls.append(a),
                                                     comments if "--paginate" in a else "")[1])
    patch = [a for a in calls if "--method" in a and "PATCH" in a]
    assert patch and "issues/comments/9" in " ".join(patch[0])


def test_upsert_creates_when_no_marker():
    comments = json.dumps([{"id": 5, "body": "hi"}])
    calls = []
    upsert_comment("o/r", 3, "body", run=lambda a: (calls.append(a),
                                                     comments if "--paginate" in a else "")[1])
    post = [a for a in calls if "--method" in a and "POST" in a]
    assert post and "issues/3/comments" in " ".join(post[0])


def test_post_check_sets_conclusion():
    calls = []
    post_check("o/r", "sha1", "failure", title="t", summary="s",
               run=lambda a: (calls.append(a), "")[1])
    joined = " ".join(calls[0])
    assert "check-runs" in joined and "--method" in joined and "POST" in joined
    assert "--input" in joined  # conclusion now in JSON payload
    argv = calls[0]
    input_path = argv[argv.index("--input") + 1]
    with open(input_path, encoding="utf-8") as f:
        payload = json.load(f)
    assert payload["conclusion"] == "failure"
    assert payload["head_sha"] == "sha1"
    assert payload["name"] == "Blast Radius"
    assert payload["output"]["title"] == "t"


def test_git_show_absent_returns_none_but_reraises_real_error():
    import subprocess

    from blast_radius.action import _git_show

    def absent(args):
        raise subprocess.CalledProcessError(128, args, stderr="fatal: path 'x' does not exist in 'base'")

    assert _git_show(absent, "base", "x") is None

    def broken(args):
        raise subprocess.CalledProcessError(128, args, stderr="fatal: not a git repository")

    with pytest.raises(subprocess.CalledProcessError):
        _git_show(broken, "base", "x")


# -- main() flow tests (monkeypatched) ------------------------------------------


def _event(tmp_path, monkeypatch):
    ev = tmp_path / "event.json"
    ev.write_text(json.dumps(
        {"pull_request": {"base": {"sha": "b"}, "head": {"sha": "h"}, "number": 7}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(ev))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")


FC = FileChange(path="m.sql", new_content="x", status=FileStatus.ADDED)


def test_main_empty_changes_is_silent(tmp_path, monkeypatch):
    _event(tmp_path, monkeypatch)
    monkeypatch.setattr(action, "collect_changes", lambda *a, **k: [])
    posted = []
    monkeypatch.setattr(action, "upsert_comment", lambda *a, **k: posted.append("c"))
    monkeypatch.setattr(action, "post_check", lambda *a, **k: posted.append("k"))
    assert action.main() == 0 and posted == []


def test_main_break_posts_comment_and_failure_check(tmp_path, monkeypatch):
    _event(tmp_path, monkeypatch)
    monkeypatch.setattr(action, "collect_changes", lambda *a, **k: [FC])
    report = Report(assessments=[0], verdict=Verdict.BREAK, markdown="MD-BODY",
                    warnings=["w1"])

    class FakeAgent:
        def __init__(self, **k):
            pass

        def review(self, changes):
            return report

    monkeypatch.setattr(action, "BlastRadiusAgent", FakeAgent)
    seen = {}
    monkeypatch.setattr(action, "upsert_comment",
                        lambda repo, pr, body, **k: seen.update(body=body))
    monkeypatch.setattr(action, "post_check",
                        lambda repo, sha, concl, **k: seen.update(concl=concl))
    assert action.main() == 0
    assert seen["body"] == "MD-BODY" and seen["concl"] == "failure"


def test_main_datahub_unavailable_is_neutral(tmp_path, monkeypatch):
    _event(tmp_path, monkeypatch)
    monkeypatch.setattr(action, "collect_changes", lambda *a, **k: [FC])

    class FakeAgent:
        def __init__(self, **k):
            pass

        def review(self, changes):
            raise DataHubUnavailable("down")

    monkeypatch.setattr(action, "BlastRadiusAgent", FakeAgent)
    seen = {}
    monkeypatch.setattr(action, "upsert_comment",
                        lambda repo, pr, body, **k: seen.update(body=body))
    monkeypatch.setattr(action, "post_check",
                        lambda repo, sha, concl, **k: seen.update(concl=concl))
    assert action.main() == 0
    assert seen["concl"] == "neutral"
    assert seen["body"].startswith(MARKER) and "could not" in seen["body"].lower()


def test_main_returns_0_when_posting_raises(tmp_path, monkeypatch):
    _event(tmp_path, monkeypatch)
    monkeypatch.setattr(action, "collect_changes", lambda *a, **k: [FC])
    report = Report(assessments=[0], verdict=Verdict.BREAK, markdown="MD", warnings=[])

    class FakeAgent:
        def __init__(self, **k):
            pass

        def review(self, changes):
            return report

    monkeypatch.setattr(action, "BlastRadiusAgent", FakeAgent)

    def boom(*a, **k):
        raise RuntimeError("403 forbidden")

    monkeypatch.setattr(action, "upsert_comment", boom)
    monkeypatch.setattr(action, "post_check", boom)
    assert action.main() == 0  # posting failures must not fail the job


def test_main_returns_0_when_collect_changes_raises(tmp_path, monkeypatch):
    _event(tmp_path, monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("git error")

    monkeypatch.setattr(action, "collect_changes", boom)
    assert action.main() == 0


def test_main_enables_writeback_from_env(tmp_path, monkeypatch):
    _event(tmp_path, monkeypatch)
    monkeypatch.setenv("BLAST_RADIUS_WRITE_BACK", "true")
    captured = {}
    monkeypatch.setattr(action, "collect_changes", lambda *a, **k: [FC])

    class FakeAgent:
        def __init__(self, **k): captured.update(k)
        def review(self, changes):
            return Report(assessments=[0], verdict=Verdict.BREAK, markdown="MD", warnings=[])

    monkeypatch.setattr(action, "BlastRadiusAgent", FakeAgent)
    monkeypatch.setattr(action, "AgentContextClient", lambda cfg: "CTX")
    monkeypatch.setattr(action, "upsert_comment", lambda *a, **k: None)
    monkeypatch.setattr(action, "post_check", lambda *a, **k: None)
    assert action.main() == 0
    assert captured.get("write_back") is True and captured.get("context_client") == "CTX"
