"""Tests for dashboard/app/ingest_runner.py — including the wa_export pre-ingest step."""
from pathlib import Path
from unittest.mock import MagicMock, patch

from dashboard.app import ingest_runner


# ── Existing tests (unchanged logic, now pass skip_wa_export=True) ─────────────

def test_ingest_command_invokes_incremental_upsert(monkeypatch, tmp_path: Path):
    called = {"incremental": 0}

    def fake_incremental_upsert(*, client, rentals_dir):
        called["incremental"] += 1
        return {"indexed_count": 1}

    monkeypatch.setattr(ingest_runner, "incremental_upsert", fake_incremental_upsert)
    monkeypatch.setattr(ingest_runner, "MeilisearchIndexClient", type("C", (), {"from_env": staticmethod(lambda: object())}))

    exit_code = ingest_runner.run_scheduled_ingest(
        mode="incremental",
        rentals_dir=tmp_path,
        lock_file=tmp_path / "ingest.lock",
        skip_wa_export=True,          # isolate from WA step
    )

    assert exit_code == 0
    assert called["incremental"] == 1


def test_lock_prevents_concurrent_ingest_runs(monkeypatch, tmp_path: Path):
    lock_file = tmp_path / "ingest.lock"
    lock_file.write_text("busy", encoding="utf-8")

    called = {"incremental": 0}

    def fake_incremental_upsert(*, client, rentals_dir):
        called["incremental"] += 1
        return {}

    monkeypatch.setattr(ingest_runner, "incremental_upsert", fake_incremental_upsert)

    exit_code = ingest_runner.run_scheduled_ingest(
        mode="incremental",
        rentals_dir=tmp_path,
        lock_file=lock_file,
        client=object(),
        skip_wa_export=True,
    )

    assert exit_code == 2
    assert called["incremental"] == 0


def test_ingest_returns_nonzero_on_fatal_failure(monkeypatch, tmp_path: Path):
    def boom(*, client, rentals_dir):
        raise RuntimeError("fail")

    monkeypatch.setattr(ingest_runner, "incremental_upsert", boom)

    exit_code = ingest_runner.run_scheduled_ingest(
        mode="incremental",
        rentals_dir=tmp_path,
        lock_file=tmp_path / "ingest.lock",
        client=object(),
        skip_wa_export=True,
    )

    assert exit_code == 1


def test_cli_flags_parse_expected_modes():
    args = ingest_runner.parse_scheduler_args(["--mode", "full", "--rentals-dir", "/tmp/rentals", "--lock-file", "/tmp/lock"])

    assert args.mode == "full"
    assert args.rentals_dir == "/tmp/rentals"
    assert args.lock_file == "/tmp/lock"


# ── New: --skip-wa-export CLI flag ────────────────────────────────────────────

def test_cli_skip_wa_export_flag_defaults_false():
    args = ingest_runner.parse_scheduler_args([])
    assert args.skip_wa_export is False


def test_cli_skip_wa_export_flag_can_be_set():
    args = ingest_runner.parse_scheduler_args(["--skip-wa-export"])
    assert args.skip_wa_export is True


# ── New: run_wa_export_conversion ─────────────────────────────────────────────

def test_wa_conversion_skipped_when_converter_missing(tmp_path):
    """If the converter script doesn't exist, return False gracefully."""
    with patch.object(ingest_runner, "_WA_CONVERTER", tmp_path / "nonexistent.py"):
        result = ingest_runner.run_wa_export_conversion()
    assert result is False


def test_wa_conversion_skipped_when_rentals_json_missing(tmp_path):
    """Converter exists but output/rentals.json doesn't yet — return False."""
    converter = tmp_path / "convert_to_rentals.py"
    converter.write_text("# stub")
    with patch.object(ingest_runner, "_WA_CONVERTER", converter):
        result = ingest_runner.run_wa_export_conversion()
    assert result is False


def test_wa_conversion_called_when_data_present(tmp_path):
    """When both converter and rentals.json exist, subprocess.run is called."""
    converter = tmp_path / "convert_to_rentals.py"
    converter.write_text("# stub")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "rentals.json").write_text("[]")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "  → 5 unique rental listings"
    mock_result.stderr = ""

    with patch.object(ingest_runner, "_WA_CONVERTER", converter), \
         patch("dashboard.app.ingest_runner.subprocess.run", return_value=mock_result) as mock_run:
        result = ingest_runner.run_wa_export_conversion()

    assert result is True
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "--save" in cmd
    assert "--min-score" in cmd


def test_wa_conversion_returns_false_on_nonzero_exit(tmp_path):
    converter = tmp_path / "convert_to_rentals.py"
    converter.write_text("# stub")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "rentals.json").write_text("[]")

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "something went wrong"

    with patch.object(ingest_runner, "_WA_CONVERTER", converter), \
         patch("dashboard.app.ingest_runner.subprocess.run", return_value=mock_result):
        result = ingest_runner.run_wa_export_conversion()

    assert result is False


def test_wa_conversion_returns_false_on_timeout(tmp_path):
    import subprocess
    converter = tmp_path / "convert_to_rentals.py"
    converter.write_text("# stub")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "rentals.json").write_text("[]")

    with patch.object(ingest_runner, "_WA_CONVERTER", converter), \
         patch("dashboard.app.ingest_runner.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd="python", timeout=120)):
        result = ingest_runner.run_wa_export_conversion()

    assert result is False


def test_wa_conversion_is_non_fatal_to_ingest(monkeypatch, tmp_path):
    """A WA conversion failure must not prevent Meilisearch indexing from running."""
    called = {"incremental": 0}

    def fake_incremental_upsert(*, client, rentals_dir):
        called["incremental"] += 1
        return {"indexed_count": 5}

    def exploding_wa_conversion(*args, **kwargs):
        raise RuntimeError("WA exploded")

    monkeypatch.setattr(ingest_runner, "run_wa_export_conversion", exploding_wa_conversion)
    monkeypatch.setattr(ingest_runner, "incremental_upsert", fake_incremental_upsert)
    monkeypatch.setattr(ingest_runner, "MeilisearchIndexClient",
                        type("C", (), {"from_env": staticmethod(lambda: object())}))

    exit_code = ingest_runner.run_scheduled_ingest(
        mode="incremental",
        rentals_dir=tmp_path,
        lock_file=tmp_path / "ingest.lock",
    )

    # Ingestion still ran (exit 0) despite WA explosion
    assert exit_code == 0
    assert called["incremental"] == 1


def test_skip_wa_export_prevents_wa_call(monkeypatch, tmp_path):
    """--skip-wa-export must completely bypass run_wa_export_conversion."""
    wa_called = {"count": 0}

    def spy_wa(*args, **kwargs):
        wa_called["count"] += 1

    monkeypatch.setattr(ingest_runner, "run_wa_export_conversion", spy_wa)
    monkeypatch.setattr(ingest_runner, "incremental_upsert", lambda *, client, rentals_dir: {})
    monkeypatch.setattr(ingest_runner, "MeilisearchIndexClient",
                        type("C", (), {"from_env": staticmethod(lambda: object())}))

    ingest_runner.run_scheduled_ingest(
        mode="incremental",
        rentals_dir=tmp_path,
        lock_file=tmp_path / "ingest.lock",
        skip_wa_export=True,
    )

    assert wa_called["count"] == 0
