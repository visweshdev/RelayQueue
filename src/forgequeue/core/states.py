from enum import StrEnum


class Status(StrEnum):
    SCHEDULED = "scheduled"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRYING = "failed_retrying"
    DEAD = "dead"
    CANCELLED = "cancelled"


TERMINAL = frozenset({Status.SUCCEEDED, Status.DEAD, Status.CANCELLED})
TRANSITIONS: dict[Status | None, frozenset[Status]] = {
    None: frozenset({Status.QUEUED, Status.SCHEDULED}),
    Status.SCHEDULED: frozenset({Status.QUEUED, Status.CANCELLED}),
    Status.QUEUED: frozenset({Status.RUNNING, Status.CANCELLED}),
    Status.RUNNING: frozenset({Status.SUCCEEDED, Status.RETRYING, Status.DEAD, Status.CANCELLED}),
    Status.RETRYING: frozenset({Status.QUEUED, Status.CANCELLED}),
    Status.DEAD: frozenset({Status.QUEUED}),
    Status.SUCCEEDED: frozenset(),
    Status.CANCELLED: frozenset(),
}


class InvalidTransition(ValueError):
    pass


def transition(current: Status | None, target: Status, *, manual: bool = False) -> Status:
    if target not in TRANSITIONS[current] or (current == Status.DEAD and not manual):
        raise InvalidTransition(f"Illegal transition: {current} -> {target}")
    return target
