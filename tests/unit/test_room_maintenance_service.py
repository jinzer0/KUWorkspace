from datetime import datetime, timedelta

import pytest

from src.domain.models import RoomBookingStatus, UserRole, RoomMaintenanceSchedule
from src.domain.room_service import RoomBookingError
from src.storage.file_lock import global_lock


class TestRoomMaintenanceService:
    def test_inspect1_maintenance_uses_1800_start_0900_end_and_rejects_same_or_current_day(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)
        with mock_now(fixed_time):
            admin = create_test_user(username="InspectMaintAdmin", role=UserRole.ADMIN)
            room = create_test_room(name="회의실3A")

            schedule = room_service.create_maintenance_schedule(
                admin,
                room.id,
                datetime(2024, 6, 16, 18, 0, 0),
                datetime(2024, 6, 17, 9, 0, 0),
                "야간점검",
            )
            with pytest.raises(RoomBookingError):
                room_service.create_maintenance_schedule(
                    admin,
                    room.id,
                    datetime(2024, 6, 18, 18, 0, 0),
                    datetime(2024, 6, 18, 9, 0, 0),
                    "당일점검",
                )
            with pytest.raises(RoomBookingError):
                room_service.create_maintenance_schedule(
                    admin,
                    room.id,
                    datetime(2024, 6, 15, 18, 0, 0),
                    datetime(2024, 6, 16, 9, 0, 0),
                    "오늘점검",
                )

            assert schedule.start_time == "2024-06-16T18:00:00"
            assert schedule.end_time == "2024-06-17T09:00:00"

    def test_inspect1_maintenance_overlap_rejects_without_mutating_bookings_and_cancel_active_available(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)
        with mock_now(fixed_time):
            admin = create_test_user(username="InspectMaintAdmin2", role=UserRole.ADMIN)
            user = create_test_user(username="InspectMaintUser")
            room = create_test_room(name="회의실3B")
            booking = room_service.create_booking(
                user,
                room.id,
                datetime(2024, 6, 16, 9, 0, 0),
                datetime(2024, 6, 17, 18, 0, 0),
            )
            with pytest.raises(RoomBookingError, match="겹치는 예약|예약과 겹"):
                room_service.create_maintenance_schedule(
                    admin,
                    room.id,
                    datetime(2024, 6, 16, 18, 0, 0),
                    datetime(2024, 6, 17, 9, 0, 0),
                    "예약겹침",
                )
            active = room_service.create_maintenance_schedule(
                admin,
                room.id,
                datetime(2024, 6, 18, 18, 0, 0),
                datetime(2024, 6, 19, 9, 0, 0),
                "활성점검",
            )
            with global_lock():
                room_service.maintenance_repo.update(
                    RoomMaintenanceSchedule.from_record(
                        [
                            active.id,
                            active.room_id,
                            active.start_time,
                            active.end_time,
                            "active",
                            active.created_at,
                            active.updated_at,
                            "-",
                        ]
                    )
                )
            cancelled = room_service.cancel_maintenance_schedule(admin, active.id, "복구")

            assert room_service.booking_repo.get_by_id(booking.id).status == RoomBookingStatus.RESERVED
            assert cancelled.status == "cancelled"
            assert room_service.get_room(room.id).status.value == "available"

    def test_create_maintenance_rejects_overlapping_schedule_deterministically(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 8, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            room = create_test_room()
            start = fixed_time + timedelta(days=1, hours=1)
            end = fixed_time + timedelta(days=2, hours=1)

            schedule = room_service.create_maintenance_schedule(
                admin, room.id, start, end, "정기점검"
            )

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.create_maintenance_schedule(
                    admin, room.id, start + timedelta(hours=1), end, "중복점검"
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
            end = fixed_time + timedelta(days=3, hours=1)
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
            stored = room_service.maintenance_repo.get_by_id(schedule.id)
            assert stored.status == "cancelled"
            assert stored.cancelled_at is not None
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
            end = fixed_time + timedelta(days=4, hours=1)
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
            maintenance_end = fixed_time + timedelta(days=6, hours=1)
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

    def test_create_maintenance_rejects_existing_future_booking_without_mutation(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 8, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            user = create_test_user(username="student")
            room = create_test_room()
            start = fixed_time + timedelta(days=6, hours=1)
            end = fixed_time + timedelta(days=7, hours=1)
            booking = room_service.create_booking(user, room.id, start, end)

            with pytest.raises(RoomBookingError, match="겹치는 예약"):
                room_service.create_maintenance_schedule(admin, room.id, start, end, "긴급점검")

            updated = room_service.booking_repo.get_by_id(booking.id)
            assert updated.status == RoomBookingStatus.RESERVED
            assert updated.cancelled_at is None
            assert room_service.maintenance_repo.get_by_room(room.id) == []


    def test_policy_lifecycle_preserves_and_completes_maintenance_rows(
        self, policy_service, create_test_room, room_maintenance_repo, fake_clock
    ):
        room = create_test_room()
        schedule = RoomMaintenanceSchedule(
            id="maintenance-lifecycle",
            room_id=room.id,
            start_time="2024-06-16T09:00",
            end_time="2024-06-16T18:00",
            status="scheduled",
            created_at="2024-06-15T09:00",
            updated_at="2024-06-15T09:00",
        )
        with global_lock():
            room_maintenance_repo.add(schedule)

        fake_clock(datetime(2024, 6, 16, 9, 0, 0))
        started = policy_service.run_all_checks()
        assert started["room_maintenance_active"] == ["maintenance-lifecycle"]
        assert room_maintenance_repo.get_by_id("maintenance-lifecycle").status == "active"

        fake_clock(datetime(2024, 6, 16, 18, 0, 0))
        completed = policy_service.run_all_checks()
        stored = room_maintenance_repo.get_by_id("maintenance-lifecycle")
        assert completed["room_maintenance_expired"] == ["maintenance-lifecycle"]
        assert stored.status == "completed"
        assert stored.cancelled_at is None
