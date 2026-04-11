"""
정책 서비스 테스트

테스트 대상:
- 시점 이동 블로킹과 이벤트
- 90일 경과 패널티 초기화
- 제한 기간 만료 처리
- 6점 이상 사용자 미래 예약 자동 취소
- 사용자 예약 가능 여부 확인
"""

import pytest
from datetime import datetime, timedelta

from src.domain.penalty_service import PenaltyError
from src.domain.models import (
    RoomBooking,
    EquipmentBooking,
    RoomBookingStatus,
    EquipmentBookingStatus,
    PenaltyReason,
    UserRole,
)
from src.storage.file_lock import global_lock


class TestClockAdvance:
    """가상 시점 이동 테스트"""

    def test_prepare_advance_blocks_room_start_without_admin_action(
        self,
        policy_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        fake_clock,
    ):
        current_time = datetime(2024, 6, 16, 9, 0, 0)
        fake_clock(current_time)
        user = create_test_user()
        room = create_test_room()

        booking = RoomBooking(
            id="booking-1",
            user_id=user.id,
            room_id=room.id,
            start_time=current_time.isoformat(),
            end_time=datetime(2024, 6, 16, 18, 0, 0).isoformat(),
            status=RoomBookingStatus.RESERVED,
        )
        with global_lock():
            room_booking_repo.add(booking)

        result = policy_service.prepare_advance()

        assert result["can_advance"] is False
        assert any("체크인 요청 또는 노쇼" in blocker for blocker in result["blockers"])

    def test_prepare_advance_blocks_equipment_end_without_user_request(
        self,
        policy_service,
        create_test_user,
        create_test_equipment,
        equipment_booking_repo,
        fake_clock,
    ):
        current_time = datetime(2024, 6, 16, 18, 0, 0)
        fake_clock(current_time)
        user = create_test_user()
        equipment = create_test_equipment()

        booking = EquipmentBooking(
            id="eq-booking-1",
            user_id=user.id,
            equipment_id=equipment.id,
            start_time=datetime(2024, 6, 16, 9, 0, 0).isoformat(),
            end_time=current_time.isoformat(),
            status=EquipmentBookingStatus.CHECKED_OUT,
        )
        with global_lock():
            equipment_booking_repo.add(booking)

        result = policy_service.prepare_advance()

        assert result["can_advance"] is False
        assert any("반납 신청" in blocker for blocker in result["blockers"])

    def test_advance_time_moves_clock_and_logs_event(
        self,
        policy_service,
        audit_repo,
        fake_clock,
    ):
        current_time = datetime(2024, 6, 16, 18, 0, 0)
        fake_clock(current_time)

        result = policy_service.advance_time(actor_id="admin-1")

        assert result["can_advance"] is True
        assert result["next_time"] == datetime(2024, 6, 17, 9, 0, 0)
        assert isinstance(result["events"], list)
        assert result["events"]

        logs = audit_repo.get_by_actor("admin-1")
        assert any(log.action == "clock_advance" for log in logs)

    def test_advance_time_blocked_writes_audit_log(
        self,
        policy_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        audit_repo,
        fake_clock,
    ):
        current_time = datetime(2024, 6, 16, 9, 0, 0)
        fake_clock(current_time)
        user = create_test_user()
        room = create_test_room()

        booking = RoomBooking(
            id="blocked-booking",
            user_id=user.id,
            room_id=room.id,
            start_time=current_time.isoformat(),
            end_time=datetime(2024, 6, 16, 18, 0, 0).isoformat(),
            status=RoomBookingStatus.RESERVED,
        )
        with global_lock():
            room_booking_repo.add(booking)

        result = policy_service.advance_time(actor_id="admin-2")

        assert result["can_advance"] is True
        logs = audit_repo.get_by_actor("admin-2")
        assert any(log.action == "clock_advance" for log in logs)

    def test_prepare_advance_for_actor_shows_personalized_events_for_user(
        self,
        policy_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        fake_clock,
    ):
        current_time = datetime(2024, 6, 16, 9, 0, 0)
        fake_clock(current_time)
        user = create_test_user(username="user-personal")
        room = create_test_room()

        booking = RoomBooking(
            id="personal-booking",
            user_id=user.id,
            room_id=room.id,
            start_time=current_time.isoformat(),
            end_time=datetime(2024, 6, 16, 18, 0, 0).isoformat(),
            status=RoomBookingStatus.CHECKED_IN,
        )
        with global_lock():
            room_booking_repo.add(booking)

        result = policy_service.prepare_advance_for_actor(actor_id=user.id)

        assert any("본인의 회의실 예약이 종료될 예정입니다." in event for event in result["events"])
        assert all("당일 종료 예정 회의실" not in event for event in result["events"])

    def test_prepare_advance_for_actor_keeps_aggregate_events_for_admin(
        self,
        policy_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        fake_clock,
    ):
        current_time = datetime(2024, 6, 16, 9, 0, 0)
        fake_clock(current_time)
        admin = create_test_user(username="admin-personal", role=UserRole.ADMIN)
        user = create_test_user(username="user-aggregate")
        room = create_test_room()

        booking = RoomBooking(
            id="aggregate-booking",
            user_id=user.id,
            room_id=room.id,
            start_time=current_time.isoformat(),
            end_time=datetime(2024, 6, 16, 18, 0, 0).isoformat(),
            status=RoomBookingStatus.CHECKED_IN,
        )
        with global_lock():
            room_booking_repo.add(booking)

        result = policy_service.prepare_advance_for_actor(actor_id=admin.id)

        assert any("당일 종료 예정 회의실" in event for event in result["events"])

    def test_prepare_advance_syncs_clock_from_store(self, policy_service, fake_clock):
        fake_clock(datetime(2024, 6, 16, 9, 0, 0))
        persisted = datetime(2024, 6, 16, 18, 0, 0)
        policy_service.clock_loader = lambda: persisted

        result = policy_service.prepare_advance()

        assert result["current_time"] == persisted

    def test_advance_time_uses_synced_clock_before_transition(
        self,
        policy_service,
        fake_clock,
    ):
        fake_clock(datetime(2024, 6, 16, 9, 0, 0))
        persisted = datetime(2024, 6, 16, 18, 0, 0)
        policy_service.clock_loader = lambda: persisted

        result = policy_service.advance_time(actor_id="admin-sync")

        assert result["next_time"] == datetime(2024, 6, 17, 9, 0, 0)


