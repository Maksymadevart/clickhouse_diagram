# ClickHouse data lineage diagram

A self-updating diagram of ClickHouse tables across the `analytics`,
`analytics_aggregated`, and `mysql_replica` schemas, with links to each
table's ETL script and documentation.

The page is served by Vercel from `diagram.html`. A daily Jenkins job keeps
it in sync with the warehouse.

## Files

| File | What it is | Who edits it |
|------|-----------|--------------|
| `diagram.yaml` | **Source of truth.** Every table, its layer, icon, MV flag, and links. | Humans (curate) + the daily job (appends new / flags dropped) |
| `diagram.html` | The rendered page Vercel serves. **Generated — do not edit by hand.** | Generated automatically |
| `clickhouse_diagram.py` | The daily job: reads ClickHouse, reconciles `diagram.yaml`, regenerates HTML, commits + pushes, notifies Teams. | — |
| `generate_diagram.py` | Builds `diagram.html` from `diagram.yaml`. Imported by the job; also runnable standalone. | — |
| `jenkins_config` | Jenkins pipeline that runs the job daily at 08:00. | — |

## Daily flow

```
Jenkins (08:00 cron)
  └─ python clickhouse_diagram.py
       ├─ query system.tables in the 3 schemas
       ├─ append NEW tables to diagram.yaml  -> layer 'review', icon 'created'
       ├─ flag DROPPED tables                -> layer 'review', icon 'dropped' (links kept)
       ├─ clear flag on REAPPEARED tables    (keeps human's layer + links)
       ├─ if diagram.yaml changed: regenerate diagram.html
       ├─ commit + push to GitHub (main)
       └─ post summary to MS Teams  (errors -> ❌ warning + build fails)
  └─ GitHub push -> Vercel rebuild -> live page
```

If no tables changed, the job does nothing: no commit, no notification.

## Manual effort (the only ongoing work)

Edit `diagram.yaml` to:
1. Move tables out of the **review** lane into `bronze` / `silver` / `gold`.
2. Set the right `icon` (`none` / `clock` / `flash`) and `is_mview`.
3. Fill in `docs_url` (Confluence) and `etl_url` (GitLab) — replace `insert_link_here`.
4. Delete rows of dropped tables once they're truly gone.
5. Maintain the `edges:` section (lineage relationships are not auto-discovered).

Commit the YAML; the next run (or a local `python generate_diagram.py`) rebuilds the HTML.

## First-time setup

1. Commit all files above to the repo root on `main`.
2. **Jenkins:** point the checkout at `https://github.com/DevartSoftware/Mobion-Public.git`,
   branch `main`. Ensure the agent has `pip install clickhouse-connect ruamel.yaml requests`.
3. **GitHub token:** create a classic PAT with `public_repo` scope (repo is public),
   store it as a Jenkins "Secret text" credential, and put its id in `jenkins_config`
   where `REPLACE_WITH_GITHUB_TOKEN_CRED_ID` is.
4. **Vercel:** connect the repo, set the output to serve `diagram.html` (static).
5. **Engine filter:** confirm `engine_is_included()` in `clickhouse_diagram.py` matches
   what your cluster actually has (run the `GROUP BY engine` audit once).

## Local rebuild

```
pip install pyyaml
python generate_diagram.py            # reads diagram.yaml -> writes diagram.html
```
