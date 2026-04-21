# pyright: reportImportCycles=false

import atexit
from datetime import datetime

from src.cli.validators import validate_date_plan, validate_time_plan


def read_clock_marker():
    from src import config
    from src.storage.integrity import DataIntegrityError

    config.ensure_data_dir()
    try:
        return (
            config.CLOCK_FILE.read_text(encoding="utf-8").strip()
            or config.CLOCK_SENTINEL
        )
    except FileNotFoundError:
        return config.CLOCK_SENTINEL
    except OSError as error:
        raise DataIntegrityError(
            f"시계 파일을 읽을 수 없습니다: {config.CLOCK_FILE} ({error})"
        ) from error


def load_persisted_clock():
    from src import config
    from src.storage.integrity import DataIntegrityError

    marker = read_clock_marker()
    if marker == config.CLOCK_SENTINEL:
        return None
    try:
        return datetime.fromisoformat(marker)
    except ValueError as error:
        raise DataIntegrityError(
            f"시계 파일 형식이 올바르지 않습니다: {config.CLOCK_FILE} ({marker})"
        ) from error


def persist_clock(current_time):
    from src import config
    from src.storage.integrity import DataIntegrityError

    if isinstance(current_time, datetime):
        current_time = current_time.replace(second=0, microsecond=0).isoformat(
            timespec="minutes"
        )
    config.ensure_data_dir()
    try:
        config.CLOCK_FILE.write_text(current_time, encoding="utf-8")
    except OSError as error:
        raise DataIntegrityError(
            f"시계 파일을 저장할 수 없습니다: {config.CLOCK_FILE} ({error})"
        ) from error


def _iter_datetime_strings(record):
    for value in vars(record).values():
        if not isinstance(value, str):
            continue
        try:
            yield datetime.fromisoformat(value)
        except ValueError:
            continue


def get_latest_data_timestamp():
    from src import config

    from src.storage.repositories import (
        UserRepository,
        RoomRepository,
        EquipmentAssetRepository,
        RoomBookingRepository,
        EquipmentBookingRepository,
        PenaltyRepository,
        AuditLogRepository,
    )

    repositories = [
        UserRepository(),
        RoomRepository(),
        EquipmentAssetRepository(),
        RoomBookingRepository(),
        EquipmentBookingRepository(),
        PenaltyRepository(),
        AuditLogRepository(),
    ]

    latest = None
    for repository in repositories:
        for record in repository.get_all():
            for timestamp in _iter_datetime_strings(record):
                if latest is None or timestamp > latest:
                    latest = timestamp
    return latest


def prompt_initial_clock(latest_data_time_getter=None, saved_clock_time_getter=None):
    """프로그램 시작 시 운영 시작 시점을 입력받습니다."""
    if latest_data_time_getter is None:
        latest_data_time = get_latest_data_timestamp()
    else:
        latest_data_time = latest_data_time_getter()
    if saved_clock_time_getter is None:
        saved_clock_time = load_persisted_clock()
    else:
        saved_clock_time = saved_clock_time_getter()

    if saved_clock_time is not None:
        print(
            "\n이전 종료 시점부터 운영을 재개합니다. "
            f"({saved_clock_time.strftime('%Y-%m-%d %H:%M')})"
        )
        return saved_clock_time

    while True:
        print("\n운영 시작 시점을 설정합니다.")
        date_str = input("시작 날짜 (YYYY-MM-DD): ")
        slot_str = input("시작 슬롯 (09:00 또는 18:00): ")

        valid, base_date, error = validate_date_plan(date_str)
        if not valid or base_date is None:
            print(f"✗ {error}")
            continue

        time_valid, slot_time, time_error = validate_time_plan(slot_str)
        if not time_valid or slot_time is None:
            print(f"✗ {time_error}")
            continue

        start_time = datetime(
            base_date.year,
            base_date.month,
            base_date.day,
            slot_time.hour,
            slot_time.minute,
        )

        if latest_data_time is not None and start_time < latest_data_time:
            print(
                "✗ 시작 시점이 기존 데이터의 최신 시각보다 빠릅니다. "
                f"(최신 기록: {latest_data_time.strftime('%Y-%m-%d %H:%M')})"
            )
            continue

        return start_time


def persist_clock_state():
    from src.runtime_clock import get_active_clock

    active_clock = get_active_clock()
    if active_clock is None:
        return
    persist_clock(active_clock.now())


def initialize_runtime_clock(clock):
    atexit.register(persist_clock_state)
    return clock
