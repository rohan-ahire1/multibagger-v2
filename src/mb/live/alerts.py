"""Push notifications through ntfy. Every message is also printed, so the job log has it when no topic is set."""
from __future__ import annotations

import os
import sys

import requests

from mb.config.models import PaperAlerts


class Alerter:
    def __init__(self, cfg: PaperAlerts):
        self.cfg = cfg
        self.topic = os.environ.get(cfg.topic_env) or None

    def send(self, title: str, body: str, priority: str = "default", tags: tuple[str, ...] = ()) -> bool:
        """True if the push was delivered. A failed push is printed, never raised: alerting must not stop the job."""
        print(f"[{priority}] {title}\n{body}", file=sys.stderr)
        if not self.topic:
            return False
        try:
            resp = requests.post(f"{self.cfg.ntfy_url.rstrip('/')}/{self.topic}", data=body.encode(), timeout=15,
                                 headers={"Title": title, "Priority": priority, "Tags": ",".join(tags)})
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"alert push failed: {e}", file=sys.stderr)
            return False
        return True
