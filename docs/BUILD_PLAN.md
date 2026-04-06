# Dashboard Build Checklist

This checklist implements a containerized dashboard stack with `FastAPI + HTMX + Meilisearch`, while keeping scraping independent.

## AI Guidance Rules Applied

All phases in this checklist should follow:

- `docs/ai_guidance/search/MEILISEARCH_GUIDE.md`
- `docs/ai_guidance/data/INGESTION_PIPELINE_RULES.md`
- `docs/ai_guidance/frontend/HTMX_PATTERNS.md`
- `docs/ai_guidance/devops/DOCKER_COMPOSE_WORKFLOW.md`
- `docs/ai_guidance/python/PYTEST_BACKEND_TESTING.md`
- `docs/ai_guidance/NAMING.md`
- `docs/ai_guidance/technical_writing/documentation_guidance.md`

---

## Phase 1 — Project skeleton and local app boot

- [x] Create `dashboard/app/main.py`
- [x] Create `dashboard/app/templates/`
- [x] Create `dashboard/app/static/`
- [x] Create `dashboard/tests/`
- [x] Add minimal FastAPI app with health endpoint and home route
- [x] Add Dockerfile for dashboard API container
- [x] Add dependency file (`requirements.txt` or `pyproject.toml`)
- [x] Verify API starts in container and returns a basic page
- [x] Verify `GET /health` returns healthy status

### Unit tests (required before Phase 2)
- [x] `test_health_endpoint_returns_200`
- [x] `test_home_route_returns_200`
- [x] `test_home_uses_template_response`

---

## Phase 2 — Listing document model and ingestion pipeline

- [ ] Define normalized dashboard document schema from `rentals/*/info.json` and folder metadata
- [ ] Build ingestion module to discover listing folders
- [ ] Build ingestion module to parse `info.json`
- [ ] Build ingestion module to generate stable `id`
- [ ] Build ingestion module to normalize fields for faceting and sort
- [ ] Add idempotent upsert behavior (same input -> same document id and values)
- [ ] Verify ingestion function returns validated documents
- [ ] Verify invalid listings are skipped with structured warnings

### Unit tests (required before Phase 3)
- [ ] `test_discovers_listing_folders`
- [ ] `test_parses_info_json_to_document`
- [ ] `test_generates_stable_document_id`
- [ ] `test_skips_invalid_listing_without_crashing`
- [ ] `test_price_bucket_computation`

---

## Phase 3 — Meilisearch integration and indexing jobs

- [ ] Add Meilisearch client wrapper
- [ ] Configure searchable attributes
- [ ] Configure filterable attributes (facets)
- [ ] Configure sortable attributes
- [ ] Implement `full_reindex` command
- [ ] Implement `incremental_upsert` command
- [ ] Add optional startup bootstrap mode
- [ ] Add standalone ingest command for cron
- [ ] Verify documents are indexed into Meilisearch
- [ ] Verify faceting and sorting are configured and queryable

### Unit tests (required before Phase 4)
- [ ] `test_creates_index_if_missing`
- [ ] `test_applies_index_settings`
- [ ] `test_upsert_sends_expected_documents`
- [ ] `test_full_reindex_clears_then_reloads`
- [ ] `test_incremental_upsert_is_idempotent`

---

## Phase 4 — Search and facets API contract

- [ ] Implement backend search service mapping request params to Meilisearch query
- [ ] Support text query (`q`)
- [ ] Support multi-select facets
- [ ] Support sort options (`price asc/desc`, `recent`)
- [ ] Support pagination
- [ ] Return results and facet distributions in a stable response shape
- [ ] Expose endpoint(s) suitable for HTMX partial rendering
- [ ] Ensure consistent query parsing and filter expression building

### Unit tests (required before Phase 5)
- [ ] `test_empty_query_returns_first_page`
- [ ] `test_text_query_passed_to_search_engine`
- [ ] `test_multiple_facets_build_correct_filter_expression`
- [ ] `test_sort_option_maps_to_search_sort`
- [ ] `test_pagination_offsets_are_correct`

---

## Phase 5 — HTMX UI (results, facet panel, controls)

- [ ] Build full page shell template
- [ ] Build results partial template
- [ ] Build facets partial template
- [ ] Build pagination partial template
- [ ] Wire HTMX live search input (debounced)
- [ ] Wire HTMX facet toggles and filter chips
- [ ] Wire HTMX sort changes
- [ ] Wire HTMX pagination
- [ ] Add URL sync with `hx-push-url` for shareable state
- [ ] Verify dashboard is fully searchable with HTMX
- [ ] Verify card links target `rentals/{folder}/listing.html`

### Unit tests (required before Phase 6)
- [ ] `test_results_partial_renders_listing_cards`
- [ ] `test_facet_partial_renders_counts`
- [ ] `test_selected_filters_are_marked_active`
- [ ] `test_empty_state_message_renders`
- [ ] `test_listing_card_link_points_to_local_listing_html`

---

## Phase 6 — Scheduling, operations, and container orchestration

- [ ] Add `docker-compose` service for `dashboard-api`
- [ ] Add `docker-compose` service for `meilisearch`
- [ ] Add cron-compatible ingestion command (called after nightly scrape)
- [ ] Add simple locking strategy to prevent overlapping ingestion jobs
- [ ] Add operational docs for startup, reindex, and backup/restore of search data
- [ ] Verify end-to-end flow: scraper writes files -> cron runs ingestion -> dashboard reflects new data

### Unit tests (required before completion)
- [ ] `test_ingest_command_invokes_incremental_upsert`
- [ ] `test_lock_prevents_concurrent_ingest_runs`
- [ ] `test_ingest_returns_nonzero_on_fatal_failure`
- [ ] `test_cli_flags_parse_expected_modes`

---

## Phase 7 — Quality hardening and release readiness

- [ ] Add validation and sanitization for user query params
- [ ] Add graceful error UI states for search backend outages
- [ ] Add logging and request IDs for debugging
- [ ] Complete final performance and accessibility pass
- [ ] Verify production-ready first release candidate

### Unit tests (required before release)
- [ ] `test_invalid_filter_values_are_rejected_or_ignored_safely`
- [ ] `test_search_backend_timeout_returns_safe_error_state`
- [ ] `test_unexpected_search_error_is_handled_without_500_template_crash`
- [ ] `test_query_param_validation_rules`

---

## Definition of Done

- [ ] All phase unit tests pass before moving to next phase
- [ ] Dashboard is deployable in container
- [ ] Ingestion works both on launch (optional bootstrap) and via cron
- [ ] Search supports text relevance, multi-facet filtering, sorting, and pagination
