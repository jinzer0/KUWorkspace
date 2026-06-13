"""
회의실 예약 서비스
"""

from datetime import datetime, timedelta
from dataclasses import dataclass, replace

from src.domain.models import (
    User,
    Room,
    RoomBooking,
    RoomBookingStatus,
    RoomMaintenanceSchedule,
    ResourceStatus,
    UserRole,
    generate_id,
    now_iso,
)
from src.domain.daily_booking_rules import (
    build_maintenance_period,
    build_daily_booking_period,
    validate_maintenance_dates,
    validate_daily_booking_dates,
)
from src.domain.restriction_rules import evaluate_user_restriction
from src.storage.repositories import (
    UserRepository,
    RoomRepository,
    RoomBookingRepository,
    EquipmentBookingRepository,
    RoomMaintenanceRepository,
    AuditLogRepository,
    UnitOfWork,
)
from src.storage.file_lock import global_lock
from src.runtime_clock import get_runtime_clock
from src.config import (
    MAX_ACTIVE_ROOM_BOOKINGS,
    MAX_RESTRICTED_ROOM_BOOKINGS,
    LATE_CANCEL_THRESHOLD_MINUTES,
    FIXED_BOOKING_START_HOUR,
    FIXED_BOOKING_START_MINUTE,
    FIXED_BOOKING_END_HOUR,
    FIXED_BOOKING_END_MINUTE,
)
from src.domain.field_rules import (
    validate_reason_text,
    validate_reservation_memo_text,
    validate_room_capacity,
    validate_room_location,
    validate_room_name,
)


MAX_ROOM_RESOURCES = 20


class RoomBookingError(Exception):
    """회의실 예약 처리 중 발생하는 예외입니다."""

    pass


class AdminRequiredError(Exception):
    """관리자 권한이 필요한 작업에서 발생하는 예외입니다."""

    pass


@dataclass(frozen=True)
class RoomOperationalOverview:
    room_name: str
    capacity: int
    location: str
    operational_status: str
    reservation_summary: str


def _require_admin(user):
    """사용자에게 관리자 권한이 있는지 확인합니다."""
    if user.role != UserRole.ADMIN:
        raise AdminRequiredError("관리자만 수행할 수 있는 작업입니다.")


