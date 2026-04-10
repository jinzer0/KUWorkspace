import pytest

from src.storage.integrity import DataIntegrityError
from src.storage.jsonl_handler import decode_record, read_jsonl


def test_read_jsonl_creates_missing_file(tmp_path):
    file_path = tmp_path / "users.txt"

    result = read_jsonl(file_path, lambda line: line)

    assert result == []
    assert file_path.exists()


def test_decode_record_rejects_trailing_escape():
    with pytest.raises(ValueError, match="이스케이프"):
        decode_record("value\\")


def test_read_jsonl_fails_on_blank_line(tmp_path):
    file_path = tmp_path / "users.txt"
    file_path.write_text("first\n\nthird\n", encoding="utf-8")

    with pytest.raises(DataIntegrityError, match="비어 있습니다"):
        read_jsonl(file_path, lambda line: line)


def test_read_jsonl_wraps_record_parse_error_with_line_number(tmp_path):
    file_path = tmp_path / "users.txt"
    file_path.write_text("good\nbad\n", encoding="utf-8")

    def parser(value):
        if value == ["bad"]:
            raise ValueError("boom")
        return value

    with pytest.raises(DataIntegrityError, match="2번째 줄"):
        read_jsonl(file_path, parser)
