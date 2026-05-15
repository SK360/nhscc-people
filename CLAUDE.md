# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

This is the **NHSCC People** project — a historical results database and GitHub Pages dashboard for the Northern Hills Sports Car Club autocross series. It covers ~26 years of event history (2000–present).

### File structure

```
nhscc_scraper.py   — Scrapes nhscc.com and populates nhscc_results.db
export_json.py     — Reads nhscc_results.db and writes docs/data.json
docs/index.html    — Single-file GitHub Pages dashboard (loads data.json)
docs/data.json     — Pre-built JSON payload (committed, served by GH Pages)
nhscc_results.db   — SQLite database (NOT committed; lives in repo root only)
dashboard.py       — Old local HTTP dashboard (superseded by GH Pages; ignore)
```

### Pipeline

```
nhscc_scraper.py  →  nhscc_results.db  →  export_json.py  →  docs/data.json  →  docs/index.html
```

### Git / worktree workflow

All active Claude work happens in a **git worktree** at:
`.claude/worktrees/goofy-keller-6d51ad/`

Push pattern (worktree branch → main):
```bash
git push origin claude/goofy-keller-6d51ad:main
```

The DB (`nhscc_results.db`) lives **only** in the main repo root
(`/Users/matt/Git/nhscc-people/nhscc_results.db`). When running the scraper
or export from the worktree, copy it in first and remove it after:

```bash
cp /Users/matt/Git/nhscc-people/nhscc_results.db ./nhscc_results.db
python3 nhscc_scraper.py --year 2025
python3 export_json.py
cp nhscc_results.db /Users/matt/Git/nhscc-people/nhscc_results.db
rm nhscc_results.db
```

---

## Running the Scraper (`nhscc_scraper.py`)

```bash
# One-time setup
pip install requests beautifulsoup4 playwright
playwright install chromium

# Usage
python3 nhscc_scraper.py                    # Scrape all (skips already-scraped URLs)
python3 nhscc_scraper.py --year 2024        # Single year
python3 nhscc_scraper.py --start-year 2020  # From 2020 onward
python3 nhscc_scraper.py --delay 0.5        # Seconds between requests (default 1.0)
python3 nhscc_scraper.py --csv              # Also export CSV
python3 nhscc_scraper.py --lookup "Jay Gyger"  # Quick person lookup
```

**IMPORTANT**: If you need to re-scrape events that are already in the DB
(e.g. bad data was stored), you must `DELETE FROM results WHERE source_url = ?`
first. The `already_scraped()` check will skip them otherwise.

---

## Running the Export (`export_json.py`)

```bash
python3 export_json.py   # writes docs/data.json
```

No arguments. Reads `nhscc_results.db` from the same directory.

---

## Scraper Architecture (`nhscc_scraper.py`)

### Data model — `DriverResult` dataclass (~line 37)

One row per driver per event:
`event_date`, `event_year`, `car_class`, `car_number`, `name`, `car`,
`best_time`, `pax_index`, `pax_time`, `source_url`, `scrape_method`

### Event registry (~lines 55–330)

Hard-coded list of `(year, event_id, url)` tuples covering all known events.
Adding a new season requires manually appending entries.

### Parser selection (`is_js_rendered()`)

- Returns `True` if HTML contains `"Loading data"`, `"Loading... please wait"`, or `"hostType()"` → use Playwright.
- Returns `False` → use `parse_static_html()` (then fallback to `parse_finish_time_page()` if that yields nothing).

### Parser: `parse_static_html()`

Handles all pre-JS-era static pages. **Four historical formats exist:**

| Era | Format | Key signals |
|-----|---------|-------------|
| Some 2002–2003 | Fixed-width `<pre>` block | `<pre>` tag present → delegates to `parse_pre_format()` |
| 2003–2004 | HTML table, headers: Class / Car# / Name / Car / … / Best / Place / PAX | Has "Name" or "Driver" and "Class" in header |
| 2005–2006 | HTML table, headers: Class / CarID / Name / Car / Run1…P4 / **Best** / PAX Index / PAX Time / Place | 16-column SpeedCode export format |
| 2007–2008 | Similar table, fewer run columns | Same col_map approach |

The parser uses a flexible **header-based column mapping** (`col_map` dict built by `_find_col()`). This correctly maps "Best" → `best_time`, "PAX Time" → `pax_time`, "PAX Index" → `pax_index` regardless of how many run-time columns precede them.

**Known past issue (resolved)**: The original scraper stored PAX Index values (0.777–0.908) in `best_time` for 2005–2006 events. Those rows were deleted from the DB and re-scraped in May 2026 with the corrected parser. If you ever see `best_time < 5` for pre-2007 events, that event needs to be re-scraped.

### Parser: `parse_pre_format()`

Fixed-width text parser for the `<pre>` format. Accepts both `Driver` and `Name` as the driver column header (different events use different labels). Extracts column positions from character offsets in the header line.

### Parser: `parse_finish_time_page()` + `scrape_with_playwright()`

Used for modern Finish-Time JS pages (2008–present mostly). Playwright renders the page, waits for "Loading data" to disappear, then `parse_finish_time_page()` parses the DOM table. Handles class-separator rows (single-cell rows like `"SS  [Street]"`) and derives class from CarID when not set explicitly.

### Other behaviors

