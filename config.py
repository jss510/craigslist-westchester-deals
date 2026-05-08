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

# Each entry is one search query. CL category codes:
#   ele=electronics, msa=musical instruments, tla=tools,
#   sss=general for-sale, app=appliances, hsh=household, tag=toys+games.
SEARCHES = [
    {"key": "electronics", "cat": "ele"},
    {"key": "instruments", "cat": "msa"},
    {"key": "tools",       "cat": "tla"},
    {"key": "lego_sss",    "cat": "sss", "query": "lego"},
    {"key": "lego_tag",    "cat": "tag", "query": "lego"},
    {"key": "espresso_app",  "cat": "app", "query": "espresso"},
    {"key": "rancilio_app",  "cat": "app", "query": "rancilio"},
    {"key": "breville_app",  "cat": "app", "query": "breville"},
    {"key": "gaggia_app",    "cat": "app", "query": "gaggia"},
    {"key": "vitamix_app",   "cat": "app", "query": "vitamix"},
    {"key": "kitchenaid_app","cat": "app", "query": "kitchenaid"},
    {"key": "lecreuset_hsh", "cat": "hsh", "query": "le creuset"},
    {"key": "wusthof_hsh",   "cat": "hsh", "query": "wusthof"},
]

# How far back the dedupe window stretches. The routine fires every 4h, so 5h covers
# overlap (one boundary listing may be re-scored, fine).
DEFAULT_SINCE_HOURS = 5

# Filtering
MIN_ASKING_PRICE = 2  # drop listings priced $1 or below (scam/bait flag)

# Per-search sanity cap on asking price (above this, almost certainly not undervalued)
MAX_PRICE_BY_KEY = {
    "electronics":     2000,
    "instruments":     3000,
    "tools":           1500,
    "lego_sss":        1000,
    "lego_tag":        1000,
    "espresso_app":     800,
    "rancilio_app":     800,
    "breville_app":     800,
    "gaggia_app":       800,
    "vitamix_app":      400,
    "kitchenaid_app":   400,
    "lecreuset_hsh":    400,
    "wusthof_hsh":      400,
}

# HTTP politeness
REQUEST_TIMEOUT_SEC = 30
DELAY_BETWEEN_DETAIL_FETCHES_SEC = 1.5
