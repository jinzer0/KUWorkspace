"""
도메인 모델 직렬화 테스트

테스트 대상:
- User, Room, EquipmentAsset, RoomBooking, EquipmentBooking, Penalty, AuditLog
- to_dict/from_dict, to_json/from_json 라운드트립
- Enum 필드 직렬화/역직렬화
"""

import json
from datetime import datetime

from src.domain.models import (
    User,
    UserRole,
    Room,
    EquipmentAsset,
    RoomBooking,
    EquipmentBooking,
    Penalty,
    AuditLog,
    RoomBookingStatus,
    EquipmentBookingStatus,
    ResourceStatus,
    PenaltyReason,
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
