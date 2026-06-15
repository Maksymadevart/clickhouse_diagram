#!/usr/bin/env python3
"""
clickhouse_diagram.py
---------------------
Daily automated sync of the ClickHouse data-lineage diagram.

WHAT IT DOES (run once a day by Jenkins):
  1. Connects to ClickHouse and lists tables in the monitored schemas.
  2. Reconciles that live list against diagram.yaml:
       - NEW table in ClickHouse, not in YAML
             -> appended to YAML in the 'review' layer, icon 'created'.
       - table in YAML, NO LONGER in ClickHouse (was DROPped)
             -> moved to 'review' layer, icon 'dropped'  (links untouched).
       - table previously marked 'dropped' that REAPPEARS in ClickHouse
             -> dropped icon cleared (back to 'none'); its layer + links
                are left exactly as a human set them.
       - materialized views are flagged with is_mview: true (separate badge).
  3. If (and only if) the YAML changed, regenerates diagram.html.
  4. If the YAML changed, commits both files and pushes to GitHub,
     then posts a summary to the MS Teams channel.
  5. On ANY error, posts a warning to Teams and exits non-zero
     (so Jenkins also marks the build red).

MANUAL EFFORT (humans, by editing diagram.yaml):
  - move 'review' tables into bronze/silver/gold and set the right icon
  - fill in docs_url and etl_url links
  - delete rows of dropped tables once they are truly gone
  - maintain the `edges:` section (lineage relationships)

ENVIRONMENT VARIABLES (provided by Jenkins credentials):
  HOST_CLICKHOUSE, CLICKHOUSE_USERNAME, CLICKHOUSE_PASSWORD
  MSTEAMS_WEBHOOK_URL
  GITHUB_TOKEN            (personal access token with repo write scope)

Dependencies:
    pip install clickhouse-connect ruamel.yaml requests
"""

import os
import sys
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests
import clickhouse_connect
from ruamel.yaml import YAML

# ============================================================
# CONFIGURATION
# ============================================================

# Schemas to monitor (hardcoded for now)
MONITORED_SCHEMAS = ["analytics", "analytics_aggregated", "mysql_replica"]

# Which ClickHouse engines should appear in the diagram.
# We show TABLES only — including tables that are *populated by* a materialized
# view (those are ordinary MergeTree tables; a human marks them is_mview: true
# in the YAML). We do NOT show the materialized-view OBJECTS themselves, nor
# plain Views / Dictionaries / Distributed proxies.
# >>> Adjust here if your `GROUP BY engine` audit shows you want others. <<<
def engine_is_included(engine: str) -> bool:
    e = engine or ""
    if "MaterializedView" in e:        # the MV object itself: EXCLUDE (not a table)
        return False
    if e == "View":                    # plain saved-query views: exclude
        return False
    if e == "Dictionary":              # dictionaries: exclude
        return False
    if e.startswith("Distributed"):    # distributed proxies: exclude
        return False
    # everything else (MergeTree, ReplacingMergeTree, SummingMergeTree,
    # AggregatingMergeTree, ReplicatedMergeTree, Shared*MergeTree, Log, Memory,
    # etc.) -> include
    return True


# Layer assigned to brand-new and to dropped tables until a human reclassifies.
REVIEW_LAYER = "review"

# Icon values understood by the HTML renderer:
#   none | clock | flash | created | dropped
ICON_NONE = "none"
ICON_CREATED = "created"
ICON_DROPPED = "dropped"

PLACEHOLDER = "insert_link_here"

# File paths (script is expected to run from the Automation/ dir;
# the repo files live one level up next to it — adjust if your layout differs)
SCRIPT_DIR = Path(__file__).resolve().parent
YAML_PATH = SCRIPT_DIR / "diagram.yaml"
HTML_PATH = SCRIPT_DIR / "diagram.html"

# Git / GitHub
GIT_REMOTE_BRANCH = "main"
GIT_COMMIT_NAME = "lineage-bot"
GIT_COMMIT_EMAIL = "lineage-bot@users.noreply.github.com"

# ruamel YAML configured to preserve comments, order, and quoting.
# sequence=4, offset=2 makes list items indent under their parent key:
#   tables:
#     - id: ...
# which matches the hand-written original file's style.
yaml = YAML()
yaml.preserve_quotes = True
yaml.indent(mapping=2, sequence=4, offset=2)
yaml.width = 4096  # don't wrap long URLs


