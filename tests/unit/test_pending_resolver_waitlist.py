from datetime import datetime, timedelta

import pytest

from src.domain.models import (
    EquipmentBooking,
    EquipmentBookingStatus,
    RoomBookingStatus,
    UserRole,
    WaitingListEntry,
)
from src.cli.user_menu import UserMenu
from src.storage.repositories import WaitingListRepository
from src.domain.room_service import RoomBookingError
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
    assert temp_data_dir.joinpath("waitlist.txt").read_text(encoding="utf-8") == "corrupt|authoritative|no\n"


def test_plan0001_pending_priority_uses_penalty_then_created_at(
    policy_service,
    create_test_user,
    room_booking_repo,
    room_booking_factory,
    temp_data_dir,
    fake_clock,
):
    current_time = datetime(2024, 6, 16, 9, 0, 0)
    fake_clock(current_time)
    high_penalty = create_test_user(username="PlanHighPenalty", penalty_points=4)
    earliest_low = create_test_user(username="PlanEarliestLow", penalty_points=0)
    later_low = create_test_user(username="PlanLaterLow", penalty_points=0)

    with global_lock():
        room_booking_repo.add(
            room_booking_factory(
                id="plan-high-penalty",
                user_id=high_penalty.id,
                room_id="room-plan-priority",
                start_time="2024-06-17T09:00",
                end_time="2024-06-17T18:00",
                status=RoomBookingStatus.PENDING,
                created_at="2024-06-15T08:00",
            )
        )
        room_booking_repo.add(
            room_booking_factory(
                id="plan-earliest-low",
                user_id=earliest_low.id,
                room_id="room-plan-priority",
                start_time="2024-06-17T09:00",
                end_time="2024-06-17T18:00",
                status=RoomBookingStatus.PENDING,
                created_at="2024-06-15T09:00",
            )
        )
        room_booking_repo.add(
            room_booking_factory(
                id="plan-later-low",
                user_id=later_low.id,
                room_id="room-plan-priority",
                start_time="2024-06-17T09:00",
                end_time="2024-06-17T18:00",
                status=RoomBookingStatus.PENDING,
                created_at="2024-06-15T10:00",
            )
        )

    result = policy_service.run_all_checks(current_time)

    assert result["room_pending_promoted"] == ["plan-earliest-low"]
    assert result["room_pending_cancelled"] == ["plan-later-low", "plan-high-penalty"]
    assert not temp_data_dir.joinpath("waitlist.txt").exists()


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

    assert result["waitlist_projection"] == ""
    assert temp_data_dir.joinpath("waitlist.txt").read_text(encoding="utf-8") == "garbage\n"
    assert room_booking_repo.get_by_id("room-pending-projection").status == RoomBookingStatus.PENDING
    assert equipment_booking_repo.get_by_id("equipment-pending-projection").status == EquipmentBookingStatus.PENDING