- `safe_float()` treats `999` / `999.999` (NHSCC's DNF marker) as `None`.
- `source_url` is the deduplication key.
- The scraper prints `✓` / `⚠` / `✗` per event.

---

## Export Architecture (`export_json.py`)

### Name normalization

**`normalize_name(name)`** — lowercases, strips whitespace, removes `(Non Points)` / `NP` suffixes.

**`strip_annotation(name)`** — same removals but preserves original case (used for display names).

**`canonical_name(variants)`** — picks the longest title-cased variant from a list; falls back to longest overall. Used to auto-select the best display name from DB variants.

### Alias / merge system

**`ALIASES` dict** — maps a normalized name variant → the normalized canonical group key. All variants sharing the same canonical key are merged into one driver record. Current entries:

```python
ALIASES = {
    # Schneider variants
    "sexy dave schneider":          "david schneider",
    'dave "gomez" schneider':       "david schneider",
    "dave schneider":               "david schneider",
    "david scheider":               "david schneider",   # typo
    # Calvin
    "calvin c-money owens":         "calvin owens",
    # Chris Yoder (Jim Stout is an alias — same person)
    "chris 2022 gs ps champ yoder": "chris yoder",
    "jim stout":                    "chris yoder",
    # Bill Staley Jr variants
    "bill staley jr.":              "bill staley jr",
    "bill staley, jr.":             "bill staley jr",
    "bill jr. staley":              "bill staley jr",
    "bill jr staley":               "bill staley jr",
    # Bill Staley Sr variants
    "bill staley sr.":              "bill staley sr",
    "bill staley, sr.":             "bill staley sr",
    "bill sr. staley":              "bill staley sr",
}
```

**`DISPLAY_OVERRIDES` dict** — forces a specific display name for a canonical group key (bypasses `canonical_name()` auto-selection):

```python
DISPLAY_OVERRIDES = {
    "david schneider": "David Schneider",
    "calvin owens":    "Calvin Owens",
    "chris yoder":     "Chris Yoder",
    "bill staley jr":  "Bill Staley Jr",
    "bill staley sr":  "Bill Staley Sr",
}
```

**"Bill Staley"** (no Jr/Sr suffix, 20 events) is kept as a separate driver — it's ambiguous which Staley those entries belong to.

### FTD (Fastest Time of Day) computation

The export computes per-event FTD winners:
- Filters `best_time BETWEEN 20 AND 200` (excludes DNFs, PAX indexes, and bad data)
- Takes the single lowest `best_time` per `source_url` (alphabetical tiebreak on name)
- Sorts chronologically and accumulates per-driver: **win count**, **win rate** (wins ÷ events attended), **all FTD cars** (list of `{car, n}` sorted by wins), and **longest consecutive win streak**
- Course designs change every event; **raw times are NOT comparable across events** — only win counts/streaks are meaningful

### Output: `docs/data.json`

```json
{
  "generated": "2026-05-15",
  "stats":   { "drivers": 3121, "events": 213, "first_year": 2000, "last_year": 2026 },
  "years":   [ { "event_year": 2026, "events": 4, "entries": 307 }, … ],
  "drivers": [ {
    "name": "Jay Gyger",
    "variants": ["other known names"],
    "count": 206,
    "last_seen": "2026-05-03",
    "last_cls": "SS",
    "last_car": "2020 Chevrolet Corvette",
    "history": [ { "date": "…", "cls": "…", "num": "…", "car": "…", "best": 28.5, "pax": 23.1 }, … ]
  }, … ],
  "ftd": {
    "leaders": [ {
      "name": "Jeremy Deitzel",
      "wins": 19,
      "events": 38,
      "win_rate": 50.0,
      "cars": [ { "car": "Mitsubishi EVO", "n": 15 }, … ],
      "streak": 10
    }, … ],
    "events": [ { "date": "…", "year": 2026, "driver": "…", "cls": "…", "car": "…", "time": 28.451 }, … ]
  }
}
```

---

## Dashboard (`docs/index.html`)

Single-file HTML/CSS/JS app. No build step. Loads `data.json` via `fetch()`.

### Tabs

| Tab | Panel ID | Content |
|-----|----------|---------|
| 🔍 Search | `panel-search` | Name search + top-10 Most Events leaderboard + Events by Year grid |
| ★ Interesting Facts | `panel-facts` | 12 curated `.fact-card` items in a responsive grid |
| 🏁 FTD | `panel-ftd` | FTD leaderboard table + full event-by-event FTD history |

### Key JS functions

- `renderLeaderboard(drivers)` — top-10 Most Events
- `renderYears(years)` — year grid with bar charts
- `renderFTD(ftd)` → `renderFTDLeaderboard(leaders)` + `renderFTDHistory(events)`
- `renderResults(drivers)` / `driverCard(d, expanded)` — search results
- `escHtml(s)` — XSS-safe HTML escaping

### CSS design tokens (`:root`)

`--bg`, `--surface`, `--surface2`, `--border`, `--accent` (red), `--accent2` (orange), `--text`, `--muted`, `--green`, `--yellow`

### Responsive behavior

- `@media (max-width: 480px)`: hides subtitle, badge layout wraps to full width
- `@media (max-width: 600px)`: facts grid goes 1-column; FTD table hides Car and Streak columns (`.ftd-sm-hide`)

---

## Known Data Notes

- **2005-09-11 event**: URL `HTML_Export1_RF/HTML_Export1.htm` returns 404. No data for this event.
- **2005–2006 class column**: The "Class" column (col 0) in SpeedCode exports shows a PAX class grouping code (e.g. "AP"), which may differ from the competition class encoded in the CarID (e.g. "SM2" from "92SM2"). The scraper uses col 0 as `car_class` for these years.
- **No test suite, linter config, or build step.**
- Use `python3`, not `python` (the latter is not available on this machine).
