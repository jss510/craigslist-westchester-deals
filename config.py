"""Tunable parameters for the stateless Craigslist fetcher."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"

CL_BASE = "https://newyork.craigslist.org"
CL_AREA = "wch"  # Westchester sub-area of NYC site
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Each entry is one search query. We use canonical CL category codes (the modern
# "all" forms) plus an explicit purveyor=owner filter (added in fetcher._build_search_url).
#   ela=electronics, msa=musical instruments, tla=tools, ppa=appliances,
#   cba=collectibles, taa=toys+games, vga=video gaming, sss=general for-sale.
SEARCHES = [
    {"key": "electronics",   "cat": "ela"},
    {"key": "instruments",   "cat": "msa"},
    {"key": "tools",         "cat": "tla"},
    {"key": "appliances",    "cat": "ppa"},
    {"key": "collectibles",  "cat": "cba"},
    {"key": "toys_games",    "cat": "taa"},
    {"key": "video_gaming",  "cat": "vga"},
    # Targeted keyword searches in adjacent categories (relevance-ordered; full scan)
    {"key": "lego_sss",      "cat": "sss", "query": "lego"},
]

# How far back the dedupe window stretches. The routine fires every 4h, so 5h covers
# overlap (one boundary listing may be re-scored, fine).
DEFAULT_SINCE_HOURS = 5

# Filtering
MIN_ASKING_PRICE = 2  # drop listings priced $1 or below (scam/bait flag)

# Per-search sanity cap on asking price (above this, almost certainly not undervalued)
MAX_PRICE_BY_KEY = {
    "electronics":   2000,
    "instruments":   3000,
    "tools":         1500,
    "appliances":    1000,
    "collectibles":  3000,  # cards/comics/vinyl can run high
    "toys_games":     500,
    "video_gaming":  1500,  # retro consoles + premium new-gen
    "lego_sss":      1000,
}

# HTTP politeness
REQUEST_TIMEOUT_SEC = 30
DELAY_BETWEEN_DETAIL_FETCHES_SEC = 1.0

# Per-search cap on stubs to inspect (CL sorts newest-first so the freshest listings
# are always at the top). With since_hours=5 and Westchester volume of ~10-30
# listings/cat/day, 40 is plenty of margin while keeping each fetch run bounded.
MAX_STUBS_PER_SEARCH = 40
