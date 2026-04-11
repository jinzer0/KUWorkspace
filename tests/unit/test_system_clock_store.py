from datetime import datetime

import pytest

from src.runtime_clock import ClockError
from src.system_clock_store import (
    load_clock_time,
    save_clock_time,
    initialize_clock_file,
    INITIAL_CLOCK_VALUE,
    ClockStoreError,
)


def test_initialize_clock_file_writes_initial_value(temp_data_dir):
    initialize_clock_file()
    assert (temp_data_dir / "system_clock.txt").read_text(encoding="utf-8") == INITIAL_CLOCK_VALUE


def test_load_clock_time_returns_none_for_initial_value(temp_data_dir):
    initialize_clock_file()
    assert load_clock_time() is None


def test_save_and_load_clock_time_roundtrip(temp_data_dir):
    save_clock_time(datetime(2026, 6, 15, 18, 0, 0))
    assert load_clock_time() == datetime(2026, 6, 15, 18, 0, 0)


def test_load_clock_time_raises_for_invalid_value(temp_data_dir):
    clock_file = temp_data_dir / "system_clock.txt"
    clock_file.write_text("2026-06-15T10:00", encoding="utf-8")

    with pytest.raises(ClockStoreError):
        load_clock_time()


def test_save_clock_time_raises_for_invalid_slot(temp_data_dir):
    with pytest.raises(ClockError):
        save_clock_time(datetime(2026, 6, 15, 10, 0, 0))
