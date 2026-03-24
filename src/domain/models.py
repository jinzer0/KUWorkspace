"""
도메인 모델 정의 (Dataclasses + Enums)
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid
import json

from src.runtime_clock import get_current_time

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
    CHECKED_IN = "checked_in"
    CHECKOUT_REQUESTED = "checkout_requested"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"
    ADMIN_CANCELLED = "admin_cancelled"


class EquipmentBookingStatus(str, Enum):
    """장비 예약 상태"""

    RESERVED = "reserved"
    CHECKED_OUT = "checked_out"
    RETURN_REQUESTED = "return_requested"
    RETURNED = "returned"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"
    ADMIN_CANCELLED = "admin_cancelled"


class PenaltyReason(str, Enum):
    """패널티 사유"""

    NO_SHOW = "no_show"
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
