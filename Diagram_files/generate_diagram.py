#!/usr/bin/env python3
"""
generate_diagram.py
-------------------
Reads diagram.yaml and produces a self-contained diagram.html file.

Usage:
    pip install pyyaml          # (ruamel also works; only safe_load is used here)
    python generate_diagram.py
    python generate_diagram.py --input diagram.yaml --output diagram.html

This module is also imported by clickhouse_diagram.py, which calls
generate_html(data) directly so there is a single source of HTML truth.

LAYERS (column lanes):
    bronze | silver | gold | review

YAML icon values (mutually exclusive, one per table):
    none     = no icon (default)
    clock    = scheduled ETL          (grey clock icon)
    flash    = realtime loaded data   (red lightning bolt icon)
    created  = newly discovered table awaiting human triage (green plus)
    dropped  = table dropped in ClickHouse, kept for review  (red trash)

Separate flag (rendered as its own badge, independent of icon):
    is_mview: true|false   = materialized view
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is not installed. Run: pip install pyyaml")
    sys.exit(1)

PLACEHOLDER = "insert_link_here"


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate(data: dict) -> None:
    ids = {t["id"] for t in data.get("tables", [])}
    for edge in data.get("edges", []):
        if edge["from"] not in ids:
            print(f"WARNING: edge 'from' id '{edge['from']}' not found in tables")
        if edge["to"] not in ids:
            print(f"WARNING: edge 'to' id '{edge['to']}' not found in tables")
    for table in data.get("tables", []):
        icon = table.get("icon", "none")
        if icon not in ("none", "clock", "flash", "created", "dropped"):
            print(f"WARNING: table '{table['id']}' has unknown icon '{icon}' "
                  f"— use none|clock|flash|created|dropped")
        layer = table.get("layer", "review")
        if layer not in ("bronze", "silver", "gold", "review"):
            print(f"WARNING: table '{table['id']}' has unknown layer '{layer}' "
                  f"— use bronze|silver|gold|review")


def generate_html(data: dict) -> str:
    tables = data.get("tables", [])
    edges  = data.get("edges", [])

    for t in tables:
        t.setdefault("icon", "none")
        t.setdefault("is_mview", False)
        t["docs_active"] = t.get("docs_url", PLACEHOLDER) != PLACEHOLDER
        t["etl_active"]  = t.get("etl_url",  PLACEHOLDER) != PLACEHOLDER

    tables_json = json.dumps(tables, ensure_ascii=False)
    edges_json  = json.dumps(edges,  ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ClickHouse data lineage</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  :root {{
    --bronze:      #b46414;
    --bronze-bg:   rgba(180,100,20,0.07);
    --bronze-bd:   rgba(180,100,20,0.22);
    --silver:      #5a7a96;
    --silver-bg:   rgba(90,122,150,0.06);
    --silver-bd:   rgba(90,122,150,0.2);
    --gold:        #9a7d10;
    --gold-bg:     rgba(154,125,16,0.07);
    --gold-bd:     rgba(154,125,16,0.25);
    --review:      #808080;
    --review-bg:   rgba(128,128,128,0.05);
    --review-bd:   rgba(128,128,128,0.18);
    --bg:          #ffffff;
    --bg2:         #f6f6f4;
    --text:        #1a1a18;
    --text2:       #5a5a56;
    --text3:       #9a9a94;
    --border:      rgba(0,0,0,0.10);
    --border2:     rgba(0,0,0,0.18);
    --hl-bg:       rgba(55,138,221,0.07);
    --hl-bd:       #378ADD;
    --hl-src-bg:   rgba(29,158,117,0.07);
    --hl-src-bd:   #1D9E75;
    --hl-dst-bg:   rgba(186,117,23,0.08);
    --hl-dst-bd:   #BA7517;
    --link-color:  #185FA5;
    --link-bd:     rgba(55,138,221,0.35);
    --link-bg-h:   rgba(55,138,221,0.08);
    --dim-color:   #a0a09a;
    --dim-bd:      rgba(0,0,0,0.10);
    --icon-clock:  #8a8a84;
    --icon-flash:  #c0392b;
    --icon-created:#1D9E75;
    --icon-dropped:#c0392b;
    --mview-color: #6b4ea0;
    --mview-bd:    rgba(107,78,160,0.40);
    --mview-bg:    rgba(107,78,160,0.10);
    --lane-gap:    24px;
  }}

  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg:         #1c1c1a;
      --bg2:        #252523;
      --text:       #e2e0d8;
      --text2:      #a8a89e;
      --text3:      #686860;
      --border:     rgba(255,255,255,0.10);
      --border2:    rgba(255,255,255,0.18);
      --bronze-bg:  rgba(180,100,20,0.12);
      --silver-bg:  rgba(90,122,150,0.10);
      --gold-bg:    rgba(154,125,16,0.12);
      --review-bg:  rgba(128,128,128,0.08);
      --dim-color:  #686860;
      --icon-clock: #a0a09a;
      --icon-flash: #e05a4a;
      --icon-created:#27c08a;
      --icon-dropped:#e05a4a;
      --mview-color:#a98fd6;
      --mview-bd:   rgba(169,143,214,0.45);
      --mview-bg:   rgba(169,143,214,0.14);
    }}
  }}

  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    padding: 20px;
    min-height: 100vh;
  }}

  h1 {{ font-size: 16px; font-weight: 500; margin-bottom: 14px; }}

  .controls {{
    display: flex;
    gap: 6px;
    margin-bottom: 14px;
    flex-wrap: wrap;
    align-items: center;
  }}
  .ctrl-btn {{
    font-size: 11px;
    padding: 4px 12px;
    border: 0.5px solid var(--border2);
    border-radius: 6px;
    background: transparent;
    color: var(--text2);
    cursor: pointer;
    transition: background 0.12s;
  }}
  .ctrl-btn:hover  {{ background: var(--bg2); }}
  .ctrl-btn.active {{ background: var(--bg2); color: var(--text); }}
  .hint {{ margin-left: auto; font-size: 11px; color: var(--text3); }}

  .scroll-wrap {{ overflow-x: auto; position: relative; }}

  .lanes {{
    display: flex;
    gap: var(--lane-gap);
    min-width: 900px;
    position: relative;
  }}

  .lane {{
    flex: 1;
    padding: 10px 8px 18px;
    border-radius: 10px;
  }}
  .lane-bronze {{ background: var(--bronze-bg); border: 0.5px solid var(--bronze-bd); }}
  .lane-silver {{ background: var(--silver-bg); border: 0.5px solid var(--silver-bd); }}
  .lane-gold   {{ background: var(--gold-bg);   border: 0.5px solid var(--gold-bd);   }}
  .lane-review {{ background: var(--review-bg); border: 0.5px solid var(--review-bd); }}

  .lane-hdr {{
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 10px;
    padding-bottom: 8px;
    border-bottom: 0.5px solid var(--border);
  }}
  .hdot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
  .hd-bronze {{ background: var(--bronze); }}
  .hd-silver {{ background: var(--silver); }}
  .hd-gold   {{ background: var(--gold);   }}
  .hd-review {{ background: var(--review); }}
  .htitle {{ font-size: 12px; font-weight: 500; }}
  .hsub   {{ font-size: 10px; color: var(--text3); margin-left: auto; }}
  .hcount {{ font-size: 10px; color: var(--text3); text-align: center; margin-top: 4px; }}

  .tcard {{
    background: var(--bg);
    border: 0.5px solid var(--border);
    border-radius: 6px;
    padding: 5px 8px;
    margin-bottom: 6px;
    transition: border-color 0.12s;
    cursor: pointer;
  }}
  .tcard:hover  {{ border-color: var(--border2); }}
  .tcard.hl     {{ border-color: var(--hl-bd)     !important; background: var(--hl-bg); }}
  .tcard.hl-src {{ border-color: var(--hl-src-bd) !important; background: var(--hl-src-bg); }}
  .tcard.hl-dst {{ border-color: var(--hl-dst-bd) !important; background: var(--hl-dst-bg); }}

  .card-top  {{ display: flex; align-items: flex-start; gap: 4px; }}
  .card-meta {{ flex: 1; min-width: 0; }}
  .schema-lbl {{ font-size: 9px; color: var(--text3); margin-bottom: 1px; }}
  .tname      {{ font-size: 11px; font-weight: 500; word-break: break-all; }}

  .card-badges {{ display: flex; flex-direction: column; align-items: flex-end; gap: 2px; flex-shrink: 0; }}
  .card-icon {{ width: 14px; height: 14px; margin-top: 2px; }}
  .icon-clock   {{ color: var(--icon-clock); }}
  .icon-flash   {{ color: var(--icon-flash); }}
  .icon-created {{ color: var(--icon-created); }}
  .icon-dropped {{ color: var(--icon-dropped); }}

  .mview-badge {{
    font-size: 8px;
    font-weight: 600;
    letter-spacing: 0.3px;
    color: var(--mview-color);
    border: 0.5px solid var(--mview-bd);
    background: var(--mview-bg);
    border-radius: 3px;
    padding: 0 3px;
    line-height: 12px;
  }}

  .card-links {{ display: flex; gap: 5px; margin-top: 5px; }}
  .clink {{
    font-size: 9px;
    text-decoration: none;
    padding: 1px 6px;
    border-radius: 3px;
    transition: background 0.1s;
    white-space: nowrap;
  }}
  .clink-active {{
    color: var(--link-color);
    border: 0.5px solid var(--link-bd);
  }}
  .clink-active:hover {{ background: var(--link-bg-h); }}
  .clink-disabled {{
    color: var(--dim-color);
    border: 0.5px solid var(--dim-bd);
    cursor: default;
    pointer-events: none;
    opacity: 0.5;
  }}

  svg.edges {{
    position: absolute;
    top: 0; left: 0;
    width: 100%; height: 100%;
    pointer-events: none;
    overflow: visible;
  }}

  .legend {{ display: flex; gap: 16px; margin-top: 4px; margin-bottom: 14px; flex-wrap: wrap; align-items: center; }}
  .legend-item {{ display: flex; align-items: center; gap: 5px; font-size: 10px; color: var(--text2); }}
  .li-box {{ width: 10px; height: 10px; border-radius: 2px; }}
  .li-src {{ background: var(--hl-src-bg); border: 0.5px solid var(--hl-src-bd); }}
  .li-dst {{ background: var(--hl-dst-bg); border: 0.5px solid var(--hl-dst-bd); }}

  /* ===== Focus-mode overlay ===== */
  .focus-backdrop {{
    position: fixed; inset: 0;
    background: rgba(0,0,0,0.45);
    backdrop-filter: blur(2px);
    display: none;
    z-index: 1000;
    opacity: 0;
    transition: opacity 0.18s ease;
  }}
  .focus-backdrop.show {{ display: block; opacity: 1; }}
  @media (prefers-color-scheme: dark) {{
    .focus-backdrop {{ background: rgba(0,0,0,0.6); }}
  }}
  .focus-panel {{
    position: absolute;
    top: 50%; left: 50%;
    transform: translate(-50%, -50%) scale(0.96);
    transition: transform 0.18s ease;
    background: var(--bg);
    border: 0.5px solid var(--border2);
    border-radius: 14px;
    box-shadow: 0 12px 48px rgba(0,0,0,0.28);
    padding: 22px 24px 20px;
    max-width: min(94vw, 1100px);
    max-height: 90vh;
    overflow: auto;
  }}
  .focus-backdrop.show .focus-panel {{ transform: translate(-50%, -50%) scale(1); }}
  .focus-title {{
    font-size: 12px; color: var(--text2); margin-bottom: 14px;
    display: flex; align-items: center; gap: 8px;
  }}
  .focus-title b {{ color: var(--text); font-weight: 600; }}
  .focus-hint {{ margin-left: auto; font-size: 10px; color: var(--text3); }}
  .focus-stage {{ position: relative; }}
  .focus-cols {{ display: flex; gap: 60px; align-items: flex-start; }}
  .focus-col {{ display: flex; flex-direction: column; gap: 18px; min-width: 180px; }}
  .focus-col-lbl {{
    font-size: 9px; text-transform: uppercase; letter-spacing: 0.6px;
    color: var(--text3); margin-bottom: 2px; text-align: center;
  }}
  .fcard {{
    background: var(--bg);
    border: 1px solid var(--border2);
    border-radius: 9px;
    padding: 10px 12px;
    width: 200px;
    cursor: pointer;
    transition: border-color 0.12s, box-shadow 0.12s, transform 0.12s;
  }}
  .fcard:hover {{ box-shadow: 0 4px 16px rgba(0,0,0,0.12); transform: translateY(-1px); }}
  .fcard.is-center {{ border-color: var(--hl-bd); box-shadow: 0 0 0 2px var(--hl-bg); cursor: default; }}
  .fcard .schema-lbl {{ font-size: 10px; }}
  .fcard .tname {{ font-size: 13px; }}
  .fcard .card-links {{ margin-top: 8px; }}
  .fcard .clink {{ font-size: 10px; padding: 2px 8px; }}
  .focus-svg {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; overflow: visible; z-index: 1; }}
</style>
</head>
<body>

<h1>ClickHouse data lineage</h1>

<div class="controls">
  <button class="ctrl-btn active" onclick="setSchema('all', this)">All schemas</button>
  <button class="ctrl-btn" onclick="setSchema('analytics', this)">analytics</button>
  <button class="ctrl-btn" onclick="setSchema('analytics_aggregated', this)">analytics_aggregated</button>
  <button class="ctrl-btn" onclick="setSchema('mysql_replica', this)">mysql_replica</button>
  <span class="hint">Hover to preview lineage · Click to lock · Click elsewhere to clear</span>
</div>

<div class="legend">
  <div class="legend-item">
    <svg width="26" height="10">
      <defs><marker id="la" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
        <path d="M2 1L8 5L2 9" fill="none" stroke="#8aa0b8" stroke-width="1.5"/></marker></defs>
      <line x1="0" y1="5" x2="24" y2="5" stroke="#8aa0b8" stroke-width="1.5" marker-end="url(#la)"/>
    </svg>
    Single-source ETL
  </div>
  <div class="legend-item">
    <svg width="26" height="10">
      <line x1="0" y1="5" x2="26" y2="5" stroke="#378ADD" stroke-width="1.5" stroke-dasharray="4 2"/>
    </svg>
    Multi-source join
  </div>
  <div class="legend-item"><div class="li-box li-src"></div> Source table</div>
  <div class="legend-item"><div class="li-box li-dst"></div> Output table</div>
  <div class="legend-item">
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="#8a8a84" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="8" cy="8" r="6"/><polyline points="8,4 8,8 11,10"/>
    </svg>
    Scheduled ETL
  </div>
  <div class="legend-item">
    <svg width="10" height="14" viewBox="0 0 10 16" fill="#c0392b" stroke="none">
      <polygon points="6,0 0,9 4,9 4,16 10,7 6,7"/>
    </svg>
    Realtime data
  </div>
  <div class="legend-item">
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="#1D9E75" stroke-width="1.6" stroke-linecap="round">
      <circle cx="8" cy="8" r="6.5"/><line x1="8" y1="5" x2="8" y2="11"/><line x1="5" y1="8" x2="11" y2="8"/>
    </svg>
    New table (triage)
  </div>
  <div class="legend-item">
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="#c0392b" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
      <polyline points="3,4 13,4"/><path d="M5 4 L5.7 13 H10.3 L11 4"/><line x1="6.6" y1="6" x2="6.8" y2="11"/><line x1="9.4" y1="6" x2="9.2" y2="11"/>
    </svg>
    Dropped (verify &amp; remove)
  </div>
  <div class="legend-item">
    <span class="mview-badge">MV</span> Materialized view
  </div>
  <div class="legend-item">
    <span style="font-size:10px;color:var(--dim-color);border:0.5px solid var(--dim-bd);padding:1px 5px;border-radius:3px;opacity:0.6;">Docs</span>
    Link not yet added
  </div>
</div>


<div class="scroll-wrap" id="scroll-wrap">
  <div class="lanes" id="lanes">
    <div class="lane lane-bronze">
      <div class="lane-hdr"><div class="hdot hd-bronze"></div><span class="htitle">Bronze</span><span class="hsub">raw ingestion</span></div>
      <div id="col-bronze"></div>
    </div>
    <div class="lane lane-silver">
      <div class="lane-hdr"><div class="hdot hd-silver"></div><span class="htitle">Silver</span><span class="hsub">cleaned</span></div>
      <div id="col-silver"></div>
    </div>
    <div class="lane lane-gold">
      <div class="lane-hdr"><div class="hdot hd-gold"></div><span class="htitle">Gold</span><span class="hsub">analytics-ready</span></div>
      <div id="col-gold"></div>
    </div>
    <div class="lane lane-review">
      <div class="lane-hdr"><div class="hdot hd-review"></div><span class="htitle">Review</span><span class="hsub">new / dropped — needs triage</span></div>
      <div id="col-review"></div>
    </div>
  </div>
  <svg class="edges" id="edge-svg"></svg>
</div>

<div class="focus-backdrop" id="focus-backdrop">
  <div class="focus-panel" id="focus-panel" onclick="event.stopPropagation()">
    <div class="focus-title">
      <span>Lineage focus — <b id="focus-name"></b></span>
      <span class="focus-hint">Click a related table to re-focus · click outside to exit</span>
    </div>
    <div class="focus-stage">
      <div class="focus-cols" id="focus-cols"></div>
      <svg class="focus-svg" id="focus-svg"></svg>
    </div>
  </div>
</div>

<script>
const TABLES = {tables_json};
const EDGES  = {edges_json};

let activeSchema = 'all';
let pinnedId = null;

function iconSVG(icon) {{
  if (icon === 'clock') return `
    <svg class="card-icon icon-clock" viewBox="0 0 16 16" fill="none"
        stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <title>Scheduled ETL</title>
      <circle cx="8" cy="8" r="6"/><polyline points="8,4 8,8 11,10"/>
    </svg>`;
  if (icon === 'flash') return `
    <svg class="card-icon icon-flash" viewBox="0 0 10 16" fill="currentColor" stroke="none">
      <title>Realtime data</title>
      <polygon points="6,0 0,9 4,9 4,16 10,7 6,7"/>
    </svg>`;
  if (icon === 'created') return `
    <svg class="card-icon icon-created" viewBox="0 0 16 16" fill="none"
        stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
      <title>New table — set layer and links</title>
      <circle cx="8" cy="8" r="6.5"/><line x1="8" y1="5" x2="8" y2="11"/><line x1="5" y1="8" x2="11" y2="8"/>
    </svg>`;
  if (icon === 'dropped') return `
    <svg class="card-icon icon-dropped" viewBox="0 0 16 16" fill="none"
        stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
      <title>Dropped in ClickHouse — verify, then remove from YAML</title>
      <polyline points="3,4 13,4"/><path d="M5 4 L5.7 13 H10.3 L11 4"/>
      <line x1="6.6" y1="6" x2="6.8" y2="11"/><line x1="9.4" y1="6" x2="9.2" y2="11"/>
    </svg>`;
  return '';
}}

function badgesHTML(t) {{
  let html = '<div class="card-badges">';
  html += iconSVG(t.icon || 'none');
  if (t.is_mview) html += '<span class="mview-badge" title="Materialized view">MV</span>';
  html += '</div>';
  return html;
}}

function linkHTML(label, url, active) {{
  if (active) return `<a class="clink clink-active" href="${{url}}" target="_blank" rel="noopener">${{label}}</a>`;
  return `<span class="clink clink-disabled" title="Link not yet added">${{label}}</span>`;
}}

function render() {{
  ['bronze','silver','gold','review'].forEach(layer => {{
    const col = document.getElementById('col-' + layer);
    col.innerHTML = '';
    const rows = TABLES.filter(t =>
      t.layer === layer &&
      (activeSchema === 'all' || t.schema === activeSchema)
    );
    rows.forEach(t => {{
      const d = document.createElement('div');
      d.className = 'tcard';
      d.id = 'card-' + t.id;
      d.dataset.id = t.id;
      d.innerHTML = `
        <div class="card-top">
          <div class="card-meta">
            <div class="schema-lbl">${{t.schema}}</div>
            <div class="tname">${{t.name}}</div>
          </div>
          ${{badgesHTML(t)}}
        </div>
        <div class="card-links">
          ${{linkHTML('Docs', t.docs_url, t.docs_active)}}
          ${{linkHTML('ETL',  t.etl_url,  t.etl_active)}}
        </div>`;
      d.addEventListener('mouseenter', () => {{ if (!pinnedId) highlight(t.id); }});
      d.addEventListener('mouseleave', () => {{ if (!pinnedId) clearHL(); }});
      d.addEventListener('click', (e) => {{
        e.stopPropagation();
        if (e.target.closest('a')) return;   // let Docs/ETL links work
        if (hasRelations(t.id)) {{            // related tables -> open focus overlay
          openFocus(t.id);
        }} else if (pinnedId === t.id) {{      // no relations -> old pin behaviour
          pinnedId = null; clearHL();
        }} else {{
          pinnedId = t.id; highlight(t.id);
        }}
      }});
      col.appendChild(d);
    }});
    const cnt = document.createElement('div');
    cnt.className = 'hcount';
    cnt.textContent = rows.length + ' table' + (rows.length !== 1 ? 's' : '');
    col.appendChild(cnt);
  }});
  setTimeout(drawEdges, 80);
}}

function setSchema(s, btn) {{
  activeSchema = s;
  pinnedId = null;
  document.querySelectorAll('.ctrl-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  render();
}}

function getRect(id) {{
  const el = document.getElementById('card-' + id);
  if (!el) return null;
  const wrap = document.getElementById('lanes');
  const wr = wrap.getBoundingClientRect();
  const er = el.getBoundingClientRect();
  if (er.width === 0) return null;
  return {{
    left:  er.left  - wr.left,
    right: er.right - wr.left,
    cy:    er.top   - wr.top + er.height / 2,
  }};
}}

function drawEdges() {{
  const svg  = document.getElementById('edge-svg');
  const wrap = document.getElementById('lanes');
  svg.setAttribute('viewBox', `0 0 ${{wrap.offsetWidth}} ${{wrap.offsetHeight}}`);
  svg.innerHTML = `<defs><marker id="ah" viewBox="0 0 10 10" refX="8" refY="5"
    markerWidth="5" markerHeight="5" orient="auto-start-reverse">
    <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke"
      stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </marker></defs>`;
  EDGES.forEach(e => {{
    const fr = getRect(e.from);
    const to = getRect(e.to);
    if (!fr || !to) return;
    const x1 = fr.right + 1, y1 = fr.cy;
    const x2 = to.left  - 1, y2 = to.cy;
    const cx = (x1 + x2) / 2;
    const stroke = e.type === 'multi' ? '#378ADD' : '#8aa0b8';
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('d', `M${{x1}},${{y1}} C${{cx}},${{y1}} ${{cx}},${{y2}} ${{x2}},${{y2}}`);
    p.setAttribute('fill', 'none');
    p.setAttribute('stroke', stroke);
    p.setAttribute('stroke-width', '1.5');
    p.setAttribute('opacity', '0.5');
    p.setAttribute('marker-end', 'url(#ah)');
    p.dataset.from = e.from;
    p.dataset.to   = e.to;
    if (e.type === 'multi') p.setAttribute('stroke-dasharray', '5 3');
    svg.appendChild(p);
  }});
}}

function highlight(id) {{
  const sources = new Set(), dests = new Set();
  EDGES.forEach(e => {{
    if (e.to   === id) sources.add(e.from);
    if (e.from === id) dests.add(e.to);
  }});
  document.querySelectorAll('.tcard').forEach(c => {{
    const cid = c.dataset.id;
    c.classList.remove('hl', 'hl-src', 'hl-dst');
    if      (cid === id)        c.classList.add('hl');
    else if (sources.has(cid)) c.classList.add('hl-src');
    else if (dests.has(cid))   c.classList.add('hl-dst');
  }});
  document.getElementById('edge-svg').querySelectorAll('path[data-from]').forEach(p => {{
    const active = p.dataset.from === id || p.dataset.to === id;
    p.setAttribute('opacity',      active ? '0.9' : '0.06');
    p.setAttribute('stroke-width', active ? '2'   : '1');
  }});
}}

function clearHL() {{
  document.querySelectorAll('.tcard').forEach(c =>
    c.classList.remove('hl', 'hl-src', 'hl-dst'));
  document.getElementById('edge-svg').querySelectorAll('path[data-from]').forEach(p => {{
    p.setAttribute('opacity',      '0.5');
    p.setAttribute('stroke-width', '1.5');
  }});
}}

window.addEventListener('resize', drawEdges);
document.addEventListener('click', () => {{
  if (pinnedId) {{
    pinnedId = null;
    clearHL();
  }}
}});

// ===== Focus mode =====
const TABLE_BY_ID = {{}};
TABLES.forEach(t => TABLE_BY_ID[t.id] = t);

const UP = {{}};   // id -> set of direct sources (feeds into id)
const DOWN = {{}}; // id -> set of direct targets (id feeds into)
EDGES.forEach(e => {{
  (DOWN[e.from] = DOWN[e.from] || new Set()).add(e.to);
  (UP[e.to]     = UP[e.to]     || new Set()).add(e.from);
}});

function relatedSet(id) {{
  // full chain: all ancestors (upstream) + all descendants (downstream) + self
  const seen = new Set([id]);
  (function up(n){{ (UP[n]||[]).forEach(p => {{ if(!seen.has(p)){{ seen.add(p); up(p);}} }}); }})(id);
  (function dn(n){{ (DOWN[n]||[]).forEach(c => {{ if(!seen.has(c)){{ seen.add(c); dn(c);}} }}); }})(id);
  return seen;
}}

function hasRelations(id) {{
  return (UP[id] && UP[id].size) || (DOWN[id] && DOWN[id].size);
}}

const LAYER_ORDER = ['bronze','silver','gold','review'];
const LAYER_LABEL = {{bronze:'Bronze', silver:'Silver', gold:'Gold', review:'Review'}};

function openFocus(centerId) {{
  if (!hasRelations(centerId)) return;   // do nothing for unrelated tables
  const ids = relatedSet(centerId);
  const cols = document.getElementById('focus-cols');
  cols.innerHTML = '';
  document.getElementById('focus-name').textContent =
    (TABLE_BY_ID[centerId].schema + '.' + TABLE_BY_ID[centerId].name);

  LAYER_ORDER.forEach(layer => {{
    const members = [...ids].filter(i => TABLE_BY_ID[i] && TABLE_BY_ID[i].layer === layer);
    if (!members.length) return;
    const col = document.createElement('div');
    col.className = 'focus-col';
    const lbl = document.createElement('div');
    lbl.className = 'focus-col-lbl';
    lbl.textContent = LAYER_LABEL[layer];
    col.appendChild(lbl);
    members.forEach(i => col.appendChild(buildFocusCard(i, centerId)));
    cols.appendChild(col);
  }});

  document.getElementById('focus-backdrop').classList.add('show');
  setTimeout(() => drawFocusEdges(ids), 30);
}}

function buildFocusCard(id, centerId) {{
  const t = TABLE_BY_ID[id];
  const d = document.createElement('div');
  d.className = 'fcard' + (id === centerId ? ' is-center' : '');
  d.id = 'fcard-' + id;
  d.innerHTML = `
    <div class="card-top">
      <div class="card-meta">
        <div class="schema-lbl">${{t.schema}}</div>
        <div class="tname">${{t.name}}</div>
      </div>
      ${{badgesHTML(t)}}
    </div>
    <div class="card-links">
      ${{linkHTML('Docs', t.docs_url, t.docs_active)}}
      ${{linkHTML('ETL',  t.etl_url,  t.etl_active)}}
    </div>`;
  if (id !== centerId) {{
    d.addEventListener('click', (e) => {{
      if (e.target.closest('a')) return;   // let links work
      e.stopPropagation();
      openFocus(id);                        // re-focus on the clicked related table
    }});
  }}
  return d;
}}

function fcardRect(id, stageRect) {{
  const el = document.getElementById('fcard-' + id);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return {{
    left: r.left - stageRect.left,
    right: r.right - stageRect.left,
    cy: r.top - stageRect.top + r.height/2,
  }};
}}

function drawFocusEdges(ids) {{
  const svg = document.getElementById('focus-svg');
  const stage = svg.parentElement.getBoundingClientRect();
  svg.setAttribute('viewBox', `0 0 ${{svg.parentElement.offsetWidth}} ${{svg.parentElement.offsetHeight}}`);
  svg.innerHTML = `<defs><marker id="fah" viewBox="0 0 10 10" refX="8" refY="5"
    markerWidth="6" markerHeight="6" orient="auto-start-reverse">
    <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5"
      stroke-linecap="round" stroke-linejoin="round"/></marker></defs>`;
  EDGES.forEach(e => {{
    if (!ids.has(e.from) || !ids.has(e.to)) return;
    const fr = fcardRect(e.from, stage), to = fcardRect(e.to, stage);
    if (!fr || !to) return;
    const x1 = fr.right + 1, y1 = fr.cy, x2 = to.left - 1, y2 = to.cy;
    const cx = (x1 + x2) / 2;
    const stroke = e.type === 'multi' ? '#378ADD' : '#8aa0b8';
    const p = document.createElementNS('http://www.w3.org/2000/svg','path');
    p.setAttribute('d', `M${{x1}},${{y1}} C${{cx}},${{y1}} ${{cx}},${{y2}} ${{x2}},${{y2}}`);
    p.setAttribute('fill','none'); p.setAttribute('stroke', stroke);
    p.setAttribute('stroke-width','1.8'); p.setAttribute('opacity','0.8');
    p.setAttribute('marker-end','url(#fah)');
    if (e.type === 'multi') p.setAttribute('stroke-dasharray','5 3');
    svg.appendChild(p);
  }});
}}

function closeFocus() {{
  document.getElementById('focus-backdrop').classList.remove('show');
}}

document.getElementById('focus-backdrop').addEventListener('click', closeFocus);
document.addEventListener('keydown', (e) => {{ if (e.key === 'Escape') closeFocus(); }});
window.addEventListener('resize', () => {{
  const bd = document.getElementById('focus-backdrop');
  if (bd.classList.contains('show')) {{
    const center = document.querySelector('.fcard.is-center');
    if (center) drawFocusEdges(relatedSet(center.id.replace('fcard-','')));
  }}
}});

render();
</script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Generate lineage HTML from YAML")
    parser.add_argument("--input",  default="diagram.yaml", help="Input YAML file")
    parser.add_argument("--output", default="diagram.html", help="Output HTML file")
    args = parser.parse_args()

    input_path  = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"ERROR: {input_path} not found")
        sys.exit(1)

    print(f"Reading {input_path} ...")
    data = load_yaml(input_path)

    print("Validating ...")
    validate(data)

    print("Generating HTML ...")
    html = generate_html(data)

    output_path.write_text(html, encoding="utf-8")
    print(f"Done — {output_path} ({len(html):,} bytes)")

    tables = data.get("tables", [])
    docs_ready = sum(1 for t in tables if t.get("docs_url", PLACEHOLDER) != PLACEHOLDER)
    etl_ready  = sum(1 for t in tables if t.get("etl_url",  PLACEHOLDER) != PLACEHOLDER)
    print(f"  Tables : {len(tables)}  |  Edges: {len(data.get('edges', []))}")
    print(f"  Docs links ready : {docs_ready}/{len(tables)}")
    print(f"  ETL  links ready : {etl_ready}/{len(tables)}")


if __name__ == "__main__":
    main()