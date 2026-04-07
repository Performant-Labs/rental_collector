"""Integration test to validate ingestion against real scraper output.

This test discovers actual info.json files from the rentals directory
and validates that the ingestion pipeline correctly maps all fields.
It will fail if the scraper schema changes without corresponding
updates to the ingestion code.
"""

from pathlib import Path

import pytest

from dashboard.app.ingestion import (
    build_documents_from_rentals,
    discover_listing_folders,
    normalise_listing_document,
    parse_listing_info,
)


def _get_rentals_dir() -> Path | None:
    """Locate rentals directory from container or local paths."""
    # Try container path first (/app is the working directory in container)
    container_path = Path("/app/rentals")
    if container_path.exists():
        return container_path

    # Fallback to relative path from test file
    test_file = Path(__file__).resolve()
    relative_path = test_file.parents[2] / "rentals"  # tests -> dashboard -> repo_root
    if relative_path.exists():
        return relative_path

    return None


def test_ingestion_handles_real_scraper_output():
    """Validate ingestion works with actual scraper-generated info.json files."""
    rentals_dir = _get_rentals_dir()

    if rentals_dir is None:
        pytest.skip("No rentals directory found - run scraper first")

    folders = discover_listing_folders(rentals_dir)
    if not folders:
        pytest.skip("No listing folders with info.json found")

    # Test a sample of real listings (up to 5)
    sample_folders = folders[:5]
    errors = []

    for folder in sample_folders:
        try:
            info_path = folder / "info.json"
            raw = parse_listing_info(info_path)
            document = normalise_listing_document(raw, folder)

            # Validate required fields are present and correctly typed
            assert isinstance(document.get("id"), str), f"{folder.name}: id must be string"
            assert isinstance(document.get("title"), str), f"{folder.name}: title must be string"
            assert document.get("title"), f"{folder.name}: title must not be empty"
            assert isinstance(document.get("source"), str), f"{folder.name}: source must be string"
            assert isinstance(document.get("listing_path"), str), f"{folder.name}: listing_path must be string"

            # Validate optional fields have correct types when present
            price_usd = document.get("price_usd")
            if price_usd is not None:
                assert isinstance(price_usd, int), f"{folder.name}: price_usd must be int, got {type(price_usd)}"
                assert price_usd > 0, f"{folder.name}: price_usd must be positive"

            # Validate boolean fields
            assert isinstance(document.get("has_photos"), bool), f"{folder.name}: has_photos must be bool"
            assert isinstance(document.get("has_contact"), bool), f"{folder.name}: has_contact must be bool"

            # Validate price_bucket is computed correctly
            price_bucket = document.get("price_bucket")
            assert isinstance(price_bucket, str), f"{folder.name}: price_bucket must be string"
            # Price buckets are now open-ended $500 chunks: <500, 500+, 1000+, 1500+, etc.
            assert price_bucket == "unknown" or price_bucket.endswith("+"), f"{folder.name}: invalid price_bucket format {price_bucket}"

            # Cross-check: if usdPerMonth exists in raw, price_usd should be populated
            if "usdPerMonth" in raw and raw["usdPerMonth"] is not None:
                if document.get("price_usd") is None:
                    errors.append(f"{folder.name}: usdPerMonth={raw['usdPerMonth']} but price_usd is None - ingestion bug")

        except Exception as exc:
            errors.append(f"{folder.name}: {exc}")

    if errors:
        pytest.fail("Ingestion errors with real scraper data:\n" + "\n".join(errors))


def test_price_field_mapping_regression():
    """Specific regression test for price field mapping from scraper to document.

    The scraper outputs 'usdPerMonth' (camelCase) but ingestion previously
    only looked for 'price_usd' (snake_case), causing all prices to be None.
    """
    rentals_dir = _get_rentals_dir()

    if rentals_dir is None:
        pytest.skip("No rentals directory found")

    folders = discover_listing_folders(rentals_dir)

    # Find at least one listing with usdPerMonth to validate
    listings_with_price = 0
    listings_with_missing_price = 0

    for folder in folders[:10]:  # Check first 10
        info_path = folder / "info.json"
        raw = parse_listing_info(info_path)

        has_usd_per_month = "usdPerMonth" in raw and raw["usdPerMonth"] is not None

        if has_usd_per_month:
            listings_with_price += 1
            document = normalise_listing_document(raw, folder)

            if document.get("price_usd") is None:
                listings_with_missing_price += 1
                pytest.fail(
                    f"{folder.name}: usdPerMonth={raw['usdPerMonth']} present in raw data "
                    f"but price_usd is None in document - ingestion is not mapping the field correctly"
                )

    # Assert we actually tested something meaningful
    if listings_with_price == 0:
        pytest.skip("No listings with usdPerMonth found in sample - cannot validate price mapping")

    # All listings with usdPerMonth should have price_usd in document
    assert listings_with_missing_price == 0, f"{listings_with_missing_price} listings lost their price during ingestion"
