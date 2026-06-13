"""Plan 0001 deterministic CLI smoke coverage."""

from datetime import datetime, timedelta
from dataclasses import replace
from pathlib import Path

import pytest

from src.cli.guest_menu import GuestMenu
from src.cli.user_menu import UserMenu
from src.cli.menu import input_start_gate, pause, review_action
from src.domain.equipment_service import EquipmentBookingError
from src.domain.models import (
    EquipmentAsset,
    EquipmentBooking,
    EquipmentBookingStatus,
    PenaltyReason,
    ResourceStatus,
    RoomBookingStatus,
    UserRole,
)
from src.domain.room_service import RoomBookingError
from src.storage.file_lock import global_lock
from src.storage.jsonl_handler import decode_record
from src.storage.repositories import WaitingListRepository


def _drive_inputs(monkeypatch, values):
    iterator = iter(values)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(iterator))


def _make_services(
    user_repo,
    room_repo,
    equipment_repo,
    room_booking_repo,
    equipment_booking_repo,
    room_maintenance_repo,
    penalty_repo,
    audit_repo,
    fake_clock,
    now,
):
    from src.domain.auth_service import AuthService
    from src.domain.equipment_service import EquipmentService
    from src.domain.penalty_service import PenaltyService
    from src.domain.policy_service import PolicyService
    from src.domain.room_service import RoomService

    clock = fake_clock(now)
    auth_service = AuthService(user_repo=user_repo)
    penalty_service = PenaltyService(
        user_repo=user_repo,
        penalty_repo=penalty_repo,
        audit_repo=audit_repo,
        clock=clock,
    )
    room_service = RoomService(
        room_repo=room_repo,
        booking_repo=room_booking_repo,
        equipment_booking_repo=equipment_booking_repo,
        maintenance_repo=room_maintenance_repo,
        user_repo=user_repo,
        audit_repo=audit_repo,
        penalty_service=penalty_service,
        clock=clock,
    )
    equipment_service = EquipmentService(
        equipment_repo=equipment_repo,
        booking_repo=equipment_booking_repo,
        room_booking_repo=room_booking_repo,
        user_repo=user_repo,
        audit_repo=audit_repo,
        penalty_service=penalty_service,
        clock=clock,
    )
    policy_service = PolicyService(
        user_repo=user_repo,
        room_booking_repo=room_booking_repo,
        equipment_booking_repo=equipment_booking_repo,
        equipment_repo=equipment_repo,
        room_maintenance_repo=room_maintenance_repo,
        penalty_repo=penalty_repo,
        audit_repo=audit_repo,
        penalty_service=penalty_service,
        clock=clock,
    )
    return auth_service, penalty_service, room_service, equipment_service, policy_service


def _add_rooms(create_test_room, count):
    return [
        create_test_room(name=f"회의실{index}A", capacity=4, location=f"{index}층", description="회의실")
        for index in range(1, count + 1)
    ]


def _add_equipment(create_test_equipment, count):
    return [
        create_test_equipment(
            id=f"NB-{index:03d}",
            serial_number=f"NB-{index:03d}",
            name="노트북",
            asset_type="laptop",
            description="노트북",
        )
        for index in range(1, count + 1)
    ]


