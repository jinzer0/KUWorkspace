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
        ("16", "_submit_message"),
    ],
)
def test_user_menu_dispatches_actions(
    monkeypatch,
    auth_service,
    room_service,
    equipment_service,
    penalty_service,
    policy_service,
    message_service,
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
        message_service=message_service,
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
    message_service,
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
        message_service=message_service,
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
        ("1", "_show_rooms"),
        ("2", "_change_room_status"),
        ("3", "_show_all_room_bookings"),
        ("4", "_room_checkin"),
        ("5", "_room_checkout"),
        ("6", "_admin_modify_room_booking"),
        ("7", "_admin_cancel_room_booking"),
        ("8", "_show_equipment"),
        ("9", "_change_equipment_status"),
        ("10", "_show_all_equipment_bookings"),
        ("11", "_equipment_checkout"),
        ("12", "_equipment_return"),
        ("13", "_admin_modify_equipment_booking"),
        ("14", "_admin_cancel_equipment_booking"),
        ("15", "_show_users"),
        ("16", "_show_user_detail"),
        ("17", "_apply_damage_penalty"),
        ("18", "_mark_room_no_show"),
        ("19", "_mark_equipment_no_show"),
        ("20", "_force_room_late_checkout"),
        ("21", "_force_equipment_late_return"),
        ("22", "_show_messages"),
    ],
)
def test_admin_menu_dispatches_actions(
    monkeypatch,
    auth_service,
    room_service,
    equipment_service,
    penalty_service,
    policy_service,
    message_service,
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
        message_service=message_service,
    )
    calls = []
    inputs = iter([choice, "0"])

    monkeypatch.setattr(menu, "_run_policy_checks", lambda: True)
    monkeypatch.setattr(menu, "_refresh_admin", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
    monkeypatch.setattr("src.cli.admin_menu.confirm", lambda _msg: True)
    monkeypatch.setattr("src.cli.admin_menu.print_success", lambda *_: None)
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
    message_service,
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
        message_service=message_service,
    )
    created = {}
    inputs = iter(["23", "0"])

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
