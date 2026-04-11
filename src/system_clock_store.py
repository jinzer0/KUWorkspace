from datetime import datetime
from pathlib import Path
import os
import tempfile

import src.config as config
from src.runtime_clock import normalize_slot, ClockError


INITIAL_CLOCK_VALUE = "0000-00-00T00:00"


class ClockStoreError(Exception):
    """운영 시계 파일 입출력 오류"""


def _clock_file_path():
    return config.SYSTEM_CLOCK_FILE


def _read_raw_value(file_path: Path):
    if not file_path.exists():
        return INITIAL_CLOCK_VALUE
    return file_path.read_text(encoding="utf-8").strip() or INITIAL_CLOCK_VALUE


def load_clock_time():
    raw = _read_raw_value(_clock_file_path())
    if raw == INITIAL_CLOCK_VALUE:
        return None
    try:
        loaded = datetime.fromisoformat(raw)
        return normalize_slot(loaded)
    except (ValueError, ClockError) as error:
        raise ClockStoreError(f"운영 시계 파일 값이 올바르지 않습니다: {raw}") from error


def save_clock_time(dt):
    normalized = normalize_slot(dt)
    value = normalized.isoformat(timespec="minutes")
    target = _clock_file_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False, dir=str(target.parent)
    ) as temp_file:
        temp_file.write(value)
        temp_path = temp_file.name
    os.replace(temp_path, target)


def initialize_clock_file():
    path = _clock_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(INITIAL_CLOCK_VALUE, encoding="utf-8")
