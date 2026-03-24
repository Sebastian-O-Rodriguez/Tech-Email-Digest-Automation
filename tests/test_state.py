"""Tests for state persistence."""

import json
from pathlib import Path

from email_ingester.models import State
from email_ingester.state import load_state, save_state


class TestLoadState:
    def test_missing_file_returns_empty(self, tmp_path: Path):
        """Scenario 1: missing file returns empty State."""
        state = load_state(tmp_path / "nonexistent.json")
        assert state.delta_token is None
        assert state.processed_ids == set()
        assert state.last_run is None

    def test_corrupt_json_returns_empty(self, tmp_path: Path):
        """Scenario 2: corrupt JSON returns empty State (not crash)."""
        path = tmp_path / "state.json"
        path.write_text("not valid json!!!")
        state = load_state(path)
        assert state.delta_token is None
        assert state.processed_ids == set()
        assert state.last_run is None

    def test_valid_json_loads_correctly(self, tmp_path: Path):
        """Scenario 3: valid JSON loads delta_token, processed_ids as set, last_run."""
        path = tmp_path / "state.json"
        path.write_text(
            json.dumps(
                {
                    "delta_token": "tok123",
                    "processed_ids": ["a", "b"],
                    "last_run": "2026-03-23T00:00:00",
                }
            )
        )
        state = load_state(path)
        assert state.delta_token == "tok123"
        assert state.processed_ids == {"a", "b"}
        assert isinstance(state.processed_ids, set)
        assert state.last_run == "2026-03-23T00:00:00"

    def test_partial_json_uses_defaults(self, tmp_path: Path):
        """Scenario 4: partial JSON (missing keys) still works with defaults."""
        path = tmp_path / "state.json"
        # Only delta_token present — processed_ids and last_run missing
        path.write_text(json.dumps({"delta_token": "tok-only"}))
        state = load_state(path)
        assert state.delta_token == "tok-only"
        assert state.processed_ids == set()
        assert state.last_run is None

    def test_partial_json_empty_object(self, tmp_path: Path):
        """Scenario 4 variant: completely empty JSON object uses all defaults."""
        path = tmp_path / "state.json"
        path.write_text("{}")
        state = load_state(path)
        assert state.delta_token is None
        assert state.processed_ids == set()
        assert state.last_run is None


class TestSaveState:
    def test_creates_file(self, tmp_path: Path):
        """Scenario 5: creates file if it doesn't exist."""
        path = tmp_path / "state.json"
        assert not path.exists()
        save_state(path, State())
        assert path.exists()

    def test_creates_parent_directories(self, tmp_path: Path):
        """Scenario 6: creates parent directories if needed."""
        path = tmp_path / "deeply" / "nested" / "dir" / "state.json"
        assert not path.parent.exists()
        save_state(path, State())
        assert path.exists()

    def test_converts_set_to_sorted_list(self, tmp_path: Path):
        """Scenario 7: converts set to sorted list in JSON output."""
        path = tmp_path / "state.json"
        state = State(processed_ids={"charlie", "alpha", "bravo"})
        save_state(path, state)
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["processed_ids"] == ["alpha", "bravo", "charlie"]
        assert isinstance(raw["processed_ids"], list)


