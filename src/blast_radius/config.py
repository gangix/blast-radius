"""Connection and instance configuration, driven by environment variables.

The demo warehouse's URNs are namespaced with an instance prefix (``b2fd91``)
baked in by the datapack, so table names alone are not enough to address an
entity — we need platform + prefix + fabric (env). Centralising that here keeps
every URN we build consistent and lets the same code point at a different
DataHub (e.g. the hosted judging instance) with no code changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_SERVER = "http://localhost:8080"


@dataclass(frozen=True)
class DataHubConfig:
    """How to reach DataHub and how this instance's URNs are namespaced."""

    server: str = DEFAULT_SERVER
    token: str | None = None
    #: Warehouse platform the demo tables live on (URN platform segment).
    platform: str = "snowflake"
    #: Instance prefix baked into datapack URNs, e.g. ``b2fd91`` -> ``b2fd91.db.schema.table``.
    instance_prefix: str = "b2fd91"
    #: DataHub fabric / environment segment of dataset URNs.
    fabric: str = "PROD"

    @classmethod
    def from_env(cls) -> DataHubConfig:
        return cls(
            server=os.getenv("DATAHUB_GMS_URL", DEFAULT_SERVER),
            token=os.getenv("DATAHUB_GMS_TOKEN") or None,
            platform=os.getenv("BLAST_RADIUS_PLATFORM", "snowflake"),
            instance_prefix=os.getenv("BLAST_RADIUS_PREFIX", "b2fd91"),
            fabric=os.getenv("BLAST_RADIUS_FABRIC", "PROD"),
        )

    def qualify(self, table: str) -> str:
        """Prepend the instance prefix to a ``db.schema.table`` name."""
        table = table.strip()
        if self.instance_prefix and not table.startswith(f"{self.instance_prefix}."):
            return f"{self.instance_prefix}.{table}"
        return table
