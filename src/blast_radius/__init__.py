"""Blast Radius — PR Impact Guardian for data teams.

A pre-merge impact review: given a data PR, it asks DataHub what breaks
downstream and who actually depends on it, before anyone merges.

The package is split so the *facts* are deterministic and the *phrasing* is not:

    config          connection + instance settings (env-driven)
    models          plain result types (lineage nodes, queries, usage, owners)
    datahub_client  the only place that talks to DataHub — the source of truth
"""

from .agent import BlastRadiusAgent, DataHubUnavailable, Report
from .comment import CommentContext, render_comment
from .config import DataHubConfig
from .datahub_client import DataHubClient
from .diff_parser import Change, ChangeKind, DiffParser, FileChange, FileStatus
from .models import LineageNode, Owner, QueryRef, Usage
from .resolver import ResolvedTable, TableResolver
from .severity import Assessment, ImpactFacts, ImpactSignals, Verdict, assess, worst_verdict

__all__ = [
    "Assessment",
    "BlastRadiusAgent",
    "Change",
    "ChangeKind",
    "CommentContext",
    "DataHubClient",
    "DataHubConfig",
    "DataHubUnavailable",
    "DiffParser",
    "FileChange",
    "FileStatus",
    "ImpactFacts",
    "ImpactSignals",
    "LineageNode",
    "Owner",
    "QueryRef",
    "Report",
    "ResolvedTable",
    "TableResolver",
    "Usage",
    "Verdict",
    "assess",
    "render_comment",
    "worst_verdict",
]

__version__ = "0.1.0"
