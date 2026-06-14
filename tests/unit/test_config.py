from datetime import datetime

import pytest

from src.config import (
    CLOCK_FILE,
    DATA_FILES,
    ROOM_MAINTENANCE_FILE,
    WAITLIST_FILE,
    ensure_data_dir,
)
from src.runtime_clock import (
    ALLOWED_CLOCK_SLOTS,
    ClockError,
    compute_next_slot,
    normalize_slot,
)
from src.storage.integrity import DataIntegrityError


def test_ensure_data_dir_creates_all_data_files(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.DATA_DIR", tmp_path)
    monkeypatch.setattr("src.config.CLOCK_FILE", tmp_path / "clock.txt")
    monkeypatch.setattr(
        "src.config.DATA_FILES",
        [
            tmp_path / "users.txt",
            tmp_path / "rooms.txt",
            tmp_path / "equipments.txt",
            tmp_path / "room_bookings.txt",
            tmp_path / "equipment_booking.txt",
            tmp_path / "room_maintenance.txt",
            tmp_path / "waiting_list.txt",
            tmp_path / "penalties.txt",
            tmp_path / "audit_log.txt",
            tmp_path / "clock.txt",
        ],
    )

    ensure_data_dir()

    for file_path in [
        tmp_path / "users.txt",
        tmp_path / "rooms.txt",
        tmp_path / "equipments.txt",
        tmp_path / "room_bookings.txt",
        tmp_path / "equipment_booking.txt",
        tmp_path / "room_maintenance.txt",
        tmp_path / "waiting_list.txt",
        tmp_path / "penalties.txt",
        tmp_path / "audit_log.txt",
        tmp_path / "clock.txt",
    ]:
        assert file_path.exists()
        assert file_path.is_file()

    assert (tmp_path / "clock.txt").read_text(encoding="utf-8").strip() == "0000-00-00T00:00"


def test_clock_file_decision_uses_only_clock_txt():
    data_file_names = {file_path.name for file_path in DATA_FILES}

    assert CLOCK_FILE.name == "clock.txt"
    assert ROOM_MAINTENANCE_FILE.name == "room_maintenance.txt"
    assert WAITLIST_FILE.name == "waiting_list.txt"
    assert "clock.txt" in data_file_names
    assert "room_maintenance.txt" in data_file_names
    assert "waiting_list.txt" in data_file_names
    assert "system_clock.txt" not in data_file_names
    assert "waitlist.txt" not in data_file_names


def test_plan0001_waiting_list_file_is_required():
    data_file_names = {file_path.name for file_path in DATA_FILES}

    assert WAITLIST_FILE.name == "waiting_list.txt"
    assert "waiting_list.txt" in data_file_names
    assert "waitlist.txt" not in data_file_names


def test_plan0001_ensure_data_dir_creates_waiting_and_room_maintenance_files(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.DATA_DIR", tmp_path)
    monkeypatch.setattr("src.config.CLOCK_FILE", tmp_path / "clock.txt")
    monkeypatch.setattr(
        "src.config.DATA_FILES",
        [
            tmp_path / "users.txt",
            tmp_path / "rooms.txt",
            tmp_path / "equipments.txt",
            tmp_path / "room_bookings.txt",
            tmp_path / "equipment_booking.txt",
            tmp_path / "room_maintenance.txt",
            tmp_path / "waiting_list.txt",
            tmp_path / "penalties.txt",
            tmp_path / "audit_log.txt",
            tmp_path / "clock.txt",
        ],
    )

    ensure_data_dir()

    assert (tmp_path / "waiting_list.txt").exists()
    assert (tmp_path / "room_maintenance.txt").exists()
    assert not (tmp_path / "waitlist.txt").exists()


def test_runtime_clock_slots_are_locked_to_09_and_18():
    assert ALLOWED_CLOCK_SLOTS == {(9, 0), (18, 0)}
    assert normalize_slot(datetime(2026, 6, 15, 9, 0)) == datetime(2026, 6, 15, 9, 0)
    assert normalize_slot(datetime(2026, 6, 15, 18, 0)) == datetime(2026, 6, 15, 18, 0)
    assert compute_next_slot(datetime(2026, 6, 15, 9, 0)) == datetime(2026, 6, 15, 18, 0)
    assert compute_next_slot(datetime(2026, 6, 15, 18, 0)) == datetime(2026, 6, 16, 9, 0)

    with pytest.raises(ClockError):
        _ = normalize_slot(datetime(2026, 6, 15, 10, 0))


def test_ensure_data_dir_fails_fast_on_permission_error(monkeypatch, tmp_path):
    monkeypatch.setattr("src.config.DATA_DIR", tmp_path)
    monkeypatch.setattr("src.config.CLOCK_FILE", tmp_path / "clock.txt")
    monkeypatch.setattr("src.config.DATA_FILES", [tmp_path / "users.txt"])

    def fail_touch(self, *args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(type(tmp_path / "users.txt"), "touch", fail_touch)

    with pytest.raises(DataIntegrityError, match="생성할 수 없습니다"):
        ensure_data_dir()
