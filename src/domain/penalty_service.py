"""
패널티 서비스 - 패널티 점수 계산 및 적용
"""

from datetime import datetime, timedelta
from math import ceil
from dataclasses import replace

from src.domain.models import (
    Penalty,
    PenaltyReason,
    UserRole,
    generate_id,
    now_iso,
)
from src.domain.restriction_rules import evaluate_user_restriction
from src.storage.repositories import (
    UserRepository,
    PenaltyRepository,
    AuditLogRepository,
    UnitOfWork,
)
from src.storage.file_lock import global_lock
from src.config import (
    NO_SHOW_PENALTY,
    LATE_CANCEL_PENALTY,
    MAX_DAMAGE_PENALTY,
    PENALTY_WARNING_THRESHOLD,
    PENALTY_RESTRICTION_THRESHOLD,
    PENALTY_BAN_THRESHOLD,
    RESTRICTION_DURATION_DAYS,
    BAN_DURATION_DAYS,
    PENALTY_RESET_DAYS,
    STREAK_BONUS_COUNT,
)


class PenaltyError(Exception):
    """패널티 관련 예외"""


class AdminRequiredError(Exception):
    """관리자 권한 필요 예외"""


def _require_admin(user):
    """관리자 권한 확인"""
    if user.role != UserRole.ADMIN:
        raise AdminRequiredError("관리자만 수행할 수 있는 작업입니다.")


