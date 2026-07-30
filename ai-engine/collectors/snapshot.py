import json
import os
from datetime import datetime, timezone
from config import SNAPSHOT_FILE
from collectors.prometheus import collect_metrics
from utils.logger import get_logger

log = get_logger("snapshot")

def take_snapshot():
    """Collect one full system snapshot and append it to the snapshot file."""
    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metrics": collect_metrics(),
        # logs / traces added later (Phase 2 extension)
    }

    os.makedirs(os.path.dirname(SNAPSHOT_FILE), exist_ok=True)
    with open(SNAPSHOT_FILE, "a") as f:
        f.write(json.dumps(snapshot) + "\n")

    # Quick summary line for visibility
    summary = ", ".join(
        f"{svc}:err={m['error_rate']}" for svc, m in snapshot["metrics"].items()
    )
    log.info(f"Snapshot @ {snapshot['timestamp']} | {summary}")
    return snapshot