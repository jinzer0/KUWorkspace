from datetime import datetime

from src import config
from src.storage.integrity import DataIntegrityError

from src.storage.repositories import (
    UserRepository,
    RoomRepository,
    EquipmentAssetRepository,
    RoomBookingRepository,
    EquipmentBookingRepository,
    PenaltyRepository,
    AuditLogRepository,
)


def read_clock_marker():
    config.ensure_data_dir()
    try:
        return (
            config.CLOCK_FILE.read_text(encoding="utf-8").strip()
            or config.CLOCK_SENTINEL
        )
    except OSError as error:
        raise DataIntegrityError(
            f"시계 파일을 읽을 수 없습니다: {config.CLOCK_FILE} ({error})"
        ) from error


def load_persisted_clock():
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
