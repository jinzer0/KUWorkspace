from src.storage.jsonl_handler import read_jsonl


def test_read_jsonl_creates_missing_file(tmp_path):
    file_path = tmp_path / "users.txt"

    result = read_jsonl(file_path, lambda line: line)

    assert result == []
    assert file_path.exists()