# ============================================================
# TEAMS NOTIFICATION  (uses your team's relay format)
# ============================================================

def send_teams_message(message: str) -> None:
    webhook = os.environ["MSTEAMS_WEBHOOK_URL"]
    payload = {"message": message}
    headers = {"Content-Type": "application/json"}
    response = requests.post(
        webhook,
        headers=headers,
        data=json.dumps(payload),
        timeout=15,
    )
    response.raise_for_status()


# ============================================================
# CLICKHOUSE
# ============================================================

def get_clickhouse_client():
    return clickhouse_connect.get_client(
        host=os.environ["HOST_CLICKHOUSE"],
        port=8443,
        username=os.environ["CLICKHOUSE_USERNAME"],
        password=os.environ["CLICKHOUSE_PASSWORD"],
        secure=True,  # port 8443 is HTTPS
    )


def fetch_live_tables(client) -> dict:
    """
    Returns a dict keyed by (schema, name) -> {} for every TABLE in the
    monitored schemas that passes the engine filter.

    Note: materialized-view OBJECTS are excluded by engine_is_included(), so
    everything returned here is an ordinary table. Whether a table is
    *populated by* a materialized view is a human judgement recorded as
    is_mview: true in the YAML — it is NOT something system.tables can tell us,
    so the scanner never sets it.
    """
    schemas_sql = ", ".join("'%s'" % s for s in MONITORED_SCHEMAS)
    query = f"""
        SELECT
            database,
            name,
            engine
        FROM system.tables
        WHERE database IN ({schemas_sql})
          AND is_temporary = 0
          AND name NOT LIKE '.inner.%'
          AND name NOT LIKE '.inner_id.%'
        ORDER BY database, name
    """
    result = client.query(query)
    live = {}
    for database, name, engine in result.result_rows:
        if not engine_is_included(engine):
            continue
        live[(database, name)] = {}
    return live


# ============================================================
# YAML RECONCILIATION
# ============================================================

def make_id(schema: str, name: str) -> str:
    """Stable handle for edges + DOM. Table names are unique across schemas,
    so schema_name is collision-free. Sanitise anything odd."""
    raw = f"{schema}_{name}"
    return "".join(c if (c.isalnum() or c == "_") else "_" for c in raw)


def load_yaml(path: Path):
    if not path.exists():
        # bootstrap an empty structure if the file is missing
        return {"tables": [], "edges": []}
    with open(path, encoding="utf-8") as f:
        data = yaml.load(f)
    if data is None:
        data = {}
    data.setdefault("tables", [])
    data.setdefault("edges", [])
    return data


def reconcile(data, live: dict):
    """
    Mutates `data` in place. Returns (added, dropped, reappeared) lists of
    "schema.name" strings describing what changed, for the Teams message.
    """
    tables = data["tables"]
    by_key = {(t["schema"], t["name"]): t for t in tables}

    added, dropped, reappeared = [], [], []

    # --- NEW tables: in ClickHouse, not in YAML -> append to review/created
    for (schema, name), meta in live.items():
        if (schema, name) in by_key:
            continue
        new_row = {
            "id": make_id(schema, name),
            "schema": schema,
            "name": name,
            "layer": REVIEW_LAYER,
            "icon": ICON_CREATED,
            "is_mview": False,   # human sets true later if the table is fed by an MV
            "docs_url": PLACEHOLDER,
            "etl_url": PLACEHOLDER,
        }
        tables.append(new_row)
        # put a blank line before this appended row so the file stays readable
        try:
            tables.yaml_set_comment_before_after_key(
                len(tables) - 1, before="\n"
            )
        except Exception:
            pass  # plain list (e.g. bootstrap path) — spacing is cosmetic only
        by_key[(schema, name)] = new_row
        added.append(f"{schema}.{name}")

    # --- DROPPED / REAPPEARED: walk existing YAML rows
    for (schema, name), row in by_key.items():
        in_clickhouse = (schema, name) in live
        current_icon = row.get("icon", ICON_NONE)

        if not in_clickhouse:
            # table is gone from ClickHouse
            if current_icon != ICON_DROPPED:
                # newly dropped this run -> mark it, never delete, never touch links
                row["layer"] = REVIEW_LAYER
                row["icon"] = ICON_DROPPED
                dropped.append(f"{schema}.{name}")
            # else: already marked dropped on a previous run -> leave as is
        else:
            # table exists in ClickHouse
            if current_icon == ICON_DROPPED:
                # it came back -> clear the dropped flag only.
                # leave layer + links exactly where the human had them.
                row["icon"] = ICON_NONE
                reappeared.append(f"{schema}.{name}")
            # NOTE: is_mview is a HUMAN-OWNED field. The scanner cannot tell
            # whether a table is populated by a materialized view, so we never
            # touch it here — doing so would wipe the human's label every run.

    return added, dropped, reappeared


