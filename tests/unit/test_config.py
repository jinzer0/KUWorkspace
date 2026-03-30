from src.config import DATA_FILES, ensure_data_dir


def test_ensure_data_dir_creates_all_data_files(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.DATA_DIR", tmp_path)
    monkeypatch.setattr(
        "src.config.DATA_FILES",
        [
            tmp_path / "users.txt",
            tmp_path / "rooms.txt",
            tmp_path / "audit_log.txt",
            tmp_path / "message.txt",
        ],
    )

    ensure_data_dir()

    for file_path in [
        tmp_path / "users.txt",
        tmp_path / "rooms.txt",
        tmp_path / "audit_log.txt",
        tmp_path / "message.txt",
    ]:
        assert file_path.exists()
        assert file_path.is_file()


def test_ensure_data_dir_with_temp_data_dir_fixture_creates_message_file(temp_data_dir):
    """Verify that ensure_data_dir() creates message.txt in the isolated temp directory."""
    ensure_data_dir()
    
    message_file = temp_data_dir / "message.txt"
    assert message_file.exists(), f"message.txt not created in isolated temp dir: {temp_data_dir}"
    assert message_file.is_file()
