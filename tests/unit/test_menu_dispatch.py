import pytest
from datetime import date
from types import SimpleNamespace

from src.cli.admin_menu import AdminMenu
from src.cli.user_menu import UserMenu
from src.domain.models import ResourceStatus, UserRole


@pytest.mark.parametrize(
    ("choice", "method_name"),
    [
        ("1", "_show_rooms"),
        ("2", "_create_room_booking"),
        ("3", "_show_my_room_bookings"),
        ("4", "_modify_room_booking"),
        ("5", "_cancel_room_booking"),
        ("6", "_request_room_checkin"),
        ("7", "_request_room_checkout"),
        ("8", "_show_equipment"),
        ("9", "_create_equipment_booking"),
        ("10", "_show_my_equipment_bookings"),
        ("11", "_modify_equipment_booking"),
        ("12", "_cancel_equipment_booking"),
        ("13", "_request_equipment_pickup"),
        ("14", "_request_equipment_return"),
        ("15", "_show_my_status"),
        ("16", "_create_waiting_list_request"),
        ("17", "_open_clock"),
    ],
)
def test_user_menu_dispatches_actions(
    monkeypatch,
    auth_service,
    room_service,
    equipment_service,
    penalty_service,
    policy_service,
    create_test_user,
    choice,
    method_name,
):
    user = create_test_user()
    menu = UserMenu(
        user=user,
        auth_service=auth_service,
        room_service=room_service,
        equipment_service=equipment_service,
        penalty_service=penalty_service,
        policy_service=policy_service,
    )
    calls = []
    inputs = iter([choice, "0"])

    monkeypatch.setattr(menu, "_run_policy_checks", lambda: True)
    monkeypatch.setattr(menu, "_refresh_user", lambda: True)
    monkeypatch.setattr(menu.penalty_service, "get_user_status", lambda _user: {})
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
    monkeypatch.setattr("src.cli.user_menu.confirm", lambda _msg: True)
    monkeypatch.setattr("src.cli.user_menu.print_success", lambda *_: None)
    if method_name == "_open_clock":
        monkeypatch.setattr(
            "src.cli.user_menu.ClockMenu",
            lambda *_args, **_kwargs: type("FakeClock", (), {"run": lambda _self: calls.append(method_name)})(),
        )
    else:
        monkeypatch.setattr(menu, method_name, lambda: calls.append(method_name))

    assert menu.run() is True
    assert calls == [method_name]


def test_user_menu_opens_clock_with_user_actor(
    monkeypatch,
    auth_service,
    room_service,
    equipment_service,
    penalty_service,
    policy_service,
    create_test_user,
):
    user = create_test_user()
    menu = UserMenu(
        user=user,
        auth_service=auth_service,
        room_service=room_service,
        equipment_service=equipment_service,
        penalty_service=penalty_service,
        policy_service=policy_service,
    )
    created = {}
    inputs = iter(["17", "0"])

    class FakeClockMenu:
        def __init__(self, policy_service, actor_id="system", allow_advance=True):
            created["policy_service"] = policy_service
            created["actor_id"] = actor_id
            created["allow_advance"] = allow_advance

        def run(self):
            created["ran"] = True

    monkeypatch.setattr(menu, "_run_policy_checks", lambda: True)
    monkeypatch.setattr(menu, "_refresh_user", lambda: True)
    monkeypatch.setattr(menu.penalty_service, "get_user_status", lambda _user: {})
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
    monkeypatch.setattr("src.cli.user_menu.confirm", lambda _msg: True)
    monkeypatch.setattr("src.cli.user_menu.print_success", lambda *_: None)
    monkeypatch.setattr("src.cli.user_menu.ClockMenu", FakeClockMenu)

    assert menu.run() is True
    assert created == {
        "policy_service": policy_service,
        "actor_id": user.id,
        "allow_advance": True,
        "ran": True,
    }


