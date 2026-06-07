"""
도메인 모델 정의 (Dataclasses + Enums)
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Optional, List
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

    PENDING = "pending"
    RESERVED = "reserved"
    CHECKIN_REQUESTED = "checkin_requested"
    CHECKED_IN = "checked_in"
    CHECKOUT_REQUESTED = "checkout_requested"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ADMIN_CANCELLED = "admin_cancelled"


class EquipmentBookingStatus(str, Enum):
    """장비 예약 상태"""

    PENDING = "pending"
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
    FREQUENT_CANCEL = "frequent_cancel"
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


def normalize_datetime_string(
    value: Optional[str],
    *,
    strict: bool = False,
    field_name: str = "datetime",
) -> Optional[str]:
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(value)
        return dt.replace(second=0, microsecond=0).isoformat(timespec="minutes")
    except ValueError as error:
        if strict:
            raise ValueError(f"{field_name} 형식이 올바르지 않습니다: {value}") from error
        return value


def normalize_persisted_text(value: Optional[str], max_length: int = 20) -> str:
    if value is None:
        return ""
    return value.replace("\r", " ").replace("\n", " ")[:max_length]


def _normalize_future_status_item(item: dict[str, Any]) -> dict[str, str]:
    schedule_id = str(item.get("id") or generate_id())
    start_time = normalize_datetime_string(
        item.get("start_time"), strict=True, field_name="future_status_start_time"
    )
    end_time = normalize_datetime_string(
        item.get("end_time"), strict=True, field_name="future_status_end_time"
    )
    if start_time is None or end_time is None:
        raise ValueError("future status schedule requires start_time and end_time")
    if datetime.fromisoformat(start_time) >= datetime.fromisoformat(end_time):
        raise ValueError("future status schedule start_time must be before end_time")

    target_status = ResourceStatus(item.get("status"))
    restore_status = ResourceStatus(item.get("restore_status", ResourceStatus.AVAILABLE.value))
    state = str(item.get("state", "pending"))
    if state not in {"pending", "started", "completed", "cancelled"}:
        raise ValueError("future status schedule state is invalid")

    normalized = {
        "id": schedule_id,
        "start_time": start_time,
        "end_time": end_time,
        "status": target_status.value,
        "restore_status": restore_status.value,
        "state": state,
    }
    if item.get("applied_start_at"):
        normalized["applied_start_at"] = normalize_datetime_string(
            item.get("applied_start_at"), strict=True, field_name="applied_start_at"
        ) or ""
    if item.get("applied_end_at"):
        normalized["applied_end_at"] = normalize_datetime_string(
            item.get("applied_end_at"), strict=True, field_name="applied_end_at"
        ) or ""
    if item.get("cancelled_at"):
        normalized["cancelled_at"] = normalize_datetime_string(
            item.get("cancelled_at"), strict=True, field_name="cancelled_at"
        ) or ""
    return normalized


def decode_future_status_changes(value: Optional[str]) -> list[dict[str, str]]:
    if not value:
        return []
    try:
        raw_items = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError("future_status_changes must be canonical JSON") from error
    if not isinstance(raw_items, list):
        raise ValueError("future_status_changes must be a list")
    normalized = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise ValueError("future_status_changes items must be objects")
        normalized.append(_normalize_future_status_item(raw_item))
    return sorted(normalized, key=lambda item: (item["start_time"], item["end_time"], item["id"]))


def encode_future_status_changes(items: list[dict[str, Any]]) -> str:
    normalized = [_normalize_future_status_item(item) for item in items]
    normalized.sort(key=lambda item: (item["start_time"], item["end_time"], item["id"]))
    if not normalized:
        return ""
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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
    room_cancel_restricted_until: Optional[str] = None
    equipment_cancel_restricted_until: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        """딕셔너리 변환"""
        d = asdict(self)
        d["role"] = self.role.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "User":
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
            normalize_datetime_string(self.room_cancel_restricted_until),
            normalize_datetime_string(self.equipment_cancel_restricted_until),
            normalize_datetime_string(self.created_at),
            normalize_datetime_string(self.updated_at),
        ]

    @classmethod
    def from_record(cls, record: List[Optional[str]]) -> "User":
        if len(record) == 8:
            username, password, role, points, streak, restriction_until, created_at, updated_at = record
            room_cancel_restricted_until = None
            equipment_cancel_restricted_until = None
        elif len(record) == 10:
            (
                username,
                password,
                role,
                points,
                streak,
                restriction_until,
                room_cancel_restricted_until,
                equipment_cancel_restricted_until,
                created_at,
                updated_at,
            ) = record
        else:
            raise ValueError("users.txt record must contain 8 or 10 fields")
        user_key = username or ""
        validate_username_text(user_key)
        validate_password_text(password or "")
        return cls(
            id=user_key,
            username=user_key,
            password=password or "",
            role=UserRole(role),
            penalty_points=int(points or "0"),
            normal_use_streak=int(streak or "0"),
            restriction_until=normalize_datetime_string(
                restriction_until,
                strict=True,
                field_name="restriction_until",
            ),
            room_cancel_restricted_until=normalize_datetime_string(
                room_cancel_restricted_until,
                strict=True,
                field_name="room_cancel_restricted_until",
            ),
            equipment_cancel_restricted_until=normalize_datetime_string(
                equipment_cancel_restricted_until,
                strict=True,
                field_name="equipment_cancel_restricted_until",
            ),
            created_at=normalize_datetime_string(created_at, strict=True, field_name="created_at") or now_iso(),
            updated_at=normalize_datetime_string(updated_at, strict=True, field_name="updated_at") or now_iso(),
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

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Room":
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
            created_at=normalize_datetime_string(created_at, strict=True, field_name="created_at") or now_iso(),
            updated_at=normalize_datetime_string(updated_at, strict=True, field_name="updated_at") or now_iso(),
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
    future_status_changes: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EquipmentAsset":
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
            encode_future_status_changes(
                decode_future_status_changes(self.future_status_changes)
            ),
        ]

    @classmethod
    def from_record(cls, record: List[Optional[str]]) -> "EquipmentAsset":
        if len(record) == 7:
            equipment_id = record[2] or ""
            name, asset_type, serial_number, status, description, created_at, updated_at = record
            if not equipment_id:
                equipment_id = serial_number or ""
            future_status_changes = ""
        elif len(record) == 8:
            name, asset_type, serial_number, status, description, created_at, updated_at, future_status_changes = record
            equipment_id = serial_number or ""
        else:
            raise ValueError("equipments.txt record must contain 7 or 8 fields")
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
            future_status_changes=encode_future_status_changes(
                decode_future_status_changes(future_status_changes)
            ),
            created_at=normalize_datetime_string(created_at, strict=True, field_name="created_at") or now_iso(),
            updated_at=normalize_datetime_string(updated_at, strict=True, field_name="updated_at") or now_iso(),
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
    memo: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RoomBooking":
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
            normalize_persisted_text(self.memo),
        ]

    @classmethod
    def from_record(cls, record: List[Optional[str]]) -> "RoomBooking":
        if len(record) == 13:
            memo = ""
        elif len(record) == 14:
            memo = record[13] or ""
            record = record[:13]
        else:
            raise ValueError("room_bookings.txt record must contain 13 or 14 fields")
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
            start_time=normalize_datetime_string(start_time, strict=True, field_name="start_time") or now_iso(),
            end_time=normalize_datetime_string(end_time, strict=True, field_name="end_time") or now_iso(),
            status=RoomBookingStatus(status),
            checked_in_at=normalize_datetime_string(checked_in_at, strict=True, field_name="checked_in_at"),
            requested_checkin_at=normalize_datetime_string(requested_checkin_at, strict=True, field_name="requested_checkin_at"),
            requested_checkout_at=normalize_datetime_string(requested_checkout_at, strict=True, field_name="requested_checkout_at"),
            completed_at=normalize_datetime_string(completed_at, strict=True, field_name="completed_at"),
            cancelled_at=normalize_datetime_string(cancelled_at, strict=True, field_name="cancelled_at"),
            created_at=normalize_datetime_string(created_at, strict=True, field_name="created_at") or now_iso(),
            updated_at=normalize_datetime_string(updated_at, strict=True, field_name="updated_at") or now_iso(),
            memo=normalize_persisted_text(memo),
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
    group_id: Optional[str] = None
    memo: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EquipmentBooking":
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
            self.group_id,
            normalize_persisted_text(self.memo),
        ]

    @classmethod
    def from_record(cls, record: List[Optional[str]]) -> "EquipmentBooking":
        if len(record) == 13:
            group_id = None
            memo = ""
        elif len(record) == 15:
            group_id = record[13]
            memo = record[14] or ""
            record = record[:13]
        else:
            raise ValueError("equipment_booking.txt record must contain 13 or 15 fields")
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
            start_time=normalize_datetime_string(start_time, strict=True, field_name="start_time") or now_iso(),
            end_time=normalize_datetime_string(end_time, strict=True, field_name="end_time") or now_iso(),
            status=EquipmentBookingStatus(status),
            checked_out_at=normalize_datetime_string(checked_out_at, strict=True, field_name="checked_out_at"),
            requested_pickup_at=normalize_datetime_string(requested_pickup_at, strict=True, field_name="requested_pickup_at"),
            requested_return_at=normalize_datetime_string(requested_return_at, strict=True, field_name="requested_return_at"),
            returned_at=normalize_datetime_string(returned_at, strict=True, field_name="returned_at"),
            cancelled_at=normalize_datetime_string(cancelled_at, strict=True, field_name="cancelled_at"),
            created_at=normalize_datetime_string(created_at, strict=True, field_name="created_at") or now_iso(),
            updated_at=normalize_datetime_string(updated_at, strict=True, field_name="updated_at") or now_iso(),
            group_id=group_id,
            memo=normalize_persisted_text(memo),
        )


@dataclass
class RoomMaintenanceSchedule:
    """회의실 점검 일정"""

    id: str
    room_id: str
    start_time: str
    end_time: str
    reason: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RoomMaintenanceSchedule":
        return cls(**data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "RoomMaintenanceSchedule":
        return cls.from_dict(json.loads(json_str))

    def to_record(self) -> List[Optional[str]]:
        return [
            self.id,
            self.room_id,
            normalize_datetime_string(self.start_time),
            normalize_datetime_string(self.end_time),
            normalize_persisted_text(self.reason),
            normalize_datetime_string(self.created_at),
            normalize_datetime_string(self.updated_at),
        ]

    @classmethod
    def from_record(cls, record: List[Optional[str]]) -> "RoomMaintenanceSchedule":
        if len(record) != 7:
            raise ValueError("room_maintenance.txt record must contain 7 fields")
        schedule_id, room_id, start_time, end_time, reason, created_at, updated_at = record
        return cls(
            id=schedule_id or generate_id(),
            room_id=room_id or "",
            start_time=normalize_datetime_string(start_time, strict=True, field_name="start_time") or now_iso(),
            end_time=normalize_datetime_string(end_time, strict=True, field_name="end_time") or now_iso(),
            reason=normalize_persisted_text(reason),
            created_at=normalize_datetime_string(created_at, strict=True, field_name="created_at") or now_iso(),
            updated_at=normalize_datetime_string(updated_at, strict=True, field_name="updated_at") or now_iso(),
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

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["reason"] = self.reason.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Penalty":
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
            created_at=normalize_datetime_string(created_at, strict=True, field_name="created_at") or now_iso(),
            updated_at=normalize_datetime_string(updated_at, strict=True, field_name="updated_at"),
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditLog":
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
            created_at=normalize_datetime_string(created_at, strict=True, field_name="created_at") or now_iso(),
            updated_at=normalize_datetime_string(updated_at, strict=True, field_name="updated_at"),
        )
