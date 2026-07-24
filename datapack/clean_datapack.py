"""Strip aspects unknown to DataHub server v1.6.0 from a datapack file.

The showcase datapack ships derived/feature aspects newer than the pinned
server build. In ASYNC_BATCH ingest, one unknown aspect rejects the whole
batch (HTTP 422), silently dropping valid lineage/chart aspects riding along.
Removing them yields a clean, reproducible ingest.
"""
import json
import sys
from pathlib import Path

# Aspects the v1.6.0 GMS rejects with "Unknown aspect ... " regardless of entity.
# These are derived/feature/proposal aspects newer than the pinned server build.
UNKNOWN_ASPECTS = {
    "lineageFeatures",
    "entityInferenceMetadata",
    "usageFeatures",
    "storageFeatures",
    "corpUserUsageFeatures",
    "assertionsSummary",
    "schemaProposals",
    "proposals",
}

# (entityType, aspectName) pairs to drop only for that entity type. `status` is
# valid on datasets (soft-delete) but unknown on `domain` in this build.
UNKNOWN_PAIRS = {
    ("domain", "status"),
}

src = Path(sys.argv[1])
dst = src.with_name(src.stem + ".clean.json")

records = json.loads(src.read_text(encoding="utf-8"))
kept, dropped = [], 0
for rec in records:
    aspect = rec.get("aspectName")
    entity = rec.get("entityType")
    if aspect in UNKNOWN_ASPECTS or (entity, aspect) in UNKNOWN_PAIRS:
        dropped += 1
        continue
    kept.append(rec)

dst.write_text(json.dumps(kept, indent=2), encoding="utf-8")
print(f"{src.name}: {len(records)} records -> kept {len(kept)}, dropped {dropped}")
print(f"wrote {dst}")
