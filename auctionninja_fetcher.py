"""AuctionNinja fetcher — scrapes nearby estate-auction lots closing soon.

Output is normalized to the same listing JSON shape used by the CL fetcher, with
`source: "auctionninja"` so the cloud-routine scoring step knows to treat
asking_price as `current_bid * (1 + buyer's_premium)` and to surface ending-time
prominently in the digest.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config import (
    AN_ALLOWED_STATES, AN_BUYERS_PREMIUM_PCT, AN_HOME_ZIP, AN_LOCAL_CITIES,
    AN_MAX_HOURS_TO_CLOSE, AN_MAX_LOTS_PER_SALE,
    REQUEST_TIMEOUT_SEC, USER_AGENT,
)

log = logging.getLogger(__name__)

AN_BASE = "https://www.auctionninja.com"
PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)")
LOT_ID_RE = re.compile(r"MainItmID(\d+)")
# Match e.g. "Fri, May 08 2026 @ 8:00 PM EDT"
CLOSE_TIME_RE = re.compile(
    r"(?P<dow>\w{3}),\s+(?P<month>\w{3})\s+(?P<day>\d+)\s+(?P<year>\d{4})\s+@\s+"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s+(?P<ampm>AM|PM)\s+(?P<tz>\w{2,4})",
    re.IGNORECASE,
)
TZ_OFFSETS = {"EDT": -4, "EST": -5, "CDT": -5, "CST": -6, "MDT": -6, "MST": -7, "PDT": -7, "PST": -8}
MONTH_MAP = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


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


def _parse_money(text: str | None) -> float | None:
    if not text:
        return None
    m = PRICE_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _parse_close_time(text: str) -> datetime | None:
    """Parse 'Fri, May 08 2026 @ 8:00 PM EDT' into a tz-aware UTC datetime."""
    m = CLOSE_TIME_RE.search(text)
    if not m:
        return None
    g = m.groupdict()
    month = MONTH_MAP.get(g["month"][:3].title())
    if not month:
        return None
    hour = int(g["hour"]) % 12
    if g["ampm"].upper() == "PM":
        hour += 12
    offset = TZ_OFFSETS.get(g["tz"].upper(), -4)  # default EDT
    try:
        local = datetime(
            int(g["year"]), month, int(g["day"]),
            hour, int(g["minute"]), 0,
            tzinfo=timezone(timedelta(hours=offset)),
        )
        return local.astimezone(timezone.utc)
    except ValueError:
        return None


def _matches_local_city(location: str) -> bool:
    """Return True if `location` (e.g. 'Pelham, NY') is in our 5-mile whitelist."""
    if not location:
        return False
    loc = location.lower()
    if AN_ALLOWED_STATES:
        if not any(f", {st.lower()}" in loc for st in AN_ALLOWED_STATES):
            return False
    return any(city in loc for city in AN_LOCAL_CITIES)


def fetch_active_sales(session: requests.Session) -> list[dict]:
    """Pull /auctions?zip=<AN_HOME_ZIP> — AN sorts results by distance from this zip."""
    url = f"{AN_BASE}/auctions?zip={AN_HOME_ZIP}"
    log.info("Fetching AN sales: %s", url)
    r = _get(session, url)
    soup = BeautifulSoup(r.content, "lxml")
    sales: list[dict] = []
    for box in soup.select(".featured-auctions-box-in"):
        a = box.find("a", href=True)
        if not a:
            continue
        title_el = box.select_one(".auctions-title")
        company_el = box.select_one(".auction-company-name")
        # `.auctions-loca` holds "City, ST | Local Pickup..."
        loc_el = box.select_one(".auctions-loca")
        location = ""
        if loc_el:
            location = loc_el.get_text(" | ", strip=True).split("|")[0].strip()
        # `.auction-iteam-detail` is reused for two purposes:
        #   - close time: "Begins to close | Fri, May 08 2026 @ 8:00 PM EDT"
        #   - or pre-launch placeholder: "Coming Soon"
        close_time_text = ""
        is_coming_soon = False
        for d in box.select(".auction-iteam-detail"):
            txt = d.get_text(" | ", strip=True)
            if "@" in txt and ("AM" in txt.upper() or "PM" in txt.upper()):
                close_time_text = txt
                break
            if "coming soon" in txt.lower():
                is_coming_soon = True
        sales.append({
            "title": title_el.get_text(strip=True) if title_el else "",
            "location": location,
            "close_time_text": close_time_text,
            "close_time_utc": _parse_close_time(close_time_text),
            "is_coming_soon": is_coming_soon,
            "seller": company_el.get_text(strip=True) if company_el else "",
            "url": a["href"].split("?")[0],
        })
    log.info("  parsed %d sale cards", len(sales))
    return sales


def filter_in_scope_sales(sales: list[dict], now: datetime) -> list[dict]:
    """Apply 5-mile city whitelist + 36-hour close-window filter.
    Excludes Coming-Soon sales (they have no close time yet)."""
    cutoff = now + timedelta(hours=AN_MAX_HOURS_TO_CLOSE)
    out: list[dict] = []
    for sale in sales:
        if not _matches_local_city(sale.get("location", "")):
            continue
        if sale.get("is_coming_soon"):
            continue  # surfaced separately via filter_watch_list
        ct = sale.get("close_time_utc")
        if not ct:
            log.debug("  skip %r: no parseable close time", sale.get("title"))
            continue
        if ct < now:
            continue
        if ct > cutoff:
            log.debug("  skip %r: closes in %s (>%dh)", sale.get("title"), ct - now, AN_MAX_HOURS_TO_CLOSE)
            continue
        out.append(sale)
    log.info("  kept %d sales after city + time filters", len(out))
    return out


def filter_watch_list_sales(sales: list[dict]) -> list[dict]:
    """Coming-soon sales matching the city whitelist. Sale-level metadata only —
    we don't fetch lots from these (bidding isn't open; scoring isn't meaningful yet)."""
    out: list[dict] = []
    for sale in sales:
        if not sale.get("is_coming_soon"):
            continue
        if not _matches_local_city(sale.get("location", "")):
            continue
        out.append({
            "title": sale.get("title"),
            "location": sale.get("location"),
            "auctioneer": sale.get("seller"),
            "sale_url": sale.get("url"),
            "status": "coming_soon",
        })
    log.info("  watch-list sales (coming soon, in 5mi): %d", len(out))
    return out


