from src.config import DATA_FILES, ensure_data_dir


def test_ensure_data_dir_creates_all_data_files(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.DATA_DIR", tmp_path)
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
    ]:
        assert file_path.exists()
        assert file_path.is_file()
