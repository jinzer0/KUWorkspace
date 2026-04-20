import pytest

from src.config import DATA_FILES, ensure_data_dir
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
        tmp_path / "penalties.txt",
        tmp_path / "audit_log.txt",
        tmp_path / "clock.txt",
    ]:
        assert file_path.exists()
        assert file_path.is_file()

    assert (tmp_path / "clock.txt").read_text(encoding="utf-8").strip() == "0000-00-00T00:00"


def test_ensure_data_dir_fails_fast_on_permission_error(monkeypatch, tmp_path):
    monkeypatch.setattr("src.config.DATA_DIR", tmp_path)
    monkeypatch.setattr("src.config.CLOCK_FILE", tmp_path / "clock.txt")
    monkeypatch.setattr("src.config.DATA_FILES", [tmp_path / "users.txt"])

    def fail_touch(self, *args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(type(tmp_path / "users.txt"), "touch", fail_touch)

    with pytest.raises(DataIntegrityError, match="생성할 수 없습니다"):
        ensure_data_dir()