def _parse_lots_from_page(html: bytes) -> list[dict]:
    """Extract lot stubs from one paginated catalog page."""
    soup = BeautifulSoup(html, "lxml")
    lots: list[dict] = []
    for box in soup.select(".search-catalog-item-box"):
        m = LOT_ID_RE.search(box.get("id", ""))
        if not m:
            continue
        lot_id = m.group(1)
        price_el = box.select_one(".ci-price")
        title_a = box.select_one(".hot-items-title a")
        lot_num_el = box.select_one(".lot-number")
        img_el = box.select_one(".cstm-img-center img, .single-item img")
        thumb_url = None
        if img_el:
            src = img_el.get("src") or ""
            if src.startswith("http"):
                thumb_url = src.replace("/Thumbs/", "/")

        title = title_a.get_text(strip=True) if title_a else ""
        detail_url = title_a.get("href") if title_a else None
        current_bid = _parse_money(price_el.get_text() if price_el else None)
        lot_num = lot_num_el.get_text(strip=True).replace("Lot #:", "").strip() if lot_num_el else ""

        lots.append({
            "lot_id": lot_id,
            "title": title,
            "url": detail_url,
            "current_bid": current_bid,
            "lot_number": lot_num,
            "thumbnail_url": thumb_url,
        })
    return lots