def test_plan0001_cli_frequent_cancel_smoke(
    user_repo,
    room_repo,
    equipment_repo,
    room_booking_repo,
    equipment_booking_repo,
    room_maintenance_repo,
    penalty_repo,
    audit_repo,
    room_booking_factory,
    create_test_user,
    fake_clock,
):
    fixed_time = datetime(2026, 6, 15, 9, 0)
    _auth_service, penalty_service, _room_service, _equipment_service, _policy_service = _make_services(
        user_repo,
        room_repo,
        equipment_repo,
        room_booking_repo,
        equipment_booking_repo,
        room_maintenance_repo,
        penalty_repo,
        audit_repo,
        fake_clock,
        fixed_time,
    )

    def add_room_booking(user_id, booking_id, days_until_start, cancelled_days_ago=None, status=RoomBookingStatus.CANCELLED):
        start_time = fixed_time + timedelta(days=days_until_start)
        cancelled_at = None
        if cancelled_days_ago is not None:
            cancelled_at = (fixed_time - timedelta(days=cancelled_days_ago)).isoformat()
        booking = room_booking_factory(
            id=booking_id,
            user_id=user_id,
            room_id="room-frequent-cancel",
            start_time=start_time.isoformat(),
            end_time=(start_time + timedelta(hours=1)).isoformat(),
            status=status,
            cancelled_at=cancelled_at,
        )
        with global_lock():
            room_booking_repo.add(booking)
        return booking

    third_user = create_test_user(username="Freqthird1")
    add_room_booking(third_user.id, "third-prior-a", days_until_start=-8, cancelled_days_ago=10)
    add_room_booking(third_user.id, "third-prior-b", days_until_start=-3, cancelled_days_ago=5)
    third_current = add_room_booking(
        third_user.id,
        "third-current",
        days_until_start=13,
        status=RoomBookingStatus.RESERVED,
    )

    third_impact, third_created = penalty_service.apply_cancel_impact(
        user=third_user,
        booking_type="room_booking",
        booking_id=third_current.id,
        booking_start_time=third_current.start_time,
        domain_bookings=room_booking_repo.get_by_user(third_user.id),
        actor_id=third_user.id,
    )

    assert third_impact.frequent_cancel_count == 3
    assert third_impact.applies_cancel_restriction is True
    assert third_impact.cancel_restriction_field == "room_cancel_restricted_until"
    assert third_impact.penalty_reasons == (PenaltyReason.FREQUENT_CANCEL,)
    assert [(penalty.reason, penalty.points) for penalty in third_created] == [
        (PenaltyReason.FREQUENT_CANCEL, 1)
    ]
    third_updated = user_repo.get_by_id(third_user.id)
    assert third_updated.penalty_points == 1
    assert third_updated.room_cancel_restricted_until is not None
    assert third_updated.equipment_cancel_restricted_until is None

    fourth_user = create_test_user(username="Freqfourth1", penalty_points=1)
    existing_restriction = (fixed_time + timedelta(days=3)).isoformat(timespec="minutes")
    with global_lock():
        fourth_user = user_repo.update(
            replace(fourth_user, room_cancel_restricted_until=existing_restriction)
        )
    for index, cancelled_days_ago in enumerate((12, 8, 4), start=1):
        add_room_booking(
            fourth_user.id,
            f"fourth-prior-{index}",
            days_until_start=-cancelled_days_ago + 2,
            cancelled_days_ago=cancelled_days_ago,
        )
    fourth_current = add_room_booking(
        fourth_user.id,
        "fourth-current",
        days_until_start=13,
        status=RoomBookingStatus.RESERVED,
    )

    fourth_impact, fourth_created = penalty_service.apply_cancel_impact(
        user=fourth_user,
        booking_type="room_booking",
        booking_id=fourth_current.id,
        booking_start_time=fourth_current.start_time,
        domain_bookings=room_booking_repo.get_by_user(fourth_user.id),
        actor_id=fourth_user.id,
    )

    assert fourth_impact.frequent_cancel_count == 4
    assert fourth_impact.applies_cancel_restriction is False
    assert fourth_impact.cancel_restriction_until is None
    assert [(penalty.reason, penalty.points) for penalty in fourth_created] == [
        (PenaltyReason.FREQUENT_CANCEL, 1)
    ]
    fourth_updated = user_repo.get_by_id(fourth_user.id)
    assert fourth_updated.penalty_points == 2
    assert fourth_updated.room_cancel_restricted_until == existing_restriction

    late_user = create_test_user(username="Freqlate1")
    for index, cancelled_days_ago in enumerate((12, 8, 4), start=1):
        add_room_booking(
            late_user.id,
            f"late-prior-{index}",
            days_until_start=-cancelled_days_ago + 2,
            cancelled_days_ago=cancelled_days_ago,
        )
    late_start = fixed_time + timedelta(minutes=30)
    late_current = room_booking_factory(
        id="late-current",
        user_id=late_user.id,
        room_id="room-frequent-cancel",
        start_time=late_start.isoformat(),
        end_time=(late_start + timedelta(hours=1)).isoformat(),
        status=RoomBookingStatus.RESERVED,
    )
    with global_lock():
        room_booking_repo.add(late_current)

    late_impact, late_created = penalty_service.apply_cancel_impact(
        user=late_user,
        booking_type="room_booking",
        booking_id=late_current.id,
        booking_start_time=late_current.start_time,
        domain_bookings=room_booking_repo.get_by_user(late_user.id),
        actor_id=late_user.id,
    )

    assert late_impact.is_late_cancel is True
    assert late_impact.qualifies_frequent_cancel is False
    assert late_impact.penalty_reasons == (PenaltyReason.LATE_CANCEL,)
    assert [(penalty.reason, penalty.points) for penalty in late_created] == [
        (PenaltyReason.LATE_CANCEL, 2)
    ]
    late_penalties = penalty_repo.get_by_user(late_user.id)
    assert [penalty.reason for penalty in late_penalties].count(PenaltyReason.LATE_CANCEL) == 1
    assert [penalty.reason for penalty in late_penalties].count(PenaltyReason.FREQUENT_CANCEL) == 0


