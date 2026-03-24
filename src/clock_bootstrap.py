from datetime import datetime

from src.storage.repositories import (
    UserRepository,
    RoomRepository,
    EquipmentAssetRepository,
    RoomBookingRepository,
    EquipmentBookingRepository,
    PenaltyRepository,
    AuditLogRepository,
)


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