class TestPenaltyResetAutomation:
    """90일 경과 패널티 초기화 테스트"""

    def test_penalty_reset_after_90_days(
        self, policy_service, create_test_user, penalty_repo, mock_now
    ):
        """마지막 패널티 후 90일 경과 시 점수 초기화"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user(penalty_points=5)

        # 91일 전 패널티 생성
        from src.domain.models import Penalty, generate_id

        old_penalty = Penalty(
            id=generate_id(),
            user_id=user.id,
            reason=PenaltyReason.OTHER,
            points=3,
            related_type="room_booking",
            related_id="old-booking",
            created_at=(fixed_time - timedelta(days=91)).isoformat(),
        )
        with global_lock():
            penalty_repo.add(old_penalty)

        with mock_now(fixed_time):
            results = policy_service.run_all_checks(fixed_time)

            assert user.id in results["penalty_reset_users"]


class TestRestrictionExpiry:
    """제한 기간 만료 테스트"""

    def test_restriction_expires(
        self, policy_service, create_test_user, user_repo, mock_now
    ):
        """제한 기간 만료 시 restriction_until 초기화"""
        # 제한 기간이 이미 지난 사용자
        expired_time = datetime(2024, 6, 10, 10, 0, 0)
        check_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(check_time):
            user = create_test_user(
                penalty_points=3, restriction_until=expired_time.isoformat()
            )

            results = policy_service.run_all_checks(check_time)

            assert user.id in results["restriction_expired_users"]

            updated = user_repo.get_by_id(user.id)
            assert updated.restriction_until is None

    def test_restriction_not_expired(
        self, policy_service, create_test_user, user_repo, mock_now
    ):
        """제한 기간이 아직 남아있으면 유지"""
        check_time = datetime(2024, 6, 15, 10, 0, 0)
        future_time = datetime(2024, 6, 20, 10, 0, 0)

        with mock_now(check_time):
            user = create_test_user(
                penalty_points=3, restriction_until=future_time.isoformat()
            )

            results = policy_service.run_all_checks(check_time)

            assert user.id not in results["restriction_expired_users"]

            updated = user_repo.get_by_id(user.id)
            assert updated.restriction_until is not None

    def test_restriction_expiry_writes_audit_log(
        self, policy_service, create_test_user, audit_repo, mock_now
    ):
        expired_time = datetime(2024, 6, 10, 10, 0, 0)
        check_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(check_time):
            user = create_test_user(
                penalty_points=3, restriction_until=expired_time.isoformat()
            )

            policy_service.run_all_checks(check_time)

        logs = audit_repo.get_by_actor("system")
        assert any(
            log.action == "restriction_expired" and log.target_id == user.id
            for log in logs
        )


class TestBannedUserBookingCancellation:
    """6점 이상 사용자 예약 자동 취소 테스트"""

    def test_banned_user_future_bookings_cancelled(
        self,
        policy_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        mock_now,
    ):
        """6점 이상 사용자의 미래 예약 자동 취소"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user(
                penalty_points=6,
                restriction_until=(fixed_time + timedelta(days=30)).isoformat(),
            )
            room = create_test_room()

            # 미래 예약 생성
            future_booking = RoomBooking(
                id="future-booking",
                user_id=user.id,
                room_id=room.id,
                start_time=(fixed_time + timedelta(hours=2)).isoformat(),
                end_time=(fixed_time + timedelta(hours=3)).isoformat(),
                status=RoomBookingStatus.RESERVED,
            )
            with global_lock():
                room_booking_repo.add(future_booking)

            results = policy_service.run_all_checks(fixed_time)

            assert "future-booking" in results["banned_user_cancelled_bookings"]

            updated = room_booking_repo.get_by_id("future-booking")
            assert updated.status == RoomBookingStatus.ADMIN_CANCELLED

    def test_banned_user_past_bookings_not_cancelled(
        self,
        policy_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        mock_now,
    ):
        """6점 이상 사용자라도 이미 시작된 예약은 취소하지 않음"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user(
                penalty_points=6,
                restriction_until=(fixed_time + timedelta(days=30)).isoformat(),
            )
            room = create_test_room()

            # 과거 시작 예약 (체크인 상태)
            past_booking = RoomBooking(
                id="past-booking",
                user_id=user.id,
                room_id=room.id,
                start_time=(fixed_time - timedelta(hours=1)).isoformat(),
                end_time=(fixed_time + timedelta(hours=1)).isoformat(),
                status=RoomBookingStatus.CHECKED_IN,
            )
            with global_lock():
                room_booking_repo.add(past_booking)

            results = policy_service.run_all_checks(fixed_time)

            # 체크인 상태이므로 취소되지 않음
            assert "past-booking" not in results["banned_user_cancelled_bookings"]

    def test_banned_user_auto_cancellation_writes_audit_log(
        self,
        policy_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        audit_repo,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user(
                penalty_points=6,
                restriction_until=(fixed_time + timedelta(days=30)).isoformat(),
            )
            room = create_test_room()
            future_booking = RoomBooking(
                id="future-audit-booking",
                user_id=user.id,
                room_id=room.id,
                start_time=(fixed_time + timedelta(hours=2)).isoformat(),
                end_time=(fixed_time + timedelta(hours=3)).isoformat(),
                status=RoomBookingStatus.RESERVED,
            )
            with global_lock():
                room_booking_repo.add(future_booking)

            policy_service.run_all_checks(fixed_time)

        logs = audit_repo.get_by_actor("system")
        assert any(
            log.action == "auto_cancel_banned_user"
            and log.target_id == "future-audit-booking"
            for log in logs
        )


class TestCheckUserCanBook:
    """사용자 예약 가능 여부 확인 테스트"""

    def test_normal_user_can_book(self, policy_service, create_test_user):
        """정상 사용자 예약 가능"""
        user = create_test_user(penalty_points=0)

        can_book, max_total, message = policy_service.check_user_can_book(user)

        assert can_book is True
        assert max_total == 2
        assert message == ""

    def test_restricted_user_limited_booking(
        self, policy_service, create_test_user, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user(
                penalty_points=4,
                restriction_until=(fixed_time + timedelta(days=7)).isoformat(),
            )

            can_book, max_total, message = policy_service.check_user_can_book(user)

            assert can_book is True
            assert max_total == 2
            assert "각 예약 유형별" in message

    def test_banned_user_cannot_book(self, policy_service, create_test_user, mock_now):
        """6점 이상 사용자는 예약 불가"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user(
                penalty_points=6,
                restriction_until=(fixed_time + timedelta(days=30)).isoformat(),
            )

            can_book, max_total, message = policy_service.check_user_can_book(user)

            assert can_book is False
            assert max_total == 0
            assert "금지" in message

    def test_nonexistent_user_cannot_book(self, policy_service, user_factory):
        fake_user = user_factory(id="missing-user")

        with pytest.raises(PenaltyError) as exc_info:
            policy_service.check_user_can_book(fake_user)

        assert "존재하지 않는 사용자" in str(exc_info.value)