# ============================================================
# HTML GENERATION
# ============================================================

def generate_html(data) -> str:
    """Delegates to generate_diagram.py so there is ONE source of HTML truth."""
    import generate_diagram
    return generate_diagram.generate_html(data)


# ============================================================
# GIT
# ============================================================

def run_git(*args) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(SCRIPT_DIR),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout.strip()


def has_changes() -> bool:
    """True if diagram.yaml or diagram.html differ from what's committed."""
    out = run_git("status", "--porcelain", "diagram.yaml", "diagram.html")
    return bool(out.strip())


def commit_and_push(summary: str) -> None:
    token = os.environ["GITHUB_TOKEN"]

    # Build an authenticated push URL from the existing origin remote.
    origin = run_git("remote", "get-url", "origin")
    # origin looks like https://github.com/ORG/REPO.git
    if origin.startswith("https://"):
        push_url = origin.replace(
            "https://", f"https://x-access-token:{token}@", 1
        )
    else:
        raise RuntimeError(f"Unexpected origin URL (need https): {origin}")

    run_git("config", "user.name", GIT_COMMIT_NAME)
    run_git("config", "user.email", GIT_COMMIT_EMAIL)
    run_git("add", "diagram.yaml", "diagram.html")
    run_git("commit", "-m", f"chore(lineage): {summary}")
    run_git("push", push_url, f"HEAD:{GIT_REMOTE_BRANCH}")


# ============================================================
# MAIN
# ============================================================

def main():
    run_ts = datetime.now(timezone.utc)
    today = run_ts.date()

    client = get_clickhouse_client()
    live = fetch_live_tables(client)

    if not live:
        # Defensive: an empty result almost certainly means a connection or
        # permissions problem, NOT that every table was dropped. Do not let
        # the reconciler mark the entire diagram as dropped.
        raise RuntimeError(
            "system.tables returned 0 rows for the monitored schemas — "
            "aborting before reconciliation to avoid mass false 'dropped' marks. "
            "Check connectivity / permissions / schema names."
        )

    data = load_yaml(YAML_PATH)
    added, dropped, reappeared = reconcile(data, live)

    if not (added or dropped or reappeared):
        print("No table changes. Nothing to do.")
        return

    # Write YAML back (ruamel preserves comments + order of untouched rows)
    with open(YAML_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f)

    # Regenerate HTML from the updated YAML
    html = generate_html(data)
    HTML_PATH.write_text(html, encoding="utf-8")

    # Only commit if files actually differ on disk vs git
    if not has_changes():
        print("Reconcile reported changes but git sees no diff. Skipping commit.")
        return

    # Build the Teams summary
    parts = []
    if added:
        parts.append(f"{len(added)} new")
    if dropped:
        parts.append(f"{len(dropped)} dropped")
    if reappeared:
        parts.append(f"{len(reappeared)} reappeared")
    summary = ", ".join(parts) + " table(s)"

    commit_and_push(summary)

    # Compose the human-readable message
    lines = [f"✅ [{today}] ClickHouse lineage updated: {summary}."]
    if added:
        lines.append("🆕 New (set layer + links): " + ", ".join(sorted(added)))
    if dropped:
        lines.append("🗑️ Dropped (verify, then remove from YAML): " + ", ".join(sorted(dropped)))
    if reappeared:
        lines.append("♻️ Reappeared (dropped flag cleared): " + ", ".join(sorted(reappeared)))
    send_teams_message("\n".join(lines))

    print(summary)


if __name__ == "__main__":
    run_ts = datetime.now(timezone.utc)
    try:
        main()
    except Exception as exc:
        # Best-effort warning to Teams, then fail the build.
        try:
            send_teams_message(
                f"❌ [{run_ts.date()}] ClickHouse lineage sync FAILED.\nError: {exc}"
            )
        except Exception as notify_exc:
            print(f"ALSO failed to notify Teams: {notify_exc}", file=sys.stderr)
        print(f"FATAL: {exc}", file=sys.stderr)
        sys.exit(1)
