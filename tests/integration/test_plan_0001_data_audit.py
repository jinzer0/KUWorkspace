"""Plan 0001 data-file audit and isolated seed compatibility tests."""

from datetime import datetime, timedelta
from importlib import import_module
from pathlib import Path

from src.config import CLOCK_SENTINEL, ensure_data_dir
from src.domain.models import (
    AuditLog,
    EquipmentAsset,
    EquipmentBooking,
    EquipmentBookingStatus,
    Penalty,
    PenaltyReason,
    ResourceStatus,
    Room,
    RoomBooking,
    RoomBookingStatus,
    RoomMaintenanceSchedule,
    User,
    UserRole,
    WaitingListEntry,
)
from src.storage.file_lock import global_lock
from src.storage.jsonl_handler import decode_record
from src.storage.repositories import (
    AuditLogRepository,
    EquipmentAssetRepository,
    EquipmentBookingRepository,
    PenaltyRepository,
    RoomBookingRepository,
    RoomMaintenanceRepository,
    RoomRepository,
    UserRepository,
    WaitingListRepository,
)


REQUIRED_FIELD_COUNTS = {
    "users.txt": 10,
    "rooms.txt": 7,
    "equipments.txt": 8,
    "room_bookings.txt": 14,
    "equipment_booking.txt": 15,
    "room_maintenance.txt": 8,
    "waiting_list.txt": 7,
    "penalties.txt": 9,
    "audit_log.txt": 8,
    "clock.txt": 1,
}


