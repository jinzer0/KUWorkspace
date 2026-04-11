"""
도메인 모델 정의 (Dataclasses + Enums)
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional, List
import uuid
import json

from src.runtime_clock import get_current_time
from src.domain.field_rules import (
    validate_username_text,
    validate_password_text,
    validate_room_name,
    validate_room_capacity,
    validate_room_location,
    validate_room_description,
    validate_equipment_name,
    validate_equipment_asset_type,
    validate_equipment_serial,
    validate_equipment_description,
)

# ===== Enums =====


class UserRole(str, Enum):
    """사용자 역할"""

    USER = "user"
    ADMIN = "admin"


class ResourceStatus(str, Enum):
    """회의실/장비 운영 상태"""

    AVAILABLE = "available"
    MAINTENANCE = "maintenance"
    DISABLED = "disabled"


class RoomBookingStatus(str, Enum):
    """회의실 예약 상태"""

    RESERVED = "reserved"
    CHECKIN_REQUESTED = "checkin_requested"
    CHECKED_IN = "checked_in"
    CHECKOUT_REQUESTED = "checkout_requested"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ADMIN_CANCELLED = "admin_cancelled"


class EquipmentBookingStatus(str, Enum):
    """장비 예약 상태"""

    RESERVED = "reserved"
    PICKUP_REQUESTED = "pickup_requested"
    CHECKED_OUT = "checked_out"
    RETURN_REQUESTED = "return_requested"
    RETURNED = "returned"
    CANCELLED = "cancelled"
    ADMIN_CANCELLED = "admin_cancelled"


class PenaltyReason(str, Enum):
    """패널티 사유"""

    LATE_CANCEL = "late_cancel"
    LATE_RETURN = "late_return"
    DAMAGE = "damage"
    CONTAMINATION = "contamination"
    OTHER = "other"


# ===== Helper Functions =====


def generate_id() -> str:
    """UUID 생성"""
    return str(uuid.uuid4())


def now_iso() -> str:
    """현재 시각 ISO 형식 문자열"""
    return get_current_time().isoformat()


def parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """ISO 문자열을 datetime으로 변환"""
    if dt_str is None:
        return None
    return datetime.fromisoformat(dt_str)


def normalize_datetime_string(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(value)
        return dt.replace(second=0, microsecond=0).isoformat(timespec="minutes")
    except ValueError:
        return value


def normalize_persisted_text(value: Optional[str], max_length: int = 20) -> str:
    if value is None:
        return ""
    return value.replace("\r", " ").replace("\n", " ")[:max_length]


# ===== Dataclasses =====


@dataclass
class User:
    """사용자 계정"""

    id: str
    username: str
    password: str  # 평문 저장 (과제 요구사항)
    role: UserRole
    penalty_points: int = 0
    normal_use_streak: int = 0
    restriction_until: Optional[str] = None  # ISO datetime or None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        """딕셔너리 변환"""
        d = asdict(self)
        d["role"] = self.role.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "User":
        """딕셔너리에서 생성"""
        data = data.copy()
        data["role"] = UserRole(data["role"])
        return cls(**data)

    def to_json(self) -> str:
        """JSON 문자열 변환"""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "User":
        """JSON 문자열에서 생성"""
        return cls.from_dict(json.loads(json_str))

    def to_record(self) -> List[Optional[str]]:
        validate_username_text(self.username)
        validate_password_text(self.password)
        return [
            self.username,
            self.password,
            self.role.value,
            str(self.penalty_points),
            str(self.normal_use_streak),
            normalize_datetime_string(self.restriction_until),
            normalize_datetime_string(self.created_at),
            normalize_datetime_string(self.updated_at),
        ]

    @classmethod
    def from_record(cls, record: List[Optional[str]]) -> "User":
        if len(record) == 8:
            user_id = record[0] or ""
            username, password, role, points, streak, restriction_until, created_at, updated_at = record
            if not user_id:
                user_id = username or ""
        else:
            user_id, username, password, role, points, streak, restriction_until, created_at, updated_at = record
        user_key = username or user_id or ""
        validate_username_text(user_key)
        validate_password_text(password or "")
        return cls(
            id=user_id or user_key,
            username=user_key,
            password=password or "",
            role=UserRole(role),
            penalty_points=int(points or "0"),
            normal_use_streak=int(streak or "0"),
            restriction_until=normalize_datetime_string(restriction_until),
            created_at=normalize_datetime_string(created_at) or now_iso(),
            updated_at=normalize_datetime_string(updated_at) or now_iso(),
        )


@dataclass
class Room:
    """회의실"""

    id: str
    name: str
    capacity: int
    location: str
    status: ResourceStatus = ResourceStatus.AVAILABLE
    description: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Room":
        data = data.copy()
        data["status"] = ResourceStatus(data["status"])
        return cls(**data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "Room":
        return cls.from_dict(json.loads(json_str))

    def to_record(self) -> List[Optional[str]]:
        validate_room_name(self.name)
        validate_room_capacity(self.capacity)
        validate_room_location(self.location)
        validate_room_description(self.description)
        return [
            self.name,
            str(self.capacity),
            self.location,
            self.status.value,
            self.description,
            normalize_datetime_string(self.created_at),
            normalize_datetime_string(self.updated_at),
        ]

    @classmethod
    def from_record(cls, record: List[Optional[str]]) -> "Room":
        if len(record) == 7:
            room_id = record[0] or ""
            name, capacity, location, status, description, created_at, updated_at = record
            if not room_id:
                room_id = name or ""
        else:
            room_id, name, capacity, location, status, description, created_at, updated_at = record
        room_key = name or room_id or ""
        validate_room_name(room_key)
        validate_room_capacity(int(capacity or "0"))
        validate_room_location(location or "")
        validate_room_description(description or "")
        return cls(
            id=room_id or room_key,
            name=room_key,
            capacity=int(capacity or "0"),
            location=location or "",
            status=ResourceStatus(status),
            description=description or "",
            created_at=normalize_datetime_string(created_at) or now_iso(),
            updated_at=normalize_datetime_string(updated_at) or now_iso(),
        )


@dataclass
class EquipmentAsset:
    """장비 자산 (개별 자산 단위 관리)"""

    id: str
    name: str
    asset_type: str  # 장비 종류 (예: 프로젝터, 노트북 등)
    serial_number: str
    status: ResourceStatus = ResourceStatus.AVAILABLE
    description: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "EquipmentAsset":
        data = data.copy()
        data["status"] = ResourceStatus(data["status"])
        return cls(**data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "EquipmentAsset":
        return cls.from_dict(json.loads(json_str))

    def to_record(self) -> List[Optional[str]]:
        validate_equipment_name(self.name)
        validate_equipment_asset_type(self.asset_type)
        validate_equipment_serial(self.serial_number)
        validate_equipment_description(self.description)
        return [
            self.name,
            self.asset_type,
            self.serial_number,
            self.status.value,
            self.description,
            normalize_datetime_string(self.created_at),
            normalize_datetime_string(self.updated_at),
        ]

    @classmethod
    def from_record(cls, record: List[Optional[str]]) -> "EquipmentAsset":
        if len(record) == 7:
            equipment_id = record[2] or ""
            name, asset_type, serial_number, status, description, created_at, updated_at = record
            if not equipment_id:
                equipment_id = serial_number or ""
        else:
            equipment_id, name, asset_type, serial_number, status, description, created_at, updated_at = record
        serial_key = serial_number or equipment_id or ""
        validate_equipment_name(name or "")
        validate_equipment_asset_type(asset_type or "")
        validate_equipment_serial(serial_key)
        validate_equipment_description(description or "")
        return cls(
            id=equipment_id or serial_key,
            name=name or "",
            asset_type=asset_type or "",
            serial_number=serial_key,
            status=ResourceStatus(status),
            description=description or "",
            created_at=normalize_datetime_string(created_at) or now_iso(),
            updated_at=normalize_datetime_string(updated_at) or now_iso(),
        )


@dataclass
class RoomBooking:
    """회의실 예약"""

    id: str
    user_id: str
    room_id: str
    start_time: str  # ISO datetime
    end_time: str  # ISO datetime
    status: RoomBookingStatus = RoomBookingStatus.RESERVED
    checked_in_at: Optional[str] = None
    requested_checkin_at: Optional[str] = None
    requested_checkout_at: Optional[str] = None
    completed_at: Optional[str] = None
    cancelled_at: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "RoomBooking":
        data = data.copy()
        data["status"] = RoomBookingStatus(data["status"])
        return cls(**data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "RoomBooking":
        return cls.from_dict(json.loads(json_str))

    def to_record(self) -> List[Optional[str]]:
        return [
            self.id,
            self.user_id,
            self.room_id,
            normalize_datetime_string(self.start_time),
            normalize_datetime_string(self.end_time),
            self.status.value,
            normalize_datetime_string(self.checked_in_at),
            normalize_datetime_string(self.requested_checkin_at),
            normalize_datetime_string(self.requested_checkout_at),
            normalize_datetime_string(self.completed_at),
            normalize_datetime_string(self.cancelled_at),
            normalize_datetime_string(self.created_at),
            normalize_datetime_string(self.updated_at),
        ]

    @classmethod
    def from_record(cls, record: List[Optional[str]]) -> "RoomBooking":
        (
            booking_id,
            user_id,
            room_id,
            start_time,
            end_time,
            status,
            checked_in_at,
            requested_checkin_at,
            requested_checkout_at,
            completed_at,
            cancelled_at,
            created_at,
            updated_at,
        ) = record
        return cls(
            id=booking_id or generate_id(),
            user_id=user_id or "",
            room_id=room_id or "",
            start_time=normalize_datetime_string(start_time) or now_iso(),
            end_time=normalize_datetime_string(end_time) or now_iso(),
            status=RoomBookingStatus(status),
            checked_in_at=normalize_datetime_string(checked_in_at),
            requested_checkin_at=normalize_datetime_string(requested_checkin_at),
            requested_checkout_at=normalize_datetime_string(requested_checkout_at),
            completed_at=normalize_datetime_string(completed_at),
            cancelled_at=normalize_datetime_string(cancelled_at),
            created_at=normalize_datetime_string(created_at) or now_iso(),
            updated_at=normalize_datetime_string(updated_at) or now_iso(),
        )


@dataclass
class EquipmentBooking:
    """장비 예약"""

    id: str
    user_id: str
    equipment_id: str
    start_time: str  # ISO datetime
    end_time: str  # ISO datetime
    status: EquipmentBookingStatus = EquipmentBookingStatus.RESERVED
    checked_out_at: Optional[str] = None
    requested_pickup_at: Optional[str] = None
    requested_return_at: Optional[str] = None
    returned_at: Optional[str] = None
    cancelled_at: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "EquipmentBooking":
        data = data.copy()
        data["status"] = EquipmentBookingStatus(data["status"])
        return cls(**data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "EquipmentBooking":
        return cls.from_dict(json.loads(json_str))

    def to_record(self) -> List[Optional[str]]:
        return [
            self.id,
            self.user_id,
            self.equipment_id,
            normalize_datetime_string(self.start_time),
            normalize_datetime_string(self.end_time),
            self.status.value,
            normalize_datetime_string(self.checked_out_at),
            normalize_datetime_string(self.requested_pickup_at),
            normalize_datetime_string(self.requested_return_at),
            normalize_datetime_string(self.returned_at),
            normalize_datetime_string(self.cancelled_at),
            normalize_datetime_string(self.created_at),
            normalize_datetime_string(self.updated_at),
        ]

    @classmethod
    def from_record(cls, record: List[Optional[str]]) -> "EquipmentBooking":
        (
            booking_id,
            user_id,
            equipment_id,
            start_time,
            end_time,
            status,
            checked_out_at,
            requested_pickup_at,
            requested_return_at,
            returned_at,
            cancelled_at,
            created_at,
            updated_at,
        ) = record
        return cls(
            id=booking_id or generate_id(),
            user_id=user_id or "",
            equipment_id=equipment_id or "",
            start_time=normalize_datetime_string(start_time) or now_iso(),
            end_time=normalize_datetime_string(end_time) or now_iso(),
            status=EquipmentBookingStatus(status),
            checked_out_at=normalize_datetime_string(checked_out_at),
            requested_pickup_at=normalize_datetime_string(requested_pickup_at),
            requested_return_at=normalize_datetime_string(requested_return_at),
            returned_at=normalize_datetime_string(returned_at),
            cancelled_at=normalize_datetime_string(cancelled_at),
            created_at=normalize_datetime_string(created_at) or now_iso(),
            updated_at=normalize_datetime_string(updated_at) or now_iso(),
        )


@dataclass
class Penalty:
    """패널티 기록 (append-only)"""

    id: str
    user_id: str
    reason: PenaltyReason
    points: int
    related_type: str  # 'room_booking' or 'equipment_booking'
    related_id: str
    memo: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["reason"] = self.reason.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Penalty":
        data = data.copy()
        data["reason"] = PenaltyReason(data["reason"])
        return cls(**data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "Penalty":
        return cls.from_dict(json.loads(json_str))

    def to_record(self) -> List[Optional[str]]:
        return [
            self.id,
            self.user_id,
            self.reason.value,
            str(self.points),
            self.related_type,
            self.related_id,
            normalize_persisted_text(self.memo),
            normalize_datetime_string(self.created_at),
            normalize_datetime_string(self.updated_at),
        ]

    @classmethod
    def from_record(cls, record: List[Optional[str]]) -> "Penalty":
        penalty_id, user_id, reason, points, related_type, related_id, memo, created_at, updated_at = record
        return cls(
            id=penalty_id or generate_id(),
            user_id=user_id or "",
            reason=PenaltyReason(reason),
            points=int(points or "0"),
            related_type=related_type or "",
            related_id=related_id or "",
            memo=normalize_persisted_text(memo),
            created_at=normalize_datetime_string(created_at) or now_iso(),
            updated_at=normalize_datetime_string(updated_at),
        )


@dataclass
class AuditLog:
    """감사 로그 (append-only)"""

    id: str
    actor_id: str  # 수행자 ID (시스템인 경우 'system')
    action: str  # 수행한 작업
    target_type: str  # 대상 유형
    target_id: str  # 대상 ID
    details: str = ""  # 추가 정보
    created_at: str = field(default_factory=now_iso)
    updated_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AuditLog":
        return cls(**data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "AuditLog":
        return cls.from_dict(json.loads(json_str))

    def to_record(self) -> List[Optional[str]]:
        return [
            self.id,
            self.actor_id,
            self.action,
            self.target_type,
            self.target_id,
            normalize_persisted_text(self.details),
            normalize_datetime_string(self.created_at),
            normalize_datetime_string(self.updated_at),
        ]

    @classmethod
    def from_record(cls, record: List[Optional[str]]) -> "AuditLog":
        log_id, actor_id, action, target_type, target_id, details, created_at, updated_at = record
        return cls(
            id=log_id or generate_id(),
            actor_id=actor_id or "",
            action=action or "",
            target_type=target_type or "",
            target_id=target_id or "",
            details=normalize_persisted_text(details),
            created_at=normalize_datetime_string(created_at) or now_iso(),
            updated_at=normalize_datetime_string(updated_at),
        )
