from datetime import datetime
from typing import List, Optional


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
        buf.append("\\")
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
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()
        return []

    records = []
    with open(file_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            if not line:
                continue
            records.append(from_json(decode_record(line)))
    return records


def write_jsonl(file_path, records, to_json):
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(encode_record(to_json(record)) + "\n")