def _decoded_nonempty_rows(path):
    return [decode_record(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_plan0001_data_audit_required_files_and_exact_field_counts(temp_data_dir):
    ensure_data_dir()
    timestamp = datetime(2026, 6, 1, 9, 0).isoformat(timespec="minutes")
    with global_lock():
        UserRepository(temp_data_dir / "users.txt").add(
            User(id="Audituser1", username="Audituser1", password="pass1", role=UserRole.USER)
        )
        RoomRepository(temp_data_dir / "rooms.txt").add(
            Room(
                id="회의실1A",
                name="회의실1A",
                capacity=4,
                location="1층",
                status=ResourceStatus.AVAILABLE,
                description="회의실",
            )
        )
        EquipmentAssetRepository(temp_data_dir / "equipments.txt").add(
            EquipmentAsset(
                id="NB-001",
                name="노트북",
                asset_type="laptop",
                serial_number="NB-001",
                status=ResourceStatus.AVAILABLE,
                description="노트북",
                future_status_changes="2026-06-10, maintenance",
            )
        )
        RoomBookingRepository(temp_data_dir / "room_bookings.txt").add(
            RoomBooking(
                id="room-booking-1",
                user_id="Audituser1",
                room_id="회의실1A",
                start_time=timestamp,
                end_time=(datetime.fromisoformat(timestamp) + timedelta(hours=9)).isoformat(timespec="minutes"),
                status=RoomBookingStatus.RESERVED,
                memo="메모",
            )
        )
        EquipmentBookingRepository(temp_data_dir / "equipment_booking.txt").add(
            EquipmentBooking(
                id="equipment-booking-1",
                user_id="Audituser1",
                equipment_id="NB-001",
                start_time=timestamp,
                end_time=(datetime.fromisoformat(timestamp) + timedelta(hours=9)).isoformat(timespec="minutes"),
                status=EquipmentBookingStatus.RESERVED,
                group_id="group-1",
                memo="메모",
            )
        )
        RoomMaintenanceRepository(temp_data_dir / "room_maintenance.txt").add(
            RoomMaintenanceSchedule(
                id="maintenance-1",
                room_id="회의실1A",
                start_time=timestamp,
                end_time=(datetime.fromisoformat(timestamp) + timedelta(hours=9)).isoformat(timespec="minutes"),
                status="scheduled",
            )
        )
        WaitingListRepository(temp_data_dir / "waiting_list.txt").add(
            WaitingListEntry(
                id="waiting-1",
                username="Audituser1",
                related_type="room_booking",
                related_id="room-booking-1",
                user_count=2,
            )
        )
        PenaltyRepository(temp_data_dir / "penalties.txt").add(
            Penalty(
                id="penalty-1",
                user_id="Audituser1",
                reason=PenaltyReason.FREQUENT_CANCEL,
                points=1,
                related_type="room_booking",
                related_id="room-booking-1",
                memo="빈번취소",
            )
        )
        AuditLogRepository(temp_data_dir / "audit_log.txt").add(
            AuditLog(
                id="audit-1",
                actor_id="Audituser1",
                action="audit",
                target_type="system",
                target_id="data",
                details="필드점검",
            )
        )
    (temp_data_dir / "clock.txt").write_text(CLOCK_SENTINEL, encoding="utf-8")

    for file_name, field_count in REQUIRED_FIELD_COUNTS.items():
        path = temp_data_dir / file_name
        assert path.exists(), file_name
        rows = _decoded_nonempty_rows(path)
        assert rows, file_name
        assert all(len(row) == field_count for row in rows), file_name
    assert not (temp_data_dir / "waitlist.txt").exists()


def test_plan0001_data_audit_seed_data_isolated_legacy_admin_compatible(
    temp_data_dir,
    monkeypatch,
):
    import src.config as config

    seed_data = import_module("scripts.seed_data")
    monkeypatch.setattr(seed_data, "DATA_DIR", temp_data_dir)
    monkeypatch.setattr(seed_data, "CURRENT_DATA_FILES", list(config.DATA_FILES[:-1]))
    monkeypatch.setattr(seed_data, "LEGACY_DATA_FILES", [
        temp_data_dir / "equipment_assets.txt",
        temp_data_dir / "equipment_bookings.txt",
        temp_data_dir / "message.txt",
    ])
    monkeypatch.setattr(seed_data, "UserRepository", lambda: UserRepository(temp_data_dir / "users.txt"))
    monkeypatch.setattr(seed_data, "RoomRepository", lambda: RoomRepository(temp_data_dir / "rooms.txt"))
    monkeypatch.setattr(
        seed_data,
        "EquipmentAssetRepository",
        lambda: EquipmentAssetRepository(temp_data_dir / "equipments.txt"),
    )

    seed_data.seed(reset=True)

    user_repo = UserRepository(temp_data_dir / "users.txt")
    room_repo = RoomRepository(temp_data_dir / "rooms.txt")
    equipment_repo = EquipmentAssetRepository(temp_data_dir / "equipments.txt")
    admin = user_repo.get_by_username("admin")
    assert admin is not None
    assert admin.role == UserRole.ADMIN
    assert admin.password == "admin123"
    assert len(room_repo.get_all()) == 9
    assert len(equipment_repo.get_all()) == 12
    assert all((temp_data_dir / file_name).exists() for file_name in REQUIRED_FIELD_COUNTS)
    assert (temp_data_dir / "waiting_list.txt").exists()
    assert not (temp_data_dir / "waitlist.txt").exists()

    user_rows = _decoded_nonempty_rows(temp_data_dir / "users.txt")
    equipment_rows = _decoded_nonempty_rows(temp_data_dir / "equipments.txt")
    assert all(len(row) == 10 for row in user_rows)
    assert all(len(row) == 8 for row in equipment_rows)


def test_inspect1_seed_data_writes_current_user_and_equipment_schema_widths(
    temp_data_dir,
    monkeypatch,
):
    import src.config as config

    seed_data = import_module("scripts.seed_data")
    monkeypatch.setattr(seed_data, "DATA_DIR", temp_data_dir)
    monkeypatch.setattr(seed_data, "CURRENT_DATA_FILES", list(config.DATA_FILES[:-1]))
    monkeypatch.setattr(seed_data, "LEGACY_DATA_FILES", [])
    monkeypatch.setattr(seed_data, "UserRepository", lambda: UserRepository(temp_data_dir / "users.txt"))
    monkeypatch.setattr(seed_data, "RoomRepository", lambda: RoomRepository(temp_data_dir / "rooms.txt"))
    monkeypatch.setattr(
        seed_data,
        "EquipmentAssetRepository",
        lambda: EquipmentAssetRepository(temp_data_dir / "equipments.txt"),
    )

    seed_data.seed(reset=True)

    user_rows = _decoded_nonempty_rows(temp_data_dir / "users.txt")
    equipment_rows = _decoded_nonempty_rows(temp_data_dir / "equipments.txt")
    assert user_rows
    assert equipment_rows
    assert all(len(row) == 10 for row in user_rows)
    assert all(len(row) == 8 for row in equipment_rows)


def test_inspect1_checked_in_sample_data_uses_current_user_and_equipment_widths():
    repo_root = Path(__file__).resolve().parents[2]
    user_rows = _decoded_nonempty_rows(repo_root / "data" / "users.txt")
    equipment_rows = _decoded_nonempty_rows(repo_root / "data" / "equipments.txt")

    assert user_rows
    assert equipment_rows
    assert all(len(row) == 10 for row in user_rows)
    assert all(len(row) == 8 for row in equipment_rows)
