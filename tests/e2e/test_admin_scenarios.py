"""관리자 시나리오 E2E 테스트"""

import pytest
from datetime import datetime, timedelta

from src.domain.room_service import RoomBookingError
from src.domain.penalty_service import PenaltyError
from src.domain.models import (
    UserRole,
    RoomBookingStatus,
    EquipmentBookingStatus,
    ResourceStatus,
    PenaltyReason,
)
from src.storage.file_lock import global_lock


class TestAdminPenaltyManagement:
    def test_admin_applies_damage_penalty(
        self, auth_service, room_service, penalty_service, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("damage_user", "pass")
            admin = auth_service.signup("damage_admin", "pass", role=UserRole.ADMIN)
            room = create_test_room()

            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time,
                fixed_time.replace(hour=18),
            )
            room_service.request_check_in(user, booking.id)
            room_service.check_in(admin, booking.id)

        with mock_now(datetime(2024, 6, 15, 18, 0, 0)):
            room_service.check_out(admin, booking.id)

            penalty = penalty_service.apply_damage(
                admin=admin,
                user=user,
                booking_type="room_booking",
                booking_id=booking.id,
                points=3,
                memo="책상 파손",
            )

            assert penalty.reason == PenaltyReason.DAMAGE
            assert penalty.points == 3
            assert auth_service.get_user(user.id).penalty_points == 3

    def test_admin_damage_penalty_range_validation(self, auth_service, penalty_service):
        user = auth_service.signup("range_user", "pass")
        admin = auth_service.signup("range_admin", "pass", role=UserRole.ADMIN)

        with pytest.raises(PenaltyError):
            penalty_service.apply_damage(
                admin=admin,
                user=user,
                booking_type="room_booking",
                booking_id="b1",
                points=0,
                memo="test",
            )

        with pytest.raises(PenaltyError):
            penalty_service.apply_damage(
                admin=admin,
                user=user,
                booking_type="room_booking",
                booking_id="b2",
                points=6,
                memo="test",
            )


class TestAdminStatusChange:
    def test_room_maintenance_cancels_future_bookings(
        self, auth_service, room_service, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("maint_user", "pass")
            user2 = auth_service.signup("maint_user_2", "pass")
            admin = auth_service.signup("maint_admin", "pass", role=UserRole.ADMIN)
            room = create_test_room()

            room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(days=1),
                fixed_time + timedelta(days=2),
            )
            room_service.create_booking(
                user2,
                room.id,
                fixed_time + timedelta(days=3),
                fixed_time + timedelta(days=4),
            )

            updated_room, cancelled = room_service.update_room_status(
                admin, room.id, ResourceStatus.MAINTENANCE
            )

            assert updated_room.status == ResourceStatus.MAINTENANCE
            assert len(cancelled) == 2
            assert all(b.status == RoomBookingStatus.ADMIN_CANCELLED for b in cancelled)

    def test_equipment_disabled_cancels_future_bookings(
        self, auth_service, equipment_service, create_test_equipment, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("disabled_user", "pass")
            admin = auth_service.signup("disabled_admin", "pass", role=UserRole.ADMIN)
            equipment = create_test_equipment()

            equipment_service.create_booking(
                user,
                equipment.id,
                fixed_time + timedelta(days=1),
                fixed_time + timedelta(days=3),
            )

            updated_eq, cancelled = equipment_service.update_equipment_status(
                admin, equipment.id, ResourceStatus.DISABLED
            )

            assert updated_eq.status == ResourceStatus.DISABLED
            assert len(cancelled) == 1
            assert cancelled[0].status == EquipmentBookingStatus.ADMIN_CANCELLED


class TestAdminBookingCancellation:
    def test_admin_cancels_user_booking(
        self, auth_service, room_service, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("cancel_target", "pass")
            admin = auth_service.signup("cancel_admin", "pass", role=UserRole.ADMIN)
            room = create_test_room()

            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(days=1),
                fixed_time + timedelta(days=2),
            )

            cancelled = room_service.admin_cancel_booking(admin, booking.id, "시설 긴급 점검")
            assert cancelled.status == RoomBookingStatus.ADMIN_CANCELLED

    def test_admin_cannot_cancel_checked_in_booking(
        self, auth_service, room_service, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("checkin_cancel", "pass")
            admin = auth_service.signup("checkin_admin", "pass", role=UserRole.ADMIN)
            room = create_test_room()

            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time,
                fixed_time.replace(hour=18),
            )

            room_service.request_check_in(user, booking.id)
            room_service.check_in(admin, booking.id)

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.admin_cancel_booking(admin, booking.id, "긴급 상황")

            assert "reserved" in str(exc_info.value)


class TestAdminPolicyExecution:
    def test_admin_forced_clock_advance_keeps_penalty_on_original_user(
        self,
        auth_service,
        policy_service,
        create_test_room,
        room_booking_repo,
        fake_clock,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)
        fake_clock(fixed_time)
        user = auth_service.signup("late_cancel_user", "pass")
        admin = auth_service.signup("clock_admin", "pass", role=UserRole.ADMIN)
        room = create_test_room()

        from src.domain.models import RoomBooking

        booking = RoomBooking(
            id="late-cancel-booking",
            user_id=user.id,
            room_id=room.id,
            start_time=fixed_time.isoformat(),
            end_time=fixed_time.replace(hour=18).isoformat(),
            status=RoomBookingStatus.RESERVED,
        )
        with global_lock():
            room_booking_repo.add(booking)

        result = policy_service.advance_time(actor_id=admin.id, force=True)

        assert result["can_advance"] is True
        assert auth_service.get_user(admin.id).penalty_points == 0
        assert auth_service.get_user(user.id).penalty_points == 2


class TestAdminPenaltyHistory:
    def test_admin_views_user_penalty_history(self, auth_service, penalty_service):
        user = auth_service.signup("history_user", "pass")
        admin = auth_service.signup("history_admin", "pass", role=UserRole.ADMIN)

        penalty_service.apply_late_cancel(user, "room_booking", "b1")
        penalty_service.apply_damage(
            admin=admin,
            user=user,
            booking_type="equipment_booking",
            booking_id="b2",
            points=2,
            memo="화면 손상",
        )

        history = penalty_service.get_user_penalties(user.id)

        assert len(history) == 2
        reasons = {p.reason for p in history}
        assert PenaltyReason.LATE_CANCEL in reasons
        assert PenaltyReason.DAMAGE in reasons
