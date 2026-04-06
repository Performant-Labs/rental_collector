from pathlib import Path

from dashboard.app import ingest_runner


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
    )

    assert exit_code == 1


def test_cli_flags_parse_expected_modes():
    args = ingest_runner.parse_scheduler_args(["--mode", "full", "--rentals-dir", "/tmp/rentals", "--lock-file", "/tmp/lock"])

    assert args.mode == "full"
    assert args.rentals_dir == "/tmp/rentals"
    assert args.lock_file == "/tmp/lock"
