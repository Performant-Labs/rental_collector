# HTMX Patterns

This document defines HTMX conventions for server-rendered dashboard interactions.

## Design Principles
- Server renders HTML; HTMX swaps partials.
- Prefer simple declarative HTMX attributes over custom JavaScript.
- Keep URL/state shareable for search and facets.

## Endpoint and Template Structure
- Full page route serves shell + initial state.
- Partial endpoints return:
  - results list/grid
  - facet panel
  - pagination controls
- Template naming should clearly indicate partial purpose (e.g. `_results.html`).

## Interaction Standards
- Search input:
  - use debounced requests (`delay`) to reduce load.
  - update both results and facet counts.
- Facet toggles:
  - support multi-select.
  - reflect selected state visually and in query params.
- Sorting and pagination:
  - preserve active filters/query.
  - avoid resetting state unexpectedly.

## URL and State
- Use `hx-push-url` for navigable/shareable filter states.
- Query params should be deterministic and backend-parseable.
- Back/forward browser navigation should restore visible state.

## Error and Empty States
- Render friendly empty state when no results match filters.
- Render graceful partial-level error message when backend search fails.
- Do not expose raw backend traces in UI.

## Security
- Escape all user-provided values rendered in templates.
- Avoid injecting raw HTML from untrusted listing fields.