class TestGetMaxBookingsForUser:
    """사용자별 최대 예약 수 조회 테스트"""

    def test_normal_user_max_bookings(self, policy_service, create_test_user):
        """정상 사용자: 회의실 1, 장비 1"""
        user = create_test_user(penalty_points=0)

        max_room, max_equipment = policy_service.get_max_bookings_for_user(user)

        assert max_room == 1
        assert max_equipment == 1

    def test_restricted_user_max_bookings(
        self, policy_service, create_test_user, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user(
                penalty_points=3,
                restriction_until=(fixed_time + timedelta(days=7)).isoformat(),
            )

            max_room, max_equipment = policy_service.get_max_bookings_for_user(user)

            assert max_room == 1
            assert max_equipment == 1

    def test_nonexistent_user_max_bookings(self, policy_service, user_factory):
        fake_user = user_factory(id="missing-user")

        with pytest.raises(PenaltyError) as exc_info:
            policy_service.get_max_bookings_for_user(fake_user)

        assert "존재하지 않는 사용자" in str(exc_info.value)

    def test_banned_user_no_bookings(self, policy_service, create_test_user, mock_now):
        """금지 사용자: 0건"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user(
                penalty_points=6,
                restriction_until=(fixed_time + timedelta(days=30)).isoformat(),
            )

            max_room, max_equipment = policy_service.get_max_bookings_for_user(user)

            assert max_room == 0
            assert max_equipment == 0
