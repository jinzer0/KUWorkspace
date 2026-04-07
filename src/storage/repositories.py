"""
Repository 클래스 - 엔티티별 데이터 접근 계층

모든 쓰기 작업은 전역 잠금 하에서 수행되어야 함.
PLAN2.md 준수: 다중 파일 쓰기는 UnitOfWork를 통해 원자적으로 처리
"""

from datetime import datetime

from src.config import (
    USERS_FILE,
    ROOMS_FILE,
    EQUIPMENTS_FILE,
    ROOM_BOOKINGS_FILE,
    EQUIPMENT_BOOKING_FILE,
    PENALTIES_FILE,
    AUDIT_LOG_FILE,
)
from src.domain.models import (
    User,
    Room,
    EquipmentAsset,
    RoomBooking,
    EquipmentBooking,
    Penalty,
    AuditLog,
    generate_id,
    now_iso,
)
from src.storage.jsonl_handler import read_jsonl
from src.storage.atomic_writer import (
    atomic_write_jsonl,
    staged_atomic_write_jsonl_multi,
)
from src.storage.file_lock import is_lock_held

_uow_stack = []


def get_current_uow():
    """현재 활성 UnitOfWork 반환 (스택 최상위)"""
    return _uow_stack[-1] if _uow_stack else None


def require_write_lock():
    """현재 쓰기 경로가 전역 잠금 아래에 있는지 확인합니다."""
    if not is_lock_held():
        raise RuntimeError("Write operations must hold the global lock")


class UnitOfWork:
    """
    PLAN2.md 준수 다중 파일 트랜잭션 (스택 기반 중첩 지원)

    사용법:
        with UnitOfWork() as uow:
            # repo.add(), repo.update() 호출 시 자동으로 uow에 스테이징
            repo.add(record)
            # with 블록 끝에서 자동 커밋

    중첩 동작:
        - 내부 UnitOfWork는 외부 UnitOfWork에 합류 (join)
        - 모든 변경은 최외곽 UnitOfWork 종료 시 한 번에 커밋
        - 내부 UnitOfWork의 __exit__은 커밋하지 않고 스택에서만 제거
    """

    def __init__(self):
        self._staged = {}
        self._dirty_repos = {}
        self._is_nested = False
        self._parent = None

    def __enter__(self):
        global _uow_stack
        require_write_lock()
        if _uow_stack:
            # 중첩 진입: 외부 UoW에 합류
            self._is_nested = True
            self._parent = _uow_stack[-1]
            # 내부 UoW는 외부 UoW의 staged를 공유
            self._staged = self._parent._staged
            self._dirty_repos = self._parent._dirty_repos
        _uow_stack.append(self)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        global _uow_stack
        try:
            if exc_type is not None:
                # 예외 발생 시 전체 롤백
                self._rollback_all()
            elif not self._is_nested:
                # 최외곽 UoW만 커밋
                self.commit()
            # 중첩 UoW는 아무것도 하지 않음 (외부 UoW가 커밋)
        finally:
            _uow_stack.pop()
        return False

    def _rollback_all(self):
        """전체 스택 롤백"""
        if self._parent:
            self._parent._rollback_all()
        else:
            self._staged.clear()
            self._dirty_repos.clear()

    def mark_dirty(self, repo, records):
        self._staged[repo.file_path] = (records, repo.to_json)
        self._dirty_repos[repo.file_path] = repo

    def stage(self, repo, records):
        self._staged[repo.file_path] = (records, repo.to_json)

    def commit(self):
        if not self._staged:
            return
        require_write_lock()
        staged_atomic_write_jsonl_multi(self._staged)
        self._staged.clear()
        self._dirty_repos.clear()

    def rollback(self):
        self._staged.clear()
        self._dirty_repos.clear()


class BaseRepository:
    """기본 Repository 클래스"""

    def __init__(self, file_path, model_class, from_json, to_json):
        self.file_path = file_path
        self.model_class = model_class
        self.from_json = from_json
        self.to_json = to_json
        self._pending_records = None

    def get_all(self):
        """모든 레코드 조회 (UnitOfWork 활성 시 pending 포함)"""
        uow = get_current_uow()
        if uow and self.file_path in uow._staged:
            return list(uow._staged[self.file_path][0])
        return read_jsonl(self.file_path, self.from_json)

    def get_by_id(self, id):
        """ID로 레코드 조회"""
        for item in self.get_all():
            if getattr(item, "id") == id:
                return item
        return None

    def save_all(self, records):
        """모든 레코드 저장 (UnitOfWork 활성 시 스테이징)"""
        uow = get_current_uow()
        if uow:
            uow.mark_dirty(self, records)
        else:
            require_write_lock()
            atomic_write_jsonl(self.file_path, records, self.to_json)

    def add(self, record):
        """레코드 추가"""
        records = self.get_all()
        records.append(record)
        self.save_all(records)
        return record

    def update(self, record):
        """레코드 업데이트"""
        records = self.get_all()
        record_id = getattr(record, "id")

        for i, item in enumerate(records):
            if getattr(item, "id") == record_id:
                if hasattr(record, "updated_at"):
                    object.__setattr__(record, "updated_at", now_iso())
                records[i] = record
                self.save_all(records)
                return record
        return None

    def delete(self, id):
        """레코드 삭제"""
        records = self.get_all()
        original_len = len(records)
        records = [r for r in records if getattr(r, "id") != id]

        if len(records) < original_len:
            self.save_all(records)
            return True
        return False


