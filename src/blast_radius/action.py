"""GitHub Action entrypoint: run BlastRadiusAgent on a PR and post the result.

Pure decision helpers live at the top (unit-tested directly); the git/gh I/O
functions take an injected ``run`` so they stay testable; only ``_run`` and
``main`` touch real subprocesses. Same pure-core + thin-shell split as the rest
of the package.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable

from .agent import BlastRadiusAgent, DataHubUnavailable
from .comment import CommentContext
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
    payload = _write_json({
        "name": "Blast Radius",
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": conclusion,
        "output": {"title": title, "summary": summary}
    })
    run(["gh", "api", "--method", "POST", f"repos/{repo}/check-runs",
         "--input", payload])


# -- entrypoint -------------------------------------------------------------
def _run(args: list[str]) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def _infra_comment(exc: Exception) -> str:
    return (
        f"{MARKER}\n\n## ⚠️ Blast Radius — could not analyze\n\n"
        "Could not reach DataHub, so the blast radius was **not** computed. "
        "This is an infrastructure issue, not an all-clear — re-run once DataHub "
        f"is reachable.\n\n<sub>{exc}</sub>\n"
    )


def main() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        print("No GITHUB_EVENT_PATH — not running inside a GitHub Action.",
              file=sys.stderr)
        return 0
    with open(event_path, encoding="utf-8") as f:
        event = json.load(f)
    pr = event.get("pull_request")
    if not pr:
        print("Not a pull_request event; nothing to do.")
        return 0
    base, head, number = pr["base"]["sha"], pr["head"]["sha"], pr["number"]
    repo = os.environ["GITHUB_REPOSITORY"]

    changes = collect_changes(base, head, run=_run)
    if not changes:
        print("No .sql/.ddl changes; staying silent.")
        return 0

    ctx = CommentContext(
        link_base=os.getenv("BLAST_RADIUS_LINK_BASE")
        or CommentContext().link_base
    )
    try:
        report = BlastRadiusAgent(comment_ctx=ctx).review(changes)
        body, unavailable = report.markdown, False
    except DataHubUnavailable as exc:
        report, unavailable, body = None, True, _infra_comment(exc)

    upsert_comment(repo, number, body, run=_run)
    verdict = report.verdict if report else Verdict.PASS
    summary = (report.markdown if report else body)[:900]
    post_check(
        repo, head, check_conclusion(verdict, unavailable),
        title=check_title(report, unavailable), summary=summary, run=_run
    )
    for w in (report.warnings if report else []):
        print(f"::warning::{w}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