class RoomService:
    """회의실 예약 서비스"""

    def __init__(
        self,
        room_repo=None,
        booking_repo=None,
        equipment_booking_repo=None,
        maintenance_repo=None,
        user_repo=None,
        audit_repo=None,
        penalty_service=None,
        clock=None,
    ):
        from src.domain.penalty_service import PenaltyService

        self.clock = clock or get_runtime_clock()
        self.room_repo = room_repo or RoomRepository()
        self.booking_repo = booking_repo or RoomBookingRepository()
        self.equipment_booking_repo = (
            equipment_booking_repo or EquipmentBookingRepository()
        )
        self.maintenance_repo = maintenance_repo or RoomMaintenanceRepository()
        self.user_repo = user_repo or UserRepository()
        self.audit_repo = audit_repo or AuditLogRepository()
        self.penalty_service = penalty_service or PenaltyService(
            user_repo=self.user_repo,
            audit_repo=self.audit_repo,
            clock=self.clock,
        )

    def _get_existing_user(self, user):
        current_user = self.user_repo.get_by_id(user.id)
        if current_user is None:
            raise RoomBookingError("존재하지 않는 사용자입니다.")
        return current_user

    def _get_existing_user_by_id(self, user_id):
        current_user = self.user_repo.get_by_id(user_id)
        if current_user is None:
            raise RoomBookingError("존재하지 않는 사용자입니다.")
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
            raise RoomBookingError(
                f"이용이 금지된 상태입니다. 금지 해제일: {status['restriction_until']}"
            )

        cancel_restricted_until = current_user.room_cancel_restricted_until
        if cancel_restricted_until:
            restriction_end = datetime.fromisoformat(cancel_restricted_until)
            if restriction_end > self.clock.now():
                raise RoomBookingError(
                    f"빈번한 취소로 인해 예약이 제한된 상태입니다. 제한 해제일: {cancel_restricted_until}"
                )

        if status["is_restricted"]:
            room_active = len(self.booking_repo.get_quota_active_by_user(current_user.id))
            if room_active >= MAX_RESTRICTED_ROOM_BOOKINGS:
                raise RoomBookingError(
                    "패널티로 인해 추가 예약이 불가합니다."
                )

        return current_user

    def _run_policy_checks(self):
        from src.domain.policy_service import PolicyService

        PolicyService(
            user_repo=self.user_repo,
            room_booking_repo=self.booking_repo,
            equipment_booking_repo=self.equipment_booking_repo,
            penalty_repo=self.penalty_service.penalty_repo,
            audit_repo=self.audit_repo,
            penalty_service=self.penalty_service,
            clock=self.clock,
        ).run_all_checks()

    def cleanup_expired_maintenance(self):
        with global_lock(), UnitOfWork():
            return self.maintenance_repo.delete_expired(self.clock.now())

    def _ensure_no_room_maintenance(self, room_id, start_time, end_time):
        conflicts = self.maintenance_repo.get_conflicting(
            room_id, start_time.isoformat(), end_time.isoformat()
        )
        if conflicts:
            raise RoomBookingError(
                "해당 시간대에 회의실 점검 일정이 있습니다. 다른 시간을 선택해주세요."
            )

    def _validate_maintenance_time(self, start_time, end_time):
        valid, error, _ = validate_maintenance_dates(
            start_time.date(), end_time.date(), self.clock.now()
        )
        if not valid:
            raise RoomBookingError(error)
        return build_maintenance_period(start_time.date(), end_time.date())

    def _get_non_terminal_room_booking_conflicts(self, room_id, start_time, end_time):
        blocking_statuses = {
            RoomBookingStatus.PENDING,
            RoomBookingStatus.RESERVED,
            RoomBookingStatus.CHECKIN_REQUESTED,
            RoomBookingStatus.CHECKED_IN,
            RoomBookingStatus.CHECKOUT_REQUESTED,
        }
        conflicts = []
        for booking in self.booking_repo.get_by_room(room_id):
            if booking.status not in blocking_statuses:
                continue
            booking_start = datetime.fromisoformat(booking.start_time)
            booking_end = datetime.fromisoformat(booking.end_time)
            if not (end_time <= booking_start or start_time >= booking_end):
                conflicts.append(booking)
        return conflicts

    def create_maintenance_schedule(self, admin, room_id, start_time, end_time, reason=""):
        admin = self._get_existing_admin(admin)
        try:
            validate_reason_text(reason)
        except ValueError as error:
            raise RoomBookingError(str(error)) from error

        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                room = self.room_repo.get_by_id(room_id)
                if room is None:
                    raise RoomBookingError("존재하지 않는 회의실입니다.")

                start_time, end_time = self._validate_maintenance_time(start_time, end_time)
                conflicts = self.maintenance_repo.get_conflicting(
                    room_id, start_time.isoformat(), end_time.isoformat()
                )
                if conflicts:
                    raise RoomBookingError("해당 시간대에 이미 점검 일정이 있습니다.")

                booking_conflicts = self._get_non_terminal_room_booking_conflicts(
                    room_id, start_time, end_time
                )
                if booking_conflicts:
                    raise RoomBookingError(
                        "해당 기간에 겹치는 예약이 있어 점검 일정을 생성할 수 없습니다."
                    )

                schedule = RoomMaintenanceSchedule(
                    id=generate_id(),
                    room_id=room_id,
                    start_time=start_time.isoformat(),
                    end_time=end_time.isoformat(),
                    reason=reason,
                    status="scheduled",
                )
                self.maintenance_repo.add(schedule)

                self.audit_repo.log_action(
                    actor_id=admin.id,
                    action="create_room_maintenance",
                    target_type="room_maintenance",
                    target_id=schedule.id,
                    details=(
                        f"회의실: {room.name}, 기간: {start_time} ~ {end_time}, "
                        f"사유: {reason}"
                    ),
                )
                return schedule

    def cancel_maintenance_schedule(self, admin, schedule_id, reason=""):
        admin = self._get_existing_admin(admin)
        try:
            validate_reason_text(reason)
        except ValueError as error:
            raise RoomBookingError(str(error)) from error

        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                schedule = self.maintenance_repo.get_by_id(schedule_id)
                if schedule is None:
                    raise RoomBookingError("존재하지 않는 점검 일정입니다.")

                if schedule.status in {"completed", "cancelled"}:
                    raise RoomBookingError("이미 종료되었거나 취소된 점검 일정입니다.")
                room = self.room_repo.get_by_id(schedule.room_id)
                if room is None:
                    raise RoomBookingError("존재하지 않는 회의실입니다.")
                cancelled = replace(
                    schedule,
                    status="cancelled",
                    cancelled_at=now_iso(),
                    updated_at=now_iso(),
                )
                self.maintenance_repo.update(cancelled)
                if schedule.status == "active" and room.status == ResourceStatus.MAINTENANCE:
                    self.room_repo.update(
                        replace(room, status=ResourceStatus.AVAILABLE, updated_at=now_iso())
                    )
                self.audit_repo.log_action(
                    actor_id=admin.id,
                    action="cancel_room_maintenance",
                    target_type="room_maintenance",
                    target_id=schedule_id,
                    details=f"사유: {reason}",
                )
                return cancelled

    def _require_current_boundary(self, boundary_time, action_name):
        current_time = self.clock.now()
        if boundary_time != current_time:
            raise RoomBookingError(
                f"{action_name}은 현재 운영 시점({current_time.strftime('%Y-%m-%d %H:%M')})과 일치하는 예약에서만 가능합니다."
            )

    def _require_start_request_window(self, booking):
        start_time = datetime.fromisoformat(booking.start_time)
        self._require_current_boundary(start_time, "체크인 요청")

    def _require_end_request_window(self, booking):
        end_time = datetime.fromisoformat(booking.end_time)
        current_time = self.clock.now()
        if current_time > end_time:
            raise RoomBookingError(
                f"퇴실 요청은 예약 종료 시점({end_time.strftime('%Y-%m-%d %H:%M')}) 이전 또는 해당 시점에서만 가능합니다."
            )

    def _is_late_cancel(self, booking, current_time=None):
        if current_time is None:
            current_time = self.clock.now()
        start_time = datetime.fromisoformat(booking.start_time)
        if current_time >= start_time:
            return True
        return (start_time - current_time).total_seconds() / 60 <= LATE_CANCEL_THRESHOLD_MINUTES

    def _get_cancellable_booking(self, user, booking_id):
        user = self._get_existing_user(user)
        booking = self.booking_repo.get_by_id(booking_id)
        if booking is None:
            raise RoomBookingError("존재하지 않는 예약입니다.")
        if booking.user_id != user.id:
            raise RoomBookingError("본인의 예약만 취소할 수 있습니다.")
        if booking.status != RoomBookingStatus.RESERVED:
            raise RoomBookingError(
                f"'{booking.status.value}' 상태의 예약은 취소할 수 없습니다."
            )
        return user, booking

    def preview_cancel_booking_impact(self, user, booking_id):
        user, booking = self._get_cancellable_booking(user, booking_id)
        return self.penalty_service.preview_cancel_impact(
            user=user,
            booking_type="room_booking",
            booking_id=booking.id,
            booking_start_time=booking.start_time,
            domain_bookings=self.booking_repo.get_by_user(user.id),
        )

    def will_apply_late_cancel_penalty(self, user, booking_id):
        return self.preview_cancel_booking_impact(user, booking_id).is_late_cancel

    def get_all_rooms(self):
        """모든 회의실 조회"""
        return self.room_repo.get_all()

    def get_available_rooms(self):
        """예약 가능한 회의실 조회"""
        return self.room_repo.get_available()

    def get_room(self, room_id):
        """회의실 조회"""
        return self.room_repo.get_by_id(room_id)

    def get_available_rooms_for_attendees(self, attendee_count, start_time, end_time):
        rooms = [r for r in self.room_repo.get_available() if r.capacity >= attendee_count]
        rooms.sort(key=lambda room: (room.capacity, room.name))

        available = []
        for room in rooms:
            conflicts = self.booking_repo.get_confirmed_conflicting(
                room.id, start_time.isoformat(), end_time.isoformat()
            )
            if not conflicts:
                available.append(room)
        return available

    def _is_eighteen_next_day_request(self, start_time):
        current_time = self.clock.now()
        return (
            current_time.hour == FIXED_BOOKING_END_HOUR
            and current_time.minute == FIXED_BOOKING_END_MINUTE
            and start_time.date() == (current_time + timedelta(days=1)).date()
        )

    def _reject_eighteen_next_day_conflict(self, start_time, conflicts):
        if conflicts and self._is_eighteen_next_day_request(start_time):
            raise RoomBookingError(
                "18:00 다음날 예약은 선착순 예외 정책에 따라 이후 동일 자원/기간 요청이 거부됩니다."
            )

    def create_daily_booking(
        self, user, room_id, start_date, end_date, attendee_count, max_active=MAX_ACTIVE_ROOM_BOOKINGS, memo=""
    ):
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                user = self._ensure_user_can_create_booking(user)
                room = self.room_repo.get_by_id(room_id)
                if room is None:
                    raise RoomBookingError("존재하지 않는 회의실입니다.")

                if room.status != ResourceStatus.AVAILABLE:
                    raise RoomBookingError(
                        f"회의실이 현재 {room.status.value} 상태입니다."
                    )

                if attendee_count < 1:
                    raise RoomBookingError("이용 인원은 1명 이상이어야 합니다.")

                if room.capacity < attendee_count:
                    raise RoomBookingError(
                        f"선택한 회의실 수용 인원({room.capacity}명)이 이용 인원보다 작습니다."
                    )

                valid, error, _ = validate_daily_booking_dates(
                    start_date, end_date, self.clock.now()
                )
                if not valid:
                    raise RoomBookingError(error)

                start_time, end_time = build_daily_booking_period(start_date, end_date)

                active_bookings = self.booking_repo.get_quota_active_by_user(user.id)
                if len(active_bookings) >= max_active:
                    raise RoomBookingError(
                        f"활성 회의실 예약 한도({max_active}건)를 초과했습니다. 현재 활성 예약: {len(active_bookings)}건"
                    )

                conflicts = self.booking_repo.get_confirmed_conflicting(
                    room_id, start_time.isoformat(), end_time.isoformat()
                )
                self._reject_eighteen_next_day_conflict(start_time, conflicts)

                self._ensure_no_room_maintenance(room_id, start_time, end_time)
                validate_reservation_memo_text(memo)

                booking_status = (
                    RoomBookingStatus.PENDING if conflicts else RoomBookingStatus.RESERVED
                )
                booking = RoomBooking(
                    id=generate_id(),
                    user_id=user.id,
                    room_id=room_id,
                    start_time=start_time.isoformat(),
                    end_time=end_time.isoformat(),
                    status=booking_status,
                    memo=memo,
                )

                self.booking_repo.add(booking)
                self.audit_repo.log_action(
                    actor_id=user.id,
                    action="create_room_booking_daily",
                    target_type="room_booking",
                    target_id=booking.id,
                    details=f"회의실: {room.name}, 인원: {attendee_count}명, 기간: {start_time} ~ {end_time}",
                )
                return booking

    def modify_daily_booking(self, user, booking_id, start_date, end_date, memo=""):
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                user = self._get_existing_user(user)
                booking = self.booking_repo.get_by_id(booking_id)
                if booking is None:
                    raise RoomBookingError("존재하지 않는 예약입니다.")

                if booking.user_id != user.id:
                    raise RoomBookingError("본인의 예약만 변경할 수 있습니다.")

                if booking.status != RoomBookingStatus.RESERVED:
                    raise RoomBookingError(
                        f"'{booking.status.value}' 상태의 예약은 변경할 수 없습니다."
                    )

                valid, error, _ = validate_daily_booking_dates(
                    start_date, end_date, self.clock.now()
                )
                if not valid:
                    raise RoomBookingError(error)

                start_time, end_time = build_daily_booking_period(start_date, end_date)
                conflicts = self.booking_repo.get_confirmed_conflicting(
                    booking.room_id,
                    start_time.isoformat(),
                    end_time.isoformat(),
                    exclude_id=booking_id,
                )
                if conflicts:
                    raise RoomBookingError(
                        "해당 기간에 이미 예약이 있습니다. 다른 날짜를 선택해주세요."
                    )

                self._ensure_no_room_maintenance(booking.room_id, start_time, end_time)
                validate_reservation_memo_text(memo)

                updated = replace(
                    booking,
                    start_time=start_time.isoformat(),
                    end_time=end_time.isoformat(),
                    memo=memo,
                    updated_at=now_iso(),
                )
                self.booking_repo.update(updated)
                self.audit_repo.log_action(
                    actor_id=user.id,
                    action="modify_room_booking_daily",
                    target_type="room_booking",
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
                    raise RoomBookingError("존재하지 않는 예약입니다.")

                if booking.status != RoomBookingStatus.RESERVED:
                    raise RoomBookingError(
                        f"'{booking.status.value}' 상태의 예약은 변경할 수 없습니다."
                    )

                booking_user = self.user_repo.get_by_id(booking.user_id)
                if booking_user is None:
                    raise RoomBookingError("존재하지 않는 사용자입니다.")

                valid, error, _ = validate_daily_booking_dates(
                    start_date, end_date, self.clock.now()
                )
                if not valid:
                    raise RoomBookingError(error)

                start_time, end_time = build_daily_booking_period(start_date, end_date)
                conflicts = self.booking_repo.get_confirmed_conflicting(
                    booking.room_id,
                    start_time.isoformat(),
                    end_time.isoformat(),
                    exclude_id=booking_id,
                )
                if conflicts:
                    raise RoomBookingError("해당 기간에 이미 예약이 있습니다.")

                self._ensure_no_room_maintenance(booking.room_id, start_time, end_time)
                updated = replace(
                    booking,
                    start_time=start_time.isoformat(),
                    end_time=end_time.isoformat(),
                    updated_at=now_iso(),
                )
                self.booking_repo.update(updated)
                self.audit_repo.log_action(
                    actor_id=admin.id,
                    action="admin_modify_room_booking_daily",
                    target_type="room_booking",
                    target_id=booking_id,
                    details=f"변경: {start_time} ~ {end_time}",
                )
                return updated

    def create_booking(
        self, user, room_id, start_time, end_time, max_active=MAX_ACTIVE_ROOM_BOOKINGS, memo=""
    ):
        """
        회의실 예약 생성

        Args:
            user: 예약자
            room_id: 회의실 ID
            start_time: 시작 시간
            end_time: 종료 시간
            max_active: 최대 활성 예약 수 (제한 상태에 따라 다름)

        Returns:
            생성된 예약

        Raises:
            RoomBookingError: 예약 불가 시
        """
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                user = self._ensure_user_can_create_booking(user)
                effective_max_active = min(max_active, MAX_ACTIVE_ROOM_BOOKINGS)

                room = self.room_repo.get_by_id(room_id)
                if room is None:
                    raise RoomBookingError("존재하지 않는 회의실입니다.")

                if room.status != ResourceStatus.AVAILABLE:
                    raise RoomBookingError(
                        f"회의실이 현재 {room.status.value} 상태입니다."
                    )

                start_time, end_time = self._validate_booking_time(start_time, end_time)

                active_bookings = self.booking_repo.get_quota_active_by_user(user.id)
                if len(active_bookings) >= effective_max_active:
                    raise RoomBookingError(
                        f"활성 예약 한도({effective_max_active}건)를 초과했습니다. "
                        f"현재 활성 예약: {len(active_bookings)}건"
                    )

                conflicts = self.booking_repo.get_confirmed_conflicting(
                    room_id, start_time.isoformat(), end_time.isoformat()
                )
                self._reject_eighteen_next_day_conflict(start_time, conflicts)

                self._ensure_no_room_maintenance(room_id, start_time, end_time)
                validate_reservation_memo_text(memo)

                booking_status = (
                    RoomBookingStatus.PENDING if conflicts else RoomBookingStatus.RESERVED
                )
                booking = RoomBooking(
                    id=generate_id(),
                    user_id=user.id,
                    room_id=room_id,
                    start_time=start_time.isoformat(),
                    end_time=end_time.isoformat(),
                    status=booking_status,
                    memo=memo,
                )

                self.booking_repo.add(booking)

                self.audit_repo.log_action(
                    actor_id=user.id,
                    action="create_room_booking",
                    target_type="room_booking",
                    target_id=booking.id,
                    details=f"회의실: {room.name}, 시간: {start_time} ~ {end_time}",
                )

                return booking

    def _validate_booking_time(self, start_time, end_time):
        now = self.clock.now()
        if start_time < now:
            raise RoomBookingError("과거 시간은 선택할 수 없습니다.")
        if end_time <= start_time:
            raise RoomBookingError("종료 시간은 시작 시간보다 늦어야 합니다.")
        if start_time.minute % 30 != 0 or end_time.minute % 30 != 0:
            raise RoomBookingError("시간은 30분 단위로만 입력 가능합니다.")

        normalized_start = datetime.combine(
            start_time.date(),
            datetime.min.time().replace(
                hour=FIXED_BOOKING_START_HOUR,
                minute=FIXED_BOOKING_START_MINUTE,
            ),
        )
        normalized_end = datetime.combine(
            end_time.date(),
            datetime.min.time().replace(
                hour=FIXED_BOOKING_END_HOUR,
                minute=FIXED_BOOKING_END_MINUTE,
            ),
        )

        today = now.date()
        if normalized_start.date() < today:
            raise RoomBookingError("과거 시간은 선택할 수 없습니다.")
        if normalized_start.date() > today + timedelta(days=180):
            raise RoomBookingError("예약 시작일은 오늘로부터 180일 이내여야 합니다.")
        duration_days = (normalized_end.date() - normalized_start.date()).days + 1
        if duration_days > 14:
            raise RoomBookingError("예약 기간은 최대 14일까지 가능합니다.")
        return normalized_start, normalized_end

    def modify_booking(self, user, booking_id, new_start_time, new_end_time, memo=""):
        """
        예약 변경 (사용자: reserved 상태만)

        Args:
            user: 예약자
            booking_id: 예약 ID
            new_start_time: 새 시작 시간
            new_end_time: 새 종료 시간

        Returns:
            변경된 예약
        """
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                user = self._get_existing_user(user)
                booking = self.booking_repo.get_by_id(booking_id)
                if booking is None:
                    raise RoomBookingError("존재하지 않는 예약입니다.")

                if booking.user_id != user.id:
                    raise RoomBookingError("본인의 예약만 변경할 수 있습니다.")

                if booking.status != RoomBookingStatus.RESERVED:
                    raise RoomBookingError(
                        f"'{booking.status.value}' 상태의 예약은 변경할 수 없습니다. "
                        "예약 대기(reserved) 상태만 변경 가능합니다."
                    )

                new_start_time, new_end_time = self._validate_booking_time(
                    new_start_time, new_end_time
                )

                conflicts = self.booking_repo.get_confirmed_conflicting(
                    booking.room_id,
                    new_start_time.isoformat(),
                    new_end_time.isoformat(),
                    exclude_id=booking_id,
                )
                if conflicts:
                    raise RoomBookingError(
                        "해당 시간대에 이미 예약이 있습니다. 다른 시간을 선택해주세요."
                    )

                self._ensure_no_room_maintenance(booking.room_id, new_start_time, new_end_time)
                validate_reservation_memo_text(memo)

                updated = replace(
                    booking,
                    start_time=new_start_time.isoformat(),
                    end_time=new_end_time.isoformat(),
                    memo=memo,
                    updated_at=now_iso(),
                )

                self.booking_repo.update(updated)

                self.audit_repo.log_action(
                    actor_id=user.id,
                    action="modify_room_booking",
                    target_type="room_booking",
                    target_id=booking_id,
                    details=f"변경: {new_start_time} ~ {new_end_time}",
                )

                return updated


    def _promote_waitlist_for_cancelled_booking(self, booking, actor_id):
        from src.domain.policy_service import PolicyService

        return PolicyService(
            user_repo=self.user_repo,
            room_repo=self.room_repo,
            room_booking_repo=self.booking_repo,
            equipment_booking_repo=self.equipment_booking_repo,
            penalty_repo=self.penalty_service.penalty_repo,
            audit_repo=self.audit_repo,
            room_maintenance_repo=self.maintenance_repo,
            penalty_service=self.penalty_service,
            clock=self.clock,
        ).promote_room_waitlist_for_booking(booking, actor_id=actor_id)

    def cancel_booking(self, user, booking_id):
        """
        예약 취소 (사용자)

        Returns:
            (취소된 예약, 직전 취소 여부)
        """
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                user, booking = self._get_cancellable_booking(user, booking_id)
                impact, _ = self.penalty_service.apply_cancel_impact(
                    user=user,
                    booking_type="room_booking",
                    booking_id=booking.id,
                    booking_start_time=booking.start_time,
                    domain_bookings=self.booking_repo.get_by_user(user.id),
                    actor_id=user.id,
                )

                updated = replace(
                    booking,
                    status=RoomBookingStatus.CANCELLED,
                    cancelled_at=now_iso(),
                    updated_at=now_iso(),
                )

                self.booking_repo.update(updated)

                self.audit_repo.log_action(
                    actor_id=user.id,
                    action="cancel_room_booking",
                    target_type="room_booking",
                    target_id=booking_id,
                    details="사용자 취소",
                )
                self._promote_waitlist_for_cancelled_booking(booking, actor_id=user.id)

                return updated, impact.is_late_cancel

    def admin_cancel_booking(self, admin, booking_id, reason=""):
        admin = self._get_existing_admin(admin)
        try:
            validate_reason_text(reason)
        except ValueError as error:
            raise RoomBookingError(str(error)) from error
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                booking = self.booking_repo.get_by_id(booking_id)
                if booking is None:
                    raise RoomBookingError("존재하지 않는 예약입니다.")

                if booking.status != RoomBookingStatus.RESERVED:
                    raise RoomBookingError(
                        f"'{booking.status.value}' 상태의 예약은 취소할 수 없습니다. 관리자 취소는 'reserved' 상태만 가능합니다."
                    )

                booking_user = self.user_repo.get_by_id(booking.user_id)
                if booking_user is None:
                    raise RoomBookingError("존재하지 않는 사용자입니다.")

                updated = replace(
                    booking,
                    status=RoomBookingStatus.ADMIN_CANCELLED,
                    cancelled_at=now_iso(),
                    updated_at=now_iso(),
                )

                self.booking_repo.update(updated)

                self.audit_repo.log_action(
                    actor_id=admin.id,
                    action="admin_cancel_room_booking",
                    target_type="room_booking",
                    target_id=booking_id,
                    details=f"사유: {reason}",
                )
                self._promote_waitlist_for_cancelled_booking(booking, actor_id=admin.id)

                return updated

    def admin_modify_booking(self, admin, booking_id, new_start_time, new_end_time):
        admin = self._get_existing_admin(admin)
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                booking = self.booking_repo.get_by_id(booking_id)
                if booking is None:
                    raise RoomBookingError("존재하지 않는 예약입니다.")

                if booking.status != RoomBookingStatus.RESERVED:
                    raise RoomBookingError(
                        f"'{booking.status.value}' 상태의 예약은 변경할 수 없습니다."
                    )

                booking_user = self.user_repo.get_by_id(booking.user_id)
                if booking_user is None:
                    raise RoomBookingError("존재하지 않는 사용자입니다.")

                now = self.clock.now()
                start = datetime.fromisoformat(booking.start_time)
                if start <= now:
                    raise RoomBookingError("이미 시작된 예약은 변경할 수 없습니다.")

                new_start_time, new_end_time = self._validate_booking_time(
                    new_start_time, new_end_time
                )

                conflicts = self.booking_repo.get_confirmed_conflicting(
                    booking.room_id,
                    new_start_time.isoformat(),
                    new_end_time.isoformat(),
                    exclude_id=booking_id,
                )
                if conflicts:
                    raise RoomBookingError("해당 시간대에 이미 예약이 있습니다.")

                self._ensure_no_room_maintenance(booking.room_id, new_start_time, new_end_time)
                updated = replace(
                    booking,
                    start_time=new_start_time.isoformat(),
                    end_time=new_end_time.isoformat(),
                    updated_at=now_iso(),
                )

                self.booking_repo.update(updated)

                self.audit_repo.log_action(
                    actor_id=admin.id,
                    action="admin_modify_room_booking",
                    target_type="room_booking",
                    target_id=booking_id,
                    details=f"변경: {new_start_time} ~ {new_end_time}",
                )

                return updated

    def check_in(self, admin, booking_id):
        admin = self._get_existing_admin(admin)
        with global_lock():
            self._run_policy_checks()
            with UnitOfWork():
                booking = self.booking_repo.get_by_id(booking_id)
                if booking is None:
                    raise RoomBookingError("존재하지 않는 예약입니다.")

                if booking.status != RoomBookingStatus.CHECKIN_REQUESTED:
                    raise RoomBookingError(
                        f"'{booking.status.value}' 상태의 예약은 체크인할 수 없습니다."
                    )

                booking_user = self.user_repo.get_by_id(booking.user_id)
                if booking_user is None:
                    raise RoomBookingError("존재하지 않는 사용자입니다.")
                self._require_current_boundary(
                    datetime.fromisoformat(booking.start_time), "체크인"
                )

                updated = replace(
                    booking,
                    status=RoomBookingStatus.CHECKED_IN,
                    checked_in_at=now_iso(),
                    updated_at=now_iso(),
                )

                self.booking_repo.update(updated)

                self.audit_repo.log_action(
                    actor_id=admin.id,
                    action="room_check_in",
                    target_type="room_booking",
                    target_id=booking_id,
                    details="",
                )

                return updated

    def request_check_in(self, user, booking_id):
        with global_lock(), UnitOfWork():
            user = self._get_existing_user(user)
            booking = self.booking_repo.get_by_id(booking_id)
            if booking is None:
                raise RoomBookingError("존재하지 않는 예약입니다.")

            if booking.user_id != user.id:
                raise RoomBookingError("본인의 예약만 체크인 요청할 수 있습니다.")

            if booking.status != RoomBookingStatus.RESERVED:
                raise RoomBookingError(
                    f"'{booking.status.value}' 상태의 예약은 체크인 요청할 수 없습니다."
                )

            self._require_start_request_window(booking)

            updated = replace(
                booking,
                status=RoomBookingStatus.CHECKIN_REQUESTED,
                requested_checkin_at=now_iso(),
                updated_at=now_iso(),
            )
            self.booking_repo.update(updated)
            self.audit_repo.log_action(
                actor_id=user.id,
                action="request_room_check_in",
                target_type="room_booking",
                target_id=booking_id,
                details="",
            )
            return updated

    def check_out(self, admin, booking_id):
        admin = self._get_existing_admin(admin)
        with global_lock(), UnitOfWork():
            booking = self.booking_repo.get_by_id(booking_id)
            if booking is None:
                raise RoomBookingError("존재하지 않는 예약입니다.")

            if booking.status != RoomBookingStatus.CHECKED_IN:
                raise RoomBookingError(
                    f"'{booking.status.value}' 상태의 예약은 퇴실 처리할 수 없습니다."
                )

            end_time = datetime.fromisoformat(booking.end_time)
            self._require_current_boundary(end_time, "퇴실 처리")
            delay_minutes = 0

            updated = replace(
                booking,
                status=RoomBookingStatus.COMPLETED,
                completed_at=now_iso(),
                updated_at=now_iso(),
            )

            self.booking_repo.update(updated)

            self.audit_repo.log_action(
                actor_id=admin.id,
                action="room_check_out",
                target_type="room_booking",
                target_id=booking_id,
                details=f"지연: {delay_minutes}분",
            )

            booking_user = self.user_repo.get_by_id(booking.user_id)
            if booking_user is None:
                raise RoomBookingError("존재하지 않는 사용자입니다.")
            self.penalty_service.record_normal_use(booking_user)

            return updated, delay_minutes

    def force_complete_checkout(self, admin, booking_id):
        admin = self._get_existing_admin(admin)
        with global_lock(), UnitOfWork():
            booking = self.booking_repo.get_by_id(booking_id)
            if booking is None:
                raise RoomBookingError("존재하지 않는 예약입니다.")

            if booking.status != RoomBookingStatus.CHECKED_IN:
                raise RoomBookingError(
                    f"'{booking.status.value}' 상태의 예약은 지연 퇴실 처리할 수 없습니다."
                )

            end_time = datetime.fromisoformat(booking.end_time)
            self._require_current_boundary(end_time, "지연 퇴실 처리")
            delay_minutes = int((self.clock.now() - end_time).total_seconds() / 60)
            if delay_minutes <= 0:
                delay_minutes = 60

            updated = replace(
                booking,
                status=RoomBookingStatus.COMPLETED,
                completed_at=now_iso(),
                updated_at=now_iso(),
            )

            self.booking_repo.update(updated)

            booking_user = self.user_repo.get_by_id(booking.user_id)
            if booking_user is None:
                raise RoomBookingError("존재하지 않는 사용자입니다.")
            self.penalty_service.apply_late_return(
                user=booking_user,
                booking_type="room_booking",
                booking_id=booking_id,
                delay_minutes=delay_minutes,
                actor_id=admin.id,
            )

            self.audit_repo.log_action(
                actor_id=admin.id,
                action="force_complete_room_checkout",
                target_type="room_booking",
                target_id=booking_id,
                details=f"지연: {delay_minutes}분",
            )

            return updated, delay_minutes

    def request_checkout(self, user, booking_id):
        with global_lock(), UnitOfWork():
            user = self._get_existing_user(user)
            booking = self.booking_repo.get_by_id(booking_id)
            if booking is None:
                raise RoomBookingError("존재하지 않는 예약입니다.")

            if booking.user_id != user.id:
                raise RoomBookingError("본인의 예약만 퇴실 신청할 수 있습니다.")

            if booking.status != RoomBookingStatus.CHECKED_IN:
                raise RoomBookingError(
                    f"'{booking.status.value}' 상태의 예약은 퇴실 신청할 수 없습니다."
                )
            self._require_end_request_window(booking)

            updated = replace(
                booking,
                status=RoomBookingStatus.CHECKOUT_REQUESTED,
                requested_checkout_at=now_iso(),
                updated_at=now_iso(),
            )
            self.booking_repo.update(updated)
            self.audit_repo.log_action(
                actor_id=user.id,
                action="request_room_checkout",
                target_type="room_booking",
                target_id=booking_id,
                details="",
            )
            return updated

    def approve_checkout_request(self, admin, booking_id):
        admin = self._get_existing_admin(admin)
        with global_lock(), UnitOfWork():
            booking = self.booking_repo.get_by_id(booking_id)
            if booking is None:
                raise RoomBookingError("존재하지 않는 예약입니다.")

            if booking.status != RoomBookingStatus.CHECKOUT_REQUESTED:
                raise RoomBookingError(
                    f"'{booking.status.value}' 상태의 예약은 퇴실 승인 처리할 수 없습니다."
                )

            end_time = datetime.fromisoformat(booking.end_time)
            self._require_current_boundary(end_time, "퇴실 승인")
            delay_minutes = 0

            updated = replace(
                booking,
                status=RoomBookingStatus.COMPLETED,
                completed_at=now_iso(),
                updated_at=now_iso(),
            )
            self.booking_repo.update(updated)
            self.audit_repo.log_action(
                actor_id=admin.id,
                action="approve_room_checkout_request",
                target_type="room_booking",
                target_id=booking_id,
                details=f"지연: {delay_minutes}분",
            )

            booking_user = self.user_repo.get_by_id(booking.user_id)
            if booking_user is None:
                raise RoomBookingError("존재하지 않는 사용자입니다.")

            self.penalty_service.record_normal_use(booking_user)

            return updated, delay_minutes

    def get_user_bookings(self, user_id):
        """사용자의 모든 예약 조회"""
        self._get_existing_user_by_id(user_id)
        return self.booking_repo.get_by_user(user_id)

    def get_user_active_bookings(self, user_id):
        """사용자의 활성 예약 조회"""
        self._get_existing_user_by_id(user_id)
        return self.booking_repo.get_quota_active_by_user(user_id)

    def get_all_bookings(self, admin):
        """모든 예약 조회 (관리자용)"""
        self._get_existing_admin(admin)
        return self.booking_repo.get_all()

    def get_room_operational_overview(self, admin):
        """회의실별 운영 현황 개요 조회 (관리자용)"""
        self._get_existing_admin(admin)
        now = self.clock.now()
        rooms = sorted(self.room_repo.get_all(), key=lambda room: room.name)
        relevant_statuses = {
            RoomBookingStatus.RESERVED,
            RoomBookingStatus.CHECKIN_REQUESTED,
            RoomBookingStatus.CHECKED_IN,
            RoomBookingStatus.CHECKOUT_REQUESTED,
        }

        bookings_by_room = {room.id: [] for room in rooms}
        for booking in self.booking_repo.get_all():
            if booking.status in relevant_statuses:
                bookings_by_room.setdefault(booking.room_id, []).append(booking)

        overview = []
        for room in rooms:
            room_bookings = bookings_by_room.get(room.id, [])
            current_bookings = []
            upcoming_bookings = []

            for booking in room_bookings:
                start_time = datetime.fromisoformat(booking.start_time)
                end_time = datetime.fromisoformat(booking.end_time)
                if booking.status in {
                    RoomBookingStatus.CHECKED_IN,
                    RoomBookingStatus.CHECKOUT_REQUESTED,
                } and start_time <= now <= end_time:
                    current_bookings.append(booking)
                elif booking.status in {
                    RoomBookingStatus.RESERVED,
                    RoomBookingStatus.CHECKIN_REQUESTED,
                } and start_time >= now:
                    upcoming_bookings.append(booking)

            current_bookings.sort(key=lambda item: item.start_time)
            upcoming_bookings.sort(key=lambda item: item.start_time)

            if current_bookings:
                operational_status = "사용중"
                display_bookings = current_bookings + upcoming_bookings
                display_bookings.sort(key=lambda item: item.start_time)
                reservation_summary = self._format_overview_summary(display_bookings)
            elif upcoming_bookings:
                operational_status = "예약있음"
                reservation_summary = self._format_overview_summary(upcoming_bookings)
            else:
                operational_status = "예약없음"
                reservation_summary = "X"

            overview.append(
                RoomOperationalOverview(
                    room_name=room.name,
                    capacity=room.capacity,
                    location=room.location,
                    operational_status=operational_status,
                    reservation_summary=reservation_summary,
                )
            )

        return overview

    def _format_overview_summary(self, bookings):
        ranges = []
        for booking in bookings:
            start_dt = datetime.fromisoformat(booking.start_time)
            end_dt = datetime.fromisoformat(booking.end_time)
            ranges.append(
                f"{start_dt.strftime('%Y-%m-%d')} ~ {end_dt.strftime('%Y-%m-%d')}"
            )
        return "\n".join(ranges)

    def get_room_bookings(self, room_id):
        """회의실별 예약 조회"""
        return self.booking_repo.get_by_room(room_id)

    def _has_active_or_future_room_bookings(self, room_id):
        now = self.clock.now()
        blocking_statuses = {
            RoomBookingStatus.PENDING,
            RoomBookingStatus.RESERVED,
            RoomBookingStatus.CHECKIN_REQUESTED,
            RoomBookingStatus.CHECKED_IN,
            RoomBookingStatus.CHECKOUT_REQUESTED,
        }
        for booking in self.booking_repo.get_by_room(room_id):
            if booking.status not in blocking_statuses:
                continue
            if datetime.fromisoformat(booking.end_time) > now:
                return True
        return False

    def _has_active_room_maintenance(self, room_id):
        return any(
            schedule.status in {"scheduled", "active"}
            for schedule in self.maintenance_repo.get_by_room(room_id)
        )

    def _ensure_room_resource_editable(self, room):
        if room.status != ResourceStatus.AVAILABLE:
            raise RoomBookingError("사용 가능한 회의실만 수정 또는 삭제할 수 있습니다.")
        if self._has_active_or_future_room_bookings(room.id):
            raise RoomBookingError("활성 또는 미래 예약이 있는 회의실은 수정 또는 삭제할 수 없습니다.")
        if self._has_active_room_maintenance(room.id):
            raise RoomBookingError("예정 또는 진행 중인 점검 일정이 있는 회의실은 수정 또는 삭제할 수 없습니다.")

    def add_room_resource(self, admin, name, capacity, location, description=""):
        admin = self._get_existing_admin(admin)
        try:
            capacity = int(capacity)
            validate_room_name(name)
            validate_room_capacity(capacity)
            validate_room_location(location)
        except (TypeError, ValueError) as error:
            raise RoomBookingError(str(error)) from error

        with global_lock(), UnitOfWork():
            rooms = self.room_repo.get_all()
            if len(rooms) >= MAX_ROOM_RESOURCES:
                raise RoomBookingError("회의실은 최대 20개까지 등록할 수 있습니다.")
            if any(room.name == name for room in rooms):
                raise RoomBookingError("이미 등록된 회의실 이름입니다.")

            room = Room(
                id=name,
                name=name,
                capacity=capacity,
                location=location,
                status=ResourceStatus.AVAILABLE,
                description=description or "자원관리",
            )
            self.room_repo.add(room)
            self.audit_repo.log_action(
                actor_id=admin.id,
                action="add_room_resource",
                target_type="room",
                target_id=room.id,
                details=f"회의실 추가: {room.name}",
            )
            return room

    def edit_room_resource(self, admin, room_id, capacity, location):
        admin = self._get_existing_admin(admin)
        try:
            capacity = int(capacity)
            validate_room_capacity(capacity)
            validate_room_location(location)
        except (TypeError, ValueError) as error:
            raise RoomBookingError(str(error)) from error

        with global_lock(), UnitOfWork():
            room = self.room_repo.get_by_id(room_id)
            if room is None:
                raise RoomBookingError("존재하지 않는 회의실입니다.")
            self._ensure_room_resource_editable(room)
            updated_room = replace(
                room,
                capacity=capacity,
                location=location,
                updated_at=now_iso(),
            )
            self.room_repo.update(updated_room)
            self.audit_repo.log_action(
                actor_id=admin.id,
                action="edit_room_resource",
                target_type="room",
                target_id=room.id,
                details=f"수정: {capacity}명, {location}",
            )
            return updated_room

    def delete_room_resource(self, admin, room_id):
        admin = self._get_existing_admin(admin)
        with global_lock(), UnitOfWork():
            room = self.room_repo.get_by_id(room_id)
            if room is None:
                raise RoomBookingError("존재하지 않는 회의실입니다.")
            self._ensure_room_resource_editable(room)
            self.room_repo.delete(room_id)
            self.audit_repo.log_action(
                actor_id=admin.id,
                action="delete_room_resource",
                target_type="room",
                target_id=room.id,
                details=f"회의실 삭제: {room.name}",
            )
            return room

    def update_room_status(self, admin, room_id, new_status):
        admin = self._get_existing_admin(admin)
        with global_lock(), UnitOfWork():
            room = self.room_repo.get_by_id(room_id)
            if room is None:
                raise RoomBookingError("존재하지 않는 회의실입니다.")

            cancelled_bookings = []

            # maintenance 또는 disabled로 변경 시 미래 예약 취소
            if new_status in {ResourceStatus.MAINTENANCE, ResourceStatus.DISABLED}:
                now = self.clock.now()
                for booking in self.booking_repo.get_by_room(room_id):
                    if booking.status == RoomBookingStatus.RESERVED:
                        start = datetime.fromisoformat(booking.start_time)
                        if start > now:
                            booking_user = self.user_repo.get_by_id(booking.user_id)
                            if booking_user is None:
                                raise RoomBookingError("존재하지 않는 사용자입니다.")
                            updated_booking = replace(
                                booking,
                                status=RoomBookingStatus.ADMIN_CANCELLED,
                                cancelled_at=now_iso(),
                                updated_at=now_iso(),
                            )
                            self.booking_repo.update(updated_booking)
                            cancelled_bookings.append(updated_booking)

            updated_room = replace(room, status=new_status, updated_at=now_iso())

            self.room_repo.update(updated_room)

            self.audit_repo.log_action(
                actor_id=admin.id,
                action="update_room_status",
                target_type="room",
                target_id=room_id,
                details=f"상태 변경: {new_status.value}, 취소된 예약: {len(cancelled_bookings)}건",
            )

            return updated_room, cancelled_bookings
