#!/usr/bin/env python3
"""NHSCC People Dashboard — searchable web interface for the results database."""

import http.server
import json
import os
import re
import sqlite3
import urllib.parse
import webbrowser
from threading import Timer

DB_PATH = os.path.join(os.path.dirname(__file__), "nhscc_results.db")
PORT = 8787

# ---------------------------------------------------------------------------
# Database queries
# ---------------------------------------------------------------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def db_stats():
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(DISTINCT name) AS drivers, COUNT(DISTINCT source_url) AS events, "
        "MIN(event_year) AS first_year, MAX(event_year) AS last_year FROM results"
    ).fetchone()
    conn.close()
    return dict(row)

def normalize_name(name: str) -> str:
    """Fold name variants into a canonical key for grouping."""
    n = name.strip().lower()
    # Strip non-points suffixes: " NP", " (non-points)", " (non-poin...", etc.
    n = re.sub(r'\s*\(non[-\s]?poi\w*\)?$', '', n)
    n = re.sub(r'\s+np\s*$', '', n)
    # Collapse internal whitespace
    return re.sub(r'\s+', ' ', n).strip()

def canonical_name(names: list[str]) -> str:
    """Pick the best display name from a group of variants."""
    # Prefer title-case names, then the longest one
    title = [n for n in names if n == n.title()]
    pool = title if title else names
    return max(pool, key=len)

def search_drivers(q: str):
    if not q or len(q) < 2:
        return []
    conn = get_conn()
    pattern = f"%{q}%"
    raw_names = [r[0] for r in conn.execute(
        "SELECT DISTINCT name FROM results WHERE name LIKE ? COLLATE NOCASE ORDER BY name LIMIT 60",
        (pattern,)
    ).fetchall()]

    # Group name variants by their normalized key
    groups: dict[str, list[str]] = {}
    for name in raw_names:
        key = normalize_name(name)
        groups.setdefault(key, []).append(name)

    results = []
    for key, variants in groups.items():
        placeholders = ",".join("?" * len(variants))
        rows = conn.execute(
            f"SELECT event_date, event_year, car_class, car_number, car, best_time, pax_time "
            f"FROM results WHERE name IN ({placeholders}) COLLATE NOCASE ORDER BY event_date DESC",
            variants,
        ).fetchall()
        appearances = [dict(r) for r in rows]
        results.append({
            "name": canonical_name(variants),
            "variants": variants if len(variants) > 1 else [],
            "count": len(appearances),
            "last_seen": appearances[0]["event_date"] if appearances else None,
            "last_class": appearances[0]["car_class"] if appearances else None,
            "last_car": appearances[0]["car"] if appearances else None,
            "appearances": appearances,
        })

    conn.close()
    results.sort(key=lambda r: r["last_seen"] or "", reverse=True)
    return results

