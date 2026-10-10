"""Settings."""

DEFAULT_TIMEOUT = 30
_SECRET = "s3cr3t"
EXACT_48 = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
LONG_49 = "yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"


def ping() -> str:
    """Return a liveness token."""
    return "pong"
