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
    Message,
    MessageType,
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
            name="회의실 A",
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
            name="노트북 01",
            asset_type="노트북",
            serial_number="SN-12345",
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
            action="auto_no_show",
            target_type="room_booking",
            target_id="booking-789",
            details="자동 노쇼 판정",
        )

        json_str = log.to_json()
        restored = AuditLog.from_json(json_str)

        assert restored.id == log.id
        assert restored.actor_id == "system"
        assert restored.action == "auto_no_show"


class TestMessage:
    """Message 모델 테스트"""

    def test_message_to_dict_roundtrip(self):
        """Message to_dict → from_dict 라운드트립"""
        message = Message(
            id=generate_id(),
            user_id="user-123",
            created_at=now_iso(),
            type=MessageType.INQUIRY,
            content="이것은 문의입니다",
        )

        msg_dict = message.to_dict()
        restored = Message.from_dict(msg_dict)

        assert restored.id == message.id
        assert restored.user_id == message.user_id
        assert restored.created_at == message.created_at
        assert restored.type == MessageType.INQUIRY
        assert restored.content == message.content

    def test_message_to_json_roundtrip(self):
        """Message to_json → from_json 라운드트립"""
        message = Message(
            id=generate_id(),
            user_id="user-456",
            created_at=now_iso(),
            type=MessageType.REPORT,
            content="이것은 신고입니다",
        )

        json_str = message.to_json()
        restored = Message.from_json(json_str)

        assert restored.id == message.id
        assert restored.user_id == message.user_id
        assert restored.type == MessageType.REPORT
        assert restored.content == message.content

    def test_message_type_enum_serialization_inquiry(self):
        """MessageType.INQUIRY가 inquiry로 직렬화되는지 확인"""
        message = Message(
            id=generate_id(),
            user_id="user-789",
            created_at=now_iso(),
            type=MessageType.INQUIRY,
            content="content",
        )

        d = message.to_dict()
        assert d["type"] == "inquiry"

        json_str = message.to_json()
        parsed = json.loads(json_str)
        assert parsed["type"] == "inquiry"

    def test_message_type_enum_serialization_report(self):
        """MessageType.REPORT가 report로 직렬화되는지 확인"""
        message = Message(
            id=generate_id(),
            user_id="user-789",
            created_at=now_iso(),
            type=MessageType.REPORT,
            content="content",
        )

        d = message.to_dict()
        assert d["type"] == "report"

        json_str = message.to_json()
        parsed = json.loads(json_str)
        assert parsed["type"] == "report"

    def test_message_all_required_fields_preserved(self):
        """Message가 모든 필수 필드를 보존하는지 확인"""
        msg_id = generate_id()
        user_id = "user-xyz"
        created_at = now_iso()
        content = "test content 123"

        message = Message(
            id=msg_id,
            user_id=user_id,
            created_at=created_at,
            type=MessageType.INQUIRY,
            content=content,
        )

        d = message.to_dict()
        assert set(d.keys()) == {"id", "user_id", "created_at", "type", "content"}

        restored = Message.from_dict(d)
        assert restored.id == msg_id
        assert restored.user_id == user_id
        assert restored.created_at == created_at
        assert restored.content == content

    def test_message_id_default_is_generated(self):
        """Message의 id가 기본값으로 생성되는지 확인"""
        message = Message(
            user_id="user-default-test",
            type=MessageType.INQUIRY,
            content="testing defaults",
        )

        assert message.id is not None
        assert len(message.id) > 0
        assert isinstance(message.id, str)

    def test_message_created_at_default_is_generated(self):
        """Message의 created_at이 기본값으로 생성되는지 확인"""
        message = Message(
            user_id="user-time-test",
            type=MessageType.REPORT,
            content="testing time default",
        )

        assert message.created_at is not None
        assert len(message.created_at) > 0
        # Should be valid ISO format
        parsed = datetime.fromisoformat(message.created_at)
        assert isinstance(parsed, datetime)

    def test_message_without_id_and_created_at_creates_unique_records(self):
        """id와 created_at 기본값을 사용한 Message 생성이 고유 레코드를 만드는지 확인"""
        msg1 = Message(
            user_id="user-1",
            type=MessageType.INQUIRY,
            content="first",
        )
        msg2 = Message(
            user_id="user-2",
            type=MessageType.REPORT,
            content="second",
        )

        assert msg1.id != msg2.id
        # created_at might be the same or very close, so just check they exist
        assert msg1.created_at is not None
        assert msg2.created_at is not None


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