def fetch_lots_for_sale(session: requests.Session, sale: dict) -> list[dict]:
    """Paginate the sale's catalog. AuctionNinja uses ?view=40 (max) and ?Page=N
    (capital P). Continue until we get a short page or hit AN_MAX_LOTS_PER_SALE."""
    import time as _time

    base_url = sale["url"]
    all_lots: list[dict] = []
    page = 1
    PAGE_SIZE = 40  # AN's max per-page
    seen_ids: set[str] = set()

    while True:
        url = base_url + "?" + urlencode({"view": PAGE_SIZE, "Page": page})
        log.info("  fetching lots page %d: %s", page, url)
        try:
            r = _get(session, url)
        except requests.RequestException as e:
            log.warning("  page %d fetch failed: %s", page, e)
            break

        page_lots = _parse_lots_from_page(r.content)
        # De-dupe in case a page returns lots we've already seen (defensive — happens
        # if the server clamps Page beyond the last real page).
        new_lots = [l for l in page_lots if l["lot_id"] not in seen_ids]
        if not new_lots:
            log.info("  no new lots on page %d — stopping", page)
            break
        all_lots.extend(new_lots)
        seen_ids.update(l["lot_id"] for l in new_lots)
        log.info("  page %d: %d lots (total so far: %d)", page, len(new_lots), len(all_lots))

        if len(all_lots) >= AN_MAX_LOTS_PER_SALE:
            log.info("  hit AN_MAX_LOTS_PER_SALE cap (%d)", AN_MAX_LOTS_PER_SALE)
            break
        if len(page_lots) < PAGE_SIZE:
            log.info("  short page (%d < %d) — last page reached", len(page_lots), PAGE_SIZE)
            break

        page += 1
        if page > 50:
            log.warning("  pagination safety break at page 50")
            break
        _time.sleep(0.8)  # polite pacing between pages

    log.info("  parsed %d total lots from sale", len(all_lots))
    return all_lots[:AN_MAX_LOTS_PER_SALE]


def normalize_lot_to_listing(lot: dict, sale: dict) -> dict:
    """Render an AN lot into the same listing schema the cloud routine consumes for CL items."""
    current_bid = lot.get("current_bid") or 0.0
    effective_price = current_bid * (1 + AN_BUYERS_PREMIUM_PCT)
    close_iso = sale["close_time_utc"].isoformat(timespec="seconds") if sale.get("close_time_utc") else None
    return {
        "post_id": f"an_{lot['lot_id']}",
        "url": lot.get("url"),
        "title": lot.get("title"),
        "asking_price": int(round(effective_price)),  # current_bid + 20% BP
        "location": sale.get("location"),
        "posted_at": close_iso,  # sale close time — we use this slot for the routine's freshness logic
        "body": "",  # body fetched per-lot would 4x the request count; the routine can fetch the URL itself if it needs depth
        "thumbnail_url": lot.get("thumbnail_url"),
        "attrs": {
            "lot_number": lot.get("lot_number"),
            "current_bid": current_bid,
            "buyers_premium_pct": int(AN_BUYERS_PREMIUM_PCT * 100),
            "ends_at": close_iso,
            "auctioneer": sale.get("seller"),
            "sale_title": sale.get("title"),
            "sale_url": sale.get("url"),
        },
        "search_key": "auctionninja",
        "category": "auction",
        "source": "auctionninja",
    }


def fetch_all() -> dict:
    """Top-level: fetch nearby sales and split into:
      - listings: lots from sales closing within 36h (full per-lot scoring)
      - watch_list: coming-soon sales within 5mi (sale-level metadata only)
    """
    session = _session()
    now = datetime.now(timezone.utc)

    all_sales: list[dict] = []
    try:
        all_sales = fetch_active_sales(session)
    except requests.RequestException as e:
        log.error("AN /auctions?zip=%s failed: %s", AN_HOME_ZIP, e)

    in_scope = filter_in_scope_sales(all_sales, now)
    watch_list = filter_watch_list_sales(all_sales)
    log.info("AN: %d total sales -> %d in-scope (scoring), %d on watch list (coming soon)",
             len(all_sales), len(in_scope), len(watch_list))

    listings: list[dict] = []
    for sale in in_scope:
        try:
            lots = fetch_lots_for_sale(session, sale)
        except requests.RequestException as e:
            log.warning("Lot fetch failed for %r: %s", sale.get("title"), e)
            continue
        for lot in lots:
            listings.append(normalize_lot_to_listing(lot, sale))
    return {"listings": listings, "watch_list": watch_list}


if __name__ == "__main__":
    import argparse
    import json
    import sys

    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--log", action="store_true")
    parser.add_argument("--probe-sales", action="store_true",
                        help="Just list active sales for AN_ALLOWED_STATES — no lot fetches")
    args = parser.parse_args()

    if args.log:
        logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                            format="%(asctime)s %(levelname)s %(message)s")

    if args.probe_sales:
        session = _session()
        sales = fetch_active_sales(session)
        for s in sales:
            ct = s.get("close_time_utc")
            in_scope = _matches_local_city(s.get("location", ""))
            print(f"  [{'X' if in_scope else ' '}] {s.get('location'):30s} {ct} {s.get('title')[:80]}")
        sys.exit(0)

    result = fetch_all()
    print(json.dumps(result, indent=2, default=str))
