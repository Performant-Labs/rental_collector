# Pytest Backend Testing Guidance

This document defines backend testing rules for FastAPI and ingestion/search services.

## Core Principles
- Tests should be deterministic, isolated, and fast.
- Prefer unit and contract tests before broad integration coverage.
- New behavior should include tests in the same phase.

## Test Layout
- Place dashboard backend tests under `dashboard/tests/`.
- Group by concern:
  - API route tests
  - ingestion/normalization tests
  - search query-mapping tests

## FastAPI Test Standards
- Use `fastapi.testclient.TestClient` for route tests.
- Assert status code and payload shape.
- For template routes, assert template name/context keys where relevant.

## Dependency Isolation
- Mock Meilisearch client in unit tests.
- Do not depend on live external services in unit tests.
- Keep end-to-end service tests explicit and separate.

## Naming Standards
- Prefer explicit function names:
  - `test_health_endpoint_returns_200`
  - `test_multiple_facets_build_correct_filter_expression`

## Container-First Execution
- Run backend tests in container:
  - `docker compose run --rm dashboard-api python -m pytest dashboard/tests -v`
- CI/local should use the same command family to minimize drift.

## Failure Quality
- Assertions should explain behavior regressions clearly.
- Avoid brittle assertions on irrelevant formatting/details.
