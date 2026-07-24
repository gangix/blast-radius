"""GitHub Action entrypoint: run BlastRadiusAgent on a PR and post the result.

Pure decision helpers live at the top (unit-tested directly); the git/gh I/O
functions take an injected ``run`` so they stay testable; only ``_run`` and
``main`` touch real subprocesses. Same pure-core + thin-shell split as the rest
of the package.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable

from .diff_parser import FileChange, FileStatus
from .severity import Verdict

MARKER = "<!-- blast-radius:v1 -->"
_SQL_SUFFIXES = (".sql", ".ddl")
_STATUS_MAP = {
    "A": FileStatus.ADDED,
    "M": FileStatus.MODIFIED,
    "D": FileStatus.REMOVED,
    "R": FileStatus.RENAMED,
    "C": FileStatus.ADDED,
    "T": FileStatus.MODIFIED,
}
_CONCLUSION = {Verdict.BREAK: "failure", Verdict.WARN: "neutral", Verdict.PASS: "success"}


# -- pure core --------------------------------------------------------------
def is_candidate(path: str) -> bool:
    return path.lower().endswith(_SQL_SUFFIXES)


def to_file_change(path, status, old, new, *, old_path=None) -> FileChange:
    return FileChange(
        path=path,
        old_content=old,
        new_content=new,
        status=_STATUS_MAP.get(status[:1].upper(), FileStatus.MODIFIED),
        old_path=old_path,
    )


def check_conclusion(verdict: Verdict, unavailable: bool) -> str:
    return "neutral" if unavailable else _CONCLUSION[verdict]


def check_title(report, unavailable: bool) -> str:
    if unavailable or report is None:
        return "⚠️ Could not analyze — DataHub unavailable"
    n = len(report.assessments)
    return f"{report.verdict.emoji} {report.verdict.label} — {n} change{'' if n == 1 else 's'}"


# -- I/O shell (injected run) ----------------------------------------------
def _git_show(run: Callable[[list[str]], str], ref: str, path: str) -> str | None:
    try:
        return run(["git", "show", f"{ref}:{path}"])
    except Exception:  # noqa: BLE001 - path absent at this ref (added/removed)
        return None


def collect_changes(base: str, head: str, *, run: Callable[[list[str]], str]) -> list[FileChange]:
    out = run(["git", "diff", "--name-status", base, head])
    changes: list[FileChange] = []
    for line in out.splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        code = status[:1].upper()
        if code in ("R", "C"):
            old_path, path = parts[1], parts[2]
        else:
            old_path, path = None, parts[1]
        if not is_candidate(path):
            continue
        old = None if code == "A" else _git_show(run, base, old_path or path)
        new = None if code == "D" else _git_show(run, head, path)
        changes.append(to_file_change(path, status, old, new, old_path=old_path))
    return changes


def _write_json(obj) -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return path


def upsert_comment(repo: str, pr: int, body: str, *,
                   run: Callable[[list[str]], str], marker: str = MARKER) -> None:
    existing = run(["gh", "api", f"repos/{repo}/issues/{pr}/comments", "--paginate"])
    comment_id = None
    for c in json.loads(existing or "[]"):
        if (c.get("body") or "").startswith(marker):
            comment_id = c["id"]
            break
    payload = _write_json({"body": body})
    if comment_id is not None:
        run(["gh", "api", "--method", "PATCH",
             f"repos/{repo}/issues/comments/{comment_id}", "--input", payload])
    else:
        run(["gh", "api", "--method", "POST",
             f"repos/{repo}/issues/{pr}/comments", "--input", payload])


def post_check(repo: str, head_sha: str, conclusion: str, *,
               title: str, summary: str, run: Callable[[list[str]], str]) -> None:
    run(["gh", "api", "--method", "POST", f"repos/{repo}/check-runs",
         "-f", "name=Blast Radius",
         "-f", f"head_sha={head_sha}",
         "-f", "status=completed",
         "-f", f"conclusion={conclusion}",
         "-f", f"output[title]={title}",
         "-f", f"output[summary]={summary}"])
