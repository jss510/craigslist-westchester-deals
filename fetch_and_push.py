"""Local fetch wrapper for Path A (hybrid: local fetch, cloud scoring).

Designed to be invoked by Windows Task Scheduler 4x/day. It:
  1. Pulls the repo (so we have any prompt/config tweaks).
  2. Runs the fetcher to scrape CL Westchester.
  3. Writes data/latest_listings.json.
  4. Commits + pushes if the file changed.

The cloud routine then clones the repo at its next fire and reads that JSON.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import fetcher
from config import DEFAULT_SINCE_HOURS, PROJECT_ROOT

log = logging.getLogger(__name__)
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_PATH = DATA_DIR / "latest_listings.json"


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    log.info("=== fetch_and_push starting ===")

    log.info("git pull --ff-only")
    pull = run_git("pull", "--ff-only", check=False)
    if pull.returncode != 0:
        log.warning("git pull non-zero (%s): %s", pull.returncode, pull.stderr.strip())

    log.info("Running fetcher.fetch_all(since_hours=%d)", DEFAULT_SINCE_HOURS)
    try:
        listings = fetcher.fetch_all(since_hours=DEFAULT_SINCE_HOURS)
    except Exception:
        log.exception("Fetch failed")
        return 1
    log.info("Fetched %d listings", len(listings))

    DATA_DIR.mkdir(exist_ok=True)
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "since_hours": DEFAULT_SINCE_HOURS,
        "count": len(listings),
        "listings": listings,
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Wrote %s (%d bytes)", OUTPUT_PATH, OUTPUT_PATH.stat().st_size)

    status = run_git("status", "--porcelain", "data/latest_listings.json", check=False)
    if not status.stdout.strip():
        log.info("No changes to commit; exiting.")
        return 0

    run_git("add", "data/latest_listings.json")
    msg = (
        f"chore: refresh listings ({len(listings)} items, "
        f"fetched {payload['fetched_at']})"
    )
    commit = run_git("commit", "-m", msg, check=False)
    if commit.returncode != 0:
        log.error("git commit failed: %s", commit.stderr.strip())
        return 1

    push = run_git("push", check=False)
    if push.returncode != 0:
        log.error("git push failed: %s", push.stderr.strip())
        return 1

    log.info("=== fetch_and_push complete: %d listings pushed ===", len(listings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