class TestBackupAndRecovery:
    def test_save_creates_backup(self, tmp_path: Path):
        """Save twice — second save creates a .bak containing the first save's content."""
        path = tmp_path / "state.json"
        first = State(delta_token="first-token", processed_ids={"id-1"})
        save_state(path, first)

        second = State(delta_token="second-token", processed_ids={"id-2"})
        save_state(path, second)

        bak_path = path.with_suffix(".json.bak")
        assert bak_path.exists(), ".json.bak should exist after second save"
        raw = json.loads(bak_path.read_text(encoding="utf-8"))
        assert raw["delta_token"] == "first-token"
        assert raw["processed_ids"] == ["id-1"]

    def test_save_atomic_write(self, tmp_path: Path):
        """Save writes correct content and the file is readable immediately after."""
        path = tmp_path / "state.json"
        state = State(
            delta_token="tok-atomic",
            processed_ids={"msg-x", "msg-y"},
            last_run="2026-03-23T09:00:00Z",
        )
        save_state(path, state)

        assert path.exists()
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["delta_token"] == "tok-atomic"
        assert set(raw["processed_ids"]) == {"msg-x", "msg-y"}
        assert raw["last_run"] == "2026-03-23T09:00:00Z"

    def test_load_falls_back_to_backup(self, tmp_path: Path):
        """Corrupt primary + valid backup — load_state recovers from backup."""
        path = tmp_path / "state.json"
        bak_path = path.with_suffix(".json.bak")

        path.write_text("not valid json!!!", encoding="utf-8")
        bak_path.write_text(
            json.dumps(
                {
                    "delta_token": "backup-token",
                    "processed_ids": ["bak-1", "bak-2"],
                    "last_run": "2026-03-23T06:00:00Z",
                }
            ),
            encoding="utf-8",
        )

        state = load_state(path)
        assert state.delta_token == "backup-token"
        assert state.processed_ids == {"bak-1", "bak-2"}
        assert state.last_run == "2026-03-23T06:00:00Z"

    def test_load_both_corrupt(self, tmp_path: Path):
        """Both primary and backup corrupt — load_state returns empty State."""
        path = tmp_path / "state.json"
        bak_path = path.with_suffix(".json.bak")

        path.write_text("{bad json", encoding="utf-8")
        bak_path.write_text("also bad!!!", encoding="utf-8")

        state = load_state(path)
        assert state.delta_token is None
        assert state.processed_ids == set()
        assert state.last_run is None

    def test_load_primary_missing_backup_exists(self, tmp_path: Path):
        """No primary file, valid backup present — load_state recovers from backup."""
        path = tmp_path / "state.json"
        bak_path = path.with_suffix(".json.bak")

        assert not path.exists()
        bak_path.write_text(
            json.dumps(
                {
                    "delta_token": "orphan-backup-token",
                    "processed_ids": ["orphan-1"],
                    "last_run": None,
                }
            ),
            encoding="utf-8",
        )

        state = load_state(path)
        assert state.delta_token == "orphan-backup-token"
        assert state.processed_ids == {"orphan-1"}
        assert state.last_run is None

    def test_save_no_existing_file(self, tmp_path: Path):
        """First save with no prior file — no .bak is created, content is correct."""
        path = tmp_path / "state.json"
        bak_path = path.with_suffix(".json.bak")

        assert not path.exists()
        save_state(path, State(delta_token="first", processed_ids={"a", "b"}))

        assert path.exists()
        assert not bak_path.exists(), ".bak must NOT be created on first save"
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["delta_token"] == "first"
        assert set(raw["processed_ids"]) == {"a", "b"}


class TestRoundTrip:
    def test_round_trip_full_state(self, tmp_path: Path):
        """Scenario 8: save then load returns equivalent State."""
        path = tmp_path / "state.json"
        original = State(
            delta_token="delta-abc",
            processed_ids={"msg-1", "msg-2", "msg-3"},
            last_run="2026-03-23T12:00:00+00:00",
        )
        save_state(path, original)
        loaded = load_state(path)
        assert loaded.delta_token == original.delta_token
        assert loaded.processed_ids == original.processed_ids
        assert loaded.last_run == original.last_run

    def test_round_trip_empty_state(self, tmp_path: Path):
        """Scenario 9: round-trip with empty State."""
        path = tmp_path / "state.json"
        original = State()
        save_state(path, original)
        loaded = load_state(path)
        assert loaded.delta_token is None
        assert loaded.processed_ids == set()
        assert loaded.last_run is None

    def test_round_trip_large_processed_ids(self, tmp_path: Path):
        """Scenario 10: round-trip with large processed_ids set."""
        path = tmp_path / "state.json"
        large_ids = {f"msg-{i:05d}" for i in range(10_000)}
        original = State(
            delta_token="delta-large",
            processed_ids=large_ids,
            last_run="2026-03-23T18:00:00Z",
        )
        save_state(path, original)
        loaded = load_state(path)
        assert loaded.delta_token == original.delta_token
        assert loaded.processed_ids == original.processed_ids
        assert len(loaded.processed_ids) == 10_000
        assert loaded.last_run == original.last_run
