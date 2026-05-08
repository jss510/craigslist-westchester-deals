# Craigslist Westchester Deal Hunter

A scheduled Claude Code routine that scrapes Craigslist Westchester (`/wch/` on `newyork.craigslist.org`) every 4 hours, scores each new listing for arbitrage potential, and drafts a Gmail digest of the highest-scoring undervalued opportunities.

**Scope (v1):** Electronics, musical instruments, portable power tools, Lego, espresso/premium kitchen gear. Email-only — no automated outreach to sellers.

**Architecture:** A scheduled Claude Code routine (Anthropic-cloud CCR) clones this repo on each fire, runs the stateless Python fetcher, scores the results in-session, and drafts a Gmail email via the Gmail MCP connector. **No Anthropic API key, no SMTP setup, no Windows Task Scheduler.**

---

## Layout

```
Craigslist/
├── config.py           # tunables (search queries, price caps, since-hours window)
├── fetcher.py          # stateless Craigslist scraper; prints JSON to stdout
├── prompts/
│   └── routine.md      # full instruction set the routine reads each fire
├── requirements.txt
├── .gitignore
└── README.md
```

There is no database. The routine is stateless. Time-window dedupe (last 5 hours) handles the "don't re-score the same listing" problem at acceptable boundary loss (~one listing might be re-scored at the edge of the 4-hour window).

---

## Local commands (for tuning / debugging)

| Command | Purpose |
|---|---|
| `python fetcher.py --probe --search-key electronics` | Show 5 search-page stubs without hitting detail pages (fast) |
| `python fetcher.py --since-hours 5 --log` | Full fetch, prints JSON of recent listings to stdout, logs to stderr |
| `python fetcher.py --search-key tools --since-hours 12` | Run one search only |

The cloud routine runs `python fetcher.py --since-hours 5 --log > /tmp/listings.json`, then reads the JSON and does triage + scoring in-session.

---

## Tuning

All knobs in `config.py`:

- **`SEARCHES`** — add/remove keyword searches. Example to add Festool tracking:
  ```python
  {"key": "festool_tla", "cat": "tla", "query": "festool"}
  ```
- **`MIN_ASKING_PRICE`** — drop listings priced ≤ this as scam/bait (default 2).
- **`MAX_PRICE_BY_KEY`** — per-search ceiling on asking price.
- **`DEFAULT_SINCE_HOURS`** — how far back to look on each fire (default 5).

Score threshold and routine behavior live in `prompts/routine.md`. Edit there to change how Claude judges listings, what message tone to use, etc.

---

## Risks

- **Craigslist blocks the cloud IP.** CL has been aggressive with anti-bot blocks. The HTML pages worked from a local Windows machine with a real browser User-Agent (verified 2026-05-08), but Anthropic-cloud IPs may be on a blocklist. The routine is instructed to surface 403 errors prominently in its summary so we can pivot if this happens.
- **Craigslist changes the search-page DOM.** `li.cl-static-search-result` is the current selector. If it changes, `parse_search_page` returns 0 stubs — easy to spot.

---

## Out of scope (v1)

- Auto-messaging sellers — the digest contains a draft message you can paste into the CL reply form yourself.
- Photo download + Claude vision for condition assessment.
- Multi-region (locked to Westchester).
- Tracking actual purchase outcomes / closing the loop on real margin.
