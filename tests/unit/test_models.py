"""
도메인 모델 직렬화 테스트

테스트 대상:
- User, Room, EquipmentAsset, RoomBooking, EquipmentBooking, Penalty, AuditLog
- to_dict/from_dict, to_json/from_json 라운드트립
- Enum 필드 직렬화/역직렬화
"""

import json
from datetime import datetime

import pytest

from src.domain.models import (
    User,
    UserRole,
    Room,
    EquipmentAsset,
    RoomBooking,
    EquipmentBooking,
    WaitingListEntry,
    RoomMaintenanceSchedule,
    Penalty,
    AuditLog,
    RoomBookingStatus,
    EquipmentBookingStatus,
    ResourceStatus,
    PenaltyReason,
    decode_future_status_changes,
    encode_future_status_changes,
    generate_id,
    now_iso,
    parse_datetime,
)


class TestUser:
    """User 모델 테스트"""

    def test_user_to_dict_roundtrip(self, user_factory):
        """User to_dict → from_dict 라운드트립"""
        user = user_factory(
            username="testuser",
            password="pass123",
            role=UserRole.USER,
            penalty_points=3,
            normal_use_streak=5,
            restriction_until="2024-06-20T10:00:00",
        )

        # to_dict → from_dict
        user_dict = user.to_dict()
        restored = User.from_dict(user_dict)

        assert restored.id == user.id
        assert restored.username == user.username
        assert restored.password == user.password
        assert restored.role == user.role
        assert restored.penalty_points == user.penalty_points
        assert restored.normal_use_streak == user.normal_use_streak
        assert restored.restriction_until == user.restriction_until

    def test_user_to_json_roundtrip(self, user_factory):
        """User to_json → from_json 라운드트립"""
        user = user_factory(role=UserRole.ADMIN, penalty_points=0)

        # to_json → from_json
        json_str = user.to_json()
        restored = User.from_json(json_str)

        assert restored.id == user.id
        assert restored.username == user.username
        assert restored.role == UserRole.ADMIN

    def test_user_role_enum_serialization(self, user_factory):
        """UserRole enum이 문자열로 직렬화되는지 확인"""
        user = user_factory(role=UserRole.ADMIN)

        d = user.to_dict()
        assert d["role"] == "admin"  # enum value

        # JSON으로도 확인
        json_str = user.to_json()
        parsed = json.loads(json_str)
        assert parsed["role"] == "admin"

    def test_user_record_keeps_first_phase_users_txt_width(self):
        record: list[str | None] = [
            "Student1",
            "pass123",
            "user",
            "3",
            "5",
            None,
            "2026-03-20T09:00",
            "2026-03-20T09:00",
        ]

        restored = User.from_record(record)

        assert len(record) == 8
        assert restored.id == "Student1"
        assert restored.username == "Student1"
        assert restored.password == "pass123"
        assert restored.role == UserRole.USER
        assert restored.penalty_points == 3
        assert restored.normal_use_streak == 5
        assert restored.restriction_until is None
        assert restored.room_cancel_restricted_until is None
        assert restored.equipment_cancel_restricted_until is None
        assert len(restored.to_record()) == 10

    def test_user_record_writes_phase_two_users_txt_width(self):
        user = User.from_record(
            [
                "Student1",
                "pass123",
                "user",
                "3",
                "5",
                None,
                "2026-03-22T09:00",
                None,
                "2026-03-20T09:00",
                "2026-03-20T09:00",
            ]
        )

        record = user.to_record()

        assert len(record) == 10
        assert record[6] == "2026-03-22T09:00"
        assert record[7] is None

    def test_inspect1_user_legacy_rows_remain_readable_but_new_rows_are_ten_fields(self):
        legacy = User.from_record(
            [
                "LegacyUser",
                "pass123",
                "user",
                "0",
                "0",
                None,
                "2026-03-20T09:00",
                "2026-03-20T09:00",
            ]
        )
        current = User(
            id="CurrentUser",
            username="CurrentUser",
            password="pass123",
            role=UserRole.USER,
        )

        assert legacy.username == "LegacyUser"
        assert len(current.to_record()) == 10

    def test_user_record_reads_legacy_lowercase_admin_for_seed_compatibility(self):
        user = User.from_record(
            [
                "admin",
                "admin123",
                "admin",
                "0",
                "0",
                None,
                "2026-03-20T09:00",
                "2026-03-20T09:00",
            ]
        )

        assert user.id == "admin"
        assert user.username == "admin"
        assert user.password == "admin123"
        assert user.role == UserRole.ADMIN
        assert user.to_record()[0] == "admin"

    def test_user_record_rejects_blank_or_whitespace_legacy_credentials(self):
        with pytest.raises(ValueError, match="사용자명"):
            User.from_record(
                [
                    " ",
                    "admin123",
                    "admin",
                    "0",
                    "0",
                    None,
                    "2026-03-20T09:00",
                    "2026-03-20T09:00",
                ]
            )

        with pytest.raises(ValueError, match="비밀번호"):
            User.from_record(
                [
                    "admin",
                    "bad pass",
                    "admin",
                    "0",
                    "0",
                    None,
                    "2026-03-20T09:00",
                    "2026-03-20T09:00",
                ]
            )

    def test_user_record_rejects_malformed_width(self):
        with pytest.raises(ValueError, match="8 or 10"):
            User.from_record(["student1", "pass123"])