@pytest.mark.parametrize(
    ("choice", "method_name"),
    [
        ("16", "_create_waiting_list_request"),
        ("17", "_open_clock"),
    ],
)
def test_inspect1_user_menu_16_waitlist_and_17_clock_dispatch(
    monkeypatch,
    auth_service,
    room_service,
    equipment_service,
    penalty_service,
    policy_service,
    create_test_user,
    choice,
    method_name,
):
    user = create_test_user(username="InspectMenuUser")
    menu = UserMenu(
        user=user,
        auth_service=auth_service,
        room_service=room_service,
        equipment_service=equipment_service,
        penalty_service=penalty_service,
        policy_service=policy_service,
    )
    calls = []
    inputs = iter([choice, "0"])

    monkeypatch.setattr(menu, "_run_policy_checks", lambda: True)
    monkeypatch.setattr(menu, "_refresh_user", lambda: True)
    monkeypatch.setattr(menu.penalty_service, "get_user_status", lambda _user: {})
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
    monkeypatch.setattr("src.cli.user_menu.confirm", lambda _msg: True)
    monkeypatch.setattr("src.cli.user_menu.print_success", lambda *_: None)
    monkeypatch.setattr(
        "src.cli.user_menu.ClockMenu",
        lambda *_args, **_kwargs: type("FakeClock", (), {"run": lambda _self: calls.append("_open_clock")})(),
    )
    monkeypatch.setattr(
        menu,
        "_create_waiting_list_request",
        lambda: calls.append("_create_waiting_list_request"),
    )

    assert menu.run() is True
    assert calls == [method_name]


