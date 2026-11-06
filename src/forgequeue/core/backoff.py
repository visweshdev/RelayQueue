import random


def retry_delay(attempt: int, base: float = 2, cap: float = 300) -> float:
    if attempt < 1 or base < 0 or cap < base:
        raise ValueError("Invalid retry policy")
    return random.uniform(0, min(cap, base * 2 ** min(attempt - 1, 30)))
