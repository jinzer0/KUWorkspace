import json
from pathlib import Path

import pytest

from scripts import seed_data
from src import config
from src.domain.models import (
    RoomMaintenanceSchedule,
    WaitingListEntry,
)
from src.storage.file_lock import global_lock
from src.storage.integrity import DataIntegrityError, validate_all_data_files
from src.storage.jsonl_handler import encode_record
from src.storage.repositories import (
    EquipmentAssetRepository,
    EquipmentBookingRepository,
    RoomBookingRepository,
    RoomMaintenanceRepository,
    UserRepository,
    WaitingListRepository,
)


def test_old_schema_records_reload_and_write_canonical_phase_two_widths(temp_data_dir):
    config.USERS_FILE.write_text(
        encode_record(
            [
                "Student1",
                "pass123",
                "user",
                "0",
                "0",
                None,
                "2026-03-20T09:00",
                "2026-03-20T09:00",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config.EQUIPMENTS_FILE.write_text(
        encode_record(
            [
                "프로젝터",
                "projector",
                "PJ-001",
                "available",
                "HDMI포함",
                "2026-03-20T09:00",
                "2026-03-20T09:00",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config.ROOM_BOOKINGS_FILE.write_text(
        encode_record(
            [
                "room-booking-1",
                "student1",
                "회의실2A",
                "2027-06-15T11:00",
                "2027-06-15T12:00",
                "reserved",
                None,
                None,
                None,
                None,
                None,
                "2027-06-15T10:00",
                "2027-06-15T10:00",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config.EQUIPMENT_BOOKING_FILE.write_text(
        encode_record(
            [
                "equipment-booking-1",
                "student1",
                "PJ-001",
                "2026-04-10T09:00",
                "2026-04-10T18:00",
                "reserved",
                None,
                None,
                None,
                None,
                None,
                "2026-04-05T12:10",
                "2026-04-05T12:10",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config.ROOM_MAINTENANCE_FILE.write_text(
        encode_record(
            [
                "maintenance-1",
                "회의실2A",
                "2027-06-15T09:00",
                "2027-06-15T18:00",
                "정기 점검",
                "2027-06-01T09:00",
                "2027-06-01T09:00",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    user_repo = UserRepository(file_path=config.USERS_FILE)
    equipment_repo = EquipmentAssetRepository(file_path=config.EQUIPMENTS_FILE)
    room_booking_repo = RoomBookingRepository(file_path=config.ROOM_BOOKINGS_FILE)
    equipment_booking_repo = EquipmentBookingRepository(file_path=config.EQUIPMENT_BOOKING_FILE)
    maintenance_repo = RoomMaintenanceRepository(file_path=config.ROOM_MAINTENANCE_FILE)

    assert user_repo.get_all()[0].room_cancel_restricted_until is None
    assert equipment_repo.get_all()[0].future_status_changes == ""
    assert room_booking_repo.get_all()[0].memo == ""
    assert equipment_booking_repo.get_all()[0].group_id is None
    assert maintenance_repo.get_all()[0].status == "scheduled"
    assert maintenance_repo.get_all()[0].cancelled_at is None

    with global_lock():
        user_repo.save_all(user_repo.get_all())
        equipment_repo.save_all(equipment_repo.get_all())
        room_booking_repo.save_all(room_booking_repo.get_all())
        equipment_booking_repo.save_all(equipment_booking_repo.get_all())
        maintenance_repo.save_all(maintenance_repo.get_all())

    assert len(config.USERS_FILE.read_text(encoding="utf-8").strip().split("|")) == 10
    assert len(config.EQUIPMENTS_FILE.read_text(encoding="utf-8").strip().split("|")) == 8
    assert len(config.ROOM_BOOKINGS_FILE.read_text(encoding="utf-8").strip().split("|")) == 14
    assert len(config.EQUIPMENT_BOOKING_FILE.read_text(encoding="utf-8").strip().split("|")) == 15
    assert len(config.ROOM_MAINTENANCE_FILE.read_text(encoding="utf-8").strip().split("|")) == 8


def test_new_schema_records_reload_with_escape_empty_and_sentinel_values(temp_data_dir):
    config.ROOM_BOOKINGS_FILE.write_text(
        encode_record(
            [
                "room-booking-1",
                "student1",
                "회의실2A",
                "2027-06-15T11:00",
                "2027-06-15T12:00",
                "pending",
                None,
                None,
                None,
                None,
                None,
                "2027-06-15T10:00",
                "2027-06-15T10:00",
                "pipe|backslash\\memo",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config.EQUIPMENT_BOOKING_FILE.write_text(
        encode_record(
            [
                "equipment-booking-1",
                "student1",
                "PJ-001",
                "2026-04-10T09:00",
                "2026-04-10T18:00",
                "pending",
                None,
                None,
                None,
                None,
                None,
                "2026-04-05T12:10",
                "2026-04-05T12:10",
                None,
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    room_booking = RoomBookingRepository(file_path=config.ROOM_BOOKINGS_FILE).get_all()[0]
    equipment_booking = EquipmentBookingRepository(file_path=config.EQUIPMENT_BOOKING_FILE).get_all()[0]

    assert room_booking.memo == "pipe|backslash\\memo"
    assert equipment_booking.group_id is None
    assert equipment_booking.memo == ""


def test_empty_phase_two_foundation_files_are_valid(temp_data_dir):
    validate_all_data_files()

    assert RoomMaintenanceRepository(file_path=config.ROOM_MAINTENANCE_FILE).get_all() == []
    assert config.WAITLIST_FILE.exists()
    assert config.WAITLIST_FILE.read_text(encoding="utf-8") == ""


@pytest.mark.parametrize(
    ("file_path", "line"),
    [
        ("USERS_FILE", ["student1", "pass123"]),
        ("EQUIPMENTS_FILE", ["프로젝터", "projector"]),
        ("ROOM_BOOKINGS_FILE", ["room-booking-1", "student1"]),
        ("EQUIPMENT_BOOKING_FILE", ["equipment-booking-1", "student1"]),
        ("ROOM_MAINTENANCE_FILE", ["maintenance-1"]),
    ],
)
def test_validate_all_data_files_rejects_malformed_widths(temp_data_dir, file_path, line):
    getattr(config, file_path).write_text(encode_record(line) + "\n", encoding="utf-8")

    with pytest.raises(DataIntegrityError, match="데이터 파일 형식"):
        validate_all_data_files()


def test_room_maintenance_repository_reloads_written_schedule(temp_data_dir):
    repository = RoomMaintenanceRepository(file_path=config.ROOM_MAINTENANCE_FILE)
    schedule = RoomMaintenanceSchedule(
        id="maintenance-1",
        room_id="회의실2A",
        start_time="2027-06-15T09:00",
        end_time="2027-06-15T18:00",
        status="scheduled",
    )

    with global_lock():
        repository.add(schedule)

    reloaded = RoomMaintenanceRepository(file_path=config.ROOM_MAINTENANCE_FILE).get_all()

    assert len(reloaded) == 1
    assert reloaded[0].room_id == "회의실2A"
    assert reloaded[0].status == "scheduled"
    assert len(config.ROOM_MAINTENANCE_FILE.read_text(encoding="utf-8").strip().split("|")) == 8


def test_waiting_list_repository_reloads_written_entry(temp_data_dir):
    repository = WaitingListRepository(file_path=config.WAITLIST_FILE)
    entry = WaitingListEntry(
        id="waiting-1",
        username="Student1",
        related_type="room_booking",
        related_id="room-booking-1",
        user_count=3,
        created_at="2027-06-01T09:00",
        updated_at="2027-06-01T09:00",
    )

    with global_lock():
        repository.add(entry)

    reloaded = WaitingListRepository(file_path=config.WAITLIST_FILE).get_all()

    assert len(reloaded) == 1
    assert reloaded[0].id == "waiting-1"
    assert reloaded[0].username == "Student1"
    assert len(config.WAITLIST_FILE.read_text(encoding="utf-8").strip().split("|")) == 7


def test_legacy_json_future_status_rewrites_to_memo_format(temp_data_dir):
    config.EQUIPMENTS_FILE.write_text(
        encode_record(
            [
                "프로젝터",
                "projector",
                "PJ-001",
                "available",
                "HDMI포함",
                "2026-03-20T09:00",
                "2026-03-20T09:00",
                json.dumps(
                    [
                        {
                            "id": "schedule-1",
                            "start_time": "2026-04-01T09:00",
                            "status": "maintenance",
                            "state": "pending",
                        },
                        {
                            "id": "schedule-2",
                            "start_time": "2026-04-02T09:00",
                            "status": "maintenance",
                            "state": "started",
                        },
                    ],
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    repository = EquipmentAssetRepository(file_path=config.EQUIPMENTS_FILE)

    [asset] = repository.get_all()

    assert asset.future_status_changes == "2026-04-01, maintenance; 2026-04-02, maintenance"


def test_unsupported_legacy_json_future_status_raises_integrity_error(temp_data_dir):
    config.EQUIPMENTS_FILE.write_text(
        encode_record(
            [
                "프로젝터",
                "projector",
                "PJ-001",
                "available",
                "HDMI포함",
                "2026-03-20T09:00",
                "2026-03-20T09:00",
                '[{"start_time":"2026-04-01T09:00","status":"unknown","state":"pending"}]',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DataIntegrityError, match="equipments.txt"):
        EquipmentAssetRepository(file_path=config.EQUIPMENTS_FILE).get_all()


def test_seed_reset_creates_room_maintenance_and_waitlist_files(temp_data_dir, monkeypatch):
    current_files = [Path(path) for path in config.DATA_FILES if Path(path) != config.CLOCK_FILE]
    monkeypatch.setattr(seed_data, "CURRENT_DATA_FILES", current_files)
    monkeypatch.setattr(seed_data, "DATA_DIR", config.DATA_DIR)

    seed_data.reset_data_files()

    assert config.ROOM_MAINTENANCE_FILE.exists()
    assert config.WAITLIST_FILE.exists()
    assert config.CLOCK_FILE.read_text(encoding="utf-8").strip() == "0000-00-00T00:00"
