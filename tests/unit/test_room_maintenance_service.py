from datetime import datetime, timedelta

import pytest

from src.domain.models import RoomBookingStatus, UserRole
from src.domain.room_service import RoomBookingError


class TestRoomMaintenanceService:
    def test_create_maintenance_rejects_overlapping_schedule_deterministically(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 8, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            room = create_test_room()
            start = fixed_time + timedelta(days=1, hours=1)
            end = fixed_time + timedelta(days=1, hours=2)

            schedule = room_service.create_maintenance_schedule(
                admin, room.id, start, end, "정기점검"
            )

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.create_maintenance_schedule(
                    admin, room.id, start + timedelta(minutes=30), end, "중복점검"
                )

            assert schedule.id is not None
            assert "이미 점검 일정" in str(exc_info.value)
            assert [item.id for item in room_service.maintenance_repo.get_by_room(room.id)] == [
                schedule.id
            ]

    def test_cancel_maintenance_restores_room_booking_availability(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 8, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            user = create_test_user(username="student")
            room = create_test_room()
            start = fixed_time + timedelta(days=2, hours=1)
            end = fixed_time + timedelta(days=2, hours=2)
            schedule = room_service.create_maintenance_schedule(
                admin, room.id, start, end, "정기점검"
            )

            with pytest.raises(RoomBookingError):
                room_service.create_booking(user, room.id, start, end)

            cancelled = room_service.cancel_maintenance_schedule(
                admin, schedule.id, "점검 취소"
            )
            booking = room_service.create_booking(user, room.id, start, end)

            assert cancelled.id == schedule.id
            assert room_service.maintenance_repo.get_by_id(schedule.id) is None
            assert booking.status == RoomBookingStatus.RESERVED

    def test_create_booking_during_maintenance_rejects_without_writing_booking(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 8, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            user = create_test_user(username="student")
            room = create_test_room()
            start = fixed_time + timedelta(days=3, hours=1)
            end = fixed_time + timedelta(days=3, hours=2)
            room_service.create_maintenance_schedule(admin, room.id, start, end, "정기점검")

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.create_booking(user, room.id, start, end)

            assert "점검 일정" in str(exc_info.value)
            assert room_service.booking_repo.get_by_room(room.id) == []

    def test_modify_booking_during_maintenance_rejects_without_mutating_booking(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 8, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            user = create_test_user(username="student")
            room = create_test_room()
            original_start = fixed_time + timedelta(days=4, hours=1)
            original_end = fixed_time + timedelta(days=4, hours=2)
            maintenance_start = fixed_time + timedelta(days=5, hours=1)
            maintenance_end = fixed_time + timedelta(days=5, hours=2)
            booking = room_service.create_booking(user, room.id, original_start, original_end)
            room_service.create_maintenance_schedule(
                admin, room.id, maintenance_start, maintenance_end, "정기점검"
            )

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.modify_booking(
                    user, booking.id, maintenance_start, maintenance_end
                )

            unchanged = room_service.booking_repo.get_by_id(booking.id)
            assert "점검 일정" in str(exc_info.value)
            assert datetime.fromisoformat(unchanged.start_time) == datetime.fromisoformat(booking.start_time)
            assert datetime.fromisoformat(unchanged.end_time) == datetime.fromisoformat(booking.end_time)

    def test_create_maintenance_admin_cancels_existing_future_booking(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 8, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            user = create_test_user(username="student")
            room = create_test_room()
            start = fixed_time + timedelta(days=6, hours=1)
            end = fixed_time + timedelta(days=6, hours=2)
            booking = room_service.create_booking(user, room.id, start, end)

            room_service.create_maintenance_schedule(admin, room.id, start, end, "긴급점검")

            updated = room_service.booking_repo.get_by_id(booking.id)
            assert updated.status == RoomBookingStatus.ADMIN_CANCELLED
            assert updated.cancelled_at is not None
