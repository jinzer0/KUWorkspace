"""
패널티 서비스 테스트

테스트 대상:
- 직전 취소 패널티 (+2점)
- 지연 반납 패널티 (ceil(분/10)점)
- 파손/오염 패널티 (1~5점)
- 정상 이용 연속 10회 보너스 (-1점)
- 90일 경과 패널티 초기화
- 패널티 점수에 따른 제한 적용 (3점 → 7일 1건 제한, 6점 → 30일 금지)
"""

import pytest
from datetime import datetime, timedelta

from src.domain.penalty_service import (
    CancelRestrictionSummary,
    PenaltyError,
    AdminRequiredError,
)
from src.domain.models import (
    EquipmentBookingStatus,
    PenaltyReason,
    RoomBookingStatus,
    UserRole,
)
from src.storage.file_lock import global_lock



def _add_cancelled_booking(repo, booking):
    with global_lock():
        repo.add(booking)
    return booking


def _cancelled_room_booking(factory, user_id, start_time, cancelled_at):
    return factory(
        user_id=user_id,
        start_time=start_time.isoformat(),
        end_time=(start_time + timedelta(hours=1)).isoformat(),
        status=RoomBookingStatus.CANCELLED,
        cancelled_at=cancelled_at.isoformat(),
    )


def _reserved_room_booking(factory, user_id, start_time):
    return factory(
        user_id=user_id,
        start_time=start_time.isoformat(),
        end_time=(start_time + timedelta(hours=1)).isoformat(),
        status=RoomBookingStatus.RESERVED,
    )


def _cancelled_equipment_booking(factory, user_id, start_time, cancelled_at):
    return factory(
        user_id=user_id,
        start_time=start_time.isoformat(),
        end_time=(start_time + timedelta(days=1)).isoformat(),
        status=EquipmentBookingStatus.CANCELLED,
        cancelled_at=cancelled_at.isoformat(),
    )