def year_breakdown():
    conn = get_conn()
    rows = conn.execute(
        "SELECT event_year, COUNT(DISTINCT source_url) AS events, COUNT(*) AS entries "
        "FROM results GROUP BY event_year ORDER BY event_year DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NHSCC People</title>
<style>
  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #22263a;
    --border: #2e334d;
    --accent: #e84d3d;
    --accent2: #ff7c50;
    --text: #e8eaf0;
    --muted: #7a80a0;
    --green: #3ecf8e;
    --yellow: #f5a623;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; min-height: 100vh; }

  /* Header */
  header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 18px 32px; display: flex; align-items: center; gap: 16px; }
  header .logo { font-size: 22px; font-weight: 800; color: var(--accent); letter-spacing: -0.5px; }
  header .subtitle { color: var(--muted); font-size: 13px; }
  header .stats-row { margin-left: auto; display: flex; gap: 24px; }
  header .stat { text-align: right; }
  header .stat .val { font-size: 20px; font-weight: 700; color: var(--text); }
  header .stat .lbl { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }

  /* Main layout */
  main { max-width: 1100px; margin: 0 auto; padding: 32px 24px; }

  /* Search */
  .search-wrap { position: relative; margin-bottom: 28px; }
  .search-wrap input {
    width: 100%; padding: 16px 20px 16px 52px; font-size: 18px;
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    color: var(--text); outline: none; transition: border-color 0.15s;
  }
  .search-wrap input:focus { border-color: var(--accent); }
  .search-wrap input::placeholder { color: var(--muted); }
  .search-icon { position: absolute; left: 18px; top: 50%; transform: translateY(-50%); color: var(--muted); font-size: 20px; pointer-events: none; }
  .search-hint { margin-top: 8px; font-size: 13px; color: var(--muted); padding-left: 4px; }

  /* Result cards */
  .results { display: flex; flex-direction: column; gap: 16px; }

  .driver-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
  .driver-card.expanded .card-header { border-bottom: 1px solid var(--border); }
  .card-header { padding: 18px 22px; display: flex; align-items: center; gap: 16px; cursor: pointer; transition: background 0.1s; }
  .card-header:hover { background: var(--surface2); }
  .driver-name { font-size: 18px; font-weight: 700; flex: 1; }
  .badge { display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }
  .badge-class { background: rgba(232,77,61,0.15); color: var(--accent2); }
  .badge-count { background: rgba(62,207,142,0.12); color: var(--green); }
  .last-seen { font-size: 13px; color: var(--muted); text-align: right; min-width: 160px; }
  .last-seen .date { font-size: 15px; font-weight: 600; color: var(--text); }
  .chevron { color: var(--muted); font-size: 14px; transition: transform 0.2s; margin-left: 8px; }
  .expanded .chevron { transform: rotate(180deg); }

  /* History table */
  .card-body { display: none; padding: 0; }
  .expanded .card-body { display: block; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  thead th { background: var(--surface2); padding: 10px 16px; text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.6px; color: var(--muted); font-weight: 600; }
  tbody tr { border-top: 1px solid var(--border); transition: background 0.1s; }
  tbody tr:hover { background: var(--surface2); }
  tbody td { padding: 10px 16px; }
  .td-date { font-weight: 600; white-space: nowrap; }
  .td-class { }
  .td-car { color: var(--muted); font-size: 13px; }
  .td-time { font-variant-numeric: tabular-nums; }
  .td-pax { font-variant-numeric: tabular-nums; color: var(--muted); }
  .row-latest td { color: var(--yellow); }
  .row-latest .td-car { color: var(--yellow); opacity: 0.7; }

  /* Year breakdown */
  .section-title { font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px; color: var(--muted); margin-bottom: 14px; }
  .year-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 8px; }
  .year-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }
  .year-card .yr { font-size: 18px; font-weight: 700; }
  .year-card .meta { font-size: 12px; color: var(--muted); margin-top: 2px; }
  .year-card .bar { height: 3px; background: var(--border); border-radius: 2px; margin-top: 8px; overflow: hidden; }
  .year-card .bar-fill { height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent2)); border-radius: 2px; transition: width 0.4s; }

  /* Empty / loading states */
  .empty { text-align: center; padding: 48px 24px; color: var(--muted); }
  .empty .icon { font-size: 40px; margin-bottom: 12px; }
  .empty p { font-size: 15px; }
  .spinner { display: inline-block; width: 18px; height: 18px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.6s linear infinite; vertical-align: middle; margin-right: 8px; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>

<header>
  <div>
    <div class="logo">⚑ NHSCC People</div>
    <div class="subtitle">North Hills Sports Car Club &mdash; Results Database</div>
  </div>
  <div class="stats-row" id="stats-row">
    <div class="stat"><div class="val" id="s-drivers">—</div><div class="lbl">Drivers</div></div>
    <div class="stat"><div class="val" id="s-events">—</div><div class="lbl">Events</div></div>
    <div class="stat"><div class="val" id="s-years">—</div><div class="lbl">Years</div></div>
  </div>
</header>

<main>
  <div class="search-wrap">
    <span class="search-icon">🔍</span>
    <input type="text" id="search" placeholder="Search by name…" autocomplete="off" autocorrect="off" spellcheck="false">
    <div class="search-hint" id="search-hint">Type at least 2 characters to search</div>
  </div>

  <div id="results"></div>
  <div id="yearview"></div>
</main>

<script>
let debounceTimer = null;
let expandedCards = new Set();

// Load stats
fetch('/api/stats').then(r => r.json()).then(d => {
  document.getElementById('s-drivers').textContent = d.drivers.toLocaleString();
  document.getElementById('s-events').textContent = d.events.toLocaleString();
  document.getElementById('s-years').textContent = `${d.first_year}–${d.last_year}`;
});

// Load year breakdown for homepage
fetch('/api/years').then(r => r.json()).then(renderYears);

function renderYears(years) {
  const maxEntries = Math.max(...years.map(y => y.entries));
  const html = `
    <p class="section-title">Events by Year</p>
    <div class="year-grid">
      ${years.map(y => `
        <div class="year-card">
          <div class="yr">${y.event_year}</div>
          <div class="meta">${y.events} event${y.events !== 1 ? 's' : ''} &middot; ${y.entries} drivers</div>
          <div class="bar"><div class="bar-fill" style="width:${Math.round(y.entries/maxEntries*100)}%"></div></div>
        </div>
      `).join('')}
    </div>`;
  document.getElementById('yearview').innerHTML = html;
}

// Search
document.getElementById('search').addEventListener('input', e => {
  const q = e.target.value.trim();
  clearTimeout(debounceTimer);
  if (q.length < 2) {
    document.getElementById('results').innerHTML = '';
    document.getElementById('search-hint').textContent = 'Type at least 2 characters to search';
    document.getElementById('yearview').style.display = '';
    return;
  }
  document.getElementById('yearview').style.display = 'none';
  document.getElementById('search-hint').innerHTML = '<span class="spinner"></span>Searching…';
  debounceTimer = setTimeout(() => doSearch(q), 200);
});

function doSearch(q) {
  fetch(`/api/search?q=${encodeURIComponent(q)}`).then(r => r.json()).then(data => {
    const hint = document.getElementById('search-hint');
    if (data.length === 0) {
      hint.textContent = 'No results found';
      document.getElementById('results').innerHTML = `<div class="empty"><div class="icon">🏁</div><p>No drivers found matching "${q}"</p></div>`;
    } else {
      hint.textContent = `${data.length} driver${data.length !== 1 ? 's' : ''} found`;
      renderResults(data);
    }
  });
}

function renderResults(drivers) {
  const html = drivers.map(d => {
    const isExpanded = expandedCards.has(d.name) || drivers.length === 1;
    if (drivers.length === 1) expandedCards.add(d.name);
    return driverCard(d, isExpanded);
  }).join('');
  document.getElementById('results').innerHTML = `<div class="results">${html}</div>`;

  // Attach toggle listeners
  document.querySelectorAll('.card-header').forEach(h => {
    h.addEventListener('click', () => {
      const card = h.closest('.driver-card');
      const name = card.dataset.name;
      if (card.classList.contains('expanded')) {
        card.classList.remove('expanded');
        expandedCards.delete(name);
      } else {
        card.classList.add('expanded');
        expandedCards.add(name);
      }
    });
  });
}

function driverCard(d, expanded) {
  const variantNote = d.variants && d.variants.length > 1
    ? `<div style="font-size:11px;color:var(--muted);margin-top:3px">also: ${d.variants.filter(v=>v!==d.name).map(escHtml).join(', ')}</div>`
    : '';
  const rows = d.appearances.map((a, i) => {
    const isLatest = i === 0;
    const best = a.best_time != null ? a.best_time.toFixed(3) : '—';
    const pax  = a.pax_time  != null ? a.pax_time.toFixed(3)  : '—';
    return `<tr class="${isLatest ? 'row-latest' : ''}">
      <td class="td-date">${a.event_date}</td>
      <td class="td-class"><span class="badge badge-class">${a.car_class}</span></td>
      <td class="td-class">#${a.car_number}</td>
      <td class="td-car">${a.car || '—'}</td>
      <td class="td-time">${best}</td>
      <td class="td-pax">${pax}</td>
    </tr>`;
  }).join('');

  return `
  <div class="driver-card ${expanded ? 'expanded' : ''}" data-name="${escHtml(d.name)}">
    <div class="card-header">
      <div class="driver-name">${escHtml(d.name)}${variantNote}</div>
      <span class="badge badge-class">${d.last_class || '—'}</span>
      <span class="badge badge-count">${d.count} event${d.count !== 1 ? 's' : ''}</span>
      <div class="last-seen">
        <div class="lbl" style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px">Last seen</div>
        <div class="date">${d.last_seen || '—'}</div>
        <div style="font-size:12px;color:var(--muted)">${d.last_car || ''}</div>
      </div>
      <span class="chevron">▼</span>
    </div>
    <div class="card-body">
      <table>
        <thead><tr>
          <th>Date</th><th>Class</th><th>Car #</th><th>Car</th><th>Best</th><th>PAX</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  </div>`;
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
</script>
</body>
</html>"""

# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress request logs

    def send_json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        path = parsed.path

        if path == "/":
            self.send_html(HTML)
        elif path == "/api/stats":
            self.send_json(db_stats())
        elif path == "/api/years":
            self.send_json(year_breakdown())
        elif path == "/api/search":
            q = params.get("q", [""])[0]
            self.send_json(search_drivers(q))
        else:
            self.send_error(404)


if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        print(f"Database not found: {DB_PATH}")
        print("Run the scraper first: python3 nhscc_scraper.py")
        raise SystemExit(1)

    server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"NHSCC Dashboard → {url}")
    Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
