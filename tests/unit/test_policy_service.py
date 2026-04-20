"""정책 서비스 테스트"""

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
    def test_prepare_advance_blocks_room_start_without_force(
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

        result = policy_service.prepare_advance(actor_id=user.id)

        assert result["can_advance"] is False
        assert any("자동 취소" in blocker for blocker in result["blockers"])
        assert "현재 사용자에게 부과" in result["force_notice"]

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

        result = policy_service.prepare_advance(actor_id=user.id)

        assert result["can_advance"] is False
        assert any("반납 신청" in blocker for blocker in result["blockers"])

    def test_advance_time_moves_clock_and_logs_event_when_clear(
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
        assert any("운영 시점이" in event for event in result["events"])

        logs = audit_repo.get_by_actor("admin-1")
        assert any(log.action == "clock_advance" for log in logs)

    def test_advance_time_blocked_without_force_writes_audit_log(
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

        result = policy_service.advance_time(actor_id=user.id)

        assert result["can_advance"] is False
        logs = audit_repo.get_by_actor(user.id)
        assert any(log.action == "clock_advance_blocked" for log in logs)

    def test_forced_non_admin_advance_blames_advancing_user_for_start_side_penalty(
        self,
        policy_service,
        auth_service,
        create_test_room,
        room_booking_repo,
        penalty_repo,
        fake_clock,
    ):
        current_time = datetime(2024, 6, 16, 9, 0, 0)
        fake_clock(current_time)
        booking_user = auth_service.signup("booking_user", "pass")
        advancing_user = auth_service.signup("advancing_user", "pass")
        room = create_test_room()

        booking = RoomBooking(
            id="forced-room-booking",
            user_id=booking_user.id,
            room_id=room.id,
            start_time=current_time.isoformat(),
            end_time=current_time.replace(hour=18).isoformat(),
            status=RoomBookingStatus.RESERVED,
        )
        with global_lock():
            room_booking_repo.add(booking)

        result = policy_service.advance_time(actor_id=advancing_user.id, force=True)

        assert result["can_advance"] is True
        updated_booking = room_booking_repo.get_by_id(booking.id)
        assert updated_booking.status == RoomBookingStatus.ADMIN_CANCELLED
        assert auth_service.get_user(advancing_user.id).penalty_points == 2
        assert auth_service.get_user(booking_user.id).penalty_points == 0
        penalties = penalty_repo.get_by_user(advancing_user.id)
        assert penalties[0].reason == PenaltyReason.LATE_CANCEL

    def test_forced_admin_advance_keeps_penalty_on_original_user(
        self,
        policy_service,
        auth_service,
        create_test_room,
        room_booking_repo,
        penalty_repo,
        fake_clock,
    ):
        current_time = datetime(2024, 6, 16, 9, 0, 0)
        fake_clock(current_time)
        booking_user = auth_service.signup("admin_force_user", "pass")
        admin = auth_service.signup("clock_admin", "pass", role=UserRole.ADMIN)
        room = create_test_room()

        booking = RoomBooking(
            id="admin-forced-room-booking",
            user_id=booking_user.id,
            room_id=room.id,
            start_time=current_time.isoformat(),
            end_time=current_time.replace(hour=18).isoformat(),
            status=RoomBookingStatus.RESERVED,
        )
        with global_lock():
            room_booking_repo.add(booking)

        result = policy_service.advance_time(actor_id=admin.id, force=True)

        assert result["can_advance"] is True
        assert auth_service.get_user(admin.id).penalty_points == 0
        assert auth_service.get_user(booking_user.id).penalty_points == 2
        penalties = penalty_repo.get_by_user(booking_user.id)
        assert penalties[0].reason == PenaltyReason.LATE_CANCEL

    def test_forced_non_admin_advance_blames_advancing_user_for_end_side_penalty(
        self,
        policy_service,
        auth_service,
        create_test_room,
        room_booking_repo,
        penalty_repo,
        fake_clock,
    ):
        current_time = datetime(2024, 6, 16, 18, 0, 0)
        fake_clock(current_time)
        booking_user = auth_service.signup("late_checkout_owner", "pass")
        advancing_user = auth_service.signup("late_checkout_forcer", "pass")
        room = create_test_room()

        booking = RoomBooking(
            id="late-room-booking",
            user_id=booking_user.id,
            room_id=room.id,
            start_time=current_time.replace(hour=9).isoformat(),
            end_time=current_time.isoformat(),
            status=RoomBookingStatus.CHECKED_IN,
            checked_in_at=current_time.replace(hour=9).isoformat(),
        )
        with global_lock():
            room_booking_repo.add(booking)

        result = policy_service.advance_time(actor_id=advancing_user.id, force=True)

        assert result["can_advance"] is True
        assert auth_service.get_user(advancing_user.id).penalty_points == 2
        assert auth_service.get_user(booking_user.id).penalty_points == 0
        penalties = penalty_repo.get_by_user(advancing_user.id)
        assert penalties[0].reason == PenaltyReason.LATE_RETURN


class TestPenaltyResetAutomation:
    def test_penalty_reset_after_90_days(
        self, policy_service, create_test_user, penalty_repo, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user(penalty_points=5)

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
    def test_restriction_expires(
        self, policy_service, create_test_user, user_repo, mock_now
    ):
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


class TestBannedUserBookingCancellation:
    def test_banned_user_future_bookings_cancelled(
        self,
        policy_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
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


class TestCheckUserCanBook:
    def test_normal_user_can_book(self, policy_service, create_test_user):
        user = create_test_user(penalty_points=0)

        can_book, max_total, message = policy_service.check_user_can_book(user)

        assert can_book is True
        assert max_total == 2
        assert message == ""

    def test_banned_user_cannot_book(self, policy_service, create_test_user, mock_now):
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