def test_plan0001_cli_signup_validation(
    monkeypatch,
    capsys,
    auth_service,
    policy_service,
):
    menu = GuestMenu(auth_service=auth_service, policy_service=policy_service)
    _drive_inputs(
        monkeypatch,
        [
            "1",
            "lowercase",
            "1",
            "Validuser1",
            "letters",
            "pass1",
            "mismatch",
            "pass1",
            "pass1",
            "2",
            "1",
            "Validuser1",
            "pass2",
            "pass2",
            "1",
            "0",
        ],
    )

    menu._signup()

    output = capsys.readouterr().out
    assert "첫 글자 대문자" in output or "대문자로 시작" in output
    assert "숫자" in output
    assert "비밀번호가 일치하지 않습니다." in output
    assert "[회원가입 검토]" in output
    assert "0. 취소" in output
    assert "0. 돌아가기" in output
    assert auth_service.login("Validuser1", "pass2").username == "Validuser1"


def test_plan0001_cli_booking_limits(
    auth_service,
    room_service,
    equipment_service,
    penalty_service,
    create_test_room,
    create_test_equipment,
    mock_now,
):
    fixed_time = datetime(2026, 6, 1, 9, 0)
    with mock_now(fixed_time):
        normal_user = auth_service.signup("Limituser1", "pass1")
        restricted_user = auth_service.signup("Limituser2", "pass1")
        admin = auth_service.signup("Limitadmin1", "pass1", role=UserRole.ADMIN)
        rooms = _add_rooms(create_test_room, 8)
        equipment = _add_equipment(create_test_equipment, 8)

        for offset, room in enumerate(rooms[:3], start=1):
            booking = room_service.create_daily_booking(
                normal_user,
                room.id,
                fixed_time.date() + timedelta(days=offset),
                fixed_time.date() + timedelta(days=offset),
                attendee_count=2,
            )
            assert booking.status == RoomBookingStatus.RESERVED
        with pytest.raises(RoomBookingError, match="한도"):
            room_service.create_daily_booking(
                normal_user,
                rooms[3].id,
                fixed_time.date() + timedelta(days=4),
                fixed_time.date() + timedelta(days=4),
                attendee_count=2,
            )

        for offset, asset in enumerate(equipment[:3], start=1):
            booking = equipment_service.create_daily_booking(
                normal_user,
                asset.id,
                fixed_time.date() + timedelta(days=offset + 10),
                fixed_time.date() + timedelta(days=offset + 10),
            )
            assert booking.status == EquipmentBookingStatus.RESERVED
        with pytest.raises(EquipmentBookingError, match="한도"):
            equipment_service.create_daily_booking(
                normal_user,
                equipment[3].id,
                fixed_time.date() + timedelta(days=14),
                fixed_time.date() + timedelta(days=14),
            )

        penalty_service.apply_damage(
            admin,
            restricted_user,
            "room_booking",
            "restriction-trigger",
            points=3,
            memo="제한테스트",
        )
        room_service.create_daily_booking(
            restricted_user,
            rooms[4].id,
            fixed_time.date() + timedelta(days=5),
            fixed_time.date() + timedelta(days=5),
            attendee_count=2,
        )
        equipment_service.create_daily_booking(
            restricted_user,
            equipment[4].id,
            fixed_time.date() + timedelta(days=5),
            fixed_time.date() + timedelta(days=5),
        )
        with pytest.raises(RoomBookingError, match="추가 예약"):
            room_service.create_daily_booking(
                restricted_user,
                rooms[5].id,
                fixed_time.date() + timedelta(days=6),
                fixed_time.date() + timedelta(days=6),
                attendee_count=2,
            )
        with pytest.raises(EquipmentBookingError, match="추가 예약"):
            equipment_service.create_daily_booking(
                restricted_user,
                equipment[5].id,
                fixed_time.date() + timedelta(days=6),
                fixed_time.date() + timedelta(days=6),
            )


