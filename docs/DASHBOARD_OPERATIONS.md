# Dashboard Operations

This runbook covers startup, scheduled ingestion, reindexing, and backup/restore for the dashboard stack.

## Start Services

```bash
docker compose up -d dashboard-api meilisearch
```

Health checks:

```bash
curl http://localhost:8000/health
curl http://localhost:7700/health
```

## Scheduled Ingestion (Cron-Compatible)

Run incremental ingestion as a one-shot container command:

```bash
docker compose run --rm dashboard-ingest
```

Explicit mode/path example:

```bash
docker compose run --rm dashboard-ingest \
  python -m dashboard.app.ingest_runner --mode incremental --rentals-dir /app/rentals
```

The ingest runner uses a lock file to prevent overlapping jobs.

## Full Reindex

```bash
docker compose run --rm dashboard-ingest \
  python -m dashboard.app.ingest_runner --mode full --rentals-dir /app/rentals
```

Use full mode after index setting/schema changes or when recovering from index corruption.

## Suggested Cron Entries

```cron
# Nightly scrape output (existing workflow)
0 2 * * * /path/to/scrape-command

# Ingest into search index after scraper finishes
10 2 * * * cd /path/to/repo && docker compose run --rm dashboard-ingest
```

## Meilisearch Data Backup and Restore

Data is persisted in the `meili_data` volume.

Backup volume content:

```bash
docker run --rm -v todossantosrentals_meili_data:/src -v "$PWD":/backup alpine \
  tar czf /backup/meili_data_backup.tgz -C /src .
```

Restore volume content:

```bash
docker run --rm -v todossantosrentals_meili_data:/dst -v "$PWD":/backup alpine \
  sh -c "cd /dst && tar xzf /backup/meili_data_backup.tgz"
```

## Troubleshooting

- Ingest returns code `2`: another ingest run is already active (lock file present).
- Ingest returns code `1`: ingestion failed; inspect container logs and rerun.
- If search data is stale, run full reindex and verify `rentals/` contains expected listing folders.
