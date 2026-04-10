from datetime import datetime
from typing import List, Optional

from src.storage.integrity import DataIntegrityError


def _escape_field(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|")


def _unescape_field(value: str) -> str:
    result = []
    escaped = False
    for ch in value:
        if escaped:
            result.append(ch)
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        result.append(ch)
    if escaped:
        result.append("\\")
    return "".join(result)


def _split_escaped(line: str) -> list[str]:
    parts = []
    buf = []
    escaped = False
    for ch in line:
        if escaped:
            buf.append("\\")
            buf.append(ch)
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == "|":
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if escaped:
        raise ValueError("잘못된 이스케이프 시퀀스입니다.")
    parts.append("".join(buf))
    return parts


def _normalize_datetime(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value)
        return dt.replace(second=0, microsecond=0).isoformat(timespec="minutes")
    except ValueError:
        return value


def encode_record(record: List[Optional[str]]) -> str:
    encoded = []
    for value in record:
        if value is None:
            encoded.append("\\-")
            continue
        normalized = _normalize_datetime(value)
        encoded.append(_escape_field(normalized))
    return "|".join(encoded)


def decode_record(line: str) -> List[Optional[str]]:
    values = _split_escaped(line)
    decoded: List[Optional[str]] = []
    for value in values:
        if value == "\\-":
            decoded.append(None)
        else:
            decoded.append(_unescape_field(value))
    return decoded


def read_jsonl(file_path, from_json):
    if not file_path.exists():
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.touch()
        except OSError as error:
            raise DataIntegrityError(
                f"데이터 파일을 생성할 수 없습니다: {file_path} ({error})"
            ) from error
        return []

    records = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line_no, raw_line in enumerate(f, start=1):
                line = raw_line.rstrip("\n")
                if not line:
                    raise DataIntegrityError(
                        f"데이터 파일 형식이 올바르지 않습니다: {file_path} {line_no}번째 줄이 비어 있습니다."
                    )
                try:
                    records.append(from_json(decode_record(line)))
                except DataIntegrityError:
                    raise
                except (ValueError, TypeError, IndexError, UnicodeDecodeError) as error:
                    raise DataIntegrityError(
                        f"데이터 파일 형식이 올바르지 않습니다: {file_path} {line_no}번째 줄 ({error})"
                    ) from error
    except DataIntegrityError:
        raise
    except OSError as error:
        raise DataIntegrityError(
            f"데이터 파일을 읽을 수 없습니다: {file_path} ({error})"
        ) from error
    return records


def write_jsonl(file_path, records, to_json):
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(encode_record(to_json(record)) + "\n")
