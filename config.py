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

# AuctionNinja (auction-site) settings
AN_HOME_ZIP = "10803"  # Pelham, NY
# Cities/towns within ~5 miles of 10803. Match is case-insensitive substring against
# the auction's "City, ST" label. If a city name is ambiguous (e.g. "Pelham" exists
# in many states), we also constrain by state via AN_ALLOWED_STATES below.
AN_LOCAL_CITIES = [
    "pelham",         # Pelham, Pelham Manor (10803, 10805)
    "mount vernon",   # 10550, 10552, 10553
    "eastchester",    # 10709
    "bronxville",     # 10708
    "tuckahoe",       # 10707
    "new rochelle",   # 10801, 10804, 10805
    "city island",    # Bronx 10464
    "throggs neck",   # Bronx 10465
    "co-op city",     # Bronx 10475
]
AN_ALLOWED_STATES = ["NY"]  # state filter applied via ?state= URL param too
# Most online estate auctions charge a buyer's premium on top of the winning bid.
# 18-23% is industry typical; we use a conservative 20% so margin estimates aren't optimistic.
AN_BUYERS_PREMIUM_PCT = 0.20
# Only score lots whose sale closes within this many hours from now.
AN_MAX_HOURS_TO_CLOSE = 36
# Per-lot cap so a single huge sale doesn't blow up the run. 200 is plenty for a
# focused estate sale within driving distance.
AN_MAX_LOTS_PER_SALE = 200
