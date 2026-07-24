"""Deterministic extraction of data-model changes from a PR.

This module is intentionally free of any LLM. Given the changed files of a PR
(with full before/after content), it produces a precise list of
``Change`` records — dropped/renamed/retyped columns, dropped/renamed tables,
added columns — that the rest of the agent maps onto DataHub lineage. The graph
facts and the *what changed* facts are both code; the LLM only phrases them.

Two source shapes are understood:

* **SQL DDL** (schema migrations, raw ``.sql``): ``ALTER TABLE ... DROP/RENAME/
  ADD/ALTER COLUMN``, ``DROP TABLE``, ``RENAME TO``, ``CREATE TABLE``. Parsed
  with dialect-agnostic regex — DDL is regular and this stays predictable.
* **dbt models** (``.sql`` under ``models/`` or containing ``{{ ref/config }}``):
  the model's *output* columns are extracted with ``sqlglot`` before and after,
  and the difference tells us which columns the model stopped or started
  emitting. A removed output column breaks everything downstream that reads it.

Contract: callers supply :class:`FileChange` objects with full old/new content
(the GitHub Action fetches base/head blobs). We do not reconstruct content from
unified-diff hunks — that is lossy, and column-level SELECT diffing needs the
whole file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath

import sqlglot
from sqlglot.errors import SqlglotError


class ChangeKind(str, Enum):
    DROP_COLUMN = "drop_column"
    RENAME_COLUMN = "rename_column"
    ADD_COLUMN = "add_column"
    ALTER_COLUMN_TYPE = "alter_column_type"
    DROP_TABLE = "drop_table"
    RENAME_TABLE = "rename_table"
    CREATE_TABLE = "create_table"
    #: The model's SQL changed in a way that alters output but we can't pin it to
    #: a specific column (e.g. ``SELECT *``, an unparseable model). Treated as a
    #: potential silent-value change downstream.
    LOGIC_CHANGE = "logic_change"


# Kinds that can break a downstream consumer. ADD/CREATE are additive; severity
# still has the final word, this is just a fast structural signal.
_BREAKING_KINDS = frozenset(
    {
        ChangeKind.DROP_COLUMN,
        ChangeKind.RENAME_COLUMN,
        ChangeKind.ALTER_COLUMN_TYPE,
        ChangeKind.DROP_TABLE,
        ChangeKind.RENAME_TABLE,
        ChangeKind.LOGIC_CHANGE,
    }
)


class FileStatus(str, Enum):
    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"
    RENAMED = "renamed"


@dataclass(frozen=True)
class Change:
    """A single data-model change extracted from the diff."""

    kind: ChangeKind
    table: str                       # table or dbt model name as written in code
    column: str | None = None
    old: str | None = None           # previous name (rename) or type (retype)
    new: str | None = None           # new name (rename) or type (retype)
    file: str | None = None
    #: "high" for explicit DDL; "medium" for changes inferred from a SELECT.
    confidence: str = "high"
    statement: str | None = None     # source snippet, for the PR comment / audit

    @property
    def potentially_breaking(self) -> bool:
        return self.kind in _BREAKING_KINDS


@dataclass
class FileChange:
    """One changed file with full before/after content."""

    path: str
    old_content: str | None = None
    new_content: str | None = None
    status: FileStatus = FileStatus.MODIFIED
    old_path: str | None = None


# --------------------------------------------------------------------------- #
# Identifier / statement lexical helpers
# --------------------------------------------------------------------------- #

# quoted ("x") / backticked (`x`) / bracketed ([x]) / bare identifier, dotted.
_ID = r'(?:"[^"]*"|`[^`]*`|\[[^\]]*\]|[A-Za-z_][A-Za-z0-9_$]*)'
_QNAME = rf"{_ID}(?:\.{_ID})*"
_TYPE = r"[A-Za-z][A-Za-z0-9_]*(?:\s*\([^)]*\))?"


def _clean_ident(raw: str) -> str:
    """Strip surrounding quotes/brackets and any qualifier, preserving case."""
    part = raw.strip().split(".")[-1].strip()
    if len(part) >= 2 and part[0] in "\"`[" :
        part = part[1:-1]
    return part


def _clean_table(raw: str) -> str:
    """Normalise a (possibly qualified/quoted) table name, keeping qualifiers."""
    return ".".join(_clean_ident(p) for p in raw.strip().split("."))


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)      # block comments
    sql = re.sub(r"--[^\n]*", " ", sql)                    # line comments
    return sql


def _split_statements(sql: str) -> list[str]:
    return [s.strip() for s in _strip_comments(sql).split(";") if s.strip()]


def _normalise(stmt: str) -> str:
    return re.sub(r"\s+", " ", stmt).strip().lower()


# --------------------------------------------------------------------------- #
# DDL parsing (regex, dialect-agnostic)
# --------------------------------------------------------------------------- #

_RE_DROP_TABLE = re.compile(
    rf"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?({_QNAME})", re.IGNORECASE
)
_RE_CREATE_TABLE = re.compile(
    rf"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:TRANSIENT\s+|TEMP(?:ORARY)?\s+)?TABLE\s+"
    rf"(?:IF\s+NOT\s+EXISTS\s+)?({_QNAME})",
    re.IGNORECASE,
)
_RE_ALTER_TABLE = re.compile(rf"\bALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?({_QNAME})\s+(.*)", re.IGNORECASE | re.DOTALL)

# Actions inside an ALTER TABLE body (order matters — rename before drop).
_RE_RENAME_TABLE = re.compile(rf"\bRENAME\s+TO\s+({_QNAME})", re.IGNORECASE)
_RE_RENAME_COLUMN = re.compile(rf"\bRENAME\s+(?:COLUMN\s+)?({_ID})\s+TO\s+({_ID})", re.IGNORECASE)
_RE_ALTER_TYPE = re.compile(
    rf"\b(?:ALTER|MODIFY)\s+(?:COLUMN\s+)?({_ID})\s+(?:SET\s+DATA\s+)?TYPE\s+({_TYPE})", re.IGNORECASE
)
_RE_MODIFY_TYPE = re.compile(rf"\bMODIFY\s+(?:COLUMN\s+)?({_ID})\s+({_TYPE})", re.IGNORECASE)
_RE_ADD_COLUMN = re.compile(
    rf"\bADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?({_ID})\s+({_TYPE})", re.IGNORECASE
)
_RE_DROP_COLUMN = re.compile(rf"\bDROP\s+(?:COLUMN\s+)?(?:IF\s+EXISTS\s+)?({_ID})", re.IGNORECASE)

# Tokens that follow ADD/DROP/ALTER but name a table-level object, not a column.
# Without this guard, `DROP CONSTRAINT fk` reads as dropping a column "CONSTRAINT"
# and would raise a phantom breaking change in the PR comment.
_NON_COLUMN_KEYWORDS = frozenset(
    {"CONSTRAINT", "PRIMARY", "FOREIGN", "KEY", "INDEX", "UNIQUE", "CHECK", "COLUMN", "IF"}
)


def _is_column(name: str) -> bool:
    return name.upper() not in _NON_COLUMN_KEYWORDS


def parse_sql_ddl(sql: str, *, file: str | None = None) -> list[Change]:
    """Extract DDL changes from a block of SQL statements."""
    changes: list[Change] = []
    for stmt in _split_statements(sql):
        m = _RE_ALTER_TABLE.match(stmt)
        if m:
            changes.extend(_parse_alter(_clean_table(m.group(1)), m.group(2), stmt, file))
            continue
        m = _RE_DROP_TABLE.search(stmt)
        if m:
            changes.append(Change(ChangeKind.DROP_TABLE, _clean_table(m.group(1)),
                                  file=file, statement=stmt))
            continue
        m = _RE_CREATE_TABLE.search(stmt)
        if m:
            changes.append(Change(ChangeKind.CREATE_TABLE, _clean_table(m.group(1)),
                                  file=file, statement=stmt))
    return changes


def _parse_alter(table: str, body: str, stmt: str, file: str | None) -> list[Change]:
    out: list[Change] = []

    m = _RE_RENAME_TABLE.search(body)
    if m:
        out.append(Change(ChangeKind.RENAME_TABLE, table, old=table,
                          new=_clean_table(m.group(1)), file=file, statement=stmt))

    for m in _RE_RENAME_COLUMN.finditer(body):
        col = _clean_ident(m.group(1))
        if not _is_column(col):
            continue
        out.append(Change(ChangeKind.RENAME_COLUMN, table, column=col,
                          old=col, new=_clean_ident(m.group(2)),
                          file=file, statement=stmt))
    renamed_cols = {c.column for c in out if c.kind is ChangeKind.RENAME_COLUMN}

    for rx in (_RE_ALTER_TYPE, _RE_MODIFY_TYPE):
        for m in rx.finditer(body):
            col = _clean_ident(m.group(1))
            if col in renamed_cols or not _is_column(col):
                continue
            out.append(Change(ChangeKind.ALTER_COLUMN_TYPE, table, column=col,
                              new=m.group(2).strip(), file=file, statement=stmt))

    for m in _RE_ADD_COLUMN.finditer(body):
        col = _clean_ident(m.group(1))
        if not _is_column(col):  # ADD CONSTRAINT / PRIMARY KEY / ... are not columns
            continue
        out.append(Change(ChangeKind.ADD_COLUMN, table, column=col,
                          new=m.group(2).strip(), file=file, statement=stmt))

    typed_or_added = {c.column for c in out if c.kind in
                      (ChangeKind.ALTER_COLUMN_TYPE, ChangeKind.ADD_COLUMN)}
    for m in _RE_DROP_COLUMN.finditer(body):
        col = _clean_ident(m.group(1))
        # Skip shared-keyword false positives: a RENAME/ADD/ALTER token, or a
        # table-level object drop (DROP CONSTRAINT / PRIMARY KEY / INDEX ...).
        if col in renamed_cols or col in typed_or_added or not _is_column(col):
            continue
        out.append(Change(ChangeKind.DROP_COLUMN, table, column=col, file=file, statement=stmt))

    return out


# --------------------------------------------------------------------------- #
# dbt model parsing (sqlglot output-column diff)
# --------------------------------------------------------------------------- #

_JINJA_CONFIG = re.compile(r"\{\{\s*config\([\s\S]*?\)\s*\}\}", re.IGNORECASE)
_JINJA_EXPR = re.compile(r"\{\{[\s\S]*?\}\}")
_JINJA_STMT = re.compile(r"\{%[\s\S]*?%\}")


def _scrub_jinja(sql: str) -> str:
    sql = _JINJA_CONFIG.sub(" ", sql)
    sql = _JINJA_STMT.sub(" ", sql)
    sql = _JINJA_EXPR.sub("__ref__", sql)
    return sql


def _output_columns(sql: str, dialect: str) -> list[str] | None:
    """Top-level output column names, or ``None`` if undeterminable.

    Returns ``None`` for ``SELECT *`` or unparseable SQL — the caller then
    reports a LOGIC_CHANGE rather than inventing column-level facts.
    """
    try:
        expr = sqlglot.parse_one(_scrub_jinja(sql), read=dialect)
    except SqlglotError:
        return None
    if expr is None:
        return None
    try:
        names = expr.named_selects
    except SqlglotError:
        return None
    if not names or any(n == "*" or n.endswith(".*") for n in names):
        return None
    return names


def _model_name(path: str) -> str:
    return PurePosixPath(path).stem


def parse_dbt_model(fc: FileChange, dialect: str) -> list[Change]:
    model = _model_name(fc.path)

    if fc.status is FileStatus.REMOVED:
        return [Change(ChangeKind.DROP_TABLE, model, file=fc.path,
                       statement="dbt model file deleted")]
    if fc.status is FileStatus.ADDED or not fc.old_content:
        return []  # a new model breaks nothing downstream

    before = _output_columns(fc.old_content, dialect)
    after = _output_columns(fc.new_content or "", dialect)

    # Column sets undeterminable on either side -> only flag if the SQL changed.
    if before is None or after is None:
        if _normalise(fc.old_content) != _normalise(fc.new_content or ""):
            return [Change(ChangeKind.LOGIC_CHANGE, model, file=fc.path, confidence="medium",
                           statement="model SQL changed; output columns undeterminable")]
        return []

    before_set, after_set = set(before), set(after)
    dropped = [c for c in before if c not in after_set]
    added = [c for c in after if c not in before_set]

    changes = [
        Change(ChangeKind.DROP_COLUMN, model, column=c, file=fc.path, confidence="medium",
               statement="column removed from dbt model output")
        for c in dropped
    ]
    changes += [
        Change(ChangeKind.ADD_COLUMN, model, column=c, file=fc.path, confidence="medium",
               statement="column added to dbt model output")
        for c in added
    ]
    return changes


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


class DiffParser:
    """Turn changed files into a list of :class:`Change` records."""

    #: Files we treat as data-model sources.
    SQL_SUFFIXES = (".sql", ".ddl")

    def __init__(self, dialect: str = "snowflake") -> None:
        self.dialect = dialect

    def parse(self, changes: list[FileChange]) -> list[Change]:
        out: list[Change] = []
        for fc in changes:
            out.extend(self.parse_file(fc))
        return out

    def parse_file(self, fc: FileChange) -> list[Change]:
        if not self._is_sql(fc.path):
            return []
        if self._is_dbt_model(fc):
            return parse_dbt_model(fc, self.dialect)
        return self._parse_sql_ddl_file(fc)

    # -- classification ----------------------------------------------------- #
    def _is_sql(self, path: str) -> bool:
        return path.lower().endswith(self.SQL_SUFFIXES)

    @staticmethod
    def _is_dbt_model(fc: FileChange) -> bool:
        p = fc.path.replace("\\", "/").lower()
        if "/models/" in p or p.startswith("models/"):
            return True
        content = (fc.new_content or fc.old_content or "")
        return bool(re.search(r"\{\{\s*(config|ref|source)\s*\(", content))

    # -- DDL files (only newly-introduced statements for edits) ------------- #
    def _parse_sql_ddl_file(self, fc: FileChange) -> list[Change]:
        if fc.status is FileStatus.REMOVED:
            return []  # dropping a migration file is not itself a schema change
        new_sql = fc.new_content or ""
        if fc.status is FileStatus.MODIFIED and fc.old_content:
            old_stmts = {_normalise(s) for s in _split_statements(fc.old_content)}
            new_only = ";\n".join(
                s for s in _split_statements(new_sql) if _normalise(s) not in old_stmts
            )
            return parse_sql_ddl(new_only, file=fc.path)
        return parse_sql_ddl(new_sql, file=fc.path)
