class DataIntegrityError(RuntimeError):
    """데이터 파일 무결성 위반 또는 파일 접근 실패."""


def validate_all_data_files():
    """필수 데이터 파일 생성 및 전체 무결성 검증."""
    from src import config

    config.ensure_data_dir()

    from src.clock_bootstrap import load_persisted_clock
    from src.storage.repositories import (
        UserRepository,
        RoomRepository,
        EquipmentAssetRepository,
        RoomBookingRepository,
        EquipmentBookingRepository,
        PenaltyRepository,
        AuditLogRepository,
    )

    load_persisted_clock()

    repositories = [
        UserRepository(file_path=config.USERS_FILE),
        RoomRepository(file_path=config.ROOMS_FILE),
        EquipmentAssetRepository(file_path=config.EQUIPMENTS_FILE),
        RoomBookingRepository(file_path=config.ROOM_BOOKINGS_FILE),
        EquipmentBookingRepository(file_path=config.EQUIPMENT_BOOKING_FILE),
        PenaltyRepository(file_path=config.PENALTIES_FILE),
        AuditLogRepository(file_path=config.AUDIT_LOG_FILE),
    ]
    for repository in repositories:
        repository.get_all()
