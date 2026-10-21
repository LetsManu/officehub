"""Is a server of the stack (office, meetings) running? Checked when needed and remembered for a short while,
so optional parts switch themselves on and off without any setting."""

import time
import urllib.error
import urllib.request

_cache: dict[str, tuple[float, bool]] = {}


def reachable(url: str) -> bool:
    now = time.monotonic()
    hit = _cache.get(url)
    if hit and now < hit[0]:
        return hit[1]
    try:
        with urllib.request.urlopen(url, timeout=2):  # noqa: S310 - own servers inside the stack
            up = True
    except urllib.error.HTTPError:
        up = True  # it answered, so it is running
    except (OSError, ValueError):
        up = False
    _cache[url] = (now + (60 if up else 20), up)
    return up
