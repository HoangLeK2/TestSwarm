from enum import Enum, IntEnum


class AccountActionStatus(str, Enum):
    OBSERVED = "observed"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STALE = "stale"


class AccountActionRank(IntEnum):
    OBSERVED = 10
    QUEUED = 20
    RUNNING = 30
    TERMINAL = 40


TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "stale"})
ACTIVE_STATUSES = frozenset({"queued", "running"})