def test_plan0001_cli_pending_priority(
    user_repo,
    room_repo,
    equipment_repo,
    room_booking_repo,
    equipment_booking_repo,
    room_maintenance_repo,
    penalty_repo,
    audit_repo,
    create_test_room,
    create_test_equipment,
    fake_clock,
):
    fixed_time = datetime(2026, 6, 1, 9, 0)
    auth_service, _penalty_service, room_service, equipment_service, policy_service = _make_services(
        user_repo,
        room_repo,
        equipment_repo,
        room_booking_repo,
        equipment_booking_repo,
        room_maintenance_repo,
        penalty_repo,
        audit_repo,
        fake_clock,
        fixed_time,
    )
    room = create_test_room(name="회의실7A", capacity=6, location="7층", description="회의실")
    asset = create_test_equipment(
        id="NB-101", serial_number="NB-101", name="노트북", asset_type="laptop", description="노트북"
    )
    first = auth_service.signup("Prioritya1", "pass1")
    low_old = auth_service.signup("Priorityb1", "pass1")
    low_new = auth_service.signup("Priorityc1", "pass1")
    high = auth_service.signup("Priorityd1", "pass1")
    with global_lock():
        user_repo.update(replace(low_old, penalty_points=1))
        user_repo.update(replace(low_new, penalty_points=1))
        user_repo.update(replace(high, penalty_points=3))

    day = fixed_time.date() + timedelta(days=2)
    assert room_service.create_daily_booking(first, room.id, day, day, 2).status == RoomBookingStatus.RESERVED
    room_old = room_service.create_daily_booking(low_old, room.id, day, day, 2)
    room_new = room_service.create_daily_booking(low_new, room.id, day, day, 2)
    room_high = room_service.create_daily_booking(high, room.id, day, day, 2)
    assert [room_old.status, room_new.status, room_high.status] == [
        RoomBookingStatus.PENDING,
        RoomBookingStatus.PENDING,
        RoomBookingStatus.PENDING,
    ]
    with global_lock():
        room_old = room_booking_repo.update(replace(room_old, created_at="2026-06-01T07:00"))
        room_new = room_booking_repo.update(replace(room_new, created_at="2026-06-01T09:00"))
        room_high = room_booking_repo.update(replace(room_high, created_at="2026-06-01T08:00"))
    assert [item.id for item in room_booking_repo.get_pending_competition(room.id, room_old.start_time, room_old.end_time, user_repo)] == [
        room_old.id,
        room_new.id,
        room_high.id,
    ]

    equipment_start = datetime.combine(day, datetime.min.time().replace(hour=9))
    equipment_end = datetime.combine(day, datetime.min.time().replace(hour=18))
    with global_lock():
        equipment_old = equipment_booking_repo.add(EquipmentBooking(
            id="equipment-pending-old",
            user_id=low_old.id,
            equipment_id=asset.id,
            start_time=equipment_start.isoformat(),
            end_time=equipment_end.isoformat(),
            status=EquipmentBookingStatus.PENDING,
            created_at="2026-06-01T07:00",
        ))
        equipment_new = equipment_booking_repo.add(EquipmentBooking(
            id="equipment-pending-new",
            user_id=low_new.id,
            equipment_id=asset.id,
            start_time=equipment_start.isoformat(),
            end_time=equipment_end.isoformat(),
            status=EquipmentBookingStatus.PENDING,
            created_at="2026-06-01T09:00",
        ))
        equipment_high = equipment_booking_repo.add(EquipmentBooking(
            id="equipment-pending-high",
            user_id=high.id,
            equipment_id=asset.id,
            start_time=equipment_start.isoformat(),
            end_time=equipment_end.isoformat(),
            status=EquipmentBookingStatus.PENDING,
            created_at="2026-06-01T08:00",
        ))
    assert [item.id for item in equipment_booking_repo.get_pending_competition(asset.id, equipment_old.start_time, equipment_old.end_time, user_repo)] == [
        equipment_old.id,
        equipment_new.id,
        equipment_high.id,
    ]

    with global_lock():
        room_booking_repo.delete(room_booking_repo.get_by_user(first.id)[0].id)
    result = policy_service.run_all_checks(fixed_time + timedelta(days=1))
    assert result["room_pending_promoted"] == [room_old.id]
    assert result["equipment_pending_promoted"] == [equipment_old.id]

    late_clock = fake_clock(datetime(2026, 6, 10, 18, 0))
    _auth, _penalties, late_room_service, late_equipment_service, _policy = _make_services(
        user_repo,
        room_repo,
        equipment_repo,
        room_booking_repo,
        equipment_booking_repo,
        room_maintenance_repo,
        penalty_repo,
        audit_repo,
        fake_clock,
        late_clock.now(),
    )
    tomorrow = late_clock.now().date() + timedelta(days=1)
    late_room = create_test_room(name="회의실8A", capacity=6, location="8층", description="회의실")
    late_asset = create_test_equipment(
        id="NB-102", serial_number="NB-102", name="노트북", asset_type="laptop", description="노트북"
    )
    late_room_service.create_daily_booking(first, late_room.id, tomorrow, tomorrow, 2)
    late_equipment_service.create_daily_booking(first, late_asset.id, tomorrow, tomorrow)
    before_room_count = len(room_booking_repo.get_all())
    before_equipment_count = len(equipment_booking_repo.get_all())
    with pytest.raises(RoomBookingError, match="18:00"):
        late_room_service.create_daily_booking(low_old, late_room.id, tomorrow, tomorrow, 2)
    with pytest.raises(EquipmentBookingError, match="이미 예약"):
        late_equipment_service.create_daily_booking(low_old, late_asset.id, tomorrow, tomorrow)
    assert len(room_booking_repo.get_all()) == before_room_count
    assert len(equipment_booking_repo.get_all()) == before_equipment_count