class TestRoom:
    """Room 모델 테스트"""

    def test_room_to_dict_roundtrip(self, room_factory):
        """Room to_dict → from_dict 라운드트립"""
        room = room_factory(
            name="회의실4A",
            capacity=20,
            location="3층",
            status=ResourceStatus.MAINTENANCE,
            description="대형 회의실",
        )

        room_dict = room.to_dict()
        restored = Room.from_dict(room_dict)

        assert restored.id == room.id
        assert restored.name == room.name
        assert restored.capacity == room.capacity
        assert restored.location == room.location
        assert restored.status == ResourceStatus.MAINTENANCE
        assert restored.description == room.description

    def test_room_status_enum_serialization(self, room_factory):
        """ResourceStatus enum이 문자열로 직렬화되는지 확인"""
        room = room_factory(status=ResourceStatus.DISABLED)

        d = room.to_dict()
        assert d["status"] == "disabled"


class TestEquipmentAsset:
    """EquipmentAsset 모델 테스트"""

    def test_equipment_to_dict_roundtrip(self, equipment_factory):
        """EquipmentAsset to_dict → from_dict 라운드트립"""
        equipment = equipment_factory(
            name="노트북01",
            asset_type="노트북",
            serial_number="NB-123",
            status=ResourceStatus.AVAILABLE,
            description="Dell XPS 15",
        )

        eq_dict = equipment.to_dict()
        restored = EquipmentAsset.from_dict(eq_dict)

        assert restored.id == equipment.id
        assert restored.name == equipment.name
        assert restored.asset_type == equipment.asset_type
        assert restored.serial_number == equipment.serial_number
        assert restored.status == ResourceStatus.AVAILABLE

    def test_equipment_record_keeps_first_phase_equipments_txt_width(self):
        record: list[str | None] = [
            "프로젝터",
            "projector",
            "PJ-001",
            "available",
            "HDMI포함",
            "2026-03-20T09:00",
            "2026-03-20T10:00",
        ]

        restored = EquipmentAsset.from_record(record)

        assert len(record) == 7
        assert restored.id == "PJ-001"
        assert restored.name == "프로젝터"
        assert restored.asset_type == "projector"
        assert restored.serial_number == "PJ-001"
        assert restored.status == ResourceStatus.AVAILABLE
        assert restored.description == "HDMI포함"
        assert restored.future_status_changes == ""
        assert len(restored.to_record()) == 8

    def test_equipment_record_writes_phase_two_equipments_txt_width(self):
        encoded = encode_future_status_changes(
            [
                {
                    "id": "schedule-1",
                    "start_time": "2026-04-01T09:00",
                    "end_time": "2026-04-01T18:00",
                    "status": "maintenance",
                    "restore_status": "available",
                    "state": "pending",
                }
            ]
        )
        restored = EquipmentAsset.from_record(
            [
                "프로젝터",
                "projector",
                "PJ-001",
                "available",
                "HDMI포함",
                "2026-03-20T09:00",
                "2026-03-20T10:00",
                encoded,
            ]
        )

        record = restored.to_record()

        assert len(record) == 8
        assert decode_future_status_changes(record[7]) == decode_future_status_changes(encoded)

    def test_inspect1_equipment_legacy_rows_remain_readable_but_new_rows_are_eight_fields(self):
        legacy = EquipmentAsset.from_record(
            [
                "프로젝터",
                "projector",
                "PJ-001",
                "available",
                "HDMI포함",
                "2026-03-20T09:00",
                "2026-03-20T10:00",
            ]
        )
        current = EquipmentAsset(
            id="PJ-999",
            name="프로젝터",
            asset_type="projector",
            serial_number="PJ-999",
        )

        assert legacy.serial_number == "PJ-001"
        assert len(current.to_record()) == 8

    def test_plan0001_future_status_uses_memo_format(self):
        asset = EquipmentAsset.from_record(
            [
                "프로젝터",
                "projector",
                "PJ-001",
                "available",
                "HDMI포함",
                "2026-03-20T09:00",
                "2026-03-20T10:00",
                "2026-04-01, maintenance; 2026-04-02, maintenance",
            ]
        )

        assert asset.future_status_changes == "2026-04-01, maintenance; 2026-04-02, maintenance"
        assert asset.to_record()[7] == "2026-04-01, maintenance; 2026-04-02, maintenance"

    def test_equipment_future_status_changes_accepts_supported_legacy_json(self):
        encoded = '[{"id":"schedule-1","start_time":"2026-04-01T09:00:59","status":"maintenance","state":"started"}]'
        restored = EquipmentAsset.from_record(
            [
                "노트북",
                "laptop",
                "NB-999",
                "available",
                "pipe|\\-",
                "2026-03-20T09:00",
                "2026-03-20T10:00",
                encoded,
            ]
        )

        decoded = decode_future_status_changes(restored.to_record()[7])

        assert restored.to_record()[7] == "2026-04-01, maintenance"
        assert decoded[0]["id"] == "maintenance-2026-04-01"
        assert decoded[0]["start_time"] == "2026-04-01T09:00"
        assert decoded[0]["end_time"] == "2026-04-01T18:00"

    def test_equipment_future_status_changes_preserves_multiday_disabled_range(self):
        encoded = encode_future_status_changes(
            [
                {
                    "id": "schedule-1",
                    "start_time": "2026-04-01T09:00",
                    "end_time": "2026-04-03T18:00",
                    "status": "disabled",
                    "restore_status": "available",
                    "state": "pending",
                }
            ]
        )

        [decoded] = decode_future_status_changes(encoded)

        assert decoded["id"] == "schedule-1"
        assert decoded["start_time"] == "2026-04-01T09:00"
        assert decoded["end_time"] == "2026-04-03T18:00"
        assert decoded["status"] == "disabled"

    def test_equipment_future_status_changes_rejects_unknown_status(self):
        with pytest.raises(ValueError, match="not a valid"):
            encode_future_status_changes(
                [
                    {
                        "id": "schedule-1",
                        "start_time": "2026-04-01T09:00",
                        "end_time": "2026-04-01T18:00",
                        "status": "unknown",
                        "restore_status": "available",
                        "state": "pending",
                    }
                ]
            )

    def test_equipment_record_rejects_malformed_width(self):
        with pytest.raises(ValueError, match="7 or 8"):
            EquipmentAsset.from_record(["프로젝터", "projector"])