class UserRepository(BaseRepository):
    """사용자 Repository"""

    def __init__(self, file_path=USERS_FILE):
        super().__init__(
            file_path=file_path,
            model_class=User,
            from_json=User.from_record,
            to_json=lambda u: u.to_record(),
        )

    def get_by_username(self, username):
        """사용자명으로 조회"""
        for user in self.get_all():
            if user.username == username:
                return user
        return None

    def username_exists(self, username):
        """사용자명 중복 확인"""
        return self.get_by_username(username) is not None


class RoomRepository(BaseRepository):
    """회의실 Repository"""

    def __init__(self, file_path=ROOMS_FILE):
        super().__init__(
            file_path=file_path,
            model_class=Room,
            from_json=Room.from_record,
            to_json=lambda r: r.to_record(),
        )

    def get_available(self):
        """사용 가능한 회의실 조회"""
        from src.domain.models import ResourceStatus

        return [r for r in self.get_all() if r.status == ResourceStatus.AVAILABLE]


class EquipmentAssetRepository(BaseRepository):
    """장비 자산 Repository"""

    def __init__(self, file_path=EQUIPMENTS_FILE):
        super().__init__(
            file_path=file_path,
            model_class=EquipmentAsset,
            from_json=EquipmentAsset.from_record,
            to_json=lambda e: e.to_record(),
        )

    def get_available(self):
        """사용 가능한 장비 조회"""
        from src.domain.models import ResourceStatus

        return [e for e in self.get_all() if e.status == ResourceStatus.AVAILABLE]

    def get_by_type(self, asset_type):
        """종류별 장비 조회"""
        return [e for e in self.get_all() if e.asset_type == asset_type]


class RoomBookingRepository(BaseRepository):
    """회의실 예약 Repository"""

    def __init__(self, file_path=ROOM_BOOKINGS_FILE):
        super().__init__(
            file_path=file_path,
            model_class=RoomBooking,
            from_json=RoomBooking.from_record,
            to_json=lambda b: b.to_record(),
        )

    def get_by_user(self, user_id):
        """사용자별 예약 조회"""
        return [b for b in self.get_all() if b.user_id == user_id]

    def get_by_room(self, room_id):
        """회의실별 예약 조회"""
        return [b for b in self.get_all() if b.room_id == room_id]

    def get_active_by_user(self, user_id):
        from src.domain.models import RoomBookingStatus

        active_statuses = {
            RoomBookingStatus.RESERVED,
            RoomBookingStatus.CHECKIN_REQUESTED,
            RoomBookingStatus.CHECKED_IN,
            RoomBookingStatus.CHECKOUT_REQUESTED,
        }
        return [b for b in self.get_by_user(user_id) if b.status in active_statuses]

    def get_conflicting(self, room_id, start_time, end_time, exclude_id=None):
        """충돌하는 예약 조회"""
        from src.domain.models import RoomBookingStatus
        from datetime import datetime

        active_statuses = {
            RoomBookingStatus.RESERVED,
            RoomBookingStatus.CHECKIN_REQUESTED,
            RoomBookingStatus.CHECKED_IN,
            RoomBookingStatus.CHECKOUT_REQUESTED,
        }

        requested_start = datetime.fromisoformat(start_time)
        requested_end = datetime.fromisoformat(end_time)

        conflicts = []
        for booking in self.get_by_room(room_id):
            if booking.status not in active_statuses:
                continue
            if exclude_id and booking.id == exclude_id:
                continue

            booking_start = datetime.fromisoformat(booking.start_time)
            booking_end = datetime.fromisoformat(booking.end_time)
            if not (requested_end <= booking_start or requested_start >= booking_end):
                conflicts.append(booking)

        return conflicts

