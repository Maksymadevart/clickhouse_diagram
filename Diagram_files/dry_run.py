#!/usr/bin/env python3
"""
dry_run.py
----------
SAFE, READ-ONLY trial of the ClickHouse lineage sync.

It reuses the real logic from clickhouse_diagram.py (same query, same engine
filter, same reconcile rules) but it does NOT:
    - write diagram.yaml
    - write diagram.html
    - commit or push to git
    - send any Teams message

It only connects to ClickHouse and PRINTS what the real job WOULD do, so you
can eyeball the result in the Jenkins build log before running for real.

Run it from the same folder as clickhouse_diagram.py:
    python dry_run.py

Everything it prints is informational. It never changes the repo.
"""

import sys
import traceback
from collections import Counter

# Import the real module so we share one source of truth for all logic.
import clickhouse_diagram as cd


def main():
    print("=" * 70)
    print("DRY RUN — read-only. Nothing will be written, committed, or sent.")
    print("=" * 70)

    # --- 1. Connect -----------------------------------------------------
    print("\n[1/5] Connecting to ClickHouse ...")
    print(f"      host = {cd.os.environ.get('HOST_CLICKHOUSE', '(HOST_CLICKHOUSE not set!)')}")
    print(f"      monitored schemas = {cd.MONITORED_SCHEMAS}")
    client = cd.get_clickhouse_client()
    print("      Connected OK.")

    # --- 2. Raw engine audit (BEFORE the include/exclude filter) --------
    # This is the 'GROUP BY engine' audit we kept deferring. It shows every
    # engine present in the monitored schemas so we can confirm the filter
    # in clickhouse_diagram.engine_is_included() is doing the right thing.
    print("\n[2/5] Engine audit (all tables in monitored schemas, pre-filter):")
    schemas_sql = ", ".join("'%s'" % s for s in cd.MONITORED_SCHEMAS)
    audit = client.query(f"""
        SELECT database, engine, count() AS n
        FROM system.tables
        WHERE database IN ({schemas_sql})
        GROUP BY database, engine
        ORDER BY database, engine
    """)
    for database, engine, n in audit.result_rows:
        included = cd.engine_is_included(engine)
        mark = "KEEP   " if included else "EXCLUDE"
        print(f"      [{mark}] {database:<22} {engine:<28} {n}")

    # --- 3. Live table list (AFTER the filter, what the job would use) --
    print("\n[3/5] Tables the job would consider (post-filter):")
    live = cd.fetch_live_tables(client)
    by_schema = Counter(schema for (schema, _name) in live.keys())
    for schema in cd.MONITORED_SCHEMAS:
        print(f"      {schema:<22} {by_schema.get(schema, 0)} table(s)")
    mview_n = sum(1 for v in live.values() if v["is_mview"])
    print(f"      (materialized views among them: {mview_n})")
    if not live:
        print("\n      WARNING: 0 tables returned. The real job would ABORT here")
        print("      (to avoid mass false 'dropped' marks). Check connectivity,")
        print("      permissions, and schema names before the real run.")
        return

    # --- 4. Reconcile against the committed diagram.yaml ----------------
    print("\n[4/5] Reconciling against diagram.yaml (in memory only) ...")
    data = cd.load_yaml(cd.YAML_PATH)
    existing = len(data.get("tables", []))
    added, dropped, reappeared = cd.reconcile(data, live)
    print(f"      diagram.yaml currently lists {existing} table(s).")

    # --- 5. Report what WOULD change ------------------------------------
    print("\n[5/5] What the REAL job would do this run:")
    if not (added or dropped or reappeared):
        print("      No changes. The real job would do nothing: no commit, no Teams.")
    else:
        if added:
            print(f"\n      ADD {len(added)} new table(s) -> 'review' lane, icon 'created':")
            for x in sorted(added):
                tag = " [materialized view]" if live.get(tuple(x.split('.', 1)), {}).get("is_mview") else ""
                print(f"          + {x}{tag}")
        if dropped:
            print(f"\n      MARK {len(dropped)} dropped table(s) -> 'review' lane, icon 'dropped' (links kept):")
            for x in sorted(dropped):
                print(f"          ~ {x}")
        if reappeared:
            print(f"\n      CLEAR dropped flag on {len(reappeared)} reappeared table(s) (layer/links kept):")
            for x in sorted(reappeared):
                print(f"          ^ {x}")
        print("\n      It would then regenerate diagram.html, commit + push, and post to Teams.")

    print("\n" + "=" * 70)
    print("DRY RUN COMPLETE. Nothing was written, committed, or sent.")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Print the full error so we can read it in the Jenkins log.
        # Note: dry run does NOT send a Teams warning — it stays silent.
        print("\n" + "!" * 70)
        print(f"DRY RUN ERROR: {exc}")
        print("!" * 70)
        traceback.print_exc()
        sys.exit(1)