class TestRoomBooking:
    """RoomBooking 모델 테스트"""

    def test_room_booking_to_dict_roundtrip(self, room_booking_factory):
        """RoomBooking to_dict → from_dict 라운드트립"""
        booking = room_booking_factory(
            status=RoomBookingStatus.CHECKED_IN, checked_in_at="2024-06-15T10:00:00"
        )

        booking_dict = booking.to_dict()
        restored = RoomBooking.from_dict(booking_dict)

        assert restored.id == booking.id
        assert restored.user_id == booking.user_id
        assert restored.room_id == booking.room_id
        assert restored.start_time == booking.start_time
        assert restored.end_time == booking.end_time
        assert restored.status == RoomBookingStatus.CHECKED_IN
        assert restored.checked_in_at == booking.checked_in_at

    def test_room_booking_all_statuses(self, room_booking_factory):
        """모든 RoomBookingStatus enum 직렬화 확인"""
        for status in RoomBookingStatus:
            booking = room_booking_factory(status=status)
            d = booking.to_dict()
            assert d["status"] == status.value

            restored = RoomBooking.from_dict(d)
            assert restored.status == status

    def test_room_booking_record_keeps_first_phase_room_bookings_txt_width(self):
        record: list[str | None] = [
            "room-booking-1",
            "student1",
            "회의실2A",
            "2027-06-15T11:00",
            "2027-06-15T12:00",
            "completed",
            "2027-06-15T10:00",
            None,
            None,
            "2027-06-15T12:00",
            None,
            "2027-06-15T10:00",
            "2027-06-15T12:00",
        ]

        restored = RoomBooking.from_record(record)

        assert len(record) == 13
        assert restored.id == "room-booking-1"
        assert restored.user_id == "student1"
        assert restored.room_id == "회의실2A"
        assert restored.status == RoomBookingStatus.COMPLETED
        assert restored.checked_in_at == "2027-06-15T10:00"
        assert restored.requested_checkin_at is None
        assert restored.requested_checkout_at is None
        assert restored.completed_at == "2027-06-15T12:00"
        assert restored.cancelled_at is None
        assert restored.memo == ""
        assert len(restored.to_record()) == 14

    def test_room_booking_record_writes_phase_two_room_bookings_txt_width(self):
        record: list[str | None] = [
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
            "요청 메모",
        ]

        restored = RoomBooking.from_record(record)

        assert restored.status == RoomBookingStatus.PENDING
        assert restored.memo == "요청 메모"
        assert len(restored.to_record()) == 14

    def test_room_booking_record_rejects_malformed_width(self):
        with pytest.raises(ValueError, match="13 or 14"):
            RoomBooking.from_record(["booking-1", "student1"])


