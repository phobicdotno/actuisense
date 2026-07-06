"""
Newer-version check against GitHub releases.

Stdlib-only (urllib), one request with a short timeout, and fail-silent: any
network / API / parse problem simply means "no update information" (None) —
a bench tool must never break because github.com is unreachable.
"""

import json
import urllib.request
from typing import Optional, Tuple

from . import __version__

RELEASES_API = "https://api.github.com/repos/phobicdotno/actuisense/releases/latest"
RELEASES_URL = "https://github.com/phobicdotno/actuisense/releases"


def parse_version(ver: str) -> Tuple[int, ...]:
    """'v0.6.2' / '0.6.2' -> (0, 6, 2). A non-numeric part ends the tuple, so
    'v0.7.0-rc1' -> (0, 7, 0) and garbage -> ()."""
    out = []
    for part in ver.lstrip("vV").split("."):
        num = ""
        for ch in part:
            if not ch.isdigit():
                break
            num += ch
        if not num:
            break
        out.append(int(num))
    return tuple(out)


def latest_release(timeout: float = 3.0) -> Optional[str]:
    """Tag name of the newest GitHub release (e.g. 'v0.6.2'), or None on any failure."""
    try:
        req = urllib.request.Request(RELEASES_API, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "actuisense/%s" % __version__,
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            tag = json.load(r).get("tag_name")
            return tag if isinstance(tag, str) and tag else None
    except Exception:
        return None


def update_available(timeout: float = 3.0) -> Optional[str]:
    """Newest release tag if it is strictly newer than the running version, else None."""
    tag = latest_release(timeout=timeout)
    if tag and parse_version(tag) > parse_version(__version__):
        return tag
    return None
