from datetime import datetime

from src import config


def _data_integrity_error():
    integrity_module = __import__("src.storage.integrity", fromlist=["DataIntegrityError"])
    return integrity_module.DataIntegrityError


def _normalize_clock_marker(current_time):
    normalized = current_time.replace(second=0, microsecond=0)
    if (normalized.hour, normalized.minute) not in {(9, 0), (18, 0)}:
        raise ValueError("운영 시점은 09:00 또는 18:00만 사용할 수 있습니다.")
    return normalized


def read_clock_marker():
    config.ensure_data_dir()
    try:
        return (
            config.CLOCK_FILE.read_text(encoding="utf-8").strip()
            or config.CLOCK_SENTINEL
        )
    except OSError as error:
        DataIntegrityError = _data_integrity_error()
        raise DataIntegrityError(
            f"시계 파일을 읽을 수 없습니다: {config.CLOCK_FILE} ({error})"
        ) from error


def load_persisted_clock():
    marker = read_clock_marker()
    if marker == config.CLOCK_SENTINEL:
        return None
    try:
        return _normalize_clock_marker(datetime.fromisoformat(marker))
    except ValueError as error:
        DataIntegrityError = _data_integrity_error()
        raise DataIntegrityError(
            f"시계 파일 형식이 올바르지 않습니다: {config.CLOCK_FILE} ({marker}) - {error}"
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
        DataIntegrityError = _data_integrity_error()
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
    repositories_module = __import__(
        "src.storage.repositories",
        fromlist=[
            "UserRepository",
            "RoomRepository",
            "EquipmentAssetRepository",
            "RoomBookingRepository",
            "EquipmentBookingRepository",
            "PenaltyRepository",
            "AuditLogRepository",
        ],
    )
    repositories = [
        repositories_module.UserRepository(),
        repositories_module.RoomRepository(),
        repositories_module.EquipmentAssetRepository(),
        repositories_module.RoomBookingRepository(),
        repositories_module.EquipmentBookingRepository(),
        repositories_module.PenaltyRepository(),
        repositories_module.AuditLogRepository(),
    ]

    latest = None
    for repository in repositories:
        for record in repository.get_all():
            for timestamp in _iter_datetime_strings(record):
                if latest is None or timestamp > latest:
                    latest = timestamp
    return latest