class TestEquipmentBooking:
    """EquipmentBooking 모델 테스트"""

    def test_equipment_booking_to_dict_roundtrip(self, equipment_booking_factory):
        """EquipmentBooking to_dict → from_dict 라운드트립"""
        booking = equipment_booking_factory(
            status=EquipmentBookingStatus.CHECKED_OUT,
            checked_out_at="2024-06-15T10:00:00",
        )

        booking_dict = booking.to_dict()
        restored = EquipmentBooking.from_dict(booking_dict)

        assert restored.id == booking.id
        assert restored.equipment_id == booking.equipment_id
        assert restored.status == EquipmentBookingStatus.CHECKED_OUT
        assert restored.checked_out_at == booking.checked_out_at

    def test_equipment_booking_all_statuses(self, equipment_booking_factory):
        """모든 EquipmentBookingStatus enum 직렬화 확인"""
        for status in EquipmentBookingStatus:
            booking = equipment_booking_factory(status=status)
            d = booking.to_dict()
            assert d["status"] == status.value

            restored = EquipmentBooking.from_dict(d)
            assert restored.status == status

    def test_equipment_booking_record_keeps_first_phase_equipment_booking_txt_width(self):
        record: list[str | None] = [
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

        restored = EquipmentBooking.from_record(record)

        assert len(record) == 13
        assert restored.id == "equipment-booking-1"
        assert restored.user_id == "student1"
        assert restored.equipment_id == "PJ-001"
        assert restored.status == EquipmentBookingStatus.RESERVED
        assert restored.checked_out_at is None
        assert restored.requested_pickup_at is None
        assert restored.requested_return_at is None
        assert restored.returned_at is None
        assert restored.cancelled_at is None
        assert restored.group_id is None
        assert restored.memo == ""
        assert len(restored.to_record()) == 15

    def test_equipment_booking_record_writes_phase_two_equipment_booking_txt_width(self):
        record: list[str | None] = [
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
            "group-1",
            "장비 메모",
        ]

        restored = EquipmentBooking.from_record(record)

        assert restored.status == EquipmentBookingStatus.PENDING
        assert restored.group_id == "group-1"
        assert restored.memo == "장비 메모"
        assert len(restored.to_record()) == 15

    def test_equipment_booking_record_rejects_malformed_width(self):
        with pytest.raises(ValueError, match="13 or 15"):
            EquipmentBooking.from_record(["booking-1", "student1"])


class TestRoomMaintenanceSchedule:
    def test_room_maintenance_record_roundtrip(self):
        schedule = RoomMaintenanceSchedule.from_record(
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

        record = schedule.to_record()

        assert schedule.id == "maintenance-1"
        assert schedule.room_id == "회의실2A"
        assert schedule.status == "scheduled"
        assert schedule.cancelled_at is None
        assert len(record) == 8
        assert record[4] == "scheduled"
        assert record[7] == "-"

    def test_plan0001_room_maintenance_record_has_status_and_cancelled_at(self):
        schedule = RoomMaintenanceSchedule.from_record(
            [
                "maintenance-1",
                "회의실2A",
                "2027-06-15T09:00",
                "2027-06-15T18:00",
                "scheduled",
                "2027-06-01T09:00",
                "2027-06-01T09:00",
                "-",
            ]
        )

        record = schedule.to_record()

        assert len(record) == 8
        assert record[4] in {"scheduled", "active", "completed", "cancelled"}
        assert record[7] == "-"
        assert getattr(schedule, "status") == "scheduled"
        assert getattr(schedule, "cancelled_at") is None

    def test_room_maintenance_record_rejects_malformed_width(self):
        with pytest.raises(ValueError, match="7 or 8"):
            RoomMaintenanceSchedule.from_record(["maintenance-1"])


class TestWaitingListEntry:
    def test_waiting_list_record_roundtrip(self):
        entry = WaitingListEntry.from_record(
            [
                "waiting-1",
                "Student1",
                "room_booking",
                "room-booking-1",
                "3",
                "2027-06-01T09:00",
                "2027-06-01T09:00",
            ]
        )

        assert entry.id == "waiting-1"
        assert entry.username == "Student1"
        assert entry.related_type == "room_booking"
        assert entry.user_count == 3
        assert entry.to_record() == [
            "waiting-1",
            "Student1",
            "room_booking",
            "room-booking-1",
            "3",
            "2027-06-01T09:00",
            "2027-06-01T09:00",
        ]

    def test_waiting_list_record_rejects_malformed_width(self):
        with pytest.raises(ValueError, match="7 fields"):
            WaitingListEntry.from_record(["waiting-1"])


class TestPenalty:
    """Penalty 모델 테스트"""

    def test_penalty_to_dict_roundtrip(self, penalty_factory):
        """Penalty to_dict → from_dict 라운드트립"""
        penalty = penalty_factory(
            reason=PenaltyReason.LATE_RETURN, points=2, memo="30분 지연"
        )

        penalty_dict = penalty.to_dict()
        restored = Penalty.from_dict(penalty_dict)

        assert restored.id == penalty.id
        assert restored.user_id == penalty.user_id
        assert restored.reason == PenaltyReason.LATE_RETURN
        assert restored.points == 2
        assert restored.memo == "30분 지연"

    def test_penalty_all_reasons(self, penalty_factory):
        """모든 PenaltyReason enum 직렬화 확인"""
        for reason in PenaltyReason:
            penalty = penalty_factory(reason=reason)
            d = penalty.to_dict()
            assert d["reason"] == reason.value

            restored = Penalty.from_dict(d)
            assert restored.reason == reason

    def test_penalty_record_sanitizes_newlines_and_truncates_memo(self, penalty_factory):
        penalty = penalty_factory(memo="첫줄\n둘째줄-" + "a" * 50)

        record = penalty.to_record()
        memo = record[6]

        assert memo is not None
        assert "\n" not in memo
        assert "\r" not in memo
        assert len(memo) == 20


class TestAuditLog:
    """AuditLog 모델 테스트"""

    def test_audit_log_to_dict_roundtrip(self):
        """AuditLog to_dict → from_dict 라운드트립"""
        log = AuditLog(
            id=generate_id(),
            actor_id="user-123",
            action="create_booking",
            target_type="room_booking",
            target_id="booking-456",
            details="회의실 A 예약",
        )

        log_dict = log.to_dict()
        restored = AuditLog.from_dict(log_dict)

        assert restored.id == log.id
        assert restored.actor_id == log.actor_id
        assert restored.action == log.action
        assert restored.target_type == log.target_type
        assert restored.target_id == log.target_id
        assert restored.details == log.details

    def test_audit_log_to_json_roundtrip(self):
        """AuditLog to_json → from_json 라운드트립"""
        log = AuditLog(
            id=generate_id(),
            actor_id="system",
            action="policy_review",
            target_type="room_booking",
            target_id="booking-789",
            details="정책 검토 기록",
        )

        json_str = log.to_json()
        restored = AuditLog.from_json(json_str)

        assert restored.id == log.id
        assert restored.actor_id == "system"
        assert restored.action == "policy_review"

    def test_audit_log_record_sanitizes_newlines_and_truncates_details(self):
        log = AuditLog(
            id=generate_id(),
            actor_id="system",
            action="policy_review",
            target_type="room_booking",
            target_id="booking-789",
            details="첫줄\r\n둘째줄-" + "b" * 50,
        )

        record = log.to_record()
        details = record[5]

        assert details is not None
        assert "\n" not in details
        assert "\r" not in details
        assert len(details) == 20


class TestHelperFunctions:
    """헬퍼 함수 테스트"""

    def test_generate_id_uniqueness(self):
        """generate_id()가 고유한 ID를 생성하는지 확인"""
        ids = {generate_id() for _ in range(100)}
        assert len(ids) == 100  # 모두 고유해야 함

    def test_now_iso_format(self):
        """now_iso()가 ISO 형식 문자열을 반환하는지 확인"""
        iso_str = now_iso()
        # ISO 형식으로 파싱 가능해야 함
        parsed = datetime.fromisoformat(iso_str)
        assert isinstance(parsed, datetime)

    def test_parse_datetime_valid(self):
        """parse_datetime()이 유효한 ISO 문자열을 파싱하는지 확인"""
        dt_str = "2024-06-15T10:30:00"
        result = parse_datetime(dt_str)

        assert isinstance(result, datetime)
        assert result.year == 2024
        assert result.month == 6
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30

    def test_parse_datetime_none(self):
        """parse_datetime(None)이 None을 반환하는지 확인"""
        result = parse_datetime(None)
        assert result is None
