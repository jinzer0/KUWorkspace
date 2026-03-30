"""
패널티 서비스 테스트

테스트 대상:
- 노쇼 패널티 (+3점)
- 직전 취소 패널티 (+2점)
- 지연 반납 패널티 (ceil(분/10)점)
- 파손/오염 패널티 (1~5점)
- 정상 이용 연속 10회 보너스 (-1점)
- 90일 경과 패널티 초기화
- 패널티 점수에 따른 제한 적용 (3점 → 7일 1건 제한, 6점 → 30일 금지)
"""

import pytest
from datetime import datetime, timedelta

from src.domain.penalty_service import PenaltyError, AdminRequiredError
from src.domain.models import UserRole, PenaltyReason
from src.storage.file_lock import global_lock


class TestNoShowPenalty:
    """노쇼 패널티 테스트"""

    def test_apply_no_show_adds_3_points(self, penalty_service, create_test_user):
        """노쇼 시 3점 추가"""
        user = create_test_user(penalty_points=0)

        penalty = penalty_service.apply_no_show(
            user=user, booking_type="room_booking", booking_id="booking-123"
        )

        assert penalty.reason == PenaltyReason.NO_SHOW
        assert penalty.points == 3

        # 사용자 점수 확인

        updated_user = penalty_service.user_repo.get_by_id(user.id)
        assert updated_user.penalty_points == 3

    def test_no_show_resets_streak(self, penalty_service, create_test_user):
        """노쇼 발생 시 정상 이용 연속 횟수 리셋"""
        user = create_test_user(penalty_points=0, normal_use_streak=8)

        penalty_service.apply_no_show(
            user=user, booking_type="room_booking", booking_id="booking-123"
        )

        updated_user = penalty_service.user_repo.get_by_id(user.id)
        assert updated_user.normal_use_streak == 0

    def test_apply_no_show_nonexistent_user_fails(self, penalty_service, user_factory):
        fake_user = user_factory(id="missing-user")

        with pytest.raises(PenaltyError) as exc_info:
            penalty_service.apply_no_show(
                user=fake_user,
                booking_type="room_booking",
                booking_id="booking-123",
            )

        assert "존재하지 않는 사용자" in str(exc_info.value)


class TestLateCancelPenalty:
    """직전 취소 패널티 테스트"""

    def test_apply_late_cancel_adds_2_points(self, penalty_service, create_test_user):
        """직전 취소 시 2점 추가"""
        user = create_test_user(penalty_points=0)

        penalty = penalty_service.apply_late_cancel(
            user=user, booking_type="room_booking", booking_id="booking-456"
        )

        assert penalty.reason == PenaltyReason.LATE_CANCEL
        assert penalty.points == 2

        updated_user = penalty_service.user_repo.get_by_id(user.id)
        assert updated_user.penalty_points == 2


class TestLateReturnPenalty:
    """지연 반납 패널티 테스트"""

    def test_apply_late_return_1_minute(self, penalty_service, create_test_user):
        user = create_test_user(penalty_points=0)

        penalty = penalty_service.apply_late_return(
            user=user,
            booking_type="room_booking",
            booking_id="booking-789",
            delay_minutes=1,
        )

        assert penalty.points == 2

    def test_apply_late_return_10_minutes(self, penalty_service, create_test_user):
        user = create_test_user(penalty_points=0)

        penalty = penalty_service.apply_late_return(
            user=user,
            booking_type="room_booking",
            booking_id="booking-789",
            delay_minutes=10,
        )

        assert penalty.points == 2

    def test_apply_late_return_11_minutes(self, penalty_service, create_test_user):
        user = create_test_user(penalty_points=0)

        penalty = penalty_service.apply_late_return(
            user=user,
            booking_type="room_booking",
            booking_id="booking-789",
            delay_minutes=11,
        )

        assert penalty.points == 2

    def test_apply_late_return_25_minutes(self, penalty_service, create_test_user):
        user = create_test_user(penalty_points=0)

        penalty = penalty_service.apply_late_return(
            user=user,
            booking_type="room_booking",
            booking_id="booking-789",
            delay_minutes=25,
        )

        assert penalty.points == 2

    def test_apply_late_return_zero_delay_returns_none(
        self, penalty_service, create_test_user
    ):
        """지연 0분일 때 패널티 없음"""
        user = create_test_user(penalty_points=0)

        result = penalty_service.apply_late_return(
            user=user,
            booking_type="room_booking",
            booking_id="booking-789",
            delay_minutes=0,
        )

        assert result is None

    def test_apply_late_return_negative_delay_returns_none(
        self, penalty_service, create_test_user
    ):
        """지연 음수일 때 패널티 없음"""
        user = create_test_user(penalty_points=0)

        result = penalty_service.apply_late_return(
            user=user,
            booking_type="room_booking",
            booking_id="booking-789",
            delay_minutes=-10,
        )

        assert result is None

    def test_apply_late_return_zero_delay_nonexistent_user_fails(
        self, penalty_service, user_factory
    ):
        fake_user = user_factory(id="missing-user")

        with pytest.raises(PenaltyError) as exc_info:
            penalty_service.apply_late_return(
                user=fake_user,
                booking_type="room_booking",
                booking_id="booking-789",
                delay_minutes=0,
            )

        assert "존재하지 않는 사용자" in str(exc_info.value)


