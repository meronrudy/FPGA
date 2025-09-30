# common/notify.py
"""
Minimal Slack notifier.

- Reads webhook URL from env SLACK_WEBHOOK_URL unless explicitly passed.
- Provides a CLI entry: `python -m common.notify --status success --variant baseline8 --message "Hardware smoke passed"`
- Safe-by-default: if no webhook configured, it logs and exits 0 without failing the pipeline.

No external deps required (uses urllib).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from .logging import setup_logging, get_logger


def _build_run_url() -> Optional[str]:
    """
    Build a GitHub Actions run URL from environment if available.
    """
    server = os.getenv("GITHUB_SERVER_URL")
    repo = os.getenv("GITHUB_REPOSITORY")
    run_id = os.getenv("GITHUB_RUN_ID")
    if server and repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return None


def _post_json(url: str, payload: Dict[str, Any]) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        # Drain response for completeness
        _ = resp.read()


def notify_slack(
    *,
    webhook_url: Optional[str],
    status: str,
    variant: Optional[str] = None,
    message: Optional[str] = None,
    run_url: Optional[str] = None,
) -> None:
    """
    Send a Slack notification. If webhook_url is None or empty, no-op.
    """
    log = get_logger(__name__)

    hook = webhook_url or os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not hook:
        log.warning("SLACK_WEBHOOK_URL not set; skipping Slack notification")
        return

    status_emoji = {"success": ":white_check_mark:", "failure": ":x:", "warning": ":warning:"}.get(status, ":information_source:")
    vtext = f"*Variant:* `{variant}`" if variant else ""
    urltext = f"\n*Run:* {run_url}" if run_url else ""
    m = message or ""
    text = f"{status_emoji} {status.upper()} {vtext}\n{m}{urltext}".strip()

    payload: Dict[str, Any] = {"text": text}
    try:
        _post_json(hook, payload)
        log.info("Posted Slack message: %s", status)
    except urllib.error.HTTPError as e:
        log.error("Slack webhook HTTPError %s: %s", e.code, e.read())
    except Exception as e:
        log.error("Slack webhook error: %s", e)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Send a Slack notification via webhook")
    parser.add_argument("--status", choices=["success", "failure", "warning", "info"], default="info")
    parser.add_argument("--variant", help="Variant or label")
    parser.add_argument("--message", help="Message text")
    parser.add_argument("--run-url", help="CI run URL (if omitted, inferred from env)")
    parser.add_argument("--webhook-url", help="Override Slack webhook URL (otherwise env SLACK_WEBHOOK_URL)")

    args = parser.parse_args(argv)

    setup_logging()
    log = get_logger(__name__)

    run_url = args.run_url or _build_run_url()
    try:
        notify_slack(
            webhook_url=args.webhook_url,
            status=args.status,
            variant=args.variant,
            message=args.message,
            run_url=run_url,
        )
        return 0
    except Exception as e:
        # Do not break CI if notification fails
        log.error("notify_slack unexpected error: %s", e)
        return 0


if __name__ == "__main__":
    sys.exit(main())