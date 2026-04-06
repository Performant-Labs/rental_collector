# Meilisearch Guidance

This document defines how AI agents should design, evolve, and operate Meilisearch for this project.

## Scope
- Dashboard search and facet behavior.
- Indexing strategy from local rental listing data.

## Core Rules
- Keep one primary index for listings (e.g. `rentals_listings`).
- Every document must have a stable `id` derived from source + url/title key + folder context.
- Treat search index data as derived; source of truth remains `rentals/*/info.json`.
- Configure `filterableAttributes`, `sortableAttributes`, and `searchableAttributes` explicitly.
- Do not rely on Meilisearch defaults for ranking/settings in production.

## Required Attributes (v1)
- `id`
- `title`
- `description`
- `source`
- `price_usd`
- `price_bucket`
- `location`
- `listing_type`
- `has_photos`
- `has_contact`
- `scraped`
- `listing_path`

## Facet and Sort Standards
- Facet fields must be low-cardinality and normalized strings/booleans.
- Numeric filtering/sorting uses native numeric fields (`price_usd`).
- Provide stable sort keys:
  - `price_usd:asc`
  - `price_usd:desc`
  - `scraped:desc`

## Index Settings Baseline
- `filterableAttributes` includes: `source`, `price_bucket`, `location`, `listing_type`, `has_photos`, `has_contact`, `scraped`.
- `sortableAttributes` includes: `price_usd`, `scraped`.
- `searchableAttributes` prioritize: `title`, `location`, `description`, `amenities`.
- `displayedAttributes` should omit internal ingestion/debug fields.

## Migrations and Schema Evolution
- When adding/removing key attributes, support a full reindex path.
- Keep backward compatibility in API responses where feasible.
- Record index setting changes in commit messages and docs.

## Reliability Rules
- Ingestion must be idempotent.
- On Meilisearch unavailability, API should return graceful error states (not raw tracebacks).
- Never hardcode master keys in repository files.