def test_pending_conflicts_do_not_create_authoritative_waiting_list_rows(
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
    user = create_test_user(username="PendingNotWaitlist")
    waiting_repo = WaitingListRepository(file_path=temp_data_dir / "waiting_list.txt")

    with global_lock():
        room_booking_repo.add(
            room_booking_factory(
                id="wl03-room-pending",
                user_id=user.id,
                room_id="wl03-room",
                start_time="2024-06-18T09:00",
                end_time="2024-06-18T18:00",
                status=RoomBookingStatus.PENDING,
                created_at="2024-06-15T12:00",
            )
        )
        equipment_booking_repo.add(
            equipment_booking_factory(
                id="wl03-equipment-pending",
                user_id=user.id,
                equipment_id="wl03-equipment",
                start_time="2024-06-19T09:00",
                end_time="2024-06-19T18:00",
                status=EquipmentBookingStatus.PENDING,
                created_at="2024-06-15T11:00",
            )
        )

    result = policy_service.run_all_checks(current_time)

    assert result["waitlist_projection"] == ""
    assert waiting_repo.get_all() == []
    assert (temp_data_dir / "waiting_list.txt").read_text(encoding="utf-8") == ""
    assert not (temp_data_dir / "waitlist.txt").exists()


def test_inspect1_waitlist_projection_file_is_not_created_or_updated(
    policy_service,
    create_test_user,
    room_booking_repo,
    room_booking_factory,
    temp_data_dir,
    fake_clock,
):
    current_time = datetime(2024, 6, 16, 9, 0, 0)
    fake_clock(current_time)
    user = create_test_user(username="InspectWaitProjection")
    legacy_projection = temp_data_dir / "waitlist.txt"
    legacy_projection.write_text("legacy projection must stay untouched\n", encoding="utf-8")
    with global_lock():
        room_booking_repo.add(
            room_booking_factory(
                id="inspect1-room-pending-projection",
                user_id=user.id,
                room_id="room-inspect1-projection",
                start_time="2024-06-18T09:00",
                end_time="2024-06-18T18:00",
                status=RoomBookingStatus.PENDING,
                created_at="2024-06-15T12:00",
            )
        )

    result = policy_service.run_all_checks(current_time)

    assert result["waitlist_projection"] == ""
    assert legacy_projection.read_text(encoding="utf-8") == "legacy projection must stay untouched\n"


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
    equipment_pending = equipment_service.create_booking(
        equipment_waiter, equipment.id, start, end
    )

    assert room_pending.status == RoomBookingStatus.PENDING
    assert equipment_pending.status == EquipmentBookingStatus.PENDING


def test_plan0001_eighteen_next_day_exception_rejects_later_request(
    room_service,
    create_test_user,
    create_test_room,
    room_booking_repo,
    fake_clock,
):
    current_time = datetime(2024, 6, 15, 18, 0, 0)
    fake_clock(current_time)
    first_user = create_test_user(username="FirstNextDay")
    later_user = create_test_user(username="LaterNextDay")
    room = create_test_room()
    start = datetime(2024, 6, 16, 9, 0, 0)
    end = datetime(2024, 6, 16, 18, 0, 0)

    first = room_service.create_booking(first_user, room.id, start, end)

    with pytest.raises(RoomBookingError, match="선착순|18:00|거부"):
        room_service.create_booking(later_user, room.id, start, end)

    assert first.status == RoomBookingStatus.RESERVED
    assert [booking.id for booking in room_booking_repo.get_by_room(room.id)] == [first.id]


def test_plan0001_waiting_list_request_persists_seven_fields(
    create_test_user,
    create_test_room,
    auth_service,
    room_service,
    equipment_service,
    policy_service,
    temp_data_dir,
    room_booking_repo,
    room_booking_factory,
):
    user = create_test_user(username="WaitListUser")
    room = create_test_room()
    booking = room_booking_factory(
        id="waitlist-target-room-booking",
        user_id="other-user",
        room_id=room.id,
        start_time=(datetime.now() + timedelta(days=2)).replace(hour=9, minute=0, second=0, microsecond=0).isoformat(),
        end_time=(datetime.now() + timedelta(days=2)).replace(hour=18, minute=0, second=0, microsecond=0).isoformat(),
        status=RoomBookingStatus.RESERVED,
    )
    with global_lock():
        room_booking_repo.add(booking)
    repository = WaitingListRepository(file_path=temp_data_dir / "waiting_list.txt")
    menu = UserMenu(
        user,
        auth_service=auth_service,
        room_service=room_service,
        equipment_service=equipment_service,
        policy_service=policy_service,
        waiting_list_repo=repository,
    )

    entry = menu.create_waiting_list_request("room_booking", booking.id, 4)

    assert entry.username == "WaitListUser"
    raw = (temp_data_dir / "waiting_list.txt").read_text(encoding="utf-8").strip()
    fields = raw.split("|")
    assert len(fields) == 7
    assert fields[:5] == [entry.id, "WaitListUser", "room_booking", booking.id, "4"]


def test_plan0001_waiting_list_order_is_deterministic_after_reload(temp_data_dir):
    repository = WaitingListRepository(file_path=temp_data_dir / "waiting_list.txt")
    with global_lock():
        repository.add(
            WaitingListEntry(
                id="waiting-b",
                username="LaterUser",
                related_type="room_booking",
                related_id="room-booking-1",
                user_count=2,
                created_at="2024-06-15T10:00",
                updated_at="2024-06-15T10:00",
            )
        )
        repository.add(
            WaitingListEntry(
                id="waiting-a",
                username="EarlierUser",
                related_type="room_booking",
                related_id="room-booking-1",
                user_count=2,
                created_at="2024-06-15T09:00",
                updated_at="2024-06-15T09:00",
            )
        )

    reloaded = WaitingListRepository(file_path=temp_data_dir / "waiting_list.txt").get_all()

    assert [entry.id for entry in reloaded] == ["waiting-a", "waiting-b"]


def test_inspect1_waiting_list_request_targets_existing_booking_and_guards_duplicates_limits_and_dates(
    create_test_user,
    create_test_room,
    auth_service,
    room_service,
    equipment_service,
    policy_service,
    room_booking_repo,
    room_booking_factory,
    temp_data_dir,
):
    user = create_test_user(username="InspectWaiter")
    room = create_test_room(name="회의실2A")
    repository = WaitingListRepository(file_path=temp_data_dir / "waiting_list.txt")
    menu = UserMenu(
        user,
        auth_service=auth_service,
        room_service=room_service,
        equipment_service=equipment_service,
        policy_service=policy_service,
        waiting_list_repo=repository,
    )
    booking = room_booking_factory(
        id="inspect1-existing-room-booking",
        user_id="other-user",
        room_id=room.id,
        start_time=(datetime.now() + timedelta(days=2)).replace(hour=9, minute=0, second=0, microsecond=0).isoformat(),
        end_time=(datetime.now() + timedelta(days=2)).replace(hour=18, minute=0, second=0, microsecond=0).isoformat(),
        status=RoomBookingStatus.RESERVED,
    )
    with global_lock():
        room_booking_repo.add(booking)

    other_bookings = []
    for index in range(3):
        other = room_booking_factory(
            id=f"inspect1-other-booking-{index}",
            user_id=f"other-user-{index}",
            room_id=room.id,
            start_time=(datetime.now() + timedelta(days=index + 3)).replace(hour=9, minute=0, second=0, microsecond=0).isoformat(),
            end_time=(datetime.now() + timedelta(days=index + 3)).replace(hour=18, minute=0, second=0, microsecond=0).isoformat(),
            status=RoomBookingStatus.RESERVED,
        )
        other_bookings.append(other)
    with global_lock():
        for other in other_bookings:
            room_booking_repo.add(other)

    first = menu.create_waiting_list_request("room_booking", booking.id, 4)
    with pytest.raises(RoomBookingError, match="이미|중복"):
        menu.create_waiting_list_request("room_booking", booking.id, 4)
    with pytest.raises(RoomBookingError, match="존재하지 않는 예약|예약 건"):
        menu.create_waiting_list_request("room_booking", "missing-booking", 4)
    for other in other_bookings[:2]:
        menu.create_waiting_list_request("room_booking", other.id, 4)
    with pytest.raises(RoomBookingError, match="최대|3건"):
        menu.create_waiting_list_request("room_booking", other_bookings[2].id, 4)

    assert first.related_type == "room_booking"
    assert first.related_id == booking.id



def test_room_cancellation_promotes_first_eligible_waitlist_entry_and_removes_skips(
    create_test_user,
    create_test_room,
    room_service,
    room_booking_repo,
    room_booking_factory,
    temp_data_dir,
    fake_clock,
):
    current_time = datetime(2024, 6, 15, 9, 0, 0)
    fake_clock(current_time)
    owner = create_test_user(username="WaitOwner")
    missing_username = "MissingWaiter"
    banned = create_test_user(
        username="BannedWaiter",
        penalty_points=6,
        restriction_until="2024-07-15T09:00",
    )
    eligible = create_test_user(username="EligibleWaiter")
    later = create_test_user(username="LaterWaiter")
    room = create_test_room(name="회의실2B")
    target = room_booking_factory(
        id="waitlist-cancel-target",
        user_id=owner.id,
        room_id=room.id,
        start_time="2024-06-20T09:00",
        end_time="2024-06-20T18:00",
        status=RoomBookingStatus.RESERVED,
    )
    waiting_repo = WaitingListRepository(file_path=temp_data_dir / "waiting_list.txt")
    with global_lock():
        room_booking_repo.add(target)
        waiting_repo.add(WaitingListEntry("skip-missing", missing_username, "room_booking", target.id, 4, "2024-06-15T09:00", "2024-06-15T09:00"))
        waiting_repo.add(WaitingListEntry("skip-banned", banned.username, "room_booking", target.id, 4, "2024-06-15T09:01", "2024-06-15T09:01"))
        waiting_repo.add(WaitingListEntry("promote-eligible", eligible.username, "room_booking", target.id, 4, "2024-06-15T09:02", "2024-06-15T09:02"))
        waiting_repo.add(WaitingListEntry("leave-later", later.username, "room_booking", target.id, 4, "2024-06-15T09:03", "2024-06-15T09:03"))

    cancelled, _ = room_service.cancel_booking(owner, target.id)

    assert cancelled.status == RoomBookingStatus.CANCELLED
    promoted = [
        booking
        for booking in room_booking_repo.get_by_room(room.id)
        if booking.user_id == eligible.id and booking.status == RoomBookingStatus.RESERVED
    ]
    assert len(promoted) == 1
    assert promoted[0].start_time == target.start_time
    assert promoted[0].end_time == target.end_time
    assert [entry.id for entry in waiting_repo.get_by_related("room_booking", target.id)] == ["leave-later"]



def test_equipment_admin_cancellation_promotes_waitlist_entry(
    create_test_user,
    create_test_equipment,
    equipment_service,
    equipment_booking_repo,
    equipment_booking_factory,
    temp_data_dir,
    fake_clock,
):
    current_time = datetime(2024, 6, 15, 9, 0, 0)
    fake_clock(current_time)
    admin = create_test_user(username="EquipWaitAdmin", role=UserRole.ADMIN)
    owner = create_test_user(username="EquipWaitOwner")
    waiter = create_test_user(username="EquipWaiter")
    later = create_test_user(username="EquipLater")
    equipment = create_test_equipment(name="프로젝터A", asset_type="projector")
    target = equipment_booking_factory(
        id="waitlist-equipment-target",
        user_id=owner.id,
        equipment_id=equipment.id,
        start_time="2024-06-20T09:00",
        end_time="2024-06-20T18:00",
        status=EquipmentBookingStatus.RESERVED,
    )
    waiting_repo = WaitingListRepository(file_path=temp_data_dir / "waiting_list.txt")
    with global_lock():
        equipment_booking_repo.add(target)
        waiting_repo.add(WaitingListEntry("promote-equipment", waiter.username, "equipment_booking", target.id, 1, "2024-06-15T09:00", "2024-06-15T09:00"))
        waiting_repo.add(WaitingListEntry("leave-equipment", later.username, "equipment_booking", target.id, 1, "2024-06-15T09:01", "2024-06-15T09:01"))

    cancelled = equipment_service.admin_cancel_booking(admin, target.id, "점검")

    assert cancelled.status == EquipmentBookingStatus.ADMIN_CANCELLED
    promoted = [
        booking
        for booking in equipment_booking_repo.get_by_equipment(equipment.id)
        if booking.user_id == waiter.id and booking.status == EquipmentBookingStatus.RESERVED
    ]
    assert len(promoted) == 1
    assert [entry.id for entry in waiting_repo.get_by_related("equipment_booking", target.id)] == ["leave-equipment"]
