"""
회의실 예약 서비스
"""

from datetime import datetime, timedelta
from dataclasses import replace

from src.domain.models import (
    User,
    RoomBooking,
    RoomBookingStatus,
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
    RoomRepository,
    RoomBookingRepository,
    EquipmentBookingRepository,
    AuditLogRepository,
    UnitOfWork,
)
from src.storage.file_lock import global_lock
from src.runtime_clock import get_runtime_clock
from src.config import (
    MAX_BOOKING_DAYS,
    TIME_SLOT_MINUTES,
    MAX_ACTIVE_ROOM_BOOKINGS,
)


class RoomBookingError(Exception):
    """회의실 예약 처리 중 발생하는 예외입니다."""

    pass


class AdminRequiredError(Exception):
    """관리자 권한이 필요한 작업에서 발생하는 예외입니다."""

    pass


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

        if status["is_restricted"]:
            total_active = len(
                self.booking_repo.get_active_by_user(current_user.id)
            ) + len(self.equipment_booking_repo.get_active_by_user(current_user.id))
            if total_active >= 1:
                raise RoomBookingError(
                    f"패널티로 인해 활성 예약 1건만 허용됩니다. 현재 활성 예약: {total_active}건"
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

    def _require_current_boundary(self, boundary_time, action_name):
        current_time = self.clock.now()
        if boundary_time != current_time:
            raise RoomBookingError(
                f"{action_name}은 현재 운영 시점({current_time.strftime('%Y-%m-%d %H:%M')})과 일치하는 예약에서만 가능합니다."
            )

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
            conflicts = self.booking_repo.get_conflicting(
                room.id, start_time.isoformat(), end_time.isoformat()
            )
            if not conflicts:
                available.append(room)
        return available

    def create_daily_booking(
        self, user, room_id, start_date, end_date, attendee_count, max_active=1
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

                active_bookings = self.booking_repo.get_active_by_user(user.id)
                if len(active_bookings) >= max_active:
                    raise RoomBookingError(
                        f"활성 회의실 예약 한도({max_active}건)를 초과했습니다. 현재 활성 예약: {len(active_bookings)}건"
                    )

                conflicts = self.booking_repo.get_conflicting(
                    room_id, start_time.isoformat(), end_time.isoformat()
                )
                if conflicts:
                    raise RoomBookingError(
                        "해당 기간에 이미 예약이 있습니다. 다른 회의실 또는 다른 날짜를 선택해주세요."
                    )

                booking = RoomBooking(
                    id=generate_id(),
                    user_id=user.id,
                    room_id=room_id,
                    start_time=start_time.isoformat(),
                    end_time=end_time.isoformat(),
                    status=RoomBookingStatus.RESERVED,
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

    def modify_daily_booking(self, user, booking_id, start_date, end_date):
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
                conflicts = self.booking_repo.get_conflicting(
                    booking.room_id,
                    start_time.isoformat(),
                    end_time.isoformat(),
                    exclude_id=booking_id,
                )
                if conflicts:
                    raise RoomBookingError(
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
                conflicts = self.booking_repo.get_conflicting(
                    booking.room_id,
                    start_time.isoformat(),
                    end_time.isoformat(),
                    exclude_id=booking_id,
                )
                if conflicts:
                    raise RoomBookingError("해당 기간에 이미 예약이 있습니다.")

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
        self, user, room_id, start_time, end_time, max_active=MAX_ACTIVE_ROOM_BOOKINGS
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

                self._validate_booking_time(start_time, end_time)

                active_bookings = self.booking_repo.get_active_by_user(user.id)
                if len(active_bookings) >= effective_max_active:
                    raise RoomBookingError(
                        f"활성 예약 한도({effective_max_active}건)를 초과했습니다. "
                        f"현재 활성 예약: {len(active_bookings)}건"
                    )

                conflicts = self.booking_repo.get_conflicting(
                    room_id, start_time.isoformat(), end_time.isoformat()
                )
                if conflicts:
                    raise RoomBookingError(
                        "해당 시간대에 이미 예약이 있습니다. 다른 시간을 선택해주세요."
                    )

                booking = RoomBooking(
                    id=generate_id(),
                    user_id=user.id,
                    room_id=room_id,
                    start_time=start_time.isoformat(),
                    end_time=end_time.isoformat(),
                    status=RoomBookingStatus.RESERVED,
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
        """예약 시간 유효성 검사"""
        now = self.clock.now()

        # 과거 시간 예약 불가
        if start_time < now:
            raise RoomBookingError("과거 시간은 예약할 수 없습니다.")

        # 종료가 시작보다 나중이어야 함
        if end_time <= start_time:
            raise RoomBookingError("종료 시간은 시작 시간 이후여야 합니다.")

        # 14일 이내 예약만 가능
        max_date = now + timedelta(days=MAX_BOOKING_DAYS)
        if start_time > max_date:
            raise RoomBookingError(f"{MAX_BOOKING_DAYS}일 이내의 예약만 가능합니다.")

        # 30분 단위 확인
        if start_time.minute % TIME_SLOT_MINUTES != 0 or start_time.second != 0:
            raise RoomBookingError(f"예약은 {TIME_SLOT_MINUTES}분 단위로만 가능합니다.")

        if end_time.minute % TIME_SLOT_MINUTES != 0 or end_time.second != 0:
            raise RoomBookingError(f"예약은 {TIME_SLOT_MINUTES}분 단위로만 가능합니다.")

    def modify_booking(self, user, booking_id, new_start_time, new_end_time):
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

                self._validate_booking_time(new_start_time, new_end_time)

                conflicts = self.booking_repo.get_conflicting(
                    booking.room_id,
                    new_start_time.isoformat(),
                    new_end_time.isoformat(),
                    exclude_id=booking_id,
                )
                if conflicts:
                    raise RoomBookingError(
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
                    action="modify_room_booking",
                    target_type="room_booking",
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
                    raise RoomBookingError("존재하지 않는 예약입니다.")

                if booking.user_id != user.id:
                    raise RoomBookingError("본인의 예약만 취소할 수 있습니다.")

                if booking.status != RoomBookingStatus.RESERVED:
                    raise RoomBookingError(
                        f"'{booking.status.value}' 상태의 예약은 취소할 수 없습니다."
                    )

                is_late_cancel = False

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

                return updated, is_late_cancel

    def admin_cancel_booking(self, admin, booking_id, reason=""):
        admin = self._get_existing_admin(admin)
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

                self._validate_booking_time(new_start_time, new_end_time)

                conflicts = self.booking_repo.get_conflicting(
                    booking.room_id,
                    new_start_time.isoformat(),
                    new_end_time.isoformat(),
                    exclude_id=booking_id,
                )
                if conflicts:
                    raise RoomBookingError("해당 시간대에 이미 예약이 있습니다.")

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

                if booking.status != RoomBookingStatus.RESERVED:
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
            self._require_current_boundary(
                datetime.fromisoformat(booking.end_time), "퇴실 신청"
            )

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

    def mark_no_show(self, booking_id, actor_id="system"):
        """노쇼 처리"""
        with global_lock(), UnitOfWork():
            booking = self.booking_repo.get_by_id(booking_id)
            if booking is None:
                raise RoomBookingError("존재하지 않는 예약입니다.")

            if booking.status != RoomBookingStatus.RESERVED:
                raise RoomBookingError("예약 대기 상태만 노쇼 처리할 수 있습니다.")
            self._require_current_boundary(
                datetime.fromisoformat(booking.start_time), "노쇼 처리"
            )

            updated = replace(
                booking, status=RoomBookingStatus.NO_SHOW, updated_at=now_iso()
            )

            self.booking_repo.update(updated)

            self.audit_repo.log_action(
                actor_id=actor_id,
                action="room_no_show",
                target_type="room_booking",
                target_id=booking_id,
                details="",
            )

            booking_user = self.user_repo.get_by_id(booking.user_id)
            if booking_user is None:
                raise RoomBookingError("존재하지 않는 사용자입니다.")
            self.penalty_service.apply_no_show(
                user=booking_user,
                booking_type="room_booking",
                booking_id=booking_id,
                actor_id=actor_id,
            )

            return updated

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

    def get_room_bookings(self, room_id):
        """회의실별 예약 조회"""
        return self.booking_repo.get_by_room(room_id)

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
