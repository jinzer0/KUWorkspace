from datetime import datetime
from uuid import UUID


ALLOWED_CLOCK_SLOTS = {(9, 0), (18, 0)}


def _validate_uuid4(value, *, label, file_path):
    try:
        parsed = UUID(str(value), version=4)
    except (ValueError, AttributeError) as error:
        raise DataIntegrityError(
            f"의미 규칙이 올바르지 않습니다: {file_path} {label}가 UUID v4 형식이어야 합니다 ({value})"
        ) from error

    if str(parsed) != str(value):
        raise DataIntegrityError(
            f"의미 규칙이 올바르지 않습니다: {file_path} {label}가 UUID v4 형식이어야 합니다 ({value})"
        )


def _ensure_unique(records, *, key_fn, label, file_path):
    seen = set()
    for record in records:
        key = key_fn(record)
        if key in seen:
            raise DataIntegrityError(
                f"의미 규칙이 올바르지 않습니다: {file_path} {label} 중복 ({key})"
            )
        seen.add(key)


def _validate_booking_order(booking, *, resource_label, file_path):
    start = datetime.fromisoformat(booking.start_time)
    end = datetime.fromisoformat(booking.end_time)
    if start >= end:
        raise DataIntegrityError(
            f"의미 규칙이 올바르지 않습니다: {file_path} {resource_label} 예약 {booking.id}의 start_time은 end_time보다 빨라야 합니다."
        )


def _validate_active_booking_overlap(bookings, *, resource_attr, active_statuses, resource_label, file_path):
    grouped = {}
    for booking in bookings:
        if booking.status not in active_statuses:
            continue
        grouped.setdefault(getattr(booking, resource_attr), []).append(booking)

    for resource_id, resource_bookings in grouped.items():
        ordered = sorted(
            resource_bookings,
            key=lambda booking: (
                datetime.fromisoformat(booking.start_time),
                datetime.fromisoformat(booking.end_time),
                booking.id,
            ),
        )
        previous = None
        previous_end = None
        for booking in ordered:
            current_start = datetime.fromisoformat(booking.start_time)
            current_end = datetime.fromisoformat(booking.end_time)
            if previous is not None and previous_end is not None and current_start < previous_end:
                raise DataIntegrityError(
                    f"의미 규칙이 올바르지 않습니다: {file_path} {resource_label} {resource_id} 예약 {previous.id}와 {booking.id}가 겹칩니다."
                )
            previous = booking
            previous_end = current_end


