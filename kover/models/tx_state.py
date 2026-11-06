"""Transaction state enum."""

from enum import Enum


class TxnState(Enum):
    """Transaction states for MongoDB transactions."""

    NONE = "NONE"
    STARTING = "STARTING"
    IN_PROGRESS = "IN_PROGRESS"
    ABORTED = "ABORTED"
    COMMITTING = "COMMITTING"
    COMMITTED = "COMMITTED"
