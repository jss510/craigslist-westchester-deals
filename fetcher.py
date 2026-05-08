"""Stateless Craigslist Westchester fetcher. Prints JSON of recent listings to stdout.

Usage:
    python fetcher.py                          # all searches, last 5h, JSON to stdout
    python fetcher.py --since-hours 8          # widen the window
    python fetcher.py --search-key electronics # one search only
    python fetcher.py --probe                  # 5-stub preview, no detail fetch (fast)
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config import (
    CL_AREA, CL_BASE, DEFAULT_SINCE_HOURS, DELAY_BETWEEN_DETAIL_FETCHES_SEC,
    MAX_PRICE_BY_KEY, MAX_STUBS_PER_SEARCH, MIN_ASKING_PRICE, REQUEST_TIMEOUT_SEC,
    SEARCHES, USER_AGENT,
)

log = logging.getLogger(__name__)

POST_ID_RE = re.compile(r"/(\d+)\.html")
PRICE_RE = re.compile(r"\$([\d,]+)")


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


@retry(
    retry=retry_if_exception_type((requests.RequestException,)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    reraise=True,
)
def _get(session: requests.Session, url: str) -> requests.Response:
    r = session.get(url, timeout=REQUEST_TIMEOUT_SEC, allow_redirects=True)
    r.raise_for_status()
    return r


def _build_search_url(search: dict) -> str:
    """Build a CL search URL. Always filter to by-owner; legacy codes auto-redirected
    to ?purveyor=owner but canonical codes (ela/ppa/taa/cba/vga) do not."""
    cat = search["cat"]
    base = f"{CL_BASE}/search/{CL_AREA}/{cat}"
    params = ["purveyor=owner"]
    if search.get("query"):
        params.append(f"query={requests.utils.quote(search['query'])}")
    return base + "?" + "&".join(params)


def _parse_price(text: str | None) -> int | None:
    if not text:
        return None
    m = PRICE_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _parse_post_id(url: str) -> str | None:
    m = POST_ID_RE.search(url)
    return m.group(1) if m else None


def parse_search_page(html: bytes) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    for li in soup.select("li.cl-static-search-result"):
        a = li.find("a", href=True)
        if not a:
            continue
        href = a["href"]
        post_id = _parse_post_id(href)
        if not post_id:
            continue
        title_el = li.select_one(".title") or li
        price_el = li.select_one(".price")
        loc_el = li.select_one(".location")
        items.append({
            "post_id": post_id,
            "url": href,
            "title": title_el.get_text(strip=True) if title_el else None,
            "asking_price": _parse_price(price_el.get_text() if price_el else None),
            "location": loc_el.get_text(strip=True) if loc_el else None,
        })
    return items


def parse_detail_page(html: bytes) -> dict:
    soup = BeautifulSoup(html, "lxml")

    title_el = soup.select_one("#titletextonly") or soup.select_one(".postingtitletext")
    title = title_el.get_text(strip=True) if title_el else None

    price_el = soup.select_one(".price")
    price = _parse_price(price_el.get_text() if price_el else None)

    posted_el = soup.select_one("time[datetime]")
    posted_at = posted_el.get("datetime") if posted_el else None

    body_el = soup.select_one("#postingbody")
    body = None
    if body_el:
        for junk in body_el.select(".print-information, .print-qrcode-container"):
            junk.decompose()
        body = body_el.get_text(" ", strip=True)
        body = re.sub(r"^QR Code Link to This Post\s*", "", body)

    thumb = None
    for img in soup.select(".gallery img, .swipe img, figure img"):
        src = img.get("src")
        if src and src.startswith("https://images.craigslist.org/"):
            thumb = src
            break

    attrs: dict[str, str] = {}
    for grp in soup.select(".attrgroup"):
        for span in grp.select("span"):
            txt = span.get_text(" ", strip=True)
            if ":" in txt:
                k, _, v = txt.partition(":")
                if v.strip():
                    attrs[k.strip().lower()] = v.strip()

    return {
        "title": title,
        "asking_price": price,
        "posted_at": posted_at,
        "body": body,
        "thumbnail_url": thumb,
        "attrs": attrs,
    }


def _is_westchester(location: str | None) -> bool:
    if not location:
        return True
    loc = location.lower()
    blocked = (
        "stamford", "greenwich", "norwalk", "darien", "new canaan",
        "bronx", "manhattan", "brooklyn", "queens", "staten island",
        "fairfield", " ct", ",ct",
        " nj", ",nj", "jersey",
    )
    return not any(s in loc for s in blocked)


def _within_window(posted_at_iso: str | None, cutoff: datetime) -> bool:
    """True if `posted_at_iso` is None (unknown — keep) or >= cutoff."""
    if not posted_at_iso:
        return True
    try:
        ts = datetime.fromisoformat(posted_at_iso)
    except ValueError:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts >= cutoff


def fetch_one_search(session: requests.Session, search: dict, cutoff: datetime) -> list[dict]:
    """Fetch + enrich listings for one search query, filtered to last `cutoff` window.

    The CL search page does NOT reliably sort newest-first — it places multi-area
    cross-posts (and possibly other promoted listings) at the top regardless of date.
    So we scan the full stub cap and rely on the per-listing posted_at filter.
    """
    url = _build_search_url(search)
    log.info("Fetching search %s -> %s", search["key"], url)
    r = _get(session, url)
    stubs = parse_search_page(r.content)
    log.info("  parsed %d stubs (capping at %d)", len(stubs), MAX_STUBS_PER_SEARCH)
    stubs = stubs[:MAX_STUBS_PER_SEARCH]

    cap = MAX_PRICE_BY_KEY.get(search["key"])
    out: list[dict] = []
    inspected = 0
    for stub in stubs:
        price = stub.get("asking_price")
        if price is not None and price < MIN_ASKING_PRICE:
            continue
        if cap and price is not None and price > cap:
            continue
        if not _is_westchester(stub.get("location")):
            continue

        time.sleep(DELAY_BETWEEN_DETAIL_FETCHES_SEC)
        inspected += 1
        try:
            detail_resp = _get(session, stub["url"])
        except requests.RequestException as e:
            log.warning("  detail fetch failed for %s: %s", stub["post_id"], e)
            continue
        detail = parse_detail_page(detail_resp.content)
        log.info(
            "  [%d] %s ($%s) posted=%s",
            inspected, stub.get("title", "?")[:60],
            detail.get("asking_price") or stub.get("asking_price"),
            detail.get("posted_at"),
        )

        d_price = detail.get("asking_price")
        if d_price is not None and d_price < MIN_ASKING_PRICE:
            continue
        if cap and d_price is not None and d_price > cap:
            continue

        posted = detail.get("posted_at")
        if posted and not _within_window(posted, cutoff):
            continue

        merged = {
            **stub,
            **{k: v for k, v in detail.items() if v is not None and v != {}},
            "search_key": search["key"],
            "category": search["cat"],
        }
        out.append(merged)
    log.info("  kept %d listings (inspected %d details)", len(out), inspected)
    return out


def fetch_all(since_hours: int) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    session = _session()
    all_items: list[dict] = []
    for search in SEARCHES:
        try:
            all_items.extend(fetch_one_search(session, search, cutoff))
        except requests.RequestException as e:
            log.error("Search %s failed: %s", search["key"], e)
    # Dedupe by post_id (same listing can appear in multiple keyword searches)
    seen = set()
    deduped = []
    for item in all_items:
        if item["post_id"] in seen:
            continue
        seen.add(item["post_id"])
        deduped.append(item)
    return deduped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stateless Craigslist Westchester fetcher")
    parser.add_argument("--since-hours", type=int, default=DEFAULT_SINCE_HOURS)
    parser.add_argument("--search-key", help="Run only the search with this key")
    parser.add_argument("--probe", action="store_true",
                        help="Print 5 stubs from one search; skip detail fetch")
    parser.add_argument("--log", action="store_true",
                        help="Log progress to stderr; without this the script is silent on stderr")
    args = parser.parse_args(argv)

    if args.log:
        logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                            format="%(asctime)s %(levelname)s %(message)s")

    session = _session()

    if args.probe:
        search = next((s for s in SEARCHES if s["key"] == (args.search_key or "electronics")), None)
        if not search:
            print(f"Unknown search-key: {args.search_key}", file=sys.stderr)
            return 1
        url = _build_search_url(search)
        r = _get(session, url)
        stubs = parse_search_page(r.content)
        print(json.dumps({"url": url, "total_stubs": len(stubs), "first_5": stubs[:5]}, indent=2))
        return 0

    if args.search_key:
        search = next((s for s in SEARCHES if s["key"] == args.search_key), None)
        if not search:
            print(f"Unknown search-key: {args.search_key}", file=sys.stderr)
            return 1
        cutoff = datetime.now(timezone.utc) - timedelta(hours=args.since_hours)
        items = fetch_one_search(session, search, cutoff)
    else:
        items = fetch_all(args.since_hours)

    print(json.dumps(items, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