@pytest.mark.parametrize(
    ("choice", "method_name"),
    [
        ("1", "_show_all_room_bookings"),
        ("2", "_show_rooms_and_change_status"),
        ("3", "_room_checkin"),
        ("4", "_room_checkout"),
        ("5", "_admin_modify_room_booking_time"),
        ("6", "_admin_cancel_room_booking"),
        ("7", "_manage_room_resources"),
        ("8", "_show_all_equipment_bookings"),
        ("9", "_show_equipment_and_change_status"),
        ("10", "_equipment_checkout"),
        ("11", "_equipment_return"),
        ("12", "_admin_modify_equipment_booking_time"),
        ("13", "_admin_cancel_equipment_booking"),
        ("14", "_show_users"),
        ("15", "_show_user_detail"),
        ("16", "_apply_damage_penalty"),
        ("17", "_force_late_cancel_penalty"),
        ("18", "_force_room_late_checkout"),
        ("19", "_force_equipment_late_return"),
        ("20", "_open_clock"),
    ],
)
def test_admin_menu_dispatches_actions(
    monkeypatch,
    auth_service,
    room_service,
    equipment_service,
    penalty_service,
    policy_service,
    create_test_user,
    choice,
    method_name,
):
    admin = create_test_user(role=UserRole.ADMIN)
    menu = AdminMenu(
        user=admin,
        auth_service=auth_service,
        room_service=room_service,
        equipment_service=equipment_service,
        penalty_service=penalty_service,
        policy_service=policy_service,
    )
    calls = []
    inputs = iter([choice, "0"])

    monkeypatch.setattr(menu, "_run_policy_checks", lambda: True)
    monkeypatch.setattr(menu, "_refresh_admin", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
    monkeypatch.setattr("src.cli.admin_menu.confirm", lambda _msg: True)
    monkeypatch.setattr("src.cli.admin_menu.print_success", lambda *_: None)
    if method_name == "_open_clock":
        monkeypatch.setattr(
            "src.cli.admin_menu.ClockMenu",
            lambda *_args, **_kwargs: type("FakeClock", (), {"run": lambda _self: calls.append(method_name)})(),
        )
    else:
        monkeypatch.setattr(menu, method_name, lambda: calls.append(method_name))

    assert menu.run() is True
    assert calls == [method_name]


def test_admin_menu_opens_clock_with_admin_actor(
    monkeypatch,
    auth_service,
    room_service,
    equipment_service,
    penalty_service,
    policy_service,
    create_test_user,
):
    admin = create_test_user(role=UserRole.ADMIN)
    menu = AdminMenu(
        user=admin,
        auth_service=auth_service,
        room_service=room_service,
        equipment_service=equipment_service,
        penalty_service=penalty_service,
        policy_service=policy_service,
    )
    created = {}
    inputs = iter(["20", "0"])

    class FakeClockMenu:
        def __init__(self, policy_service, actor_id="system", allow_advance=True):
            created["policy_service"] = policy_service
            created["actor_id"] = actor_id
            created["allow_advance"] = allow_advance

        def run(self):
            created["ran"] = True

    monkeypatch.setattr(menu, "_run_policy_checks", lambda: True)
    monkeypatch.setattr(menu, "_refresh_admin", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
    monkeypatch.setattr("src.cli.admin_menu.confirm", lambda _msg: True)
    monkeypatch.setattr("src.cli.admin_menu.print_success", lambda *_: None)
    monkeypatch.setattr("src.cli.admin_menu.ClockMenu", FakeClockMenu)

    assert menu.run() is True
    assert created == {
        "policy_service": policy_service,
        "actor_id": admin.id,
        "allow_advance": True,
        "ran": True,
    }


@pytest.mark.parametrize("choice", ["21", "22", "23"])
def test_admin_menu_rejects_old_standalone_resource_choices(
    monkeypatch,
    auth_service,
    room_service,
    equipment_service,
    penalty_service,
    policy_service,
    create_test_user,
    choice,
):
    admin = create_test_user(role=UserRole.ADMIN)
    menu = AdminMenu(
        user=admin,
        auth_service=auth_service,
        room_service=room_service,
        equipment_service=equipment_service,
        penalty_service=penalty_service,
        policy_service=policy_service,
    )
    calls = []
    inputs = iter([choice, "0", "y"])

    monkeypatch.setattr(menu, "_run_policy_checks", lambda: True)
    monkeypatch.setattr(menu, "_refresh_admin", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
    for method_name in [
        "_create_room_maintenance",
        "_cancel_room_maintenance",
        "_schedule_equipment_future_status",
        "_cancel_equipment_future_status",
    ]:
        monkeypatch.setattr(menu, method_name, lambda name=method_name: calls.append(name))

    assert menu.run() is True
    assert calls == []


def test_admin_room_list_status_flow_skips_enter_and_confirm(
    monkeypatch,
    auth_service,
    room_service,
    equipment_service,
    penalty_service,
    policy_service,
    create_test_user,
):
    admin = create_test_user(role=UserRole.ADMIN)
    menu = AdminMenu(
        user=admin,
        auth_service=auth_service,
        room_service=room_service,
        equipment_service=equipment_service,
        penalty_service=penalty_service,
        policy_service=policy_service,
    )
    state = {"show_called": False, "confirm_called": False, "changed": False}

    monkeypatch.setattr(menu, "_show_rooms", lambda: state.__setitem__("show_called", True))
    monkeypatch.setattr(
        menu,
        "_change_room_status",
        lambda: state.__setitem__("changed", True),
    )
    monkeypatch.setattr(
        "src.cli.admin_menu.confirm",
        lambda _msg: state.__setitem__("confirm_called", True) or True,
    )

    menu._show_rooms_and_change_status()

    assert state == {
        "show_called": False,
        "confirm_called": False,
        "changed": True,
    }


def test_admin_equipment_list_status_flow_skips_enter_and_confirm(
    monkeypatch,
    auth_service,
    room_service,
    equipment_service,
    penalty_service,
    policy_service,
    create_test_user,
):
    admin = create_test_user(role=UserRole.ADMIN)
    menu = AdminMenu(
        user=admin,
        auth_service=auth_service,
        room_service=room_service,
        equipment_service=equipment_service,
        penalty_service=penalty_service,
        policy_service=policy_service,
    )
    state = {"show_called": False, "confirm_called": False, "changed": False}

    monkeypatch.setattr(
        menu,
        "_show_equipment",
        lambda: state.__setitem__("show_called", True),
    )
    monkeypatch.setattr(
        menu,
        "_change_equipment_status",
        lambda: state.__setitem__("changed", True),
    )
    monkeypatch.setattr(
        "src.cli.admin_menu.confirm",
        lambda _msg: state.__setitem__("confirm_called", True) or True,
    )

    menu._show_equipment_and_change_status()

    assert state == {
        "show_called": False,
        "confirm_called": False,
        "changed": True,
    }


def test_inspect1_admin_room_status_flow_exposes_regular_maintenance_choice(
    monkeypatch,
    capsys,
    auth_service,
    room_service,
    equipment_service,
    penalty_service,
    policy_service,
    create_test_user,
    create_test_room,
):
    admin = create_test_user(role=UserRole.ADMIN)
    create_test_room(name="회의실1A")
    menu = AdminMenu(
        user=admin,
        auth_service=auth_service,
        room_service=room_service,
        equipment_service=equipment_service,
        penalty_service=penalty_service,
        policy_service=policy_service,
    )
    room = room_service.get_all_rooms()[0]
    monkeypatch.setattr("builtins.input", lambda _prompt="": "0")
    monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
    monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
    monkeypatch.setattr("src.cli.admin_menu.select_from_list", lambda *_args, **_kwargs: room.id)

    menu._change_room_status()

    output = capsys.readouterr().out
    assert "정기 점검" in output
    assert "상태 변경" in output


def test_inspect1_admin_room_status_flow_routes_maintenance_create_or_cancel(
    monkeypatch,
    auth_service,
    room_service,
    equipment_service,
    penalty_service,
    policy_service,
    create_test_user,
    create_test_room,
):
    admin = create_test_user(role=UserRole.ADMIN)
    room = create_test_room(name="회의실2A")
    menu = AdminMenu(
        user=admin,
        auth_service=auth_service,
        room_service=room_service,
        equipment_service=equipment_service,
        penalty_service=penalty_service,
        policy_service=policy_service,
    )
    calls = []
    inputs = iter(["2", "2"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
    monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
    monkeypatch.setattr("src.cli.admin_menu.select_from_list", lambda *_args, **_kwargs: room.id)
    monkeypatch.setattr(menu, "_create_room_maintenance", lambda room_id=None: calls.append(("create", room_id)))
    monkeypatch.setattr(menu, "_cancel_room_maintenance", lambda room_id=None: calls.append(("cancel", room_id)))

    monkeypatch.setattr(menu.room_service.maintenance_repo, "get_all", lambda: [])
    menu._change_room_status()
    monkeypatch.setattr(
        menu.room_service.maintenance_repo,
        "get_all",
        lambda: [SimpleNamespace(room_id=room.id, status="scheduled")],
    )
    menu._change_room_status()

    assert calls == [("create", room.id), ("cancel", room.id)]


def test_inspect1_admin_equipment_status_flow_exposes_current_future_and_cancel_choices(
    monkeypatch,
    capsys,
    auth_service,
    room_service,
    equipment_service,
    penalty_service,
    policy_service,
    create_test_user,
    create_test_equipment,
):
    admin = create_test_user(role=UserRole.ADMIN)
    create_test_equipment(name="노트북A")
    menu = AdminMenu(
        user=admin,
        auth_service=auth_service,
        room_service=room_service,
        equipment_service=equipment_service,
        penalty_service=penalty_service,
        policy_service=policy_service,
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": "0")
    monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
    monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)

    menu._change_equipment_status()

    output = capsys.readouterr().out
    assert "현재 시점 상태 변경" in output
    assert "미래 상태 예약" in output
    assert "미래 상태 예약 취소" in output


def test_admin_equipment_future_status_cli_accepts_disabled_choice(
    monkeypatch,
    auth_service,
    room_service,
    equipment_service,
    penalty_service,
    policy_service,
    create_test_user,
    create_test_equipment,
):
    admin = create_test_user(role=UserRole.ADMIN)
    equipment = create_test_equipment(name="노트북A")
    menu = AdminMenu(
        user=admin,
        auth_service=auth_service,
        room_service=room_service,
        equipment_service=equipment_service,
        penalty_service=penalty_service,
        policy_service=policy_service,
    )
    calls = []
    inputs = iter(["3"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.admin_menu.input_start_gate", lambda _title: True)
    monkeypatch.setattr("src.cli.admin_menu.select_from_list", lambda *_args, **_kwargs: equipment.id)
    monkeypatch.setattr("src.cli.admin_menu.get_daily_date_range_input", lambda *_args: (date(2024, 6, 16), date(2024, 6, 16)))
    monkeypatch.setattr("src.cli.admin_menu.review_action", lambda *_args, **_kwargs: "confirm")
    monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
    monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
    monkeypatch.setattr("src.cli.admin_menu.print_success", lambda *_: None)

    def schedule(_admin, equipment_id, _start_time, _end_time, status):
        calls.append((equipment_id, status))
        return {"id": "schedule-1", "status": status.value, "start_time": "2024-06-16T09:00", "end_time": "2024-06-16T18:00"}

    monkeypatch.setattr(menu.equipment_service, "schedule_future_status_change", schedule)

    menu._schedule_equipment_future_status()

    assert calls == [(equipment.id, ResourceStatus.DISABLED)]


def test_admin_damage_penalty_review_cancel_does_not_apply_penalty(
    monkeypatch,
    auth_service,
    room_service,
    equipment_service,
    penalty_service,
    policy_service,
    create_test_user,
    equipment_booking_factory,
):
    admin = create_test_user(role=UserRole.ADMIN, username="PenaltyAdmin")
    target = create_test_user(username="PenaltyTarget")
    booking = equipment_booking_factory(user_id=target.id, equipment_id="equipment-1")
    menu = AdminMenu(
        user=admin,
        auth_service=auth_service,
        room_service=room_service,
        equipment_service=equipment_service,
        penalty_service=penalty_service,
        policy_service=policy_service,
    )
    selections = iter([target.id, booking.id])
    inputs = iter(["2", "2", "파손"])
    calls = []

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.admin_menu.select_from_list", lambda *_args, **_kwargs: next(selections))
    monkeypatch.setattr("src.cli.admin_menu.input_start_gate", lambda _title: True)
    monkeypatch.setattr("src.cli.admin_menu.review_action", lambda *_args, **_kwargs: "cancel")
    monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
    monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
    monkeypatch.setattr("src.cli.admin_menu.print_info", lambda *_: None)
    monkeypatch.setattr(menu.equipment_service, "get_user_bookings", lambda _user_id: [booking])
    monkeypatch.setattr(menu.penalty_service, "apply_damage", lambda *args, **kwargs: calls.append((args, kwargs)))

    menu._apply_damage_penalty()

    assert calls == []


def test_admin_damage_penalty_type_zero_returns_without_booking_query_or_pause(
    monkeypatch,
    capsys,
    auth_service,
    room_service,
    equipment_service,
    penalty_service,
    policy_service,
    create_test_user,
):
    admin = create_test_user(role=UserRole.ADMIN, username="PenaltyAdminZero")
    target = create_test_user(username="PenaltyTargetZero")
    menu = AdminMenu(
        user=admin,
        auth_service=auth_service,
        room_service=room_service,
        equipment_service=equipment_service,
        penalty_service=penalty_service,
        policy_service=policy_service,
    )
    errors = []
    state = {"booking_query": False, "paused": False}

    monkeypatch.setattr("builtins.input", lambda _prompt="": "0")
    monkeypatch.setattr("src.cli.admin_menu.select_from_list", lambda *_args, **_kwargs: target.id)
    monkeypatch.setattr("src.cli.admin_menu.pause", lambda: state.__setitem__("paused", True))
    monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
    monkeypatch.setattr("src.cli.admin_menu.print_error", errors.append)

    def fail_booking_query(_user_id):
        state["booking_query"] = True
        raise AssertionError("booking query should not run when 0 returns")

    monkeypatch.setattr(menu.equipment_service, "get_user_bookings", fail_booking_query)

    menu._apply_damage_penalty()

    output = capsys.readouterr().out
    assert "0. 돌아가기" in output
    assert errors == []
    assert state == {"booking_query": False, "paused": False}
