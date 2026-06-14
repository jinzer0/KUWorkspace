"""
패널티 서비스 - 패널티 점수 계산 및 적용
"""

from datetime import datetime, timedelta
from dataclasses import dataclass, replace

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
from src.runtime_clock import get_runtime_clock
from src.config import (
    LATE_CANCEL_PENALTY,
    LATE_CANCEL_THRESHOLD_MINUTES,
    LATE_RETURN_PENALTY,
    MAX_DAMAGE_PENALTY,
    PENALTY_WARNING_THRESHOLD,
    PENALTY_RESTRICTION_THRESHOLD,
    PENALTY_BAN_THRESHOLD,
    RESTRICTION_DURATION_DAYS,
    BAN_DURATION_DAYS,
    PENALTY_RESET_DAYS,
    STREAK_BONUS_COUNT,
)
from src.domain.field_rules import validate_reason_text


FREQUENT_CANCEL_PENALTY = 1
FREQUENT_CANCEL_LOOKBACK_DAYS = 30
FREQUENT_CANCEL_EXCLUDE_BEFORE_DAYS = 14
FREQUENT_CANCEL_RESTRICTION_COUNT = 3
FREQUENT_CANCEL_PENALTY_COUNT = FREQUENT_CANCEL_RESTRICTION_COUNT


@dataclass(frozen=True)
class CancelRestrictionSummary:
    room_cancel_count_30d: int
    equipment_cancel_count_30d: int
    max_cancel_count: int
    room_cancel_restricted_until: str | None
    equipment_cancel_restricted_until: str | None


