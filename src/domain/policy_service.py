"""정책 서비스 - 가상 시점 전환과 상태 점검을 담당합니다."""

from datetime import datetime
from dataclasses import replace

from src.domain.models import (
    RoomBookingStatus,
    EquipmentBookingStatus,
    UserRole,
    now_iso,
)
from src.storage.repositories import (
    UserRepository,
    RoomBookingRepository,
    EquipmentBookingRepository,
    PenaltyRepository,
    AuditLogRepository,
    UnitOfWork,
)
from src.storage.file_lock import global_lock
from src.storage.integrity import validate_all_data_files
from src.domain.penalty_service import PenaltyService, PenaltyError
from src.config import (
    PENALTY_BAN_THRESHOLD,
    MAX_ACTIVE_ROOM_BOOKINGS,
    MAX_ACTIVE_EQUIPMENT_BOOKINGS,
)
from src.runtime_clock import get_runtime_clock


class PolicyService:
    """정책 자동 처리 서비스"""

    def __init__(
        self,
        user_repo=None,
        room_booking_repo=None,
        equipment_booking_repo=None,
        penalty_repo=None,
        audit_repo=None,
        penalty_service=None,
        clock=None,
    ):
        self.clock = clock or get_runtime_clock()
        self.user_repo = user_repo or UserRepository()
        self.room_booking_repo = room_booking_repo or RoomBookingRepository()
        self.equipment_booking_repo = (
            equipment_booking_repo or EquipmentBookingRepository()
        )
        self.penalty_repo = penalty_repo or PenaltyRepository()
        self.audit_repo = audit_repo or AuditLogRepository()
        self.penalty_service = penalty_service or PenaltyService(
            user_repo=self.user_repo,
            penalty_repo=self.penalty_repo,
            audit_repo=self.audit_repo,
            clock=self.clock,
        )

    def run_all_checks(self, current_time=None):
        if current_time is None:
            current_time = self.clock.now()

        with global_lock():
            validate_all_data_files()
            with UnitOfWork():
                return self._run_checks_locked(current_time)

    def _run_checks_locked(self, current_time):
        results = {
            "penalty_reset_users": [],
            "restriction_expired_users": [],
            "banned_user_cancelled_bookings": [],
        }

        reset_users = self._check_penalty_resets(current_time)
        results["penalty_reset_users"] = [u.id for u in reset_users]

        expired_users = self._check_restriction_expiry(current_time)
        results["restriction_expired_users"] = [u.id for u in expired_users]

        cancelled = self._cancel_banned_user_bookings(current_time)
        results["banned_user_cancelled_bookings"] = cancelled
        return results

    def prepare_advance(self, current_time=None, actor_id="system"):
        validate_all_data_files()
        if current_time is None:
            current_time = self.clock.now()
        return self._build_advance_state(current_time, actor_id=actor_id)

    def advance_time(self, actor_id="system", force=False):
        with global_lock(), UnitOfWork():
            validate_all_data_files()
            current_time = self.clock.now()
            state = self._build_advance_state(current_time, actor_id=actor_id)
            if state["blockers"] and not force:
                self.audit_repo.log_action(
                    actor_id=actor_id,
                    action="clock_advance_blocked",
                    target_type="system_clock",
                    target_id=current_time.isoformat(),
                    details=" | ".join(state["blockers"]),
                )
                return state

            penalty_owner_id = self._resolve_forced_penalty_owner_id(actor_id, force)
            auto_events = self._handle_boundary_automation(
                current_time,
                actor_id=actor_id,
                penalty_owner_id=penalty_owner_id,
            )

            next_time = self.clock.advance()
            maintenance = self._run_checks_locked(next_time)
            events = list(state["events"])
            events.extend(auto_events)
            events.extend(self._build_post_advance_events(next_time, maintenance))

            self.audit_repo.log_action(
                actor_id=actor_id,
                action="clock_advance",
                target_type="system_clock",
                target_id=next_time.isoformat(),
                details=" | ".join(events) if events else "운영 시점 이동",
            )

            state["next_time"] = next_time
            state["events"] = events
            state["maintenance"] = maintenance
            state["forced"] = force
            state["can_advance"] = True
            return state

    def _resolve_forced_penalty_owner_id(self, actor_id, force):
        if not force:
            return None
        actor = self.user_repo.get_by_id(actor_id)
        if actor is None or actor.role == UserRole.ADMIN:
            return None
        return actor.id

    def _get_penalty_user(self, booking_user_id, penalty_owner_id=None):
        target_user_id = penalty_owner_id or booking_user_id
        return self.user_repo.get_by_id(target_user_id)

    def _handle_boundary_automation(self, current_time, actor_id="system", penalty_owner_id=None):
        if current_time.hour == 9:
            return self._auto_handle_start_slot(
                current_time,
                actor_id=actor_id,
                penalty_owner_id=penalty_owner_id,
            )
        if current_time.hour == 18:
            return self._auto_handle_end_slot(
                current_time,
                actor_id=actor_id,
                penalty_owner_id=penalty_owner_id,
            )
        return []

    def _auto_handle_start_slot(self, current_time, actor_id="system", penalty_owner_id=None):
        events = []
        now = now_iso()

        for booking in self.room_booking_repo.get_all():
            if datetime.fromisoformat(booking.start_time) != current_time:
                continue
            if booking.status == RoomBookingStatus.CHECKIN_REQUESTED:
                self.room_booking_repo.update(
                    replace(
                        booking,
                        status=RoomBookingStatus.CHECKED_IN,
                        checked_in_at=now,
                        updated_at=now,
                    )
                )
                events.append(f"회의실 예약 {booking.id[:8]} 자동 체크인 승인")
            elif booking.status == RoomBookingStatus.RESERVED:
                self.room_booking_repo.update(
                    replace(
                        booking,
                        status=RoomBookingStatus.ADMIN_CANCELLED,
                        cancelled_at=now,
                        updated_at=now,
                    )
                )
                user = self._get_penalty_user(booking.user_id, penalty_owner_id)
                if user:
                    self.penalty_service.apply_late_cancel(
                        user=user,
                        booking_type="room_booking",
                        booking_id=booking.id,
                        actor_id=actor_id,
                    )
                events.append(f"회의실 예약 {booking.id[:8]} 시작 미처리 자동 취소")

        for booking in self.equipment_booking_repo.get_all():
            if datetime.fromisoformat(booking.start_time) != current_time:
                continue
            if booking.status == EquipmentBookingStatus.PICKUP_REQUESTED:
                self.equipment_booking_repo.update(
                    replace(
                        booking,
                        status=EquipmentBookingStatus.CHECKED_OUT,
                        checked_out_at=now,
                        updated_at=now,
                    )
                )
                events.append(f"장비 예약 {booking.id[:8]} 자동 픽업 승인")
            elif booking.status == EquipmentBookingStatus.RESERVED:
                self.equipment_booking_repo.update(
                    replace(
                        booking,
                        status=EquipmentBookingStatus.ADMIN_CANCELLED,
                        cancelled_at=now,
                        updated_at=now,
                    )
                )
                user = self._get_penalty_user(booking.user_id, penalty_owner_id)
                if user:
                    self.penalty_service.apply_late_cancel(
                        user=user,
                        booking_type="equipment_booking",
                        booking_id=booking.id,
                        actor_id=actor_id,
                    )
                events.append(f"장비 예약 {booking.id[:8]} 시작 미처리 자동 취소")

        return events

    def _auto_handle_end_slot(self, current_time, actor_id="system", penalty_owner_id=None):
        events = []
        now = now_iso()

        for booking in self.room_booking_repo.get_all():
            if datetime.fromisoformat(booking.end_time) != current_time:
                continue
            if booking.status == RoomBookingStatus.CHECKOUT_REQUESTED:
                self.room_booking_repo.update(
                    replace(
                        booking,
                        status=RoomBookingStatus.COMPLETED,
                        completed_at=now,
                        updated_at=now,
                    )
                )
                user = self.user_repo.get_by_id(booking.user_id)
                if user:
                    self.penalty_service.record_normal_use(user)
                events.append(f"회의실 예약 {booking.id[:8]} 자동 퇴실 승인")
            elif booking.status == RoomBookingStatus.CHECKED_IN:
                self.room_booking_repo.update(
                    replace(
                        booking,
                        status=RoomBookingStatus.COMPLETED,
                        completed_at=now,
                        updated_at=now,
                    )
                )
                user = self._get_penalty_user(booking.user_id, penalty_owner_id)
                if user:
                    self.penalty_service.apply_late_return(
                        user=user,
                        booking_type="room_booking",
                        booking_id=booking.id,
                        delay_minutes=60,
                        actor_id=actor_id,
                    )
                events.append(f"회의실 예약 {booking.id[:8]} 지연 퇴실 자동 패널티")

        for booking in self.equipment_booking_repo.get_all():
            if datetime.fromisoformat(booking.end_time) != current_time:
                continue
            if booking.status == EquipmentBookingStatus.RETURN_REQUESTED:
                self.equipment_booking_repo.update(
                    replace(
                        booking,
                        status=EquipmentBookingStatus.RETURNED,
                        returned_at=now,
                        updated_at=now,
                    )
                )
                user = self.user_repo.get_by_id(booking.user_id)
                if user:
                    self.penalty_service.record_normal_use(user)
                events.append(f"장비 예약 {booking.id[:8]} 자동 반납 승인")
            elif booking.status == EquipmentBookingStatus.CHECKED_OUT:
                self.equipment_booking_repo.update(
                    replace(
                        booking,
                        status=EquipmentBookingStatus.RETURNED,
                        returned_at=now,
                        updated_at=now,
                    )
                )
                user = self._get_penalty_user(booking.user_id, penalty_owner_id)
                if user:
                    self.penalty_service.apply_late_return(
                        user=user,
                        booking_type="equipment_booking",
                        booking_id=booking.id,
                        delay_minutes=60,
                        actor_id=actor_id,
                    )
                events.append(f"장비 예약 {booking.id[:8]} 지연 반납 자동 패널티")

        return events

    def _build_force_notice(self, actor_id, blockers):
        if not blockers:
            return ""
        actor = self.user_repo.get_by_id(actor_id)
        if actor is None or actor.role == UserRole.ADMIN:
            return "미해결 사건이 있어도 강행할 수 있습니다. 자동 패널티는 기존 책임 사용자 기준으로 처리됩니다."
        return "강행하면 이 이동으로 발생하는 자동 패널티가 모두 현재 사용자에게 부과됩니다."

    def _build_advance_state(self, current_time, actor_id="system"):
        next_time = self.clock.next_slot()
        blockers = []

        if current_time.hour == 9:
            blockers.extend(self._collect_start_blockers(current_time))
            events = [
                f"{next_time.strftime('%Y-%m-%d %H:%M')}로 이동 준비",
                f"당일 종료 예정 회의실 {self._count_room_endings(next_time)}건, 장비 {self._count_equipment_endings(next_time)}건",
            ]
        else:
            blockers.extend(self._collect_end_blockers(current_time))
            events = [
                f"{next_time.strftime('%Y-%m-%d %H:%M')}로 이동 준비",
                f"다음 시점 시작 예정 회의실 {self._count_room_starts(next_time)}건, 장비 {self._count_equipment_starts(next_time)}건",
            ]

        return {
            "can_advance": len(blockers) == 0,
            "current_time": current_time,
            "next_time": next_time,
            "blockers": blockers,
            "events": events,
            "force_notice": self._build_force_notice(actor_id, blockers),
        }

    def _user_label(self, user_id):
        user = self.user_repo.get_by_id(user_id)
        if user is None:
            return user_id
        return user.username

    def _collect_start_blockers(self, current_time):
        blockers = []

        for booking in self.room_booking_repo.get_all():
            if booking.status not in {
                RoomBookingStatus.RESERVED,
                RoomBookingStatus.CHECKIN_REQUESTED,
            }:
                continue
            if datetime.fromisoformat(booking.start_time) != current_time:
                continue
            if booking.status == RoomBookingStatus.CHECKIN_REQUESTED:
                blockers.append(
                    f"회의실 예약 {booking.id[:8]} ({self._user_label(booking.user_id)})은 체크인 승인 대기 상태입니다."
                )
            else:
                blockers.append(
                    f"회의실 예약 {booking.id[:8]} ({self._user_label(booking.user_id)})은 체크인 요청 또는 자동 취소 처리가 필요합니다."
                )

        for booking in self.equipment_booking_repo.get_all():
            if booking.status not in {
                EquipmentBookingStatus.RESERVED,
                EquipmentBookingStatus.PICKUP_REQUESTED,
            }:
                continue
            if datetime.fromisoformat(booking.start_time) != current_time:
                continue
            if booking.status == EquipmentBookingStatus.PICKUP_REQUESTED:
                blockers.append(
                    f"장비 예약 {booking.id[:8]} ({self._user_label(booking.user_id)})은 픽업 승인 대기 상태입니다."
                )
            else:
                blockers.append(
                    f"장비 예약 {booking.id[:8]} ({self._user_label(booking.user_id)})은 픽업 요청 또는 자동 취소 처리가 필요합니다."
                )

        return blockers

    def _collect_end_blockers(self, current_time):
        blockers = []

        for booking in self.room_booking_repo.get_all():
            if datetime.fromisoformat(booking.end_time) != current_time:
                continue
            if booking.status == RoomBookingStatus.CHECKED_IN:
                blockers.append(
                    f"회의실 예약 {booking.id[:8]} ({self._user_label(booking.user_id)})은 사용자 퇴실 신청이 필요합니다."
                )
            elif booking.status == RoomBookingStatus.CHECKOUT_REQUESTED:
                blockers.append(
                    f"회의실 예약 {booking.id[:8]} ({self._user_label(booking.user_id)})은 관리자 퇴실 승인이 필요합니다."
                )

        for booking in self.equipment_booking_repo.get_all():
            if datetime.fromisoformat(booking.end_time) != current_time:
                continue
            if booking.status == EquipmentBookingStatus.CHECKED_OUT:
                blockers.append(
                    f"장비 예약 {booking.id[:8]} ({self._user_label(booking.user_id)})은 사용자 반납 신청이 필요합니다."
                )
            elif booking.status == EquipmentBookingStatus.RETURN_REQUESTED:
                blockers.append(
                    f"장비 예약 {booking.id[:8]} ({self._user_label(booking.user_id)})은 관리자 반납 승인이 필요합니다."
                )

        return blockers

    def _count_room_starts(self, target_time):
        return len(
            [
                booking
                for booking in self.room_booking_repo.get_all()
                if booking.status
                in {RoomBookingStatus.RESERVED, RoomBookingStatus.CHECKIN_REQUESTED}
                and datetime.fromisoformat(booking.start_time) == target_time
            ]
        )

    def _count_equipment_starts(self, target_time):
        return len(
            [
                booking
                for booking in self.equipment_booking_repo.get_all()
                if booking.status
                in {EquipmentBookingStatus.RESERVED, EquipmentBookingStatus.PICKUP_REQUESTED}
                and datetime.fromisoformat(booking.start_time) == target_time
            ]
        )

    def _count_room_endings(self, target_time):
        return len(
            [
                booking
                for booking in self.room_booking_repo.get_all()
                if booking.status
                in {RoomBookingStatus.CHECKED_IN, RoomBookingStatus.CHECKOUT_REQUESTED}
                and datetime.fromisoformat(booking.end_time) == target_time
            ]
        )

    def _count_equipment_endings(self, target_time):
        return len(
            [
                booking
                for booking in self.equipment_booking_repo.get_all()
                if booking.status
                in {
                    EquipmentBookingStatus.CHECKED_OUT,
                    EquipmentBookingStatus.RETURN_REQUESTED,
                }
                and datetime.fromisoformat(booking.end_time) == target_time
            ]
        )

    def _build_post_advance_events(self, current_time, maintenance):
        events = [f"운영 시점이 {current_time.strftime('%Y-%m-%d %H:%M')}로 이동했습니다."]

        reset_count = len(maintenance["penalty_reset_users"])
        expired_count = len(maintenance["restriction_expired_users"])
        cancelled_count = len(maintenance["banned_user_cancelled_bookings"])

        if reset_count:
            events.append(f"90일 경과 패널티 초기화 {reset_count}건")
        if expired_count:
            events.append(f"이용 제한 만료 처리 {expired_count}건")
        if cancelled_count:
            events.append(f"이용 금지 사용자 미래 예약 자동 취소 {cancelled_count}건")

        return events

    def _check_penalty_resets(self, current_time):
        """90일 경과 패널티 초기화"""
        reset_users = []

        for user in self.user_repo.get_all():
            if user.penalty_points > 0:
                if self.penalty_service.check_90_day_reset(user, current_time):
                    reset_users.append(user)

        return reset_users

    def _check_restriction_expiry(self, current_time):
        """제한 기간 만료 반영"""
        expired_users = []

        for user in self.user_repo.get_all():
            if user.restriction_until:
                restriction_end = datetime.fromisoformat(user.restriction_until)
                if restriction_end <= current_time:
                    # 제한 기간 만료 - restriction_until 초기화
                    updated = replace(
                        user, restriction_until=None, updated_at=now_iso()
                    )
                    self.user_repo.update(updated)

                    self.audit_repo.log_action(
                        actor_id="system",
                        action="restriction_expired",
                        target_type="user",
                        target_id=user.id,
                        details="제한 기간 만료",
                    )

                    expired_users.append(updated)

        return expired_users

    def _cancel_banned_user_bookings(self, current_time):
        """6점 이상 사용자의 미래 예약 자동 취소"""
        cancelled_ids = []

        for user in self.user_repo.get_all():
            if user.penalty_points >= PENALTY_BAN_THRESHOLD:
                # 회의실 미래 예약 취소
                for booking in self.room_booking_repo.get_by_user(user.id):
                    if booking.status == RoomBookingStatus.RESERVED:
                        start = datetime.fromisoformat(booking.start_time)
                        if start > current_time:
                            updated = replace(
                                booking,
                                status=RoomBookingStatus.ADMIN_CANCELLED,
                                cancelled_at=now_iso(),
                                updated_at=now_iso(),
                            )
                            self.room_booking_repo.update(updated)
                            cancelled_ids.append(booking.id)

                            self.audit_repo.log_action(
                                actor_id="system",
                                action="auto_cancel_banned_user",
                                target_type="room_booking",
                                target_id=booking.id,
                                details=f"사용자 {user.username} 이용 금지로 인한 자동 취소",
                            )

                # 장비 미래 예약 취소
                for booking in self.equipment_booking_repo.get_by_user(user.id):
                    if booking.status == EquipmentBookingStatus.RESERVED:
                        start = datetime.fromisoformat(booking.start_time)
                        if start > current_time:
                            updated = replace(
                                booking,
                                status=EquipmentBookingStatus.ADMIN_CANCELLED,
                                cancelled_at=now_iso(),
                                updated_at=now_iso(),
                            )
                            self.equipment_booking_repo.update(updated)
                            cancelled_ids.append(booking.id)

                            self.audit_repo.log_action(
                                actor_id="system",
                                action="auto_cancel_banned_user",
                                target_type="equipment_booking",
                                target_id=booking.id,
                                details=f"사용자 {user.username} 이용 금지로 인한 자동 취소",
                            )

        return cancelled_ids

    def check_user_can_book(self, user):
        """
        사용자가 예약 가능한지 확인

        Returns:
            (can_book: bool, max_active_total: int, message: str)
        """
        status = self.penalty_service.get_user_status(user)

        if status.get("is_banned"):
            return (
                False,
                0,
                f"이용이 금지된 상태입니다. 금지 해제일: {status.get('restriction_until', '알 수 없음')}",
            )

        if status.get("is_restricted"):
            room_active = len(self.room_booking_repo.get_active_by_user(user.id))
            equipment_active = len(
                self.equipment_booking_repo.get_active_by_user(user.id)
            )

            if room_active >= MAX_ACTIVE_ROOM_BOOKINGS and equipment_active >= MAX_ACTIVE_EQUIPMENT_BOOKINGS:
                return (
                    False,
                    MAX_ACTIVE_ROOM_BOOKINGS + MAX_ACTIVE_EQUIPMENT_BOOKINGS,
                    "패널티로 인해 추가 예약이 불가합니다.",
                )
            return (
                True,
                MAX_ACTIVE_ROOM_BOOKINGS + MAX_ACTIVE_EQUIPMENT_BOOKINGS,
                "패널티로 인해 각 예약 유형별 1건까지만 유지할 수 있습니다.",
            )

        return (
            True,
            MAX_ACTIVE_ROOM_BOOKINGS + MAX_ACTIVE_EQUIPMENT_BOOKINGS,
            "",
        )

    def get_max_bookings_for_user(self, user):
        """
        사용자의 최대 예약 가능 수 반환

        Returns:
            (max_room_bookings: int, max_equipment_bookings: int)
        """
        can_book, max_total, _ = self.check_user_can_book(user)

        if not can_book:
            return (0, 0)

        if max_total == MAX_ACTIVE_ROOM_BOOKINGS + MAX_ACTIVE_EQUIPMENT_BOOKINGS:
            room_active = len(self.room_booking_repo.get_active_by_user(user.id))
            equipment_active = len(
                self.equipment_booking_repo.get_active_by_user(user.id)
            )
            return (
                0 if room_active >= MAX_ACTIVE_ROOM_BOOKINGS else MAX_ACTIVE_ROOM_BOOKINGS,
                0 if equipment_active >= MAX_ACTIVE_EQUIPMENT_BOOKINGS else MAX_ACTIVE_EQUIPMENT_BOOKINGS,
            )

        return (MAX_ACTIVE_ROOM_BOOKINGS, MAX_ACTIVE_EQUIPMENT_BOOKINGS)

    def get_user_flow_limits(self, user):
        status = self.penalty_service.get_user_status(user)
        room_active = len(self.room_booking_repo.get_active_by_user(user.id))
        equipment_active = len(self.equipment_booking_repo.get_active_by_user(user.id))
        total_active = room_active + equipment_active

        if status.get("is_banned"):
            return {
                "can_book": False,
                "room_limit": 0,
                "equipment_limit": 0,
                "message": f"이용이 금지된 상태입니다. 금지 해제일: {status.get('restriction_until', '알 수 없음')}",
            }

        if status.get("is_restricted"):
            room_limit = 0 if room_active >= MAX_ACTIVE_ROOM_BOOKINGS else MAX_ACTIVE_ROOM_BOOKINGS
            equipment_limit = 0 if equipment_active >= MAX_ACTIVE_EQUIPMENT_BOOKINGS else MAX_ACTIVE_EQUIPMENT_BOOKINGS
            if room_limit == 0 and equipment_limit == 0:
                return {
                    "can_book": False,
                    "room_limit": room_limit,
                    "equipment_limit": equipment_limit,
                    "message": "패널티로 인해 추가 예약이 불가합니다.",
                }
            return {
                "can_book": True,
                "room_limit": room_limit,
                "equipment_limit": equipment_limit,
                "message": "패널티로 인해 각 예약 유형별 1건까지만 유지할 수 있습니다.",
            }

        return {
            "can_book": True,
            "room_limit": 0 if room_active >= 1 else 1,
            "equipment_limit": 0 if equipment_active >= 1 else 1,
            "message": "",
        }
