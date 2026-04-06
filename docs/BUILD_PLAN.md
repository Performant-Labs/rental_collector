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

- [x] Define normalized dashboard document schema from `rentals/*/info.json` and folder metadata
- [x] Build ingestion module to discover listing folders
- [x] Build ingestion module to parse `info.json`
- [x] Build ingestion module to generate stable `id`
- [x] Build ingestion module to normalize fields for faceting and sort
- [x] Add idempotent upsert behavior (same input -> same document id and values)
- [x] Verify ingestion function returns validated documents
- [x] Verify invalid listings are skipped with structured warnings

### Unit tests (required before Phase 3)
- [x] `test_discovers_listing_folders`
- [x] `test_parses_info_json_to_document`
- [x] `test_generates_stable_document_id`
- [x] `test_skips_invalid_listing_without_crashing`
- [x] `test_price_bucket_computation`

---

## Phase 3 — Meilisearch integration and indexing jobs

- [x] Add Meilisearch client wrapper
- [x] Configure searchable attributes
- [x] Configure filterable attributes (facets)
- [x] Configure sortable attributes
- [x] Implement `full_reindex` command
- [x] Implement `incremental_upsert` command
- [x] Add optional startup bootstrap mode
- [x] Add standalone ingest command for cron
- [x] Verify documents are indexed into Meilisearch
- [x] Verify faceting and sorting are configured and queryable

### Unit tests (required before Phase 4)
- [x] `test_creates_index_if_missing`
- [x] `test_applies_index_settings`
- [x] `test_upsert_sends_expected_documents`
- [x] `test_full_reindex_clears_then_reloads`
- [x] `test_incremental_upsert_is_idempotent`

---

## Phase 4 — Search and facets API contract

- [x] Implement backend search service mapping request params to Meilisearch query
- [x] Support text query (`q`)
- [x] Support multi-select facets
- [x] Support sort options (`price asc/desc`, `recent`)
- [x] Support pagination
- [x] Return results and facet distributions in a stable response shape
- [x] Expose endpoint(s) suitable for HTMX partial rendering
- [x] Ensure consistent query parsing and filter expression building

### Unit tests (required before Phase 5)
- [x] `test_empty_query_returns_first_page`
- [x] `test_text_query_passed_to_search_engine`
- [x] `test_multiple_facets_build_correct_filter_expression`
- [x] `test_sort_option_maps_to_search_sort`
- [x] `test_pagination_offsets_are_correct`

### Integration tests (start in Phase 4)
- [x] `test_api_search_endpoint_returns_expected_contract`
- [x] `test_api_search_endpoint_with_facets_and_sort`
- [x] `test_api_search_endpoint_pagination_contract`

---

## Phase 5 — HTMX UI (results, facet panel, controls)

- [x] Build full page shell template
- [x] Build results partial template
- [x] Build facets partial template
- [x] Build pagination partial template
- [x] Wire HTMX live search input (debounced)
- [x] Wire HTMX facet toggles and filter chips
- [x] Wire HTMX sort changes
- [x] Wire HTMX pagination
- [x] Add URL sync with `hx-push-url` for shareable state
- [x] Verify dashboard is fully searchable with HTMX
- [x] Verify card links target `rentals/{folder}/listing.html`

### Unit tests (required before Phase 6)
- [x] `test_results_partial_renders_listing_cards`
- [x] `test_facet_partial_renders_counts`
- [x] `test_selected_filters_are_marked_active`
- [x] `test_empty_state_message_renders`
- [x] `test_listing_card_link_points_to_local_listing_html`

### Integration tests (required before Phase 6)
- [x] `test_htmx_results_partial_updates_from_search`
- [x] `test_htmx_facet_selection_updates_results_and_counts`
- [x] `test_htmx_url_state_roundtrip_for_search_and_filters`

---

## Phase 6 — Scheduling, operations, and container orchestration

- [x] Add `docker-compose` service for `dashboard-api`
- [x] Add `docker-compose` service for `meilisearch`
- [x] Add cron-compatible ingestion command (called after nightly scrape)
- [x] Add simple locking strategy to prevent overlapping ingestion jobs
- [x] Add operational docs for startup, reindex, and backup/restore of search data
- [x] Verify end-to-end flow: scraper writes files -> cron runs ingestion -> dashboard reflects new data

### Unit tests (required before completion)
- [x] `test_ingest_command_invokes_incremental_upsert`
- [x] `test_lock_prevents_concurrent_ingest_runs`
- [x] `test_ingest_returns_nonzero_on_fatal_failure`
- [x] `test_cli_flags_parse_expected_modes`

### Integration tests (required before completion)
- [x] `test_end_to_end_scrape_artifact_to_search_index_flow`
- [x] `test_cron_ingest_updates_search_without_app_restart`
- [x] `test_full_reindex_restores_search_after_index_clear`

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

### Integration tests (required before release)
- [ ] `test_search_error_ui_and_api_fallback_behavior`
- [ ] `test_container_smoke_dashboard_and_meilisearch_health`
- [ ] `test_release_candidate_core_user_flow`

---

## Definition of Done

- [ ] All phase unit tests pass before moving to next phase
- [ ] Dashboard is deployable in container
- [ ] Ingestion works both on launch (optional bootstrap) and via cron
- [ ] Search supports text relevance, multi-facet filtering, sorting, and pagination
