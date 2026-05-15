#!/usr/bin/env python3
"""Export nhscc_results.db to docs/data.json for GitHub Pages hosting."""

import json
import os
import re
import sqlite3
from datetime import date

DB_PATH = os.path.join(os.path.dirname(__file__), "nhscc_results.db")
OUT_PATH = os.path.join(os.path.dirname(__file__), "docs", "data.json")


def normalize_name(name: str) -> str:
    n = name.strip().lower()
    n = re.sub(r'\s*\(non[-\s]?poi\w*\)?$', '', n)
    n = re.sub(r'\s+np\s*$', '', n)
    return re.sub(r'\s+', ' ', n).strip()


def canonical_name(names: list) -> str:
    title = [n for n in names if n == n.title()]
    pool = title if title else names
    return max(pool, key=len)


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

        display_name = canonical_name(variants)
        other_variants = [v for v in variants if v != display_name]

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

    conn.close()

    payload = {
        "generated": date.today().isoformat(),
        "stats":     stats,
        "years":     years,
        "drivers":   drivers,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(payload, f, separators=(",", ":"))

    size_kb = os.path.getsize(OUT_PATH) / 1024
    print(f"Exported {len(drivers)} drivers → {OUT_PATH} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