class TestDamagePenalty:
    """파손/오염 패널티 테스트"""

    def test_apply_damage_1_point(self, penalty_service, create_test_user):
        """파손 1점 부과"""
        user = create_test_user(penalty_points=0)
        admin = create_test_user(role=UserRole.ADMIN)

        penalty = penalty_service.apply_damage(
            admin=admin,
            user=user,
            booking_type="equipment_booking",
            booking_id="booking-damage",
            points=1,
            memo="경미한 스크래치",
        )

        assert penalty.reason == PenaltyReason.DAMAGE
        assert penalty.points == 1
        assert penalty.memo == "경미한 스크래치"

    def test_apply_damage_5_points(self, penalty_service, create_test_user):
        """파손 5점 부과"""
        user = create_test_user(penalty_points=0)
        admin = create_test_user(role=UserRole.ADMIN)

        penalty = penalty_service.apply_damage(
            admin=admin,
            user=user,
            booking_type="equipment_booking",
            booking_id="booking-damage",
            points=5,
            memo="심각한 파손",
        )

        assert penalty.points == 5

    def test_apply_damage_0_points_fails(self, penalty_service, create_test_user):
        """0점 부과 시 실패"""
        user = create_test_user(penalty_points=0)
        admin = create_test_user(role=UserRole.ADMIN)

        with pytest.raises(PenaltyError) as exc_info:
            penalty_service.apply_damage(
                admin=admin,
                user=user,
                booking_type="equipment_booking",
                booking_id="booking-damage",
                points=0,
                memo="테스트",
            )

        assert "1~5점 사이여야 합니다" in str(exc_info.value)

    def test_apply_damage_6_points_fails(self, penalty_service, create_test_user):
        """6점 부과 시 실패"""
        user = create_test_user(penalty_points=0)
        admin = create_test_user(role=UserRole.ADMIN)

        with pytest.raises(PenaltyError) as exc_info:
            penalty_service.apply_damage(
                admin=admin,
                user=user,
                booking_type="equipment_booking",
                booking_id="booking-damage",
                points=6,
                memo="테스트",
            )

        assert "1~5점 사이여야 합니다" in str(exc_info.value)

    def test_apply_damage_nonexistent_admin_fails(self, penalty_service, user_factory):
        user = user_factory(id="target-user", role=UserRole.USER)
        admin = user_factory(role=UserRole.ADMIN)

        with pytest.raises(AdminRequiredError) as exc_info:
            penalty_service.apply_damage(
                admin=admin,
                user=user,
                booking_type="equipment_booking",
                booking_id="booking-damage",
                points=3,
                memo="테스트",
            )

        assert "관리자" in str(exc_info.value)

    def test_apply_damage_nonexistent_user_fails(
        self, penalty_service, create_test_user, user_factory
    ):
        admin = create_test_user(role=UserRole.ADMIN)
        fake_user = user_factory(id="missing-user")

        with pytest.raises(PenaltyError) as exc_info:
            penalty_service.apply_damage(
                admin=admin,
                user=fake_user,
                booking_type="equipment_booking",
                booking_id="booking-damage",
                points=3,
                memo="테스트",
            )

        assert "존재하지 않는 사용자" in str(exc_info.value)


