#!/usr/bin/env python3
"""Export nhscc_results.db to docs/data.json for GitHub Pages hosting."""

import json
import os
import re
import sqlite3
from collections import defaultdict
from datetime import date

DB_PATH = os.path.join(os.path.dirname(__file__), "nhscc_results.db")
OUT_PATH = os.path.join(os.path.dirname(__file__), "docs", "data.json")


def normalize_name(name: str) -> str:
    n = name.strip().lower()
    n = re.sub(r'\s*\(non[-\s]?poi\w*\)?$', '', n)
    n = re.sub(r'\s+np\s*$', '', n)
    return re.sub(r'\s+', ' ', n).strip()


def strip_annotation(name: str) -> str:
    """Remove non-points suffixes from a display name, preserving case."""
    n = re.sub(r'\s*\(non[-\s]?poi\w*\)?$', '', name, flags=re.IGNORECASE)
    n = re.sub(r'\s+np\s*$', '', n, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', n).strip()


def canonical_name(names: list) -> str:
    title = [n for n in names if n == n.title()]
    pool = title if title else names
    return max(pool, key=len)


# ---------------------------------------------------------------------------
# Manual alias overrides
# ---------------------------------------------------------------------------
# Map any normalized name variant → the normalized canonical group key.
# All variants that share the same canonical key are merged into one driver.
ALIASES: dict[str, str] = {
    "sexy dave schneider":          "david schneider",
    'dave "gomez" schneider':       "david schneider",
    "dave schneider":               "david schneider",
    "david scheider":               "david schneider",   # typo
    "calvin c-money owens":         "calvin owens",
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

# Force the display name for a group (keyed by normalized canonical).
# Without an entry here, canonical_name() picks the longest title-cased variant.
DISPLAY_OVERRIDES: dict[str, str] = {
    "david schneider": "David Schneider",
    "calvin owens":    "Calvin Owens",
    "chris yoder":     "Chris Yoder",
    "bill staley jr":  "Bill Staley Jr",
    "bill staley sr":  "Bill Staley Sr",
}


def main():
    if not os.path.exists(DB_PATH):
        print(f"Database not found: {DB_PATH}")
        raise SystemExit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Stats
    s = conn.execute(
        "SELECT COUNT(DISTINCT name) AS drivers, COUNT(DISTINCT source_url) AS events, "
        "MIN(event_year) AS first_year, MAX(event_year) AS last_year FROM results"
    ).fetchone()
    stats = dict(s)

    # Years
    years = [dict(r) for r in conn.execute(
        "SELECT event_year, COUNT(DISTINCT source_url) AS events, COUNT(*) AS entries "
        "FROM results GROUP BY event_year ORDER BY event_year DESC"
    ).fetchall()]

    # All names → group by normalized key
    raw_names = [r[0] for r in conn.execute(
        "SELECT DISTINCT name FROM results ORDER BY name"
    ).fetchall()]

    groups: dict = {}
    for name in raw_names:
        key = normalize_name(name)
        key = ALIASES.get(key, key)   # merge aliased variants into canonical group
        groups.setdefault(key, []).append(name)

    # Build driver records
    drivers = []
    for key, variants in groups.items():
        placeholders = ",".join("?" * len(variants))
        rows = conn.execute(
            f"SELECT event_date, car_class, car_number, car, best_time, pax_time "
            f"FROM results WHERE name IN ({placeholders}) COLLATE NOCASE "
            f"ORDER BY event_date DESC",
            variants,
        ).fetchall()

        appearances = []
        for r in rows:
            appearances.append({
                "date": r["event_date"],
                "cls":  r["car_class"],
                "num":  r["car_number"],
                "car":  r["car"] or "",
                "best": round(r["best_time"], 3) if r["best_time"] else None,
                "pax":  round(r["pax_time"],  3) if r["pax_time"]  else None,
            })

        display_name = DISPLAY_OVERRIDES.get(key, strip_annotation(canonical_name(variants)))
        clean_variants = list(dict.fromkeys(strip_annotation(v) for v in variants))
        other_variants = [v for v in clean_variants if v != display_name]

        drivers.append({
            "name":      display_name,
            "variants":  other_variants,
            "count":     len(appearances),
            "last_seen": appearances[0]["date"]  if appearances else None,
            "last_cls":  appearances[0]["cls"]   if appearances else None,
            "last_car":  appearances[0]["car"]   if appearances else None,
            "history":   appearances,
        })

    # Sort by name for consistent output
    drivers.sort(key=lambda d: d["name"].lower())

    # -----------------------------------------------------------------------
    # FTD (Fastest Time of Day) computation
    # -----------------------------------------------------------------------
    # Build reverse lookup: any raw DB name → canonical display name
    name_to_display: dict[str, str] = {}
    for key, variants in groups.items():
        disp = DISPLAY_OVERRIDES.get(key, strip_annotation(canonical_name(variants)))
        for v in variants:
            name_to_display[v] = disp

    # Get all valid times (filter out DNF 999s, PAX indexes, and garbage data)
    ftd_raw = conn.execute(
        """
        SELECT source_url, event_date, event_year, name, car, car_class, best_time
        FROM results
        WHERE best_time BETWEEN 20 AND 200
        ORDER BY source_url, best_time, name
        """
    ).fetchall()

    # One FTD winner per event (lowest time; alphabetical on ties)
    ftd_by_url: dict = {}
    for row in ftd_raw:
        if row["source_url"] not in ftd_by_url:
            ftd_by_url[row["source_url"]] = row

    # Sort chronologically
    ftd_winners = sorted(ftd_by_url.values(), key=lambda r: r["event_date"])

    # Build event list and accumulate stats in one pass
    ftd_events_list: list = []
    win_counts: dict  = defaultdict(int)
    win_cars: dict    = defaultdict(lambda: defaultdict(int))
    max_streaks: dict = defaultdict(int)
    prev_winner: str | None = None
    cur_streak = 0

    for row in ftd_winners:
        raw_name = row["name"]
        disp = name_to_display.get(raw_name, strip_annotation(raw_name))
        ftd_events_list.append({
            "date":   row["event_date"],
            "year":   row["event_year"],
            "driver": disp,
            "cls":    row["car_class"],
            "car":    row["car"] or "",
            "time":   round(row["best_time"], 3),
        })
        win_counts[disp] += 1
        win_cars[disp][row["car"] or ""] += 1
        if disp == prev_winner:
            cur_streak += 1
        else:
            cur_streak = 1
            prev_winner = disp
        if cur_streak > max_streaks[disp]:
            max_streaks[disp] = cur_streak

    total_events_map = {d["name"]: d["count"] for d in drivers}

    ftd_leaders: list = []
    for name, wins in win_counts.items():
        # All cars used for FTD wins, sorted by win count descending
        cars = sorted(win_cars[name].items(), key=lambda x: -x[1])
        total    = total_events_map.get(name, wins)
        win_rate = round(wins / total * 100, 1)
        ftd_leaders.append({
            "name":     name,
            "wins":     wins,
            "events":   total,
            "win_rate": win_rate,
            "cars":     [{"car": car, "n": n} for car, n in cars],
            "streak":   max_streaks[name],
        })
    ftd_leaders.sort(key=lambda l: (-l["wins"], l["name"].lower()))

    ftd = {
        "leaders": ftd_leaders,
        "events":  list(reversed(ftd_events_list)),  # newest first for display
    }

    conn.close()

    payload = {
        "generated": date.today().isoformat(),
        "stats":     stats,
        "years":     years,
        "drivers":   drivers,
        "ftd":       ftd,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(payload, f, separators=(",", ":"))

    size_kb = os.path.getsize(OUT_PATH) / 1024
    print(f"Exported {len(drivers)} drivers → {OUT_PATH} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
