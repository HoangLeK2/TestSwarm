"""Campaign dispatch limits and tuning (DF-T-04-008)."""
from __future__ import annotations

import os

# Max devices per single dispatch fan-out (protect API/DB transaction time).
MAX_DISPATCH_TARGETS: int = int(os.environ.get("CAMPAIGN_DISPATCH_MAX_TARGETS", "500"))

# Ticket DF-T-04-008: campaign payload including overrides should stay ≤ 5 MB.
MAX_PER_DEVICE_OVERRIDES_BYTES: int = int(
    os.environ.get("CAMPAIGN_PER_DEVICE_OVERRIDES_MAX_BYTES", str(5 * 1024 * 1024))
)

# Bulk insert chunk size for campaign_targets snapshots.
CAMPAIGN_TARGET_INSERT_CHUNK: int = 200
