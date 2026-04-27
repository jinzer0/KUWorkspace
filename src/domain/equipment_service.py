"""
장비 예약 서비스
"""

from datetime import datetime, timedelta
from dataclasses import replace

from src.domain.models import (
    User,
    EquipmentAsset,
    EquipmentBooking,
    EquipmentBookingStatus,
    ResourceStatus,
    UserRole,
    generate_id,
    now_iso,
)
from src.domain.daily_booking_rules import (
    build_daily_booking_period,
    validate_daily_booking_dates,
)
from src.domain.restriction_rules import evaluate_user_restriction
from src.storage.repositories import (
    UserRepository,
    RoomBookingRepository,
    EquipmentAssetRepository,
    EquipmentBookingRepository,
    PenaltyRepository,
    AuditLogRepository,
    UnitOfWork,
)
from src.storage.file_lock import global_lock
from src.runtime_clock import get_runtime_clock
from src.config import (
    MAX_ACTIVE_EQUIPMENT_BOOKINGS,
    LATE_CANCEL_THRESHOLD_MINUTES,
    FIXED_BOOKING_END_HOUR,
    FIXED_BOOKING_END_MINUTE,
)
from src.domain.field_rules import validate_reason_text


class EquipmentBookingError(Exception):
    """장비 예약 관련 예외"""


class AdminRequiredError(Exception):
    """관리자 권한 필요 예외"""


def _require_admin(user):
    """관리자 권한 확인"""
    if user.role != UserRole.ADMIN:
        raise AdminRequiredError("관리자만 수행할 수 있는 작업입니다.")