def test_plan0001_cli_admin_resource_edits(
    user_repo,
    room_repo,
    equipment_repo,
    room_booking_repo,
    equipment_booking_repo,
    room_maintenance_repo,
    penalty_repo,
    audit_repo,
    fake_clock,
):
    fixed_time = datetime(2026, 6, 1, 9, 0)
    auth_service, _penalty_service, room_service, equipment_service, policy_service = _make_services(
        user_repo,
        room_repo,
        equipment_repo,
        room_booking_repo,
        equipment_booking_repo,
        room_maintenance_repo,
        penalty_repo,
        audit_repo,
        fake_clock,
        fixed_time,
    )
    admin = auth_service.signup("Adminedit1", "pass1", role=UserRole.ADMIN)
    user = auth_service.signup("Adminuser1", "pass1")
    room = room_service.add_room_resource(admin, "회의실9A", "6", "9층")
    edited = room_service.edit_room_resource(admin, room.id, "8", "8층")
    assert (edited.capacity, edited.location) == (8, "8층")

    maintenance = room_service.create_maintenance_schedule(
        admin,
        room.id,
        fixed_time + timedelta(days=2, hours=9),
        fixed_time + timedelta(days=3),
        reason="정기점검",
    )
    assert maintenance.status == "scheduled"
    assert room_maintenance_repo.get_by_id(maintenance.id).to_record()
    assert room_service.cancel_maintenance_schedule(admin, maintenance.id, "취소").status == "cancelled"

    active = room_service.create_maintenance_schedule(
        admin,
        room.id,
        fixed_time + timedelta(days=4, hours=9),
        fixed_time + timedelta(days=5),
        reason="정기점검",
    )
    active_result = policy_service.run_all_checks(fixed_time + timedelta(days=4, hours=10))
    assert active.id in active_result["room_maintenance_active"][0:]
    complete_result = policy_service.run_all_checks(fixed_time + timedelta(days=5, hours=1))
    assert active.id in complete_result["room_maintenance_expired"]
    assert room_maintenance_repo.get_by_id(active.id).status == "completed"

    for index in range(1, 13):
        with global_lock():
            equipment_repo.add(
                EquipmentAsset(
                    id=f"EQ-{index:03d}",
                    name="장비",
                    asset_type="asset",
                    serial_number=f"EQ-{index:03d}",
                    status=ResourceStatus.AVAILABLE,
                    description="장비",
                )
            )
    added = equipment_service.add_equipment_resource(admin, "카메라", "camera", "카메라")
    renamed = equipment_service.edit_equipment_resource_name(admin, added.id, "캠코더")
    assert renamed.name == "캠코더"
    future = equipment_service.schedule_future_status_change(
        admin,
        renamed.id,
        fixed_time + timedelta(days=5),
        fixed_time + timedelta(days=5, hours=9),
        ResourceStatus.MAINTENANCE,
    )
    with pytest.raises(EquipmentBookingError, match="예정된 maintenance"):
        equipment_service.create_daily_booking(
            user,
            renamed.id,
            (fixed_time + timedelta(days=5)).date(),
            (fixed_time + timedelta(days=5)).date(),
        )
    future_result = policy_service.run_all_checks(fixed_time + timedelta(days=5, hours=1))
    assert any(renamed.id in event for event in future_result["equipment_future_status_changes"])
    assert equipment_repo.get_by_id(renamed.id).status == ResourceStatus.MAINTENANCE
    assert future["status"] == ResourceStatus.MAINTENANCE.value


