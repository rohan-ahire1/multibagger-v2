from __future__ import annotations

import requests

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}
NSE_HOME = "https://www.nseindia.com/"


def build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_HEADERS)
    return s


def bootstrap(session: requests.Session, timeout_s: float) -> None:
    """NSE APIs need cookies from the home page first."""
    try:
        session.get(NSE_HOME, timeout=timeout_s)
    except requests.RequestException:
        pass