class TestStreakBonus:
    """정상 이용 연속 보너스 테스트"""

    def test_record_normal_use_increments_streak(
        self, penalty_service, create_test_user
    ):
        """정상 이용 기록 시 streak 증가"""
        user = create_test_user(penalty_points=0, normal_use_streak=0)

        penalty_service.record_normal_use(user)

        updated_user = penalty_service.user_repo.get_by_id(user.id)
        assert updated_user.normal_use_streak == 1

    def test_streak_bonus_at_10_reduces_penalty(
        self, penalty_service, create_test_user
    ):
        """10회 연속 정상 이용 시 1점 차감"""
        user = create_test_user(penalty_points=2, normal_use_streak=9)

        result = penalty_service.record_normal_use(user)

        assert result is True  # 점수 차감됨

        updated_user = penalty_service.user_repo.get_by_id(user.id)
        assert updated_user.penalty_points == 1
        assert updated_user.normal_use_streak == 0  # 리셋

    def test_streak_bonus_no_reduction_if_zero_points(
        self, penalty_service, create_test_user
    ):
        """패널티 0점일 때 연속 10회 달성해도 음수가 되지 않음"""
        user = create_test_user(penalty_points=0, normal_use_streak=9)

        result = penalty_service.record_normal_use(user)

        assert result is False  # 차감되지 않음

        updated_user = penalty_service.user_repo.get_by_id(user.id)
        assert updated_user.penalty_points == 0
        assert updated_user.normal_use_streak == 0  # 여전히 리셋

    def test_streak_bonus_clears_restriction_when_points_drop_below_3(
        self, penalty_service, create_test_user
    ):
        """3점에서 10회 보너스로 2점이 되면 즉시 제한 해제"""
        restriction_until = (datetime.now() + timedelta(days=5)).isoformat()
        user = create_test_user(
            penalty_points=3, normal_use_streak=9, restriction_until=restriction_until
        )

        result = penalty_service.record_normal_use(user)

        assert result is True

        updated_user = penalty_service.user_repo.get_by_id(user.id)
        assert updated_user.penalty_points == 2
        assert updated_user.restriction_until is None

        status = penalty_service.get_user_status(updated_user)
        assert status["is_restricted"] is False
        assert status["max_active_bookings"] == 2

    def test_record_normal_use_nonexistent_user_fails(
        self, penalty_service, user_factory
    ):
        fake_user = user_factory(id="missing-user")

        with pytest.raises(PenaltyError) as exc_info:
            penalty_service.record_normal_use(fake_user)

        assert "존재하지 않는 사용자" in str(exc_info.value)


class TestPenaltyReset90Days:
    """90일 경과 패널티 초기화 테스트"""

    def test_reset_after_90_days(self, penalty_service, create_test_user, penalty_repo):
        """마지막 패널티 후 90일 경과 시 초기화"""
        user = create_test_user(penalty_points=5)

        # 91일 전 패널티 생성
        from src.domain.models import Penalty, PenaltyReason, generate_id

        old_penalty = Penalty(
            id=generate_id(),
            user_id=user.id,
            reason=PenaltyReason.NO_SHOW,
            points=3,
            related_type="room_booking",
            related_id="old-booking",
            created_at=(datetime.now() - timedelta(days=91)).isoformat(),
        )
        with global_lock():
            penalty_repo.add(old_penalty)

        current_time = datetime.now()
        result = penalty_service.check_90_day_reset(user, current_time)

        assert result is True

        updated_user = penalty_service.user_repo.get_by_id(user.id)
        assert updated_user.penalty_points == 0
        assert updated_user.restriction_until is None

    def test_no_reset_before_90_days(
        self, penalty_service, create_test_user, penalty_repo
    ):
        """90일 미만이면 초기화되지 않음"""
        user = create_test_user(penalty_points=5)

        # 89일 전 패널티 생성
        from src.domain.models import Penalty, PenaltyReason, generate_id

        recent_penalty = Penalty(
            id=generate_id(),
            user_id=user.id,
            reason=PenaltyReason.NO_SHOW,
            points=3,
            related_type="room_booking",
            related_id="recent-booking",
            created_at=(datetime.now() - timedelta(days=89)).isoformat(),
        )
        with global_lock():
            penalty_repo.add(recent_penalty)

        current_time = datetime.now()
        result = penalty_service.check_90_day_reset(user, current_time)

        assert result is False

        updated_user = penalty_service.user_repo.get_by_id(user.id)
        assert updated_user.penalty_points == 5  # 변경 없음

    def test_check_90_day_reset_nonexistent_user_fails(
        self, penalty_service, user_factory
    ):
        fake_user = user_factory(id="missing-user")

        with pytest.raises(PenaltyError) as exc_info:
            penalty_service.check_90_day_reset(fake_user, datetime.now())

        assert "존재하지 않는 사용자" in str(exc_info.value)