def _validate_semantic_integrity(repository_map, record_map):
    from src.domain.models import (
        RoomBookingStatus,
        EquipmentBookingStatus,
    )
    from src.storage.repositories import (
        AuditLogRepository,
        EquipmentAssetRepository,
        EquipmentBookingRepository,
        PenaltyRepository,
        RoomBookingRepository,
        RoomRepository,
        UserRepository,
    )

    users = record_map.get(UserRepository, [])
    rooms = record_map.get(RoomRepository, [])
    equipments = record_map.get(EquipmentAssetRepository, [])
    room_bookings = record_map.get(RoomBookingRepository, [])
    equipment_bookings = record_map.get(EquipmentBookingRepository, [])
    penalties = record_map.get(PenaltyRepository, [])
    audit_logs = record_map.get(AuditLogRepository, [])

    user_repo = repository_map.get(UserRepository)
    room_repo = repository_map.get(RoomRepository)
    equipment_repo = repository_map.get(EquipmentAssetRepository)
    room_booking_repo = repository_map.get(RoomBookingRepository)
    equipment_booking_repo = repository_map.get(EquipmentBookingRepository)
    penalty_repo = repository_map.get(PenaltyRepository)
    audit_repo = repository_map.get(AuditLogRepository)

    if user_repo:
        _ensure_unique(users, key_fn=lambda user: user.username, label="username", file_path=user_repo.file_path)
        for user in users:
            if user.penalty_points < 0:
                raise DataIntegrityError(
                    f"의미 규칙이 올바르지 않습니다: {user_repo.file_path} 사용자 {user.username}의 penalty_points는 0 이상이어야 합니다."
                )
            if user.normal_use_streak < 0:
                raise DataIntegrityError(
                    f"의미 규칙이 올바르지 않습니다: {user_repo.file_path} 사용자 {user.username}의 normal_use_streak는 0 이상이어야 합니다."
                )
            if user.penalty_points >= 3 and not user.restriction_until:
                raise DataIntegrityError(
                    f"의미 규칙이 올바르지 않습니다: {user_repo.file_path} 사용자 {user.username}는 제한/금지 점수에 맞는 restriction_until이 필요합니다."
                )
    if room_repo:
        _ensure_unique(rooms, key_fn=lambda room: room.name, label="room name", file_path=room_repo.file_path)
    if equipment_repo:
        _ensure_unique(
            equipments,
            key_fn=lambda equipment: equipment.serial_number,
            label="serial_number",
            file_path=equipment_repo.file_path,
        )

    user_ids = {user.id for user in users} | {user.username for user in users}
    room_ids = {room.id for room in rooms} | {room.name for room in rooms}
    equipment_ids = {equipment.id for equipment in equipments} | {equipment.serial_number for equipment in equipments}
    room_booking_ids = {booking.id for booking in room_bookings}
    equipment_booking_ids = {booking.id for booking in equipment_bookings}

    active_room_statuses = {
        RoomBookingStatus.RESERVED,
        RoomBookingStatus.CHECKIN_REQUESTED,
        RoomBookingStatus.CHECKED_IN,
        RoomBookingStatus.CHECKOUT_REQUESTED,
    }
    active_equipment_statuses = {
        EquipmentBookingStatus.RESERVED,
        EquipmentBookingStatus.PICKUP_REQUESTED,
        EquipmentBookingStatus.CHECKED_OUT,
        EquipmentBookingStatus.RETURN_REQUESTED,
    }

    if room_booking_repo:
        _ensure_unique(
            room_bookings,
            key_fn=lambda booking: booking.id,
            label="room booking id",
            file_path=room_booking_repo.file_path,
        )
        for booking in room_bookings:
            _validate_uuid4(
                booking.id,
                label="room booking id",
                file_path=room_booking_repo.file_path,
            )
            _validate_booking_order(booking, resource_label="회의실", file_path=room_booking_repo.file_path)
            if booking.user_id not in user_ids:
                raise DataIntegrityError(
                    f"의미 규칙이 올바르지 않습니다: {room_booking_repo.file_path} 예약 {booking.id}의 user_id가 users.txt에 없습니다 ({booking.user_id})."
                )
            if booking.room_id not in room_ids:
                raise DataIntegrityError(
                    f"의미 규칙이 올바르지 않습니다: {room_booking_repo.file_path} 예약 {booking.id}의 room_id가 rooms.txt에 없습니다 ({booking.room_id})."
                )
        _validate_active_booking_overlap(
            room_bookings,
            resource_attr="room_id",
            active_statuses=active_room_statuses,
            resource_label="회의실",
            file_path=room_booking_repo.file_path,
        )

    if equipment_booking_repo:
        _ensure_unique(
            equipment_bookings,
            key_fn=lambda booking: booking.id,
            label="equipment booking id",
            file_path=equipment_booking_repo.file_path,
        )
        for booking in equipment_bookings:
            _validate_uuid4(
                booking.id,
                label="equipment booking id",
                file_path=equipment_booking_repo.file_path,
            )
            _validate_booking_order(booking, resource_label="장비", file_path=equipment_booking_repo.file_path)
            if booking.user_id not in user_ids:
                raise DataIntegrityError(
                    f"의미 규칙이 올바르지 않습니다: {equipment_booking_repo.file_path} 예약 {booking.id}의 username이 users.txt에 없습니다 ({booking.user_id})."
                )
            if booking.equipment_id not in equipment_ids:
                raise DataIntegrityError(
                    f"의미 규칙이 올바르지 않습니다: {equipment_booking_repo.file_path} 예약 {booking.id}의 serial_id가 equipments.txt에 없습니다 ({booking.equipment_id})."
                )
        _validate_active_booking_overlap(
            equipment_bookings,
            resource_attr="equipment_id",
            active_statuses=active_equipment_statuses,
            resource_label="장비",
            file_path=equipment_booking_repo.file_path,
        )

    if penalty_repo:
        _ensure_unique(
            penalties,
            key_fn=lambda penalty: penalty.id,
            label="penalty id",
            file_path=penalty_repo.file_path,
        )
        for penalty in penalties:
            _validate_uuid4(
                penalty.id,
                label="penalty id",
                file_path=penalty_repo.file_path,
            )
            if penalty.user_id not in user_ids:
                raise DataIntegrityError(
                    f"의미 규칙이 올바르지 않습니다: {penalty_repo.file_path} 패널티 {penalty.id}의 username이 users.txt에 없습니다 ({penalty.user_id})."
                )
            if penalty.points < 1:
                raise DataIntegrityError(
                    f"의미 규칙이 올바르지 않습니다: {penalty_repo.file_path} 패널티 {penalty.id}의 points는 1 이상이어야 합니다."
                )
            if penalty.related_type == "room_booking":
                if penalty.related_id not in room_booking_ids:
                    raise DataIntegrityError(
                        f"의미 규칙이 올바르지 않습니다: {penalty_repo.file_path} 패널티 {penalty.id}의 related_id가 room_bookings.txt에 없습니다 ({penalty.related_id})."
                    )
                related_booking = next(
                    (booking for booking in room_bookings if booking.id == penalty.related_id),
                    None,
                )
                if related_booking is None or related_booking.user_id != penalty.user_id:
                    raise DataIntegrityError(
                        f"의미 규칙이 올바르지 않습니다: {penalty_repo.file_path} 패널티 {penalty.id}의 관련 회의실 예약 사용자가 일치하지 않습니다."
                    )
            elif penalty.related_type == "equipment_booking":
                if penalty.related_id not in equipment_booking_ids:
                    raise DataIntegrityError(
                        f"의미 규칙이 올바르지 않습니다: {penalty_repo.file_path} 패널티 {penalty.id}의 related_id가 equipment_booking.txt에 없습니다 ({penalty.related_id})."
                    )
                related_booking = next(
                    (booking for booking in equipment_bookings if booking.id == penalty.related_id),
                    None,
                )
                if related_booking is None or related_booking.user_id != penalty.user_id:
                    raise DataIntegrityError(
                        f"의미 규칙이 올바르지 않습니다: {penalty_repo.file_path} 패널티 {penalty.id}의 관련 장비 예약 사용자가 일치하지 않습니다."
                    )
            else:
                raise DataIntegrityError(
                    f"의미 규칙이 올바르지 않습니다: {penalty_repo.file_path} 패널티 {penalty.id}의 related_type이 허용되지 않습니다 ({penalty.related_type})."
                )

    if audit_repo:
        _ensure_unique(
            audit_logs,
            key_fn=lambda log: log.id,
            label="audit log id",
            file_path=audit_repo.file_path,
        )
        for log in audit_logs:
            _validate_uuid4(
                log.id,
                label="audit log id",
                file_path=audit_repo.file_path,
            )
            if log.actor_id != "system" and log.actor_id not in user_ids:
                raise DataIntegrityError(
                    f"의미 규칙이 올바르지 않습니다: {audit_repo.file_path} 로그 {log.id}의 actor가 users.txt에 없습니다 ({log.actor_id})."
                )