class EquipmentBookingRepository(BaseRepository):
    """장비 예약 Repository"""

    def __init__(self, file_path=EQUIPMENT_BOOKING_FILE):
        super().__init__(
            file_path=file_path,
            model_class=EquipmentBooking,
            from_json=EquipmentBooking.from_record,
            to_json=lambda b: b.to_record(),
        )

    def get_by_user(self, user_id):
        """사용자별 예약 조회"""
        return [b for b in self.get_all() if b.user_id == user_id]

    def get_by_equipment(self, equipment_id):
        """장비별 예약 조회"""
        return [b for b in self.get_all() if b.equipment_id == equipment_id]

    def get_active_by_user(self, user_id):
        from src.domain.models import EquipmentBookingStatus

        active_statuses = {
            EquipmentBookingStatus.RESERVED,
            EquipmentBookingStatus.PICKUP_REQUESTED,
            EquipmentBookingStatus.CHECKED_OUT,
            EquipmentBookingStatus.RETURN_REQUESTED,
        }
        return [b for b in self.get_by_user(user_id) if b.status in active_statuses]

    def get_conflicting(self, equipment_id, start_time, end_time, exclude_id=None):
        """충돌하는 예약 조회"""
        from src.domain.models import EquipmentBookingStatus
        from datetime import datetime

        active_statuses = {
            EquipmentBookingStatus.RESERVED,
            EquipmentBookingStatus.PICKUP_REQUESTED,
            EquipmentBookingStatus.CHECKED_OUT,
            EquipmentBookingStatus.RETURN_REQUESTED,
        }

        requested_start = datetime.fromisoformat(start_time)
        requested_end = datetime.fromisoformat(end_time)

        conflicts = []
        for booking in self.get_by_equipment(equipment_id):
            if booking.status not in active_statuses:
                continue
            if exclude_id and booking.id == exclude_id:
                continue

            booking_start = datetime.fromisoformat(booking.start_time)
            booking_end = datetime.fromisoformat(booking.end_time)
            if not (requested_end <= booking_start or requested_start >= booking_end):
                conflicts.append(booking)

        return conflicts

class PenaltyRepository:
    """패널티 Repository (append-only, UnitOfWork 지원)"""

    def __init__(self, file_path=PENALTIES_FILE):
        self.file_path = file_path
        self.to_json = lambda p: p.to_record()

    def get_all(self):
        """모든 패널티 조회"""
        uow = get_current_uow()
        if uow and self.file_path in uow._staged:
            return list(uow._staged[self.file_path][0])
        return read_jsonl(self.file_path, Penalty.from_record)

    def get_by_user(self, user_id):
        """사용자별 패널티 조회"""
        return [p for p in self.get_all() if p.user_id == user_id]

    def add(self, penalty):
        """패널티 추가 (UnitOfWork 활성 시 스테이징)"""
        records = self.get_all()
        records.append(penalty)
        uow = get_current_uow()
        if uow:
            uow.stage(self, records)
        else:
            require_write_lock()
            atomic_write_jsonl(self.file_path, records, self.to_json)
        return penalty

    def get_total_points(self, user_id):
        """사용자의 총 패널티 점수"""
        return sum(p.points for p in self.get_by_user(user_id))

    def get_last_penalty_date(self, user_id):
        """사용자의 마지막 패널티 날짜"""
        penalties = self.get_by_user(user_id)
        if not penalties:
            return None

        latest = max(penalties, key=lambda p: p.created_at)
        return datetime.fromisoformat(latest.created_at)

    def exists(self, user_id, reason, related_type, related_id, memo=None):
        for penalty in self.get_by_user(user_id):
            if penalty.reason != reason:
                continue
            if penalty.related_type != related_type or penalty.related_id != related_id:
                continue
            if memo is not None and penalty.memo != memo:
                continue
            return True
        return False


class AuditLogRepository:
    """감사 로그 Repository (append-only, UnitOfWork 지원)"""

    def __init__(self, file_path=AUDIT_LOG_FILE):
        self.file_path = file_path
        self.to_json = lambda l: l.to_record()

    def get_all(self):
        """모든 로그 조회"""
        uow = get_current_uow()
        if uow and self.file_path in uow._staged:
            return list(uow._staged[self.file_path][0])
        return read_jsonl(self.file_path, AuditLog.from_record)

    def add(self, log):
        """로그 추가 (UnitOfWork 활성 시 스테이징)"""
        records = self.get_all()
        records.append(log)
        uow = get_current_uow()
        if uow:
            uow.stage(self, records)
        else:
            require_write_lock()
            atomic_write_jsonl(self.file_path, records, self.to_json)
        return log

    def log_action(self, actor_id, action, target_type, target_id, details=""):
        """액션 로깅 헬퍼"""
        log = AuditLog(
            id=generate_id(),
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details,
            updated_at=now_iso(),
        )
        return self.add(log)

    def get_by_actor(self, actor_id):
        """수행자별 로그 조회"""
        return [l for l in self.get_all() if l.actor_id == actor_id]

    def get_by_target(self, target_type, target_id):
        """대상별 로그 조회"""
        return [
            l
            for l in self.get_all()
            if l.target_type == target_type and l.target_id == target_id
        ]
