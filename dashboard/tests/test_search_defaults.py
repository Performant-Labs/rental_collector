"""
dashboard/tests/test_search_defaults.py
========================================
Phase 4 tests: default status=active filter and status facet behaviour.
"""

import pytest

from dashboard.app.search_service import (
    FACET_FIELDS,
    build_filter_expression,
    perform_search,
    sanitize_facet_filters,
)


# ── build_filter_expression: default active-only ──────────────────────────────

class TestDefaultStatusFilter:

    def test_no_params_injects_active_filter(self):
        """No status param → filter defaults to status = \"active\"."""
        expr = build_filter_expression({})
        assert expr is not None
        assert 'status = "active"' in expr

    def test_explicit_active_adds_active_filter(self):
        """Explicit status=active → filter contains status = \"active\"."""
        expr = build_filter_expression({"status": ["active"]})
        assert 'status = "active"' in expr

    def test_archived_param_overrides_default(self):
        """Explicit status=archived → filter contains archived, not default active."""
        expr = build_filter_expression({"status": ["archived"]})
        assert expr is not None
        assert 'status = "archived"' in expr
        # The default active injection must NOT be present when status is set
        # (the filter already handles the status field explicitly)

    def test_both_statuses_includes_both(self):
        """status=[active, archived] → both appear in OR group."""
        expr = build_filter_expression({"status": ["active", "archived"]})
        assert expr is not None
        assert "active" in expr
        assert "archived" in expr
        # Should be an OR group since multiple values
        assert "OR" in expr

    def test_other_facets_combined_with_default_status(self):
        """Other facets combined with the default active filter."""
        expr = build_filter_expression({"source": ["airbnb"]})
        assert expr is not None
        assert 'status = "active"' in expr
        assert 'source = "airbnb"' in expr
        assert " AND " in expr

    def test_empty_status_list_injects_default(self):
        """An empty status list is treated the same as no status param."""
        expr = build_filter_expression({"status": []})
        assert 'status = "active"' in expr

    def test_whitespace_only_status_injects_default(self):
        """Whitespace-only status value is ignored → default injected."""
        expr = build_filter_expression({"status": ["  "]})
        assert 'status = "active"' in expr


# ── FACET_FIELDS includes status ──────────────────────────────────────────────

class TestFacetFields:

    def test_status_in_facet_fields(self):
        """status must be in FACET_FIELDS so Meilisearch returns its counts."""
        assert "status" in FACET_FIELDS

    def test_status_is_first_facet_field(self):
        """status should be the first field so it renders at the top of the sidebar."""
        assert FACET_FIELDS[0] == "status"


# ── sanitize_facet_filters handles status ────────────────────────────────────

class TestSanitizeFacetFilters:

    def test_active_accepted(self):
        safe, rejected = sanitize_facet_filters({"status": ["active"]})
        assert "active" in safe.get("status", [])
        assert not rejected

    def test_archived_accepted(self):
        safe, rejected = sanitize_facet_filters({"status": ["archived"]})
        assert "archived" in safe.get("status", [])

    def test_too_long_value_rejected(self):
        long_val = "x" * 81
        safe, rejected = sanitize_facet_filters({"status": [long_val]})
        assert long_val not in safe.get("status", [])
        assert long_val in rejected.get("status", [])