class PenaltyService:
    """패널티 서비스"""

    def __init__(self, user_repo=None, penalty_repo=None, audit_repo=None):
        self.user_repo = user_repo or UserRepository()
        self.penalty_repo = penalty_repo or PenaltyRepository()
        self.audit_repo = audit_repo or AuditLogRepository()

    def _get_existing_admin(self, admin):
        _require_admin(admin)
        current_admin = self.user_repo.get_by_id(admin.id)
        if current_admin is None or current_admin.role != UserRole.ADMIN:
            raise AdminRequiredError("관리자만 수행할 수 있는 작업입니다.")
        return current_admin

    def _get_existing_user(self, user):
        current_user = self.user_repo.get_by_id(user.id)
        if current_user is None:
            raise PenaltyError("존재하지 않는 사용자입니다.")
        return current_user

    def _get_existing_user_by_id(self, user_id):
        current_user = self.user_repo.get_by_id(user_id)
        if current_user is None:
            raise PenaltyError("존재하지 않는 사용자입니다.")
        return current_user

    def apply_no_show(self, user, booking_type, booking_id, actor_id="system"):
        """
        노쇼 패널티 적용 (+3점)

        Args:
            user: 대상 사용자
            booking_type: 'room_booking' or 'equipment_booking'
            booking_id: 예약 ID
            actor_id: 수행자 ID

        Returns:
            생성된 패널티
        """
        user = self._get_existing_user(user)
        with global_lock(), UnitOfWork():
            penalty = Penalty(
                id=generate_id(),
                user_id=user.id,
                reason=PenaltyReason.NO_SHOW,
                points=NO_SHOW_PENALTY,
                related_type=booking_type,
                related_id=booking_id,
                memo="예약 시작 후 15분 내 미출석",
                updated_at=now_iso(),
            )

            self.penalty_repo.add(penalty)
            self._update_user_penalty_points(user, NO_SHOW_PENALTY)

            self.audit_repo.log_action(
                actor_id=actor_id,
                action="apply_no_show_penalty",
                target_type="user",
                target_id=user.id,
                details=f"노쇼 패널티 +{NO_SHOW_PENALTY}점, 예약: {booking_type}/{booking_id}",
            )

            return penalty

    def apply_late_cancel(self, user, booking_type, booking_id, actor_id="system"):
        """
        직전 취소 패널티 적용 (+2점)

        Args:
            user: 대상 사용자
            booking_type: 'room_booking' or 'equipment_booking'
            booking_id: 예약 ID
            actor_id: 수행자 ID

        Returns:
            생성된 패널티
        """
        user = self._get_existing_user(user)
        with global_lock(), UnitOfWork():
            penalty = Penalty(
                id=generate_id(),
                user_id=user.id,
                reason=PenaltyReason.LATE_CANCEL,
                points=LATE_CANCEL_PENALTY,
                related_type=booking_type,
                related_id=booking_id,
                memo="예약 시작 1시간 이내 취소",
                updated_at=now_iso(),
            )

            self.penalty_repo.add(penalty)
            self._update_user_penalty_points(user, LATE_CANCEL_PENALTY)

            self.audit_repo.log_action(
                actor_id=actor_id,
                action="apply_late_cancel_penalty",
                target_type="user",
                target_id=user.id,
                details=f"직전 취소 패널티 +{LATE_CANCEL_PENALTY}점, 예약: {booking_type}/{booking_id}",
            )

            return penalty

    def apply_late_return(
        self, user, booking_type, booking_id, delay_minutes, actor_id="system"
    ):
        """
        지연 퇴실/반납 패널티 적용 (ceil(지연분/10)점)

        Args:
            user: 대상 사용자
            booking_type: 'room_booking' or 'equipment_booking'
            booking_id: 예약 ID
            delay_minutes: 지연 시간 (분)
            actor_id: 수행자 ID

        Returns:
            생성된 패널티 (지연 없으면 None)
        """
        user = self._get_existing_user(user)
        if delay_minutes <= 0:
            return None

        with global_lock(), UnitOfWork():
            points = ceil(delay_minutes / 10)

            penalty = Penalty(
                id=generate_id(),
                user_id=user.id,
                reason=PenaltyReason.LATE_RETURN,
                points=points,
                related_type=booking_type,
                related_id=booking_id,
                memo=f"지연 {delay_minutes}분",
                updated_at=now_iso(),
            )

            self.penalty_repo.add(penalty)
            self._update_user_penalty_points(user, points)

            self.audit_repo.log_action(
                actor_id=actor_id,
                action="apply_late_return_penalty",
                target_type="user",
                target_id=user.id,
                details=f"지연 반납 패널티 +{points}점 ({delay_minutes}분 지연), 예약: {booking_type}/{booking_id}",
            )

            return penalty

    def apply_damage(self, admin, user, booking_type, booking_id, points, memo):
        """
        파손/오염 패널티 적용 (관리자 수동, 1~5점)

        Args:
            admin: 수행 관리자
            user: 대상 사용자
            booking_type: 'room_booking' or 'equipment_booking'
            booking_id: 예약 ID
            points: 패널티 점수 (1~5)
            memo: 사유

        Returns:
            생성된 패널티

        Raises:
            AdminRequiredError: 관리자가 아닐 때
            PenaltyError: 점수가 범위를 벗어날 때
        """
        admin = self._get_existing_admin(admin)
        user = self._get_existing_user(user)

        if points < 1 or points > MAX_DAMAGE_PENALTY:
            raise PenaltyError(
                f"파손/오염 패널티는 1~{MAX_DAMAGE_PENALTY}점 사이여야 합니다."
            )

        with global_lock(), UnitOfWork():
            penalty = Penalty(
                id=generate_id(),
                user_id=user.id,
                reason=PenaltyReason.DAMAGE,
                points=points,
                related_type=booking_type,
                related_id=booking_id,
                memo=memo,
                updated_at=now_iso(),
            )

            self.penalty_repo.add(penalty)
            self._update_user_penalty_points(user, points)

            self.audit_repo.log_action(
                actor_id=admin.id,
                action="apply_damage_penalty",
                target_type="user",
                target_id=user.id,
                details=f"파손/오염 패널티 +{points}점, 사유: {memo}, 예약: {booking_type}/{booking_id}",
            )

            return penalty

    def _update_user_penalty_points(self, user, delta):
        """사용자 패널티 점수 업데이트"""
        # 최신 사용자 정보 조회
        current_user = self.user_repo.get_by_id(user.id)
        if current_user is None:
            raise PenaltyError("존재하지 않는 사용자입니다.")

        new_points = current_user.penalty_points + delta

        # 제한 상태 확인 및 설정
        restriction_until = current_user.restriction_until
        now = datetime.now()

        if new_points >= PENALTY_BAN_THRESHOLD:
            # 6점 이상: 30일 이용 금지
            restriction_until = (now + timedelta(days=BAN_DURATION_DAYS)).isoformat()
        elif new_points >= PENALTY_RESTRICTION_THRESHOLD:
            # 3~5점: 7일간 예약 1건 제한
            if (
                restriction_until is None
                or datetime.fromisoformat(restriction_until) < now
            ):
                restriction_until = (
                    now + timedelta(days=RESTRICTION_DURATION_DAYS)
                ).isoformat()

        # 연속 정상 이용 카운트 리셋
        updated_user = replace(
            current_user,
            penalty_points=new_points,
            restriction_until=restriction_until,
            normal_use_streak=0,  # 패널티 발생 시 리셋
            updated_at=now_iso(),
        )

        self.user_repo.update(updated_user)

    def record_normal_use(self, user):
        """
        정상 이용 기록 (10회 연속 시 1점 차감)

        Args:
            user: 대상 사용자

        Returns:
            점수 차감 여부
        """
        user = self._get_existing_user(user)
        with global_lock(), UnitOfWork():
            current_user = self.user_repo.get_by_id(user.id)
            if current_user is None:
                raise PenaltyError("존재하지 않는 사용자입니다.")

            new_streak = current_user.normal_use_streak + 1
            points_reduced = False
            new_points = current_user.penalty_points

            if new_streak >= STREAK_BONUS_COUNT:
                if new_points > 0:
                    new_points -= 1
                    points_reduced = True
                new_streak = 0

                self.audit_repo.log_action(
                    actor_id="system",
                    action="streak_bonus",
                    target_type="user",
                    target_id=user.id,
                    details=f"정상 이용 {STREAK_BONUS_COUNT}회 연속 달성, -1점",
                )

            new_restriction_until = current_user.restriction_until
            if new_points < PENALTY_RESTRICTION_THRESHOLD:
                new_restriction_until = None

            updated_user = replace(
                current_user,
                normal_use_streak=new_streak,
                penalty_points=new_points,
                restriction_until=new_restriction_until,
                updated_at=now_iso(),
            )

            self.user_repo.update(updated_user)
            return points_reduced

    def check_90_day_reset(self, user, current_time=None):
        """
        90일 경과 시 패널티 초기화

        Args:
            user: 대상 사용자
            current_time: 현재 시각 (테스트용)

        Returns:
            초기화 여부
        """
        user = self._get_existing_user(user)

        if current_time is None:
            current_time = datetime.now()

        last_penalty_date = self.penalty_repo.get_last_penalty_date(user.id)

        if last_penalty_date is None:
            return False

        days_since_last = (current_time - last_penalty_date).days

        if days_since_last >= PENALTY_RESET_DAYS:
            with global_lock(), UnitOfWork():
                current_user = self.user_repo.get_by_id(user.id)
                if current_user is None:
                    raise PenaltyError("존재하지 않는 사용자입니다.")
                if current_user.penalty_points > 0:
                    updated_user = replace(
                        current_user,
                        penalty_points=0,
                        restriction_until=None,
                        updated_at=now_iso(),
                    )
                    self.user_repo.update(updated_user)

                    self.audit_repo.log_action(
                        actor_id="system",
                        action="penalty_reset_90_days",
                        target_type="user",
                        target_id=user.id,
                        details=f"마지막 패널티 후 {days_since_last}일 경과, 점수 초기화",
                    )
                    return True

        return False

    def get_user_status(self, user):
        """
        사용자 패널티 상태 조회

        Returns:
            {
                'points': int,
                'is_banned': bool,
                'is_restricted': bool,
                'restriction_until': str or None,
                'max_active_bookings': int,
                'warning_message': str or None
            }
        """
        current_user = self._get_existing_user(user)

        status = evaluate_user_restriction(current_user, datetime.now())
        points = status["points"]
        is_banned = status["is_banned"]
        is_restricted = status["is_restricted"]
        restriction_until = status["restriction_until"]
        max_active_bookings = status["max_active_bookings"]

        # 경고 메시지
        warning = None
        if points >= PENALTY_WARNING_THRESHOLD and not is_banned:
            warning = f"패널티 점수가 {points}점입니다. 추가 위반 시 이용이 제한됩니다."

        return {
            "points": points,
            "is_banned": is_banned,
            "is_restricted": is_restricted,
            "restriction_until": restriction_until,
            "max_active_bookings": max_active_bookings,
            "warning_message": warning,
            "normal_use_streak": current_user.normal_use_streak,
        }

    def get_user_penalties(self, user_id):
        """사용자의 패널티 이력 조회"""
        self._get_existing_user_by_id(user_id)
        return self.penalty_repo.get_by_user(user_id)
