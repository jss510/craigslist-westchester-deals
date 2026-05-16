# Project notes for Claude — craigslist-westchester

## What this project is

A stateless cloud routine (`trig_01EEHuck6kBLx7xauUxDbJSR`) that scrapes
Westchester Craigslist and AuctionNinja for arbitrage opportunities and drafts
Gmail digests to jss510@gmail.com.

Two halves:
- **Local (this folder):** Python fetcher scripts hit Craigslist/AuctionNinja
  from a residential IP and commit fresh JSON to GitHub. Run by Windows Task
  Scheduler task `craigslist-fetch-push` every 4 hours.
- **Cloud (Anthropic routine):** Reads the fresh JSON from GitHub, scores
  listings, drafts a Gmail digest. Runs every 4 hours, slightly offset from
  the local fetch.

## Why this project does NOT follow the standard layout

The global CLAUDE.md says code goes in `src\`. This project deliberately does
not, because:

1. **`data\latest_listings.json` is a path contract.** The cloud routine reads
   this exact path from the GitHub repo. Moving it would require coordinated
   changes to `prompts\routine.md` AND the cloud routine config.
2. **`prompts\routine.md` is a path contract.** Same reasoning.
3. **Python files use flat imports** (`from config import ...`). Restructuring
   into a package would force `python -m <package>.fetch_and_push` invocation
   and complicate Task Scheduler.

The repo structure IS the deliverable to the cloud routine. Treat the
top-level layout as immutable unless coordinating a wider change.

The standard subfolders (`inputs\`, `outputs\`, `notes\`) ARE present and
should be used for new work (research, planning, design notes) that doesn't
participate in the cloud-routine contract.

## Key contracts and references

- **GitHub repo (private):** https://github.com/jss510/craigslist-westchester-deals
- **Cloud routine ID:** `trig_01EEHuck6kBLx7xauUxDbJSR`
  - Manage at: https://claude.ai/code/routines/trig_01EEHuck6kBLx7xauUxDbJSR
- **Cloud routine cron:** `0 0,12,16,20 * * *` UTC = 8am/12pm/4pm/8pm
  America/New_York during EDT. **Will need a 1-hour shift when DST ends in
  November** (cron is in UTC, not local time).
- **Local Windows task:** `craigslist-fetch-push` in Task Scheduler.
  WorkingDirectory must match this project's current path.
- **Entry point:** `python fetch_and_push.py` from project root.
- **Recipient email:** jss510@gmail.com. **Drafts only — never auto-sends.**

## Project-specific rules

- **Don't restructure the file layout** (see above for why).
- The Python entry point is `fetch_and_push.py` run from this project root.
  Preserve that invocation pattern.
- The `data\` folder is regenerated every fetch; don't store anything else
  there.
- Use the standard `inputs\`, `outputs\`, `notes\` subfolders for new
  workspace material that isn't part of the cloud-routine contract.

## Scope and filters (from the active routine)

- Westchester-only. Explicitly drops Bronx, Stamford CT, NJ.
- Categories in scope: electronics, musical instruments, portable power tools
  (no cabinet saws), Lego, premium kitchen gear (Rancilio, Breville, Gaggia,
  Vitamix, KitchenAid, Le Creuset, Wüsthof).
- Digest inclusion for Craigslist: `score >= 75` AND
  `fair_value_low - asking_price >= 200`.
- Digest inclusion for AuctionNinja: `score >= 75` AND
  `max_recommended_bid >= 5` where
  `max_recommended_bid = floor((fair_value_low - 200) / 1.20)`
  (the 1.20 accounts for AN's 20% buyer's premium).
- AN scope: lots from sales within ~5 miles of zip 10803, closing within 36
  hours. URL uses `?zip=10803` (proximity-sorted), not `?state=NY`.
- Items < $1 are auto-flagged as scam/bait.

## Known issues / past incidents

- Craigslist 403-blocks the Anthropic cloud sandbox IP (confirmed 2026-05-08).
  This is why fetching runs locally instead of in the cloud routine.
- DST ending in November will shift the local time of each fire by 1 hour
  unless the UTC cron is updated.