class TestPenaltyThresholds:
    """패널티 임계값 제한 테스트"""

    def test_3_points_triggers_restriction(self, penalty_service, create_test_user):
        """3점 달성 시 7일 제한 적용"""
        user = create_test_user(penalty_points=0)

        # 3점 패널티 적용
        penalty_service.apply_no_show(
            user=user, booking_type="room_booking", booking_id="booking-1"
        )

        updated_user = penalty_service.user_repo.get_by_id(user.id)
        assert updated_user.penalty_points == 3
        assert updated_user.restriction_until is not None

        # restriction_until이 약 7일 후인지 확인
        restriction_end = datetime.fromisoformat(updated_user.restriction_until)
        expected_end = datetime.now() + timedelta(days=7)
        assert (
            abs((restriction_end - expected_end).total_seconds()) < 60
        )  # 1분 오차 허용

    def test_6_points_triggers_ban(self, penalty_service, create_test_user):
        """6점 달성 시 30일 이용 금지"""
        user = create_test_user(penalty_points=3)

        # +3점으로 6점 달성
        penalty_service.apply_no_show(
            user=user, booking_type="room_booking", booking_id="booking-2"
        )

        updated_user = penalty_service.user_repo.get_by_id(user.id)
        assert updated_user.penalty_points == 6
        assert updated_user.restriction_until is not None

        # restriction_until이 약 30일 후인지 확인
        restriction_end = datetime.fromisoformat(updated_user.restriction_until)
        expected_end = datetime.now() + timedelta(days=30)
        assert abs((restriction_end - expected_end).total_seconds()) < 60


class TestUserStatus:
    """사용자 상태 조회 테스트"""

    def test_status_normal_user(self, penalty_service, create_test_user):
        """정상 사용자 상태"""
        user = create_test_user(penalty_points=0)

        status = penalty_service.get_user_status(user)

        assert status["points"] == 0
        assert status["is_banned"] is False
        assert status["is_restricted"] is False
        assert status["max_active_bookings"] == 2
        assert status["warning_message"] is None

    def test_status_warning_at_3_points(self, penalty_service, create_test_user):
        """3점 이상 시 경고 메시지"""
        user = create_test_user(
            penalty_points=3,
            restriction_until=(datetime.now() + timedelta(days=7)).isoformat(),
        )

        status = penalty_service.get_user_status(user)

        assert status["points"] == 3
        assert status["is_restricted"] is True
        assert status["max_active_bookings"] == 1
        assert status["warning_message"] is not None

    def test_status_banned_at_6_points(self, penalty_service, create_test_user):
        """6점 이상 시 이용 금지"""
        user = create_test_user(
            penalty_points=6,
            restriction_until=(datetime.now() + timedelta(days=30)).isoformat(),
        )

        status = penalty_service.get_user_status(user)

        assert status["points"] == 6
        assert status["is_banned"] is True
        assert status["max_active_bookings"] == 0

    def test_status_nonexistent_user_fails(self, penalty_service, user_factory):
        fake_user = user_factory(id="missing-user")

        with pytest.raises(PenaltyError) as exc_info:
            penalty_service.get_user_status(fake_user)

        assert "존재하지 않는 사용자" in str(exc_info.value)


class TestPenaltyHistory:
    """패널티 이력 조회 테스트"""

    def test_get_user_penalties(self, penalty_service, create_test_user):
        """사용자의 패널티 이력 조회"""
        user = create_test_user(penalty_points=0)

        # 여러 패널티 적용
        penalty_service.apply_no_show(user, "room_booking", "b1")
        penalty_service.apply_late_cancel(user, "room_booking", "b2")
        penalty_service.apply_late_return(
            user, "equipment_booking", "b3", delay_minutes=15
        )

        penalties = penalty_service.get_user_penalties(user.id)

        assert len(penalties) == 3

        reasons = {p.reason for p in penalties}
        assert PenaltyReason.NO_SHOW in reasons
        assert PenaltyReason.LATE_CANCEL in reasons
        assert PenaltyReason.LATE_RETURN in reasons

    def test_get_user_penalties_nonexistent_user_fails(self, penalty_service):
        with pytest.raises(PenaltyError) as exc_info:
            penalty_service.get_user_penalties("missing-user")

        assert "존재하지 않는 사용자" in str(exc_info.value)