class EquipmentService:
    """장비 예약 서비스"""

    def __init__(
        self,
        equipment_repo=None,
        booking_repo=None,
        room_booking_repo=None,
        user_repo=None,
        audit_repo=None,
        penalty_service=None,
        clock=None,
    ):
        from src.domain.penalty_service import PenaltyService

        self.clock = clock or get_runtime_clock()
        self.equipment_repo = equipment_repo or EquipmentAssetRepository()
        self.booking_repo = booking_repo or EquipmentBookingRepository()
        self.room_booking_repo = room_booking_repo or RoomBookingRepository()
        self.user_repo = user_repo or UserRepository()
        self.audit_repo = audit_repo or AuditLogRepository()
        self.penalty_service = penalty_service or PenaltyService(
            user_repo=self.user_repo,
            penalty_repo=PenaltyRepository(
                file_path=self.user_repo.file_path.parent / 'penalties.txt'
            ),
            audit_repo=self.audit_repo,
            clock=self.clock,
        )

    def _get_existing_user(self, user):
        current_user = self.user_repo.get_by_id(user.id)
        if current_user is None:
            raise EquipmentBookingError("존재하지 않는 사용자입니다.")
        return current_user

    def _get_existing_user_by_id(self, user_id):
        current_user = self.user_repo.get_by_id(user_id)
        if current_user is None:
            raise EquipmentBookingError("존재하지 않는 사용자입니다.")
        return current_user

    def _get_existing_admin(self, admin):
        _require_admin(admin)
        current_admin = self.user_repo.get_by_id(admin.id)
        if current_admin is None or current_admin.role != UserRole.ADMIN:
            raise AdminRequiredError("관리자만 수행할 수 있는 작업입니다.")
        return current_admin

    def _ensure_user_can_create_booking(self, user):
        current_user = self._get_existing_user(user)
        status = evaluate_user_restriction(current_user, self.clock.now())

        if status["is_banned"]:
            raise EquipmentBookingError(
                f"이용이 금지된 상태입니다. 금지 해제일: {status['restriction_until']}"
            )

        if status["is_restricted"]:
            equipment_active = len(self.booking_repo.get_active_by_user(current_user.id))
            if equipment_active >= 1:
                raise EquipmentBookingError(
                    "패널티로 인해 추가 예약이 불가합니다."
                )

        return current_user

    def _run_policy_checks(self):
        from src.domain.policy_service import PolicyService

        PolicyService(
            user_repo=self.user_repo,
            room_booking_repo=self.room_booking_repo,
            equipment_booking_repo=self.booking_repo,
            penalty_repo=self.penalty_service.penalty_repo,
            audit_repo=self.audit_repo,
            penalty_service=self.penalty_service,
            equipment_repo=self.equipment_repo,
            clock=self.clock,
        ).run_all_checks()

    def _require_current_boundary(self, boundary_time, action_name):
        current_time = self.clock.now()
        if boundary_time != current_time:
            raise EquipmentBookingError(
                f"{action_name}은 현재 운영 시점({current_time.strftime('%Y-%m-%d %H:%M')})과 일치하는 예약에서만 가능합니다."
            )

    def _require_start_request_window(self, booking):
        start_time = datetime.fromisoformat(booking.start_time)
        self._require_current_boundary(start_time, "픽업 요청")

    def _require_end_request_window(self, booking):
        end_time = datetime.fromisoformat(booking.end_time)
        self._require_current_boundary(end_time, "반납 요청")

    def _is_late_cancel(self, booking, current_time=None):
        if current_time is None:
            current_time = self.clock.now()
        start_time = datetime.fromisoformat(booking.start_time)
        if current_time >= start_time:
            return True
        return (start_time - current_time).total_seconds() / 60 <= LATE_CANCEL_THRESHOLD_MINUTES

    def will_apply_late_cancel_penalty(self, user, booking_id):
        user = self._get_existing_user(user)
        booking = self.booking_repo.get_by_id(booking_id)
        if booking is None:
            raise EquipmentBookingError("존재하지 않는 예약입니다.")
        if booking.user_id != user.id:
            raise EquipmentBookingError("본인의 예약만 취소할 수 있습니다.")
        if booking.status != EquipmentBookingStatus.RESERVED:
            raise EquipmentBookingError(
                f"'{booking.status.value}' 상태의 예약은 취소할 수 없습니다."
            )
        return self._is_late_cancel(booking)

    def get_all_equipment(self):
        """모든 장비 조회"""
        return self.equipment_repo.get_all()

    def get_available_equipment(self):
        """예약 가능한 장비 조회"""
        return self.equipment_repo.get_available()

    def get_equipment(self, equipment_id):
        """장비 조회"""
        return self.equipment_repo.get_by_id(equipment_id)

    def get_equipment_by_type(self, asset_type):
        """종류별 장비 조회"""
        return self.equipment_repo.get_by_type(asset_type)

    def get_available_equipment_by_type(self, asset_type, start_time, end_time):
        equipment_list = [
            item
            for item in self.equipment_repo.get_by_type(asset_type)
            if item.status == ResourceStatus.AVAILABLE
        ]
        available = []
        for item in equipment_list:
            conflicts = self.booking_repo.get_conflicting(
                item.id, start_time.isoformat(), end_time.isoformat()
            )
            if not conflicts:
                available.append(item)
        return available

    def create_daily_booking(
        self, user, equipment_id, start_date, end_date, max_active=1
    ):
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                user = self._ensure_user_can_create_booking(user)
                equipment = self.equipment_repo.get_by_id(equipment_id)
                if equipment is None:
                    raise EquipmentBookingError("존재하지 않는 장비입니다.")

                if equipment.status != ResourceStatus.AVAILABLE:
                    raise EquipmentBookingError(
                        f"장비가 현재 {equipment.status.value} 상태입니다."
                    )

                valid, error, _ = validate_daily_booking_dates(
                    start_date, end_date, self.clock.now()
                )
                if not valid:
                    raise EquipmentBookingError(error)

                start_time, end_time = build_daily_booking_period(start_date, end_date)

                active_bookings = self.booking_repo.get_active_by_user(user.id)
                if len(active_bookings) >= max_active:
                    raise EquipmentBookingError(
                        f"활성 장비 예약 한도({max_active}건)를 초과했습니다. 현재 활성 예약: {len(active_bookings)}건"
                    )

                conflicts = self.booking_repo.get_conflicting(
                    equipment_id, start_time.isoformat(), end_time.isoformat()
                )
                if conflicts:
                    raise EquipmentBookingError(
                        "해당 기간에 이미 예약이 있습니다. 다른 장비 또는 다른 날짜를 선택해주세요."
                    )

                booking = EquipmentBooking(
                    id=generate_id(),
                    user_id=user.id,
                    equipment_id=equipment_id,
                    start_time=start_time.isoformat(),
                    end_time=end_time.isoformat(),
                    status=EquipmentBookingStatus.RESERVED,
                )

                self.booking_repo.add(booking)
                self.audit_repo.log_action(
                    actor_id=user.id,
                    action="create_equipment_booking_daily",
                    target_type="equipment_booking",
                    target_id=booking.id,
                    details=f"장비: {equipment.name}, 기간: {start_time} ~ {end_time}",
                )
                return booking

    def modify_daily_booking(self, user, booking_id, start_date, end_date):
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                user = self._get_existing_user(user)
                booking = self.booking_repo.get_by_id(booking_id)
                if booking is None:
                    raise EquipmentBookingError("존재하지 않는 예약입니다.")

                if booking.user_id != user.id:
                    raise EquipmentBookingError("본인의 예약만 변경할 수 있습니다.")

                if booking.status != EquipmentBookingStatus.RESERVED:
                    raise EquipmentBookingError(
                        f"'{booking.status.value}' 상태의 예약은 변경할 수 없습니다."
                    )

                valid, error, _ = validate_daily_booking_dates(
                    start_date, end_date, self.clock.now()
                )
                if not valid:
                    raise EquipmentBookingError(error)

                start_time, end_time = build_daily_booking_period(start_date, end_date)
                conflicts = self.booking_repo.get_conflicting(
                    booking.equipment_id,
                    start_time.isoformat(),
                    end_time.isoformat(),
                    exclude_id=booking_id,
                )
                if conflicts:
                    raise EquipmentBookingError(
                        "해당 기간에 이미 예약이 있습니다. 다른 날짜를 선택해주세요."
                    )

                updated = replace(
                    booking,
                    start_time=start_time.isoformat(),
                    end_time=end_time.isoformat(),
                    updated_at=now_iso(),
                )
                self.booking_repo.update(updated)
                self.audit_repo.log_action(
                    actor_id=user.id,
                    action="modify_equipment_booking_daily",
                    target_type="equipment_booking",
                    target_id=booking_id,
                    details=f"변경: {start_time} ~ {end_time}",
                )
                return updated

    def admin_modify_daily_booking(self, admin, booking_id, start_date, end_date):
        admin = self._get_existing_admin(admin)
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                booking = self.booking_repo.get_by_id(booking_id)
                if booking is None:
                    raise EquipmentBookingError("존재하지 않는 예약입니다.")

                if booking.status != EquipmentBookingStatus.RESERVED:
                    raise EquipmentBookingError(
                        f"'{booking.status.value}' 상태의 예약은 변경할 수 없습니다."
                    )

                booking_user = self.user_repo.get_by_id(booking.user_id)
                if booking_user is None:
                    raise EquipmentBookingError("존재하지 않는 사용자입니다.")

                valid, error, _ = validate_daily_booking_dates(
                    start_date, end_date, self.clock.now()
                )
                if not valid:
                    raise EquipmentBookingError(error)

                start_time, end_time = build_daily_booking_period(start_date, end_date)
                conflicts = self.booking_repo.get_conflicting(
                    booking.equipment_id,
                    start_time.isoformat(),
                    end_time.isoformat(),
                    exclude_id=booking_id,
                )
                if conflicts:
                    raise EquipmentBookingError("해당 기간에 이미 예약이 있습니다.")

                updated = replace(
                    booking,
                    start_time=start_time.isoformat(),
                    end_time=end_time.isoformat(),
                    updated_at=now_iso(),
                )
                self.booking_repo.update(updated)
                self.audit_repo.log_action(
                    actor_id=admin.id,
                    action="admin_modify_equipment_booking_daily",
                    target_type="equipment_booking",
                    target_id=booking_id,
                    details=f"변경: {start_time} ~ {end_time}",
                )
                return updated

    def create_booking(
        self,
        user,
        equipment_id,
        start_time,
        end_time,
        max_active=MAX_ACTIVE_EQUIPMENT_BOOKINGS,
    ):
        """
        장비 예약 생성

        Args:
            user: 예약자
            equipment_id: 장비 ID
            start_time: 시작 시간
            end_time: 종료 시간
            max_active: 최대 활성 예약 수 (제한 상태에 따라 다름)

        Returns:
            생성된 예약

        Raises:
            EquipmentBookingError: 예약 불가 시
        """
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                user = self._ensure_user_can_create_booking(user)
                effective_max_active = min(max_active, MAX_ACTIVE_EQUIPMENT_BOOKINGS)

                equipment = self.equipment_repo.get_by_id(equipment_id)
                if equipment is None:
                    raise EquipmentBookingError("존재하지 않는 장비입니다.")

                if equipment.status != ResourceStatus.AVAILABLE:
                    raise EquipmentBookingError(
                        f"장비가 현재 {equipment.status.value} 상태입니다."
                    )

                start_time, end_time = self._validate_booking_time(start_time, end_time)

                active_bookings = self.booking_repo.get_active_by_user(user.id)
                if len(active_bookings) >= effective_max_active:
                    raise EquipmentBookingError(
                        f"활성 예약 한도({effective_max_active}건)를 초과했습니다. "
                        f"현재 활성 예약: {len(active_bookings)}건"
                    )

                conflicts = self.booking_repo.get_conflicting(
                    equipment_id, start_time.isoformat(), end_time.isoformat()
                )
                if conflicts:
                    raise EquipmentBookingError(
                        "해당 시간대에 이미 예약이 있습니다. 다른 시간을 선택해주세요."
                    )

                booking = EquipmentBooking(
                    id=generate_id(),
                    user_id=user.id,
                    equipment_id=equipment_id,
                    start_time=start_time.isoformat(),
                    end_time=end_time.isoformat(),
                    status=EquipmentBookingStatus.RESERVED,
                )

                self.booking_repo.add(booking)

                self.audit_repo.log_action(
                    actor_id=user.id,
                    action="create_equipment_booking",
                    target_type="equipment_booking",
                    target_id=booking.id,
                    details=f"장비: {equipment.name}, 시간: {start_time} ~ {end_time}",
                )

                return booking

    def _validate_booking_time(self, start_time, end_time):
        now = self.clock.now()
        if start_time < now:
            raise EquipmentBookingError("과거 시간은 선택할 수 없습니다.")
        if end_time <= start_time:
            raise EquipmentBookingError("종료 시간은 시작 시간보다 늦어야 합니다.")
        if start_time.minute % 30 != 0 or end_time.minute % 30 != 0:
            raise EquipmentBookingError("시간은 30분 단위로만 입력 가능합니다.")

        normalized_end = datetime.combine(
            end_time.date(),
            datetime.min.time().replace(
                hour=FIXED_BOOKING_END_HOUR,
                minute=FIXED_BOOKING_END_MINUTE,
            ),
        )

        today = now.date()
        if start_time.date() < today:
            raise EquipmentBookingError("과거 시간은 선택할 수 없습니다.")
        if start_time.date() > today + timedelta(days=180):
            raise EquipmentBookingError("예약 시작일은 오늘로부터 180일 이내여야 합니다.")
        duration_days = (normalized_end.date() - start_time.date()).days + 1
        if duration_days > 14:
            raise EquipmentBookingError("예약 기간은 최대 14일까지 가능합니다.")
        return start_time, normalized_end

    def modify_booking(self, user, booking_id, new_start_time, new_end_time):
        """
        예약 변경 (사용자: reserved 상태만)
        """
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                user = self._get_existing_user(user)
                booking = self.booking_repo.get_by_id(booking_id)
                if booking is None:
                    raise EquipmentBookingError("존재하지 않는 예약입니다.")

                if booking.user_id != user.id:
                    raise EquipmentBookingError("본인의 예약만 변경할 수 있습니다.")

                if booking.status != EquipmentBookingStatus.RESERVED:
                    raise EquipmentBookingError(
                        f"'{booking.status.value}' 상태의 예약은 변경할 수 없습니다. "
                        "예약 대기(reserved) 상태만 변경 가능합니다."
                    )

                new_start_time, new_end_time = self._validate_booking_time(
                    new_start_time, new_end_time
                )

                conflicts = self.booking_repo.get_conflicting(
                    booking.equipment_id,
                    new_start_time.isoformat(),
                    new_end_time.isoformat(),
                    exclude_id=booking_id,
                )
                if conflicts:
                    raise EquipmentBookingError(
                        "해당 시간대에 이미 예약이 있습니다. 다른 시간을 선택해주세요."
                    )

                updated = replace(
                    booking,
                    start_time=new_start_time.isoformat(),
                    end_time=new_end_time.isoformat(),
                    updated_at=now_iso(),
                )

                self.booking_repo.update(updated)

                self.audit_repo.log_action(
                    actor_id=user.id,
                    action="modify_equipment_booking",
                    target_type="equipment_booking",
                    target_id=booking_id,
                    details=f"변경: {new_start_time} ~ {new_end_time}",
                )

                return updated

    def cancel_booking(self, user, booking_id):
        """
        예약 취소 (사용자)

        Returns:
            (취소된 예약, 직전 취소 여부)
        """
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                user = self._get_existing_user(user)
                booking = self.booking_repo.get_by_id(booking_id)
                if booking is None:
                    raise EquipmentBookingError("존재하지 않는 예약입니다.")

                if booking.user_id != user.id:
                    raise EquipmentBookingError("본인의 예약만 취소할 수 있습니다.")

                if booking.status != EquipmentBookingStatus.RESERVED:
                    raise EquipmentBookingError(
                        f"'{booking.status.value}' 상태의 예약은 취소할 수 없습니다."
                    )

                is_late_cancel = self._is_late_cancel(booking)
                if is_late_cancel:
                    booking_user = self.user_repo.get_by_id(booking.user_id)
                    if booking_user is None:
                        raise EquipmentBookingError("존재하지 않는 사용자입니다.")
                    self.penalty_service.apply_late_cancel(
                        user=booking_user,
                        booking_type="equipment_booking",
                        booking_id=booking.id,
                        actor_id=user.id,
                    )

                updated = replace(
                    booking,
                    status=EquipmentBookingStatus.CANCELLED,
                    cancelled_at=now_iso(),
                    updated_at=now_iso(),
                )

                self.booking_repo.update(updated)

                self.audit_repo.log_action(
                    actor_id=user.id,
                    action="cancel_equipment_booking",
                    target_type="equipment_booking",
                    target_id=booking_id,
                    details="사용자 취소",
                )

                return updated, is_late_cancel

    def admin_cancel_booking(self, admin, booking_id, reason=""):
        """관리자에 의한 예약 취소"""
        admin = self._get_existing_admin(admin)
        try:
            validate_reason_text(reason)
        except ValueError as error:
            raise EquipmentBookingError(str(error)) from error
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                booking = self.booking_repo.get_by_id(booking_id)
                if booking is None:
                    raise EquipmentBookingError("존재하지 않는 예약입니다.")

                if booking.status != EquipmentBookingStatus.RESERVED:
                    raise EquipmentBookingError(
                        f"'{booking.status.value}' 상태의 예약은 취소할 수 없습니다. 관리자 취소는 'reserved' 상태만 가능합니다."
                    )

                booking_user = self.user_repo.get_by_id(booking.user_id)
                if booking_user is None:
                    raise EquipmentBookingError("존재하지 않는 사용자입니다.")

                updated = replace(
                    booking,
                    status=EquipmentBookingStatus.ADMIN_CANCELLED,
                    cancelled_at=now_iso(),
                    updated_at=now_iso(),
                )

                self.booking_repo.update(updated)

                self.audit_repo.log_action(
                    actor_id=admin.id,
                    action="admin_cancel_equipment_booking",
                    target_type="equipment_booking",
                    target_id=booking_id,
                    details=f"사유: {reason}",
                )

                return updated

    def admin_modify_booking(self, admin, booking_id, new_start_time, new_end_time):
        """관리자에 의한 예약 변경 (미래의 reserved 상태만)"""
        admin = self._get_existing_admin(admin)
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                booking = self.booking_repo.get_by_id(booking_id)
                if booking is None:
                    raise EquipmentBookingError("존재하지 않는 예약입니다.")

                if booking.status != EquipmentBookingStatus.RESERVED:
                    raise EquipmentBookingError(
                        f"'{booking.status.value}' 상태의 예약은 변경할 수 없습니다."
                    )

                booking_user = self.user_repo.get_by_id(booking.user_id)
                if booking_user is None:
                    raise EquipmentBookingError("존재하지 않는 사용자입니다.")

                now = self.clock.now()
                start = datetime.fromisoformat(booking.start_time)
                if start <= now:
                    raise EquipmentBookingError(
                        "이미 시작된 예약은 변경할 수 없습니다."
                    )

                new_start_time, new_end_time = self._validate_booking_time(
                    new_start_time, new_end_time
                )

                conflicts = self.booking_repo.get_conflicting(
                    booking.equipment_id,
                    new_start_time.isoformat(),
                    new_end_time.isoformat(),
                    exclude_id=booking_id,
                )
                if conflicts:
                    raise EquipmentBookingError("해당 시간대에 이미 예약이 있습니다.")

                updated = replace(
                    booking,
                    start_time=new_start_time.isoformat(),
                    end_time=new_end_time.isoformat(),
                    updated_at=now_iso(),
                )

                self.booking_repo.update(updated)

                self.audit_repo.log_action(
                    actor_id=admin.id,
                    action="admin_modify_equipment_booking",
                    target_type="equipment_booking",
                    target_id=booking_id,
                    details=f"변경: {new_start_time} ~ {new_end_time}",
                )

                return updated

    def checkout(self, admin, booking_id):
        """대여 시작 처리 (체크아웃)"""
        admin = self._get_existing_admin(admin)
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                booking = self.booking_repo.get_by_id(booking_id)
                if booking is None:
                    raise EquipmentBookingError("존재하지 않는 예약입니다.")

                if booking.status != EquipmentBookingStatus.PICKUP_REQUESTED:
                    raise EquipmentBookingError(
                        f"'{booking.status.value}' 상태의 예약은 대여 시작할 수 없습니다."
                    )

                booking_user = self.user_repo.get_by_id(booking.user_id)
                if booking_user is None:
                    raise EquipmentBookingError("존재하지 않는 사용자입니다.")
                self._require_current_boundary(
                    datetime.fromisoformat(booking.start_time), "대여 시작"
                )

                updated = replace(
                    booking,
                    status=EquipmentBookingStatus.CHECKED_OUT,
                    checked_out_at=now_iso(),
                    updated_at=now_iso(),
                )

                self.booking_repo.update(updated)

                equipment = self.equipment_repo.get_by_id(booking.equipment_id)
                if equipment is not None:
                    disabled_equipment = replace(
                        equipment,
                        status=ResourceStatus.DISABLED,
                        updated_at=now_iso(),
                    )
                    self.equipment_repo.update(disabled_equipment)
                
                self.audit_repo.log_action(
                    actor_id=admin.id,
                    action="equipment_checkout",
                    target_type="equipment_booking",
                    target_id=booking_id,
                    details="",
                )

                return updated

    def request_pickup(self, user, booking_id):
        with global_lock(), UnitOfWork():
            user = self._get_existing_user(user)
            booking = self.booking_repo.get_by_id(booking_id)
            if booking is None:
                raise EquipmentBookingError("존재하지 않는 예약입니다.")

            if booking.user_id != user.id:
                raise EquipmentBookingError("본인의 예약만 픽업 요청할 수 있습니다.")

            if booking.status != EquipmentBookingStatus.RESERVED:
                raise EquipmentBookingError(
                    f"'{booking.status.value}' 상태의 예약은 픽업 요청할 수 없습니다."
                )

            self._require_start_request_window(booking)

            updated = replace(
                booking,
                status=EquipmentBookingStatus.PICKUP_REQUESTED,
                requested_pickup_at=now_iso(),
                updated_at=now_iso(),
            )
            self.booking_repo.update(updated)
            self.audit_repo.log_action(
                actor_id=user.id,
                action="request_equipment_pickup",
                target_type="equipment_booking",
                target_id=booking_id,
                details="",
            )
            return updated

    def return_equipment(self, admin, booking_id):
        """
        반납 처리

        Returns:
            (완료된 예약, 지연 시간(분))
        """
        admin = self._get_existing_admin(admin)
        with global_lock(), UnitOfWork():
            booking = self.booking_repo.get_by_id(booking_id)
            if booking is None:
                raise EquipmentBookingError("존재하지 않는 예약입니다.")

            if booking.status != EquipmentBookingStatus.CHECKED_OUT:
                raise EquipmentBookingError(
                    f"'{booking.status.value}' 상태의 예약은 반납할 수 없습니다."
                )

            end_time = datetime.fromisoformat(booking.end_time)
            self._require_current_boundary(end_time, "반납 처리")
            delay_minutes = 0

            updated = replace(
                booking,
                status=EquipmentBookingStatus.RETURNED,
                returned_at=now_iso(),
                updated_at=now_iso(),
            )

            self.booking_repo.update(updated)

            self.audit_repo.log_action(
                actor_id=admin.id,
                action="equipment_return",
                target_type="equipment_booking",
                target_id=booking_id,
                details=f"지연: {delay_minutes}분",
            )

            booking_user = self.user_repo.get_by_id(booking.user_id)
            if booking_user is None:
                raise EquipmentBookingError("존재하지 않는 사용자입니다.")
            self.penalty_service.record_normal_use(booking_user)

            return updated, delay_minutes

    def force_complete_return(self, admin, booking_id):
        admin = self._get_existing_admin(admin)
        with global_lock(), UnitOfWork():
            booking = self.booking_repo.get_by_id(booking_id)
            if booking is None:
                raise EquipmentBookingError("존재하지 않는 예약입니다.")

            if booking.status != EquipmentBookingStatus.CHECKED_OUT:
                raise EquipmentBookingError(
                    f"'{booking.status.value}' 상태의 예약은 지연 반납 처리할 수 없습니다."
                )

            end_time = datetime.fromisoformat(booking.end_time)
            self._require_current_boundary(end_time, "지연 반납 처리")
            delay_minutes = int((self.clock.now() - end_time).total_seconds() / 60)
            if delay_minutes <= 0:
                delay_minutes = 60

            updated = replace(
                booking,
                status=EquipmentBookingStatus.RETURNED,
                returned_at=now_iso(),
                updated_at=now_iso(),
            )
            self.booking_repo.update(updated)

            booking_user = self.user_repo.get_by_id(booking.user_id)
            if booking_user is None:
                raise EquipmentBookingError("존재하지 않는 사용자입니다.")
            self.penalty_service.apply_late_return(
                user=booking_user,
                booking_type="equipment_booking",
                booking_id=booking_id,
                delay_minutes=delay_minutes,
                actor_id=admin.id,
            )

            self.audit_repo.log_action(
                actor_id=admin.id,
                action="force_complete_equipment_return",
                target_type="equipment_booking",
                target_id=booking_id,
                details=f"지연: {delay_minutes}분",
            )

            return updated, delay_minutes

    def request_return(self, user, booking_id):
        with global_lock(), UnitOfWork():
            user = self._get_existing_user(user)
            booking = self.booking_repo.get_by_id(booking_id)
            if booking is None:
                raise EquipmentBookingError("존재하지 않는 예약입니다.")

            if booking.user_id != user.id:
                raise EquipmentBookingError("본인의 예약만 반납 신청할 수 있습니다.")

            if booking.status != EquipmentBookingStatus.CHECKED_OUT:
                raise EquipmentBookingError(
                    f"'{booking.status.value}' 상태의 예약은 반납 신청할 수 없습니다."
                )

            updated = replace(
                booking,
                status=EquipmentBookingStatus.RETURN_REQUESTED,
                requested_return_at=now_iso(),
                updated_at=now_iso(),
            )
            self.booking_repo.update(updated)
            self.audit_repo.log_action(
                actor_id=user.id,
                action="request_equipment_return",
                target_type="equipment_booking",
                target_id=booking_id,
                details="",
            )
            return updated

    def approve_return_request(self, admin, booking_id):
        admin = self._get_existing_admin(admin)
        with global_lock(), UnitOfWork():
            booking = self.booking_repo.get_by_id(booking_id)
            if booking is None:
                raise EquipmentBookingError("존재하지 않는 예약입니다.")

            if booking.status != EquipmentBookingStatus.RETURN_REQUESTED:
                raise EquipmentBookingError(
                    f"'{booking.status.value}' 상태의 예약은 반납 승인 처리할 수 없습니다."
                )

            now = self.clock.now()
            end_time = datetime.fromisoformat(booking.end_time)
            delay_minutes = 0
            is_early_return = now < end_time

            updated = replace(
                booking,
                status=EquipmentBookingStatus.RETURNED,
                returned_at=now_iso(),
                updated_at=now_iso(),
            )
            self.booking_repo.update(updated)

            self.audit_repo.log_action(
                actor_id=admin.id,
                action="approve_equipment_return_request",
                target_type="equipment_booking",
                target_id=booking_id,
                details=f"조기반납: {is_early_return}, 지연: {delay_minutes}분",
            )

            booking_user = self.user_repo.get_by_id(booking.user_id)
            if booking_user is None:
                raise EquipmentBookingError("존재하지 않는 사용자입니다.")

            self.penalty_service.record_normal_use(booking_user)

            return updated, delay_minutes

    def get_user_bookings(self, user_id):
        """사용자의 모든 예약 조회"""
        self._get_existing_user_by_id(user_id)
        return self.booking_repo.get_by_user(user_id)

    def get_user_active_bookings(self, user_id):
        """사용자의 활성 예약 조회"""
        self._get_existing_user_by_id(user_id)
        return self.booking_repo.get_active_by_user(user_id)

    def get_all_bookings(self, admin):
        """모든 예약 조회 (관리자용)"""
        self._get_existing_admin(admin)
        return self.booking_repo.get_all()

    def get_equipment_bookings(self, equipment_id):
        """장비별 예약 조회"""
        return self.booking_repo.get_by_equipment(equipment_id)

    def update_equipment_status(self, admin, equipment_id, new_status):
        """
        장비 상태 변경

        - MAINTENANCE(점검중): 반납 완료된 당일 18:00 이후 시점 무관하게 변경 가능
        - AVAILABLE(사용가능): 장비가 점검중으로 변경된 그 다음날 09:00 이후 변경 가능

        Returns:
            (변경된 장비, 취소된 예약 목록)
        """
        admin = self._get_existing_admin(admin)
        with global_lock(), UnitOfWork():
            equipment = self.equipment_repo.get_by_id(equipment_id)
            if equipment is None:
                raise EquipmentBookingError("존재하지 않는 장비입니다.")

            now = self.clock.now()

            if new_status == ResourceStatus.MAINTENANCE:
                # 점검중으로 변경 조건:
                # 동일 상태(점검중→점검중)인 경우 DISABLED 체크 생략
                # 다른 상태에서 점검중으로 변경 시: DISABLED 상태여야 하고 반납 승인 당일 18:00 이후여야 함
                if equipment.status != ResourceStatus.MAINTENANCE:
                    if equipment.status != ResourceStatus.DISABLED:
                        raise EquipmentBookingError(
                            "[점검중] 으로 변경하려면 장비가 반납 완료된 상태([사용불가])여야 합니다."
                        )
                    latest_returned = None
                    for b in self.booking_repo.get_by_equipment(equipment_id):
                        if b.status == EquipmentBookingStatus.RETURNED and b.returned_at and b.returned_at != r'\-':
                            if latest_returned is None or b.returned_at > latest_returned.returned_at:
                                latest_returned = b
                    if latest_returned is None:
                        raise EquipmentBookingError(
                            "[점검중] 으로 변경하려면 반납 완료된 예약이 있어야 합니다."
                        )
                    returned_date = datetime.fromisoformat(latest_returned.returned_at).date()
                    today_18 = now.replace(hour=18, minute=0, second=0, microsecond=0)
                    if now.date() != returned_date or now < today_18:
                        raise EquipmentBookingError(
                            "[점검중] 으로 변경할 수 있는 시점은 반납 승인된 당일 18:00 이후입니다."
                        )

            if new_status == ResourceStatus.AVAILABLE:
                # 사용가능으로 변경 조건:
                # 동일 상태(사용가능→사용가능)인 경우 시점 체크 생략
                # 다른 상태에서 사용가능으로 변경 시: 반납 승인된 다음날 09:00 이후여야 함
                if equipment.status != ResourceStatus.AVAILABLE:
                    latest_returned = None
                    for b in self.booking_repo.get_by_equipment(equipment_id):
                        if b.status == EquipmentBookingStatus.RETURNED and b.returned_at and b.returned_at != r'\-':
                            if latest_returned is None or b.returned_at > latest_returned.returned_at:
                                latest_returned = b
                    if latest_returned is None:
                        raise EquipmentBookingError(
                            "[사용가능] 으로 변경하려면 반납 완료된 예약이 있어야 합니다."
                        )
                    returned_at = datetime.fromisoformat(latest_returned.returned_at)
                    next_day_09 = (returned_at + timedelta(days=1)).replace(
                        hour=9, minute=0, second=0, microsecond=0
                    )
                    if now < next_day_09:
                        raise EquipmentBookingError(
                            f"[사용가능] 으로 변경할 수 있는 시점은 반납 승인된 다음날 09:00 이후입니다. "
                            f"({next_day_09.strftime('%Y-%m-%d %H:%M')} 이후 가능)"
                        )

            cancelled_bookings = []

            # maintenance 또는 disabled로 변경 시 미래 예약 취소
            if new_status in {ResourceStatus.MAINTENANCE, ResourceStatus.DISABLED}:
                for booking in self.booking_repo.get_by_equipment(equipment_id):
                    if booking.status == EquipmentBookingStatus.RESERVED:
                        start = datetime.fromisoformat(booking.start_time)
                        if start > now:
                            booking_user = self.user_repo.get_by_id(booking.user_id)
                            if booking_user is None:
                                raise EquipmentBookingError(
                                    "존재하지 않는 사용자입니다."
                                )
                            updated_booking = replace(
                                booking,
                                status=EquipmentBookingStatus.ADMIN_CANCELLED,
                                cancelled_at=now_iso(),
                                updated_at=now_iso(),
                            )
                            self.booking_repo.update(updated_booking)
                            cancelled_bookings.append(updated_booking)

            updated_equipment = replace(
                equipment, status=new_status, updated_at=now_iso()
            )

            self.equipment_repo.update(updated_equipment)

            self.audit_repo.log_action(
                actor_id=admin.id,
                action="update_equipment_status",
                target_type="equipment",
                target_id=equipment_id,
                details=f"상태 변경: {new_status.value}, 취소된 예약: {len(cancelled_bookings)}건",
            )

            return updated_equipment, cancelled_bookings
