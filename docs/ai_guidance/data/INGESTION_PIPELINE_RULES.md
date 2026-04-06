# Ingestion Pipeline Rules

This document defines ingestion behavior for turning rental files into searchable documents.

## Source of Truth
- Canonical data comes from listing folders under `rentals/`.
- Parse from each listing's `info.json`.
- Derived systems (search index, API caches) are rebuildable artifacts.

## Document Construction
- Build one search document per listing folder.
- Attach deterministic `id` using a stable function of source + canonical key.
- Include `listing_path` for linking to `listing.html`.
- Preserve original values where possible; normalize into facet-friendly fields as additions.

## Normalization Rules
- `price_usd` must be integer or null.
- Build `price_bucket` deterministically (`<1000`, `1000-1499`, `1500-2000`, `unknown`).
- Parse booleans for `has_photos`, `has_contact`.
- Normalize `source` and `location` strings for consistent faceting.

## Idempotency and Incremental Upserts
- Same input must produce same output document and same `id`.
- Incremental runs should upsert changed/new docs without duplicating existing ones.
- Full reindex mode is required for schema migrations and recovery.

## Validation and Error Handling
- Invalid listings are skipped with structured warnings (include folder + reason).
- Ingestion must continue past malformed records; do not fail whole batch on one bad listing.
- Fatal failures should return non-zero exit code for cron visibility.

## Operational Rules
- Support three modes:
  - bootstrap on launch (optional)
  - scheduled incremental ingest (cron)
  - manual full reindex
- Prevent overlapping ingestion runs via lock mechanism.

## Logging
- Emit summary counts: discovered, indexed, skipped, failed.
- Keep logs machine-readable where practical for future alerting.
