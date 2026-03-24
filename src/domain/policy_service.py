"""
정책 서비스 - 자동 처리 루틴

앱 시작, 로그인 직후, 예약 관련 작업 직전, 관리자 예약 관리 메뉴 진입 시 실행
"""

from datetime import datetime
from dataclasses import replace

from src.domain.models import (
    RoomBookingStatus,
    EquipmentBookingStatus,
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
from src.domain.penalty_service import PenaltyService, PenaltyError
from src.config import NO_SHOW_GRACE_MINUTES, PENALTY_BAN_THRESHOLD


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
    ):
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
        )

    def run_all_checks(self, current_time=None):
        """
        모든 정책 점검 루틴 실행

        Returns:
            dict: 키별 점검 결과 목록을 담은 딕셔너리입니다.
        """
        if current_time is None:
            current_time = datetime.now()

        results = {
            "no_show_room": [],
            "no_show_equipment": [],
            "penalty_reset_users": [],
            "restriction_expired_users": [],
            "banned_user_cancelled_bookings": [],
        }

        with global_lock(), UnitOfWork():
            # 1. 노쇼 판정
            no_show_rooms = self._check_room_no_shows(current_time)
            results["no_show_room"] = [b.id for b in no_show_rooms]

            no_show_equipment = self._check_equipment_no_shows(current_time)
            results["no_show_equipment"] = [b.id for b in no_show_equipment]

            # 2. 90일 경과 패널티 초기화
            reset_users = self._check_penalty_resets(current_time)
            results["penalty_reset_users"] = [u.id for u in reset_users]

            # 3. 제한 기간 만료 반영
            expired_users = self._check_restriction_expiry(current_time)
            results["restriction_expired_users"] = [u.id for u in expired_users]

            # 4. 6점 이상 사용자 미래 예약 자동 취소
            cancelled = self._cancel_banned_user_bookings(current_time)
            results["banned_user_cancelled_bookings"] = cancelled

        return results

    def _check_room_no_shows(self, current_time):
        """회의실 노쇼 판정"""
        no_shows = []
        pending = self.room_booking_repo.get_pending_checkin(
            current_time, NO_SHOW_GRACE_MINUTES
        )

        for booking in pending:
            # 노쇼로 상태 변경
            updated = replace(
                booking, status=RoomBookingStatus.NO_SHOW, updated_at=now_iso()
            )
            self.room_booking_repo.update(updated)

            # 패널티 적용
            user = self.user_repo.get_by_id(booking.user_id)
            if user is None:
                raise PenaltyError("존재하지 않는 사용자입니다.")
            self.penalty_service.apply_no_show(
                user=user, booking_type="room_booking", booking_id=booking.id
            )

            self.audit_repo.log_action(
                actor_id="system",
                action="auto_no_show_room",
                target_type="room_booking",
                target_id=booking.id,
                details="자동 노쇼 판정",
            )

            no_shows.append(updated)

        return no_shows

    def _check_equipment_no_shows(self, current_time):
        """장비 노쇼 판정"""
        no_shows = []
        pending = self.equipment_booking_repo.get_pending_checkout(
            current_time, NO_SHOW_GRACE_MINUTES
        )

        for booking in pending:
            # 노쇼로 상태 변경
            updated = replace(
                booking, status=EquipmentBookingStatus.NO_SHOW, updated_at=now_iso()
            )
            self.equipment_booking_repo.update(updated)

            # 패널티 적용
            user = self.user_repo.get_by_id(booking.user_id)
            if user is None:
                raise PenaltyError("존재하지 않는 사용자입니다.")
            self.penalty_service.apply_no_show(
                user=user, booking_type="equipment_booking", booking_id=booking.id
            )

            self.audit_repo.log_action(
                actor_id="system",
                action="auto_no_show_equipment",
                target_type="equipment_booking",
                target_id=booking.id,
                details="자동 노쇼 판정",
            )

            no_shows.append(updated)

        return no_shows

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
            # 3~5점: 전체 활성 예약 1건만 허용
            room_active = len(self.room_booking_repo.get_active_by_user(user.id))
            equipment_active = len(
                self.equipment_booking_repo.get_active_by_user(user.id)
            )
            total_active = room_active + equipment_active

            if total_active >= 1:
                return (
                    False,
                    1,
                    f"패널티로 인해 활성 예약 1건만 허용됩니다. "
                    f"현재 활성 예약: {total_active}건",
                )
            return (True, 1, "패널티로 인해 활성 예약 1건만 허용됩니다.")

        return (True, 6, "")  # 정상 상태: 회의실 3 + 장비 3

    def get_max_bookings_for_user(self, user):
        """
        사용자의 최대 예약 가능 수 반환

        Returns:
            (max_room_bookings: int, max_equipment_bookings: int)
        """
        can_book, max_total, _ = self.check_user_can_book(user)

        if not can_book:
            return (0, 0)

        if max_total == 1:
            # 제한 상태: 전체 1건
            room_active = len(self.room_booking_repo.get_active_by_user(user.id))
            equipment_active = len(
                self.equipment_booking_repo.get_active_by_user(user.id)
            )

            if room_active >= 1:
                return (0, 0)
            if equipment_active >= 1:
                return (0, 0)
            return (1, 1)  # 둘 중 하나만 가능

        # 정상 상태
        from src.config import MAX_ACTIVE_ROOM_BOOKINGS, MAX_ACTIVE_EQUIPMENT_BOOKINGS

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
            if total_active >= 1:
                return {
                    "can_book": False,
                    "room_limit": 0,
                    "equipment_limit": 0,
                    "message": f"패널티로 인해 활성 예약 1건만 허용됩니다. 현재 활성 예약: {total_active}건",
                }
            return {
                "can_book": True,
                "room_limit": 1,
                "equipment_limit": 1,
                "message": "패널티로 인해 활성 예약 1건만 허용됩니다.",
            }

        return {
            "can_book": True,
            "room_limit": 0 if room_active >= 1 else 1,
            "equipment_limit": 0 if equipment_active >= 1 else 1,
            "message": "",
        }