@dataclass(frozen=True)
class CancelImpact:
    booking_type: str
    booking_id: str
    user_id: str
    is_late_cancel: bool
    qualifies_frequent_cancel: bool
    frequent_cancel_count: int
    applies_cancel_restriction: bool
    cancel_restriction_field: str | None
    cancel_restriction_until: str | None
    applies_frequent_cancel_penalty: bool
    penalty_reasons: tuple[PenaltyReason, ...]
    total_penalty_points: int

    def to_dict(self):
        return {
            "booking_type": self.booking_type,
            "booking_id": self.booking_id,
            "user_id": self.user_id,
            "is_late_cancel": self.is_late_cancel,
            "qualifies_frequent_cancel": self.qualifies_frequent_cancel,
            "frequent_cancel_count": self.frequent_cancel_count,
            "applies_cancel_restriction": self.applies_cancel_restriction,
            "cancel_restriction_field": self.cancel_restriction_field,
            "cancel_restriction_until": self.cancel_restriction_until,
            "applies_frequent_cancel_penalty": self.applies_frequent_cancel_penalty,
            "penalty_reasons": [reason.value for reason in self.penalty_reasons],
            "total_penalty_points": self.total_penalty_points,
        }


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

    def __init__(self, user_repo=None, penalty_repo=None, audit_repo=None, clock=None):
        self.user_repo = user_repo or UserRepository()
        self.penalty_repo = penalty_repo or PenaltyRepository()
        self.audit_repo = audit_repo or AuditLogRepository()
        self.clock = clock or get_runtime_clock()

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

    def _ensure_no_duplicate_penalty(
        self, user_id, reason, related_type, related_id, memo=None
    ):
        if self.penalty_repo.exists(user_id, reason, related_type, related_id, memo=memo):
            raise PenaltyError("동일한 패널티는 중복 부과할 수 없습니다.")


    def _is_late_cancel_time(self, booking_start_time, current_time):
        if current_time >= booking_start_time:
            return True
        minutes_until_start = (booking_start_time - current_time).total_seconds() / 60
        return minutes_until_start <= LATE_CANCEL_THRESHOLD_MINUTES

    def _is_qualifying_frequent_cancel(self, booking_start_time, cancelled_at):
        return booking_start_time - cancelled_at < timedelta(
            days=FREQUENT_CANCEL_EXCLUDE_BEFORE_DAYS
        )

    def _restriction_field_for_booking_type(self, booking_type):
        if booking_type == "room_booking":
            return "room_cancel_restricted_until"
        if booking_type == "equipment_booking":
            return "equipment_cancel_restricted_until"
        raise PenaltyError("지원하지 않는 예약 유형입니다.")

    def _count_recent_frequent_cancels(
        self, bookings, booking_type, user_id, current_time, include_late=False
    ):
        lookback_start = current_time - timedelta(days=FREQUENT_CANCEL_LOOKBACK_DAYS)
        if booking_type == "room_booking":
            from src.domain.models import RoomBookingStatus

            cancelled_status = RoomBookingStatus.CANCELLED
        elif booking_type == "equipment_booking":
            from src.domain.models import EquipmentBookingStatus

            cancelled_status = EquipmentBookingStatus.CANCELLED
        else:
            raise PenaltyError("지원하지 않는 예약 유형입니다.")

        count = 0
        for booking in bookings:
            if booking.user_id != user_id or booking.status != cancelled_status:
                continue
            if not booking.cancelled_at:
                continue
            cancelled_at = datetime.fromisoformat(booking.cancelled_at)
            if cancelled_at < lookback_start or cancelled_at > current_time:
                continue
            start_time = datetime.fromisoformat(booking.start_time)
            if self._is_late_cancel_time(start_time, cancelled_at):
                if include_late:
                    count += 1
                continue
            if self._is_qualifying_frequent_cancel(start_time, cancelled_at):
                count += 1
        return count


    def get_cancel_restriction_summary(self, user, room_bookings, equipment_bookings):
        current_user = self._get_existing_user(user)
        current_time = self.clock.now()
        return CancelRestrictionSummary(
            room_cancel_count_30d=self._count_recent_frequent_cancels(
                room_bookings,
                "room_booking",
                current_user.id,
                current_time,
                include_late=True,
            ),
            equipment_cancel_count_30d=self._count_recent_frequent_cancels(
                equipment_bookings,
                "equipment_booking",
                current_user.id,
                current_time,
                include_late=True,
            ),
            max_cancel_count=FREQUENT_CANCEL_RESTRICTION_COUNT,
            room_cancel_restricted_until=current_user.room_cancel_restricted_until,
            equipment_cancel_restricted_until=current_user.equipment_cancel_restricted_until,
        )

    def decide_cancel_impact(
        self, user, booking_type, booking_id, booking_start_time, domain_bookings
    ):
        user = self._get_existing_user(user)
        current_time = self.clock.now()
        if isinstance(booking_start_time, str):
            booking_start_time = datetime.fromisoformat(booking_start_time)

        is_late_cancel = self._is_late_cancel_time(booking_start_time, current_time)
        qualifies_frequent_cancel = (
            not is_late_cancel
            and self._is_qualifying_frequent_cancel(booking_start_time, current_time)
        )
        prior_count = self._count_recent_frequent_cancels(
            domain_bookings, booking_type, user.id, current_time
        )
        frequent_count = prior_count + (1 if qualifies_frequent_cancel else 0)
        restriction_field = self._restriction_field_for_booking_type(booking_type)
        applies_restriction = (
            not is_late_cancel
            and
            qualifies_frequent_cancel
            and frequent_count == FREQUENT_CANCEL_RESTRICTION_COUNT
        )
        restriction_until = None
        if applies_restriction:
            restriction_until = (
                current_time + timedelta(days=RESTRICTION_DURATION_DAYS)
            ).isoformat()

        applies_frequent_penalty = (
            not is_late_cancel
            and qualifies_frequent_cancel
            and frequent_count >= FREQUENT_CANCEL_PENALTY_COUNT
        )
        penalty_reasons = []
        total_points = 0
        if is_late_cancel:
            penalty_reasons.append(PenaltyReason.LATE_CANCEL)
            total_points += LATE_CANCEL_PENALTY
        if applies_frequent_penalty:
            penalty_reasons.append(PenaltyReason.FREQUENT_CANCEL)
            total_points += FREQUENT_CANCEL_PENALTY

        return CancelImpact(
            booking_type=booking_type,
            booking_id=booking_id,
            user_id=user.id,
            is_late_cancel=is_late_cancel,
            qualifies_frequent_cancel=qualifies_frequent_cancel,
            frequent_cancel_count=frequent_count,
            applies_cancel_restriction=applies_restriction,
            cancel_restriction_field=restriction_field if applies_restriction else None,
            cancel_restriction_until=restriction_until,
            applies_frequent_cancel_penalty=applies_frequent_penalty,
            penalty_reasons=tuple(penalty_reasons),
            total_penalty_points=total_points,
        )

    def preview_cancel_impact(
        self, user, booking_type, booking_id, booking_start_time, domain_bookings
    ):
        return self.decide_cancel_impact(
            user, booking_type, booking_id, booking_start_time, domain_bookings
        )

    def apply_cancel_impact(
        self,
        user,
        booking_type,
        booking_id,
        booking_start_time,
        domain_bookings,
        actor_id="system",
        confirm=True,
    ):
        user = self._get_existing_user(user)
        if not confirm:
            impact = self.decide_cancel_impact(
                user, booking_type, booking_id, booking_start_time, domain_bookings
            )
            return impact, []

        with global_lock(), UnitOfWork():
            impact = self.decide_cancel_impact(
                user, booking_type, booking_id, booking_start_time, domain_bookings
            )
            created_penalties = []
            for reason in impact.penalty_reasons:
                if self.penalty_repo.exists(user.id, reason, booking_type, booking_id):
                    continue
                if reason == PenaltyReason.LATE_CANCEL:
                    points = LATE_CANCEL_PENALTY
                    memo = "예약시작1시간이내취소"
                else:
                    points = FREQUENT_CANCEL_PENALTY
                    memo = "최근30일빈번취소"
                penalty = Penalty(
                    id=generate_id(),
                    user_id=user.id,
                    reason=reason,
                    points=points,
                    related_type=booking_type,
                    related_id=booking_id,
                    memo=memo,
                    updated_at=now_iso(),
                )
                self.penalty_repo.add(penalty)
                created_penalties.append(penalty)

            total_points = sum(penalty.points for penalty in created_penalties)
            current_user = self.user_repo.get_by_id(user.id)
            if current_user is None:
                raise PenaltyError("존재하지 않는 사용자입니다.")

            updated_user = current_user
            if total_points:
                new_points = current_user.penalty_points + total_points
                restriction_until = current_user.restriction_until
                now = self.clock.now()
                if new_points >= PENALTY_BAN_THRESHOLD:
                    restriction_until = (now + timedelta(days=BAN_DURATION_DAYS)).isoformat()
                elif new_points >= PENALTY_RESTRICTION_THRESHOLD:
                    if (
                        restriction_until is None
                        or datetime.fromisoformat(restriction_until) < now
                    ):
                        restriction_until = (
                            now + timedelta(days=RESTRICTION_DURATION_DAYS)
                        ).isoformat()
                updated_user = replace(
                    updated_user,
                    penalty_points=new_points,
                    restriction_until=restriction_until,
                    normal_use_streak=0,
                    updated_at=now_iso(),
                )

            if impact.applies_cancel_restriction:
                if impact.cancel_restriction_field == "room_cancel_restricted_until":
                    updated_user = replace(
                        updated_user,
                        room_cancel_restricted_until=impact.cancel_restriction_until,
                        updated_at=now_iso(),
                    )
                elif impact.cancel_restriction_field == "equipment_cancel_restricted_until":
                    updated_user = replace(
                        updated_user,
                        equipment_cancel_restricted_until=impact.cancel_restriction_until,
                        updated_at=now_iso(),
                    )

            if updated_user != current_user:
                self.user_repo.update(updated_user)

            self.audit_repo.log_action(
                actor_id=actor_id,
                action="apply_cancel_impact",
                target_type="user",
                target_id=user.id,
                details=(
                    f"예약 취소 영향 적용: {booking_type}/{booking_id}, "
                    f"late={impact.is_late_cancel}, frequent_count={impact.frequent_cancel_count}, "
                    f"penalties={len(created_penalties)}"
                ),
            )
            return impact, created_penalties

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
            self._ensure_no_duplicate_penalty(
                user.id,
                PenaltyReason.LATE_CANCEL,
                booking_type,
                booking_id,
            )
            penalty = Penalty(
                id=generate_id(),
                user_id=user.id,
                reason=PenaltyReason.LATE_CANCEL,
                points=LATE_CANCEL_PENALTY,
                related_type=booking_type,
                related_id=booking_id,
                memo="예약시작1시간이내취소",
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
        지연 퇴실/반납 패널티 적용 (+2점 고정)

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
            self._ensure_no_duplicate_penalty(
                user.id,
                PenaltyReason.LATE_RETURN,
                booking_type,
                booking_id,
            )
            penalty = Penalty(
                id=generate_id(),
                user_id=user.id,
                reason=PenaltyReason.LATE_RETURN,
                points=LATE_RETURN_PENALTY,
                related_type=booking_type,
                related_id=booking_id,
                memo=f"지연{delay_minutes}분처리",
                updated_at=now_iso(),
            )

            self.penalty_repo.add(penalty)
            self._update_user_penalty_points(user, LATE_RETURN_PENALTY)

            self.audit_repo.log_action(
                actor_id=actor_id,
                action="apply_late_return_penalty",
                target_type="user",
                target_id=user.id,
                details=f"지연 반납 패널티 +{LATE_RETURN_PENALTY}점 ({delay_minutes}분 지연), 예약: {booking_type}/{booking_id}",
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
        try:
            validate_reason_text(memo)
        except ValueError as error:
            raise PenaltyError(str(error)) from error

        with global_lock(), UnitOfWork():
            self._ensure_no_duplicate_penalty(
                user.id,
                PenaltyReason.DAMAGE,
                booking_type,
                booking_id,
            )
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
        now = self.clock.now()

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
            current_time = self.clock.now()

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

        status = evaluate_user_restriction(current_user, self.clock.now())
        points = int(status["points"] or 0)
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