def test_inspect1_cli_smoke_waitlist_status_and_canonical_data(
    monkeypatch,
    capsys,
    temp_data_dir,
    user_repo,
    room_repo,
    equipment_repo,
    room_booking_repo,
    equipment_booking_repo,
    room_maintenance_repo,
    penalty_repo,
    audit_repo,
    create_test_room,
    create_test_equipment,
    room_booking_factory,
    equipment_booking_factory,
    fake_clock,
):
    fixed_time = datetime(2026, 6, 1, 9, 0)
    auth_service, penalty_service, room_service, equipment_service, policy_service = _make_services(
        user_repo,
        room_repo,
        equipment_repo,
        room_booking_repo,
        equipment_booking_repo,
        room_maintenance_repo,
        penalty_repo,
        audit_repo,
        fake_clock,
        fixed_time,
    )
    target_owner = auth_service.signup("Waitown1", "pass1")
    waiting_user = auth_service.signup("Waituser1", "pass1")
    room = create_test_room(name="회의실5A", capacity=4, location="5층", description="회의실")
    asset = create_test_equipment(id="WT-001", serial_number="WT-001", name="웹캠", asset_type="webcam", description="웹캠")
    start = fixed_time + timedelta(days=4)
    room_target = room_service.create_daily_booking(target_owner, room.id, start.date(), start.date(), 2)
    equipment_target = equipment_service.create_daily_booking(target_owner, asset.id, start.date(), start.date())
    waitlist_repo = WaitingListRepository(temp_data_dir / "waiting_list.txt")
    menu = UserMenu(
        waiting_user,
        auth_service=auth_service,
        room_service=room_service,
        equipment_service=equipment_service,
        penalty_service=penalty_service,
        policy_service=policy_service,
        waiting_list_repo=waitlist_repo,
    )

    first_entry = menu.create_waiting_list_request("room_booking", room_target.id, 2)
    second_entry = menu.create_waiting_list_request("equipment_booking", equipment_target.id, 1)
    assert first_entry.related_type == "room_booking"
    assert second_entry.related_type == "equipment_booking"
    assert [entry.id for entry in waitlist_repo.get_ordered_by_related("room_booking", room_target.id)] == [first_entry.id]
    assert [len(row) for row in (decode_record(line) for line in (temp_data_dir / "waiting_list.txt").read_text(encoding="utf-8").splitlines() if line)] == [7, 7]
    assert not (temp_data_dir / "waitlist.txt").exists()

    with global_lock():
        user_repo.update(
            replace(
                waiting_user,
                room_cancel_restricted_until=(fixed_time + timedelta(days=10)).isoformat(timespec="minutes"),
                equipment_cancel_restricted_until=(fixed_time + timedelta(days=11)).isoformat(timespec="minutes"),
            )
        )
        room_booking_repo.add(
            room_booking_factory(
                id="status-room-cancel",
                user_id=waiting_user.id,
                room_id=room.id,
                start_time=(fixed_time + timedelta(days=3)).isoformat(),
                end_time=(fixed_time + timedelta(days=3, hours=9)).isoformat(),
                status=RoomBookingStatus.CANCELLED,
                cancelled_at=(fixed_time - timedelta(days=1)).isoformat(),
            )
        )
        equipment_booking_repo.add(
            equipment_booking_factory(
                id="status-equipment-cancel",
                user_id=waiting_user.id,
                equipment_id=asset.id,
                start_time=(fixed_time + timedelta(days=3)).isoformat(),
                end_time=(fixed_time + timedelta(days=3, hours=9)).isoformat(),
                status=EquipmentBookingStatus.CANCELLED,
                cancelled_at=(fixed_time - timedelta(days=2)).isoformat(),
            )
        )
    monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)
    menu._show_my_status()
    output = capsys.readouterr().out
    assert "취소 제한 현황" in output
    assert "회의실 직접 취소: 1/3건" in output
    assert "장비 직접 취소: 1/3건" in output
    assert "회의실 신규 예약 제한 해제일: 2026-06-11" in output
    assert "장비 신규 예약 제한 해제일: 2026-06-12" in output

    repo_root = Path(__file__).resolve().parents[2]
    checked_in_user_rows = [decode_record(line) for line in (repo_root / "data" / "users.txt").read_text(encoding="utf-8").splitlines() if line]
    checked_in_equipment_rows = [decode_record(line) for line in (repo_root / "data" / "equipments.txt").read_text(encoding="utf-8").splitlines() if line]
    assert checked_in_user_rows and all(len(row) == 10 for row in checked_in_user_rows)
    assert checked_in_equipment_rows and all(len(row) == 8 for row in checked_in_equipment_rows)