def _reserved_equipment_booking(factory, user_id, start_time):
    return factory(
        user_id=user_id,
        start_time=start_time.isoformat(),
        end_time=(start_time + timedelta(days=1)).isoformat(),
        status=EquipmentBookingStatus.RESERVED,
    )


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

    def test_apply_late_cancel_rejects_duplicate(self, penalty_service, create_test_user):
        user = create_test_user(penalty_points=0)

        penalty_service.apply_late_cancel(
            user=user, booking_type="room_booking", booking_id="booking-456"
        )

        with pytest.raises(PenaltyError) as exc_info:
            penalty_service.apply_late_cancel(
                user=user, booking_type="room_booking", booking_id="booking-456"
            )

        assert "중복" in str(exc_info.value)


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

    def test_apply_late_return_rejects_duplicate(self, penalty_service, create_test_user):
        user = create_test_user(penalty_points=0)

        penalty_service.apply_late_return(
            user=user,
            booking_type="room_booking",
            booking_id="booking-789",
            delay_minutes=25,
        )

        with pytest.raises(PenaltyError) as exc_info:
            penalty_service.apply_late_return(
                user=user,
                booking_type="room_booking",
                booking_id="booking-789",
                delay_minutes=25,
            )

        assert "중복" in str(exc_info.value)

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
        assert status["max_active_bookings"] == 6

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
            reason=PenaltyReason.OTHER,
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
            reason=PenaltyReason.OTHER,
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
        """2점 단일 직전 취소는 제한을 유발하지 않는다"""
        user = create_test_user(penalty_points=0)

        penalty_service.apply_late_cancel(
            user=user, booking_type="room_booking", booking_id="booking-1"
        )

        updated_user = penalty_service.user_repo.get_by_id(user.id)
        assert updated_user.penalty_points == 2
        assert updated_user.restriction_until is None

    def test_6_points_triggers_ban(self, penalty_service, create_test_user):
        """6점 달성 시 30일 이용 금지"""
        user = create_test_user(penalty_points=4)

        penalty_service.apply_late_cancel(
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
        assert status["max_active_bookings"] == 6
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
        assert status["max_active_bookings"] == 2
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
        penalty_service.apply_late_cancel(user, "room_booking", "b1")
        penalty_service.apply_late_return(
            user, "equipment_booking", "b2", delay_minutes=15
        )

        penalties = penalty_service.get_user_penalties(user.id)

        assert len(penalties) == 2

        reasons = {p.reason for p in penalties}
        assert PenaltyReason.LATE_CANCEL in reasons
        assert PenaltyReason.LATE_RETURN in reasons

    def test_get_user_penalties_nonexistent_user_fails(self, penalty_service):
        with pytest.raises(PenaltyError) as exc_info:
            penalty_service.get_user_penalties("missing-user")

        assert "존재하지 않는 사용자" in str(exc_info.value)


class TestCancelImpactFrequentCancel:
    def test_confirm_false_previews_third_cancel_without_mutation(
        self,
        penalty_service,
        create_test_user,
        room_booking_repo,
        room_booking_factory,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)
        with mock_now(fixed_time):
            user = create_test_user()
            for days_ago in (3, 10):
                _add_cancelled_booking(
                    room_booking_repo,
                    _cancelled_room_booking(
                        room_booking_factory,
                        user.id,
                        fixed_time - timedelta(days=days_ago - 1),
                        fixed_time - timedelta(days=days_ago),
                    ),
                )
            booking = _reserved_room_booking(
                room_booking_factory, user.id, fixed_time + timedelta(days=1)
            )
            _add_cancelled_booking(room_booking_repo, booking)

            impact, created = penalty_service.apply_cancel_impact(
                user=user,
                booking_type="room_booking",
                booking_id=booking.id,
                booking_start_time=booking.start_time,
                domain_bookings=room_booking_repo.get_by_user(user.id),
                actor_id=user.id,
                confirm=False,
            )

            assert created == []
            assert impact.frequent_cancel_count == 3
            assert impact.applies_cancel_restriction is True
            assert impact.applies_frequent_cancel_penalty is True
            assert impact.penalty_reasons == (PenaltyReason.FREQUENT_CANCEL,)
            assert penalty_service.penalty_repo.get_by_user(user.id) == []
            updated_user = penalty_service.user_repo.get_by_id(user.id)
            assert updated_user.room_cancel_restricted_until is None
            assert updated_user.penalty_points == 0

    def test_confirm_true_applies_third_cancel_restriction_with_one_point_penalty(
        self,
        penalty_service,
        create_test_user,
        room_booking_repo,
        room_booking_factory,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)
        with mock_now(fixed_time):
            user = create_test_user()
            for days_ago in (2, 8):
                _add_cancelled_booking(
                    room_booking_repo,
                    _cancelled_room_booking(
                        room_booking_factory,
                        user.id,
                        fixed_time - timedelta(days=days_ago - 1),
                        fixed_time - timedelta(days=days_ago),
                    ),
                )
            booking = _reserved_room_booking(
                room_booking_factory, user.id, fixed_time + timedelta(days=1)
            )
            _add_cancelled_booking(room_booking_repo, booking)

            impact, created = penalty_service.apply_cancel_impact(
                user=user,
                booking_type="room_booking",
                booking_id=booking.id,
                booking_start_time=booking.start_time,
                domain_bookings=room_booking_repo.get_by_user(user.id),
                actor_id=user.id,
            )

            assert [(penalty.reason, penalty.points) for penalty in created] == [
                (PenaltyReason.FREQUENT_CANCEL, 1)
            ]
            assert impact.frequent_cancel_count == 3
            updated_user = penalty_service.user_repo.get_by_id(user.id)
            assert updated_user.room_cancel_restricted_until is not None
            assert updated_user.equipment_cancel_restricted_until is None
            assert updated_user.penalty_points == 1

    def test_plan0001_frequent_cancel_is_one_point_from_third_cancel(
        self,
        penalty_service,
        create_test_user,
        room_booking_repo,
        room_booking_factory,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)
        with mock_now(fixed_time):
            user = create_test_user(username="FrequentCancelUser")
            for days_ago in (2, 8):
                _add_cancelled_booking(
                    room_booking_repo,
                    _cancelled_room_booking(
                        room_booking_factory,
                        user.id,
                        fixed_time - timedelta(days=days_ago - 1),
                        fixed_time - timedelta(days=days_ago),
                    ),
                )
            booking = _reserved_room_booking(
                room_booking_factory, user.id, fixed_time + timedelta(days=1)
            )
            _add_cancelled_booking(room_booking_repo, booking)

            impact, created = penalty_service.apply_cancel_impact(
                user=user,
                booking_type="room_booking",
                booking_id=booking.id,
                booking_start_time=booking.start_time,
                domain_bookings=room_booking_repo.get_by_user(user.id),
                actor_id=user.id,
            )

            assert impact.frequent_cancel_count == 3
            assert impact.applies_cancel_restriction is True
            assert impact.penalty_reasons == (PenaltyReason.FREQUENT_CANCEL,)
            assert [(penalty.reason, penalty.points) for penalty in created] == [
                (PenaltyReason.FREQUENT_CANCEL, 1)
            ]
            updated_user = penalty_service.user_repo.get_by_id(user.id)
            assert updated_user.room_cancel_restricted_until is not None
            assert updated_user.penalty_points == 1

    def test_fourth_qualifying_cancel_adds_frequent_cancel_penalty(
        self,
        penalty_service,
        create_test_user,
        room_booking_repo,
        room_booking_factory,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)
        with mock_now(fixed_time):
            user = create_test_user()
            for days_ago in (2, 8, 20):
                _add_cancelled_booking(
                    room_booking_repo,
                    _cancelled_room_booking(
                        room_booking_factory,
                        user.id,
                        fixed_time - timedelta(days=days_ago - 1),
                        fixed_time - timedelta(days=days_ago),
                    ),
                )
            booking = _reserved_room_booking(
                room_booking_factory, user.id, fixed_time + timedelta(days=1)
            )
            _add_cancelled_booking(room_booking_repo, booking)

            impact, created = penalty_service.apply_cancel_impact(
                user=user,
                booking_type="room_booking",
                booking_id=booking.id,
                booking_start_time=booking.start_time,
                domain_bookings=room_booking_repo.get_by_user(user.id),
                actor_id=user.id,
            )

            assert impact.frequent_cancel_count == 4
            assert impact.applies_cancel_restriction is False
            assert impact.penalty_reasons == (PenaltyReason.FREQUENT_CANCEL,)
            assert [penalty.reason for penalty in created] == [PenaltyReason.FREQUENT_CANCEL]
            updated_user = penalty_service.user_repo.get_by_id(user.id)
            assert updated_user.penalty_points == 1
            assert updated_user.room_cancel_restricted_until is None

    def test_recent_count_is_domain_specific_and_limited_to_30_days(
        self,
        penalty_service,
        create_test_user,
        room_booking_repo,
        equipment_booking_repo,
        room_booking_factory,
        equipment_booking_factory,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)
        with mock_now(fixed_time):
            user = create_test_user()
            _add_cancelled_booking(
                room_booking_repo,
                _cancelled_room_booking(
                    room_booking_factory,
                    user.id,
                    fixed_time - timedelta(days=30),
                    fixed_time - timedelta(days=31),
                ),
            )
            _add_cancelled_booking(
                equipment_booking_repo,
                _cancelled_equipment_booking(
                    equipment_booking_factory,
                    user.id,
                    fixed_time - timedelta(days=1),
                    fixed_time - timedelta(days=2),
                ),
            )
            booking = _reserved_room_booking(
                room_booking_factory, user.id, fixed_time + timedelta(days=1)
            )
            _add_cancelled_booking(room_booking_repo, booking)

            impact = penalty_service.preview_cancel_impact(
                user=user,
                booking_type="room_booking",
                booking_id=booking.id,
                booking_start_time=booking.start_time,
                domain_bookings=room_booking_repo.get_by_user(user.id),
            )

            assert impact.frequent_cancel_count == 1
            assert impact.applies_cancel_restriction is False

    def test_cancellations_at_least_14_days_before_start_are_excluded(
        self,
        penalty_service,
        create_test_user,
        room_booking_repo,
        room_booking_factory,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)
        with mock_now(fixed_time):
            user = create_test_user()
            for days_ago in (2, 8):
                _add_cancelled_booking(
                    room_booking_repo,
                    _cancelled_room_booking(
                        room_booking_factory,
                        user.id,
                        fixed_time - timedelta(days=days_ago - 1),
                        fixed_time - timedelta(days=days_ago),
                    ),
                )
            booking = _reserved_room_booking(
                room_booking_factory, user.id, fixed_time + timedelta(days=14)
            )
            _add_cancelled_booking(room_booking_repo, booking)

            impact = penalty_service.preview_cancel_impact(
                user=user,
                booking_type="room_booking",
                booking_id=booking.id,
                booking_start_time=booking.start_time,
                domain_bookings=room_booking_repo.get_by_user(user.id),
            )

            assert impact.qualifies_frequent_cancel is False
            assert impact.frequent_cancel_count == 2
            assert impact.applies_cancel_restriction is False

    def test_prior_late_cancels_do_not_count_toward_frequent_cancel(
        self,
        penalty_service,
        create_test_user,
        room_booking_repo,
        room_booking_factory,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)
        with mock_now(fixed_time):
            user = create_test_user()
            for days_ago in (2, 8):
                start_time = fixed_time - timedelta(days=days_ago) + timedelta(minutes=30)
                _add_cancelled_booking(
                    room_booking_repo,
                    _cancelled_room_booking(
                        room_booking_factory,
                        user.id,
                        start_time,
                        fixed_time - timedelta(days=days_ago),
                    ),
                )
            booking = _reserved_room_booking(
                room_booking_factory, user.id, fixed_time + timedelta(days=1)
            )
            _add_cancelled_booking(room_booking_repo, booking)

            impact = penalty_service.preview_cancel_impact(
                user=user,
                booking_type="room_booking",
                booking_id=booking.id,
                booking_start_time=booking.start_time,
                domain_bookings=room_booking_repo.get_by_user(user.id),
            )

            assert impact.frequent_cancel_count == 1
            assert impact.applies_cancel_restriction is False
            assert impact.applies_frequent_cancel_penalty is False

    def test_room_and_equipment_cancel_restrictions_are_independent(
        self,
        penalty_service,
        create_test_user,
        room_booking_repo,
        equipment_booking_repo,
        room_booking_factory,
        equipment_booking_factory,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)
        with mock_now(fixed_time):
            user = create_test_user()
            for days_ago in (2, 8):
                _add_cancelled_booking(
                    room_booking_repo,
                    _cancelled_room_booking(
                        room_booking_factory,
                        user.id,
                        fixed_time - timedelta(days=days_ago - 1),
                        fixed_time - timedelta(days=days_ago),
                    ),
                )
            room_booking = _reserved_room_booking(
                room_booking_factory, user.id, fixed_time + timedelta(days=1)
            )
            _add_cancelled_booking(room_booking_repo, room_booking)
            penalty_service.apply_cancel_impact(
                user=user,
                booking_type="room_booking",
                booking_id=room_booking.id,
                booking_start_time=room_booking.start_time,
                domain_bookings=room_booking_repo.get_by_user(user.id),
                actor_id=user.id,
            )

            for days_ago in (3, 9):
                _add_cancelled_booking(
                    equipment_booking_repo,
                    _cancelled_equipment_booking(
                        equipment_booking_factory,
                        user.id,
                        fixed_time - timedelta(days=days_ago - 1),
                        fixed_time - timedelta(days=days_ago),
                    ),
                )
            equipment_booking = _reserved_equipment_booking(
                equipment_booking_factory, user.id, fixed_time + timedelta(days=1)
            )
            _add_cancelled_booking(equipment_booking_repo, equipment_booking)
            penalty_service.apply_cancel_impact(
                user=user,
                booking_type="equipment_booking",
                booking_id=equipment_booking.id,
                booking_start_time=equipment_booking.start_time,
                domain_bookings=equipment_booking_repo.get_by_user(user.id),
                actor_id=user.id,
            )

            updated_user = penalty_service.user_repo.get_by_id(user.id)
            assert updated_user.room_cancel_restricted_until is not None
            assert updated_user.equipment_cancel_restricted_until is not None
            assert updated_user.penalty_points == 2

    def test_late_and_frequent_cancel_do_not_duplicate_existing_late_penalty(
        self,
        penalty_service,
        create_test_user,
        room_booking_repo,
        room_booking_factory,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)
        with mock_now(fixed_time):
            user = create_test_user()
            for days_ago in (2, 8, 20):
                _add_cancelled_booking(
                    room_booking_repo,
                    _cancelled_room_booking(
                        room_booking_factory,
                        user.id,
                        fixed_time - timedelta(days=days_ago - 1),
                        fixed_time - timedelta(days=days_ago),
                    ),
                )
            booking = _reserved_room_booking(
                room_booking_factory, user.id, fixed_time + timedelta(minutes=30)
            )
            _add_cancelled_booking(room_booking_repo, booking)
            penalty_service.apply_late_cancel(
                user=user,
                booking_type="room_booking",
                booking_id=booking.id,
                actor_id=user.id,
            )

            impact, created = penalty_service.apply_cancel_impact(
                user=user,
                booking_type="room_booking",
                booking_id=booking.id,
                booking_start_time=booking.start_time,
                domain_bookings=room_booking_repo.get_by_user(user.id),
                actor_id=user.id,
            )

            penalties = penalty_service.penalty_repo.get_by_user(user.id)
            assert impact.penalty_reasons == (PenaltyReason.LATE_CANCEL,)
            assert created == []
            assert [penalty.reason for penalty in penalties].count(PenaltyReason.LATE_CANCEL) == 1
            assert [penalty.reason for penalty in penalties].count(PenaltyReason.FREQUENT_CANCEL) == 0
            assert penalty_service.user_repo.get_by_id(user.id).penalty_points == 2


class TestCancelRestrictionSummary:
    def test_summary_dataclass_has_expected_fields(self):
        summary = CancelRestrictionSummary(1, 2, 3, "room-until", "equipment-until")

        assert summary.room_cancel_count_30d == 1
        assert summary.equipment_cancel_count_30d == 2
        assert summary.max_cancel_count == 3
        assert summary.room_cancel_restricted_until == "room-until"
        assert summary.equipment_cancel_restricted_until == "equipment-until"

    def test_summary_counts_recent_direct_cancels_including_late_and_excludes_admin(
        self,
        penalty_service,
        create_test_user,
        room_booking_factory,
        equipment_booking_factory,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)
        with mock_now(fixed_time):
            user = create_test_user(
                room_cancel_restricted_until="2024-06-22T09:00:00",
                equipment_cancel_restricted_until="2024-06-23T09:00:00",
            )
            other = create_test_user(username="CancelOther1")
            room_recent = _cancelled_room_booking(
                room_booking_factory,
                user.id,
                fixed_time - timedelta(days=1),
                fixed_time - timedelta(days=2),
            )
            room_late = _cancelled_room_booking(
                room_booking_factory,
                user.id,
                fixed_time - timedelta(days=3) + timedelta(minutes=30),
                fixed_time - timedelta(days=3),
            )
            room_admin = room_booking_factory(
                user_id=user.id,
                start_time=(fixed_time - timedelta(days=4)).isoformat(),
                end_time=(fixed_time - timedelta(days=4) + timedelta(hours=1)).isoformat(),
                status=RoomBookingStatus.ADMIN_CANCELLED,
                cancelled_at=(fixed_time - timedelta(days=5)).isoformat(),
            )
            room_old = _cancelled_room_booking(
                room_booking_factory,
                user.id,
                fixed_time - timedelta(days=35),
                fixed_time - timedelta(days=36),
            )
            room_other = _cancelled_room_booking(
                room_booking_factory,
                other.id,
                fixed_time - timedelta(days=1),
                fixed_time - timedelta(days=2),
            )
            equipment_recent = _cancelled_equipment_booking(
                equipment_booking_factory,
                user.id,
                fixed_time - timedelta(days=1),
                fixed_time - timedelta(days=2),
            )
            equipment_admin = equipment_booking_factory(
                user_id=user.id,
                start_time=(fixed_time - timedelta(days=1)).isoformat(),
                end_time=fixed_time.isoformat(),
                status=EquipmentBookingStatus.ADMIN_CANCELLED,
                cancelled_at=(fixed_time - timedelta(days=2)).isoformat(),
            )

            summary = penalty_service.get_cancel_restriction_summary(
                user,
                [room_recent, room_late, room_admin, room_old, room_other],
                [equipment_recent, equipment_admin],
            )

        assert summary.room_cancel_count_30d == 2
        assert summary.equipment_cancel_count_30d == 1
        assert summary.max_cancel_count == 3
        assert summary.room_cancel_restricted_until == "2024-06-22T09:00"
        assert summary.equipment_cancel_restricted_until == "2024-06-23T09:00"

    def test_late_direct_cancel_counts_for_summary_but_not_frequent_penalty(
        self,
        penalty_service,
        create_test_user,
        room_booking_factory,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)
        with mock_now(fixed_time):
            user = create_test_user()
            late_booking = _reserved_room_booking(
                room_booking_factory, user.id, fixed_time + timedelta(minutes=30)
            )
            cancelled_late = _cancelled_room_booking(
                room_booking_factory,
                user.id,
                fixed_time + timedelta(minutes=30),
                fixed_time,
            )

            impact = penalty_service.preview_cancel_impact(
                user=user,
                booking_type="room_booking",
                booking_id=late_booking.id,
                booking_start_time=late_booking.start_time,
                domain_bookings=[cancelled_late],
            )
            summary = penalty_service.get_cancel_restriction_summary(
                user, [cancelled_late], []
            )

        assert impact.penalty_reasons == (PenaltyReason.LATE_CANCEL,)
        assert impact.applies_frequent_cancel_penalty is False
        assert impact.frequent_cancel_count == 0
        assert summary.room_cancel_count_30d == 1
