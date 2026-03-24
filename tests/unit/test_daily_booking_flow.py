import pytest
from datetime import date, datetime, timedelta

from src.domain.models import EquipmentBookingStatus, ResourceStatus, RoomBookingStatus, UserRole
from src.domain.room_service import RoomBookingError
from src.domain.equipment_service import EquipmentBookingError


def test_room_daily_booking_success(room_service, create_test_user, create_test_room, mock_now):
    fixed_time = datetime(2024, 6, 15, 10, 0, 0)

    with mock_now(fixed_time):
        user = create_test_user()
        room = create_test_room(capacity=6)

        booking = room_service.create_daily_booking(
            user=user,
            room_id=room.id,
            start_date=date(2024, 6, 16),
            end_date=date(2024, 6, 18),
            attendee_count=5,
        )

        assert booking.status == RoomBookingStatus.RESERVED
        assert datetime.fromisoformat(booking.start_time) == datetime(2024, 6, 16, 9, 0, 0)
        assert datetime.fromisoformat(booking.end_time) == datetime(2024, 6, 18, 18, 0, 0)


def test_room_daily_booking_blocks_same_day(room_service, create_test_user, create_test_room, mock_now):
    fixed_time = datetime(2024, 6, 15, 10, 0, 0)

    with mock_now(fixed_time):
        user = create_test_user()
        room = create_test_room(capacity=6)

        with pytest.raises(RoomBookingError) as exc_info:
            room_service.create_daily_booking(
                user=user,
                room_id=room.id,
                start_date=date(2024, 6, 15),
                end_date=date(2024, 6, 16),
                attendee_count=4,
            )

        assert "당일 예약" in str(exc_info.value)


def test_daily_booking_blocks_over_6_month_window(
    room_service, create_test_user, create_test_room, mock_now
):
    fixed_time = datetime(2024, 6, 15, 10, 0, 0)

    with mock_now(fixed_time):
        user = create_test_user()
        room = create_test_room(capacity=8)

        with pytest.raises(RoomBookingError) as exc_info:
            room_service.create_daily_booking(
                user=user,
                room_id=room.id,
                start_date=date(2024, 12, 16),
                end_date=date(2024, 12, 16),
                attendee_count=4,
            )

        assert "6개월" in str(exc_info.value)


def test_daily_booking_blocks_over_14_days(
    equipment_service, create_test_user, create_test_equipment, mock_now
):
    fixed_time = datetime(2024, 6, 15, 10, 0, 0)

    with mock_now(fixed_time):
        user = create_test_user()
        equipment = create_test_equipment()

        with pytest.raises(EquipmentBookingError) as exc_info:
            equipment_service.create_daily_booking(
                user=user,
                equipment_id=equipment.id,
                start_date=date(2024, 6, 16),
                end_date=date(2024, 6, 30),
            )

        assert "14일" in str(exc_info.value)


def test_policy_allows_one_room_and_one_equipment_separately(
    policy_service,
    room_service,
    equipment_service,
    create_test_user,
    create_test_room,
    create_test_equipment,
    mock_now,
):
    fixed_time = datetime(2024, 6, 15, 10, 0, 0)

    with mock_now(fixed_time):
        user = create_test_user()
        room = create_test_room(capacity=6)
        equipment = create_test_equipment()

        room_service.create_daily_booking(
            user=user,
            room_id=room.id,
            start_date=date(2024, 6, 16),
            end_date=date(2024, 6, 16),
            attendee_count=4,
        )

        limits = policy_service.get_user_flow_limits(user)
        assert limits["room_limit"] == 0
        assert limits["equipment_limit"] == 1

        booking = equipment_service.create_daily_booking(
            user=user,
            equipment_id=equipment.id,
            start_date=date(2024, 6, 16),
            end_date=date(2024, 6, 16),
        )
        assert booking.status == EquipmentBookingStatus.RESERVED


def test_room_capacity_falls_back_to_larger_room(
    room_service, create_test_room, mock_now
):
    fixed_time = datetime(2024, 6, 15, 10, 0, 0)

    with mock_now(fixed_time):
        create_test_room(name="Small", capacity=4)
        create_test_room(name="Large", capacity=8)
        start_time = datetime(2024, 6, 16, 9, 0, 0)
        end_time = datetime(2024, 6, 16, 18, 0, 0)

        rooms = room_service.get_available_rooms_for_attendees(5, start_time, end_time)

        assert len(rooms) == 1
        assert rooms[0].name == "Large"


def test_room_checkout_request_and_approval_completes_without_delay_penalty(
    room_service, auth_service, create_test_user, create_test_room, mock_now
):
    with mock_now(datetime(2024, 6, 15, 10, 0, 0)):
        user = create_test_user()
        admin = create_test_user(username="admin-room", role=UserRole.ADMIN)
        room = create_test_room(capacity=6)
        booking = room_service.create_daily_booking(
            user=user,
            room_id=room.id,
            start_date=date(2024, 6, 16),
            end_date=date(2024, 6, 16),
            attendee_count=4,
        )

    with mock_now(datetime(2024, 6, 16, 9, 0, 0)):
        room_service.check_in(admin, booking.id)

    with mock_now(datetime(2024, 6, 16, 18, 0, 0)):
        requested = room_service.request_checkout(user, booking.id)
        assert requested.status == RoomBookingStatus.CHECKOUT_REQUESTED

        approved, delay_minutes = room_service.approve_checkout_request(admin, booking.id)
        assert approved.status == RoomBookingStatus.COMPLETED
        assert delay_minutes == 0
        assert auth_service.get_user(user.id).penalty_points == 0


def test_equipment_return_request_and_approval_completes_without_delay_penalty(
    equipment_service, auth_service, create_test_user, create_test_equipment, mock_now
):
    with mock_now(datetime(2024, 6, 15, 10, 0, 0)):
        user = create_test_user()
        admin = create_test_user(username="admin-equip", role=UserRole.ADMIN)
        equipment = create_test_equipment(status=ResourceStatus.AVAILABLE)
        booking = equipment_service.create_daily_booking(
            user=user,
            equipment_id=equipment.id,
            start_date=date(2024, 6, 16),
            end_date=date(2024, 6, 16),
        )

    with mock_now(datetime(2024, 6, 16, 9, 0, 0)):
        equipment_service.checkout(admin, booking.id)

    with mock_now(datetime(2024, 6, 16, 18, 0, 0)):
        requested = equipment_service.request_return(user, booking.id)
        assert requested.status == EquipmentBookingStatus.RETURN_REQUESTED

        approved, delay_minutes = equipment_service.approve_return_request(
            admin, booking.id
        )
        assert approved.status == EquipmentBookingStatus.RETURNED
        assert delay_minutes == 0
        assert auth_service.get_user(user.id).penalty_points == 0