def test_inspect1_cli_smoke_maintenance_group_quota_and_validators(
    user_repo,
    room_repo,
    equipment_repo,
    room_booking_repo,
    equipment_booking_repo,
    room_maintenance_repo,
    penalty_repo,
    audit_repo,
    create_test_room,
    create_test_equipment,
    room_booking_factory,
    fake_clock,
):
    fixed_time = datetime(2026, 6, 1, 9, 0)
    auth_service, _penalty_service, room_service, equipment_service, _policy_service = _make_services(
        user_repo,
        room_repo,
        equipment_repo,
        room_booking_repo,
        equipment_booking_repo,
        room_maintenance_repo,
        penalty_repo,
        audit_repo,
        fake_clock,
        fixed_time,
    )
    admin = auth_service.signup("Smokeadmin1", "pass1", role=UserRole.ADMIN)
    owner = auth_service.signup("Smokeowner1", "pass1")
    user = auth_service.signup("Smokeuser1", "pass1")
    quota_user = auth_service.signup("Smokequota1", "pass1")
    room = create_test_room(name="회의실6A", capacity=6, location="6층", description="회의실")
    quota_rooms = _add_rooms(create_test_room, 6)
    conflicted_asset = create_test_equipment(id="GP-001", serial_number="GP-001", name="노트북", asset_type="laptop", description="노트북")
    free_asset = create_test_equipment(id="GP-002", serial_number="GP-002", name="웹캠", asset_type="webcam", description="웹캠")

    maintenance = room_service.create_maintenance_schedule(
        admin,
        room.id,
        fixed_time + timedelta(days=6),
        fixed_time + timedelta(days=7),
        reason="정기점검",
    )
    assert maintenance.start_time == "2026-06-07T18:00:00"
    assert maintenance.end_time == "2026-06-08T09:00:00"

    with global_lock():
        room_booking_repo.add(
            room_booking_factory(
                id="maintenance-overlap",
                user_id=owner.id,
                room_id=room.id,
                start_time="2026-06-10T20:00:00",
                end_time="2026-06-11T08:00:00",
                status=RoomBookingStatus.RESERVED,
            )
        )
    before_schedule_count = len(room_maintenance_repo.get_all())
    before_booking_status = room_booking_repo.get_by_id("maintenance-overlap").status
    with pytest.raises(RoomBookingError, match="겹치는 예약"):
        room_service.create_maintenance_schedule(
            admin,
            room.id,
            fixed_time + timedelta(days=9),
            fixed_time + timedelta(days=10),
            reason="야간점검",
        )
    assert len(room_maintenance_repo.get_all()) == before_schedule_count
    assert room_booking_repo.get_by_id("maintenance-overlap").status == before_booking_status

    group_day = fixed_time.date() + timedelta(days=12)
    prior_conflict = equipment_service.create_daily_booking(owner, conflicted_asset.id, group_day, group_day)
    with global_lock():
        equipment_booking_repo.update(replace(prior_conflict, created_at="2026-06-01T08:00"))
    before_user_bookings = equipment_booking_repo.get_by_user(user.id)
    with pytest.raises(EquipmentBookingError, match="이미 예약"):
        equipment_service.create_group_booking(user, [conflicted_asset.id, free_asset.id], datetime(2026, 6, 13, 9), datetime(2026, 6, 13, 18))
    assert equipment_booking_repo.get_by_user(user.id) == before_user_bookings

    with global_lock():
        for index in range(3):
            pending_start = fixed_time + timedelta(days=20 + index)
            pending_end = pending_start + timedelta(hours=9)
            room_booking_repo.add(
                room_booking_factory(
                    id=f"quota-owner-reserved-{index}",
                    user_id=owner.id,
                    room_id=quota_rooms[index].id,
                    start_time=pending_start.isoformat(),
                    end_time=pending_end.isoformat(),
                    status=RoomBookingStatus.RESERVED,
                )
            )
            room_booking_repo.add(
                room_booking_factory(
                    id=f"quota-pending-{index}",
                    user_id=quota_user.id,
                    room_id=quota_rooms[index].id,
                    start_time=pending_start.isoformat(),
                    end_time=pending_end.isoformat(),
                    status=RoomBookingStatus.PENDING,
                )
            )
    for index in range(3):
        booking = room_service.create_daily_booking(
            quota_user,
            quota_rooms[index + 3].id,
            fixed_time.date() + timedelta(days=30 + index),
            fixed_time.date() + timedelta(days=30 + index),
            attendee_count=2,
        )
        assert booking.status == RoomBookingStatus.RESERVED

    for index in range(1, 13):
        with global_lock():
            equipment_repo.add(
                EquipmentAsset(
                    id=f"SM-{index:03d}",
                    name="장비",
                    asset_type="asset",
                    serial_number=f"SM-{index:03d}",
                    status=ResourceStatus.AVAILABLE,
                    description="장비",
                )
            )
    valid = equipment_service.add_equipment_resource(admin, "마이크", "microphoneinput", "마이크")
    assert valid.asset_type == "microphoneinput"
    with pytest.raises(EquipmentBookingError):
        equipment_service.add_equipment_resource(admin, "Projector1", "projector", "프로젝터")
    with pytest.raises(EquipmentBookingError):
        equipment_service.add_equipment_resource(admin, "프로젝터", "Projector", "프로젝터")


def test_plan0001_cli_review_navigation(monkeypatch, capsys):
    _drive_inputs(monkeypatch, ["x", "0", "9", "2", "bad", "0"])

    assert input_start_gate("입력 확인") is False
    assert review_action("검토 확인", "저장") == "retry"
    pause()

    output = capsys.readouterr().out
    assert "0. 돌아가기" in output
    assert "0. 취소" in output
    assert "다시 입력" in output
    assert "1 또는 0" in output
    assert "1, 2, 0" in output
    assert "0을 입력해주세요" in output
