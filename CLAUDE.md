# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`nhscc_scraper.py` is a standalone Python script that scrapes autocross event results from the NHSCC (Northern Hills Sports Car Club) website and stores them in a SQLite database. It handles ~25 years of event history (2000–present), spanning two distinct eras of the website: plain static HTML and JavaScript-rendered pages.

## Running the Scraper

```bash
# Dependencies (one-time setup)
pip install requests beautifulsoup4 playwright
playwright install chromium

# Basic usage
python nhscc_scraper.py                          # Scrape all events
python nhscc_scraper.py --year 2024              # Single year
python nhscc_scraper.py --start-year 2020        # From 2020 onward
python nhscc_scraper.py --output results.db      # Custom DB path
python nhscc_scraper.py --csv                    # Also export CSV
python nhscc_scraper.py --delay 2.0              # Seconds between requests
```

There is no test suite, linter config, or build step.

## Architecture

The script is organized into four logical layers:

**Data model** — `DriverResult` dataclass (line ~36): one row per driver per event. Key fields: `event_date`, `car_class`, `name`, `best_time`, `pax_index`, `pax_time`, `source_url`, `scrape_method`.

**Event registry** (lines ~54–327): a hard-coded list of `(year, event_id, url)` tuples covering all known events. Adding new events requires manually appending to this list.

**Parsers** — two distinct parsers for the two website eras:
- `parse_static_html()`: handles plain HTML tables (older events). Extracts car class from the car ID using regex (e.g., `"34ASP"` → class `"ASP"`).
- `scrape_with_playwright()` + `parse_finish_time_page()`: renders JS-heavy pages via headless Chromium and parses the resulting DOM. `is_js_rendered()` detects which parser to use by checking for `"Loading data"` in the raw HTML.

**Database layer** — SQLite via the `sqlite3` stdlib. `init_db()` creates the `results` table. `already_scraped()` prevents re-fetching URLs already in the DB, making re-runs safe and incremental.

## Key Behaviors to Know

- If Playwright is not installed, JS-rendered pages are silently skipped rather than crashing.
- `safe_float()` treats times of `999` (NHSCC's DNF marker) as `None`.
- The scraper prints `✓`, `⚠`, and `✗` status indicators per event to stdout.
- `source_url` serves as the deduplication key; re-running skips already-scraped events.
- Request delay (default 1 second) is applied between all fetches to avoid hammering the server.
