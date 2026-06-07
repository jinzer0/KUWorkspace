from datetime import datetime, timedelta

from src.domain.models import (
    EquipmentBookingStatus,
    RoomBookingStatus,
)
from src.storage.file_lock import global_lock


def test_room_pending_resolver_promotes_deterministic_winner_and_rewrites_waitlist(
    policy_service,
    create_test_user,
    room_booking_repo,
    room_booking_factory,
    temp_data_dir,
    fake_clock,
):
    current_time = datetime(2024, 6, 16, 9, 0, 0)
    fake_clock(current_time)
    high_penalty = create_test_user(username="room_high", penalty_points=4)
    later_low = create_test_user(username="room_later", penalty_points=0)
    winner = create_test_user(username="room_winner", penalty_points=0)
    temp_data_dir.joinpath("waitlist.txt").write_text("corrupt|authoritative|no\n", encoding="utf-8")

    with global_lock():
        room_booking_repo.add(
            room_booking_factory(
                id="room-pending-high",
                user_id=high_penalty.id,
                room_id="room-1",
                start_time="2024-06-17T09:00",
                end_time="2024-06-17T18:00",
                status=RoomBookingStatus.PENDING,
                created_at="2024-06-15T09:00",
            )
        )
        room_booking_repo.add(
            room_booking_factory(
                id="room-pending-later",
                user_id=later_low.id,
                room_id="room-1",
                start_time="2024-06-17T09:00",
                end_time="2024-06-17T18:00",
                status=RoomBookingStatus.PENDING,
                created_at="2024-06-15T11:00",
            )
        )
        room_booking_repo.add(
            room_booking_factory(
                id="room-pending-winner",
                user_id=winner.id,
                room_id="room-1",
                start_time="2024-06-17T09:00",
                end_time="2024-06-17T18:00",
                status=RoomBookingStatus.PENDING,
                created_at="2024-06-15T10:00",
            )
        )

    result = policy_service.run_all_checks(current_time)

    assert result["room_pending_promoted"] == ["room-pending-winner"]
    assert result["room_pending_cancelled"] == [
        "room-pending-later",
        "room-pending-high",
    ]
    assert room_booking_repo.get_by_id("room-pending-winner").status == RoomBookingStatus.RESERVED
    assert room_booking_repo.get_by_id("room-pending-later").status == RoomBookingStatus.CANCELLED
    assert room_booking_repo.get_by_id("room-pending-high").status == RoomBookingStatus.CANCELLED
    assert temp_data_dir.joinpath("waitlist.txt").read_text(encoding="utf-8") == ""


def test_pending_waitlist_projection_is_deterministic_and_non_authoritative(
    policy_service,
    create_test_user,
    room_booking_repo,
    equipment_booking_repo,
    room_booking_factory,
    equipment_booking_factory,
    temp_data_dir,
    fake_clock,
):
    current_time = datetime(2024, 6, 16, 9, 0, 0)
    fake_clock(current_time)
    user = create_test_user(username="projection_user")

    with global_lock():
        room_booking_repo.add(
            room_booking_factory(
                id="room-reserved-conflict",
                user_id="other-room-user",
                room_id="room-projection",
                start_time="2024-06-18T09:00",
                end_time="2024-06-18T18:00",
                status=RoomBookingStatus.RESERVED,
            )
        )
        room_booking_repo.add(
            room_booking_factory(
                id="room-pending-projection",
                user_id=user.id,
                room_id="room-projection",
                start_time="2024-06-18T09:00",
                end_time="2024-06-18T18:00",
                status=RoomBookingStatus.PENDING,
                created_at="2024-06-15T12:00",
            )
        )
        equipment_booking_repo.add(
            equipment_booking_factory(
                id="equipment-reserved-conflict",
                user_id="other-equipment-user",
                equipment_id="equipment-projection",
                start_time="2024-06-19T09:00",
                end_time="2024-06-19T18:00",
                status=EquipmentBookingStatus.RESERVED,
            )
        )
        equipment_booking_repo.add(
            equipment_booking_factory(
                id="equipment-pending-projection",
                user_id=user.id,
                equipment_id="equipment-projection",
                start_time="2024-06-19T09:00",
                end_time="2024-06-19T18:00",
                status=EquipmentBookingStatus.PENDING,
                created_at="2024-06-15T11:00",
            )
        )
    temp_data_dir.joinpath("waitlist.txt").write_text("garbage\n", encoding="utf-8")

    result = policy_service.run_all_checks(current_time)

    expected = (
        "equipment|equipment-projection|2024-06-19T09:00|2024-06-19T18:00|"
        "2024-06-15T11:00|equipment-pending-projection|projection_user\n"
        "room|room-projection|2024-06-18T09:00|2024-06-18T18:00|"
        "2024-06-15T12:00|room-pending-projection|projection_user\n"
    )
    assert result["waitlist_projection"] == expected
    assert temp_data_dir.joinpath("waitlist.txt").read_text(encoding="utf-8") == expected
    assert room_booking_repo.get_by_id("room-pending-projection").status == RoomBookingStatus.PENDING
    assert equipment_booking_repo.get_by_id("equipment-pending-projection").status == EquipmentBookingStatus.PENDING


def test_conflicting_room_and_equipment_requests_create_pending_rows(
    room_service,
    equipment_service,
    create_test_user,
    create_test_room,
    create_test_equipment,
    fake_clock,
):
    current_time = datetime(2024, 6, 15, 9, 0, 0)
    fake_clock(current_time)
    room_user = create_test_user(username="room_reserved_user")
    room_waiter = create_test_user(username="room_pending_user")
    equipment_user = create_test_user(username="equip_reserved")
    equipment_waiter = create_test_user(username="equip_pending")
    room = create_test_room()
    equipment = create_test_equipment()
    start = current_time + timedelta(hours=1)
    end = current_time + timedelta(hours=2)

    room_service.create_booking(room_user, room.id, start, end)
    room_pending = room_service.create_booking(room_waiter, room.id, start, end)
    equipment_service.create_booking(equipment_user, equipment.id, start, end)
    equipment_pending = equipment_service.create_booking(equipment_waiter, equipment.id, start, end)

    assert room_pending.status == RoomBookingStatus.PENDING
    assert equipment_pending.status == EquipmentBookingStatus.PENDING