class DataIntegrityError(RuntimeError):
    """데이터 파일 무결성 위반 또는 파일 접근 실패."""


def _ensure_file_exists(file_path, default_text=None):
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if not file_path.exists():
            if default_text is None:
                file_path.touch()
            else:
                file_path.write_text(default_text, encoding="utf-8")
        elif default_text is not None and not file_path.read_text(encoding="utf-8").strip():
            file_path.write_text(default_text, encoding="utf-8")
    except OSError as error:
        raise DataIntegrityError(
            f"필수 데이터 파일을 생성할 수 없습니다: {file_path} ({error})"
        ) from error


def _validate_clock_file(clock_file, clock_sentinel):
    _ensure_file_exists(clock_file, default_text=clock_sentinel)

    try:
        marker = clock_file.read_text(encoding="utf-8").strip() or clock_sentinel
    except OSError as error:
        raise DataIntegrityError(
            f"시계 파일을 읽을 수 없습니다: {clock_file} ({error})"
        ) from error

    if marker == clock_sentinel:
        return

    try:
        parsed = datetime.fromisoformat(marker)
    except ValueError as error:
        raise DataIntegrityError(
            f"시계 파일 형식이 올바르지 않습니다: {clock_file} ({marker})"
        ) from error

    normalized = parsed.replace(second=0, microsecond=0).isoformat(timespec="minutes")
    if marker != normalized:
        raise DataIntegrityError(
            f"시계 파일 형식이 올바르지 않습니다: {clock_file} ({marker})"
        )

    if (parsed.hour, parsed.minute) not in ALLOWED_CLOCK_SLOTS or parsed.second != 0 or parsed.microsecond != 0:
        raise DataIntegrityError(
            f"시계 파일 의미 규칙이 올바르지 않습니다: {clock_file} ({marker})"
        )


def validate_all_data_files(repositories=None, clock_file=None):
    """필수 데이터 파일 생성 및 전체 무결성 검증."""
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

    if repositories is None:
        config.ensure_data_dir()
        repositories = [
            UserRepository(file_path=config.USERS_FILE),
            RoomRepository(file_path=config.ROOMS_FILE),
            EquipmentAssetRepository(file_path=config.EQUIPMENTS_FILE),
            RoomBookingRepository(file_path=config.ROOM_BOOKINGS_FILE),
            EquipmentBookingRepository(file_path=config.EQUIPMENT_BOOKING_FILE),
            PenaltyRepository(file_path=config.PENALTIES_FILE),
            AuditLogRepository(file_path=config.AUDIT_LOG_FILE),
        ]
        clock_file = clock_file or config.CLOCK_FILE
    elif clock_file is None:
        first_repo = next((repo for repo in repositories if hasattr(repo, 'file_path')), None)
        if first_repo is None:
            raise DataIntegrityError('무결성 검증에 사용할 저장소 경로를 확인할 수 없습니다.')
        clock_file = first_repo.file_path.parent / 'clock.txt'

    _validate_clock_file(clock_file, config.CLOCK_SENTINEL)

    repository_map = {}
    record_map = {}
    for repository in repositories:
        _ensure_file_exists(repository.file_path)
        repository_map[type(repository)] = repository
        record_map[type(repository)] = repository.get_all()

    _validate_semantic_integrity(repository_map, record_map)
