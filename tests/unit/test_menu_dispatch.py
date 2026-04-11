import pytest

from src.cli.admin_menu import AdminMenu
from src.cli.user_menu import UserMenu
from src.domain.models import UserRole


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
        ("16", "_open_clock"),
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
    inputs = iter(["16", "0"])

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
        ("1", "_show_all_room_bookings"),
        ("2", "_show_rooms_and_change_status"),
        ("3", "_room_checkin"),
        ("4", "_room_checkout"),
        ("5", "_admin_modify_room_booking_time"),
        ("6", "_admin_cancel_room_booking"),
        ("7", "_show_all_equipment_bookings"),
        ("8", "_show_equipment_and_change_status"),
        ("9", "_equipment_checkout"),
        ("10", "_equipment_return"),
        ("11", "_admin_modify_equipment_booking_time"),
        ("12", "_admin_cancel_equipment_booking"),
        ("13", "_show_users"),
        ("14", "_show_user_detail"),
        ("15", "_apply_damage_penalty"),
        ("16", "_force_late_cancel_penalty"),
        ("17", "_force_room_late_checkout"),
        ("18", "_force_equipment_late_return"),
        ("19", "_open_clock"),
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
    inputs = iter(["19", "0"])

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
