from datetime import datetime

from src.cli.clock_menu import ClockMenu
from src.cli.guest_menu import GuestMenu


def test_guest_menu_opens_clock_in_read_only_mode(
    monkeypatch, auth_service, policy_service
):
    menu = GuestMenu(auth_service=auth_service, policy_service=policy_service)
    created = {}

    class FakeClockMenu:
        def __init__(self, policy_service, actor_id="system", allow_advance=True):
            created["policy_service"] = policy_service
            created["actor_id"] = actor_id
            created["allow_advance"] = allow_advance

        def run(self):
            created["ran"] = True

    inputs = iter(["9", "0"])

    monkeypatch.setattr(menu, "_run_policy_checks", lambda: True)
    monkeypatch.setattr("src.cli.guest_menu.ClockMenu", FakeClockMenu)
    monkeypatch.setattr("src.cli.guest_menu.confirm", lambda _msg: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

    result = menu.run()

    assert result is None
    assert created["policy_service"] is policy_service
    assert created["actor_id"] == "guest"
    assert created["allow_advance"] is False
    assert created["ran"] is True


def test_clock_menu_read_only_mode_shows_blockers_instead_of_advancing(monkeypatch):
    calls = {"advance": 0, "blockers": 0}

    class StubPolicyService:
        def prepare_advance(self):
            return {
                "current_time": datetime(2024, 6, 15, 9, 0, 0),
                "next_time": datetime(2024, 6, 15, 18, 0, 0),
                "events": [],
                "blockers": ["pending"],
                "can_advance": False,
            }

    menu = ClockMenu(StubPolicyService(), actor_id="guest", allow_advance=False)
    inputs = iter(["2", "0"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.clock_menu.print_header", lambda *_: None)
    monkeypatch.setattr("src.cli.clock_menu.pause", lambda: None)
    monkeypatch.setattr(menu, "_advance", lambda: calls.__setitem__("advance", calls["advance"] + 1))
    monkeypatch.setattr(
        menu,
        "_show_blockers",
        lambda _preview: calls.__setitem__("blockers", calls["blockers"] + 1),
    )

    menu.run()

    assert calls["advance"] == 0
    assert calls["blockers"] == 1


def test_guest_menu_signup_creates_user(monkeypatch, auth_service, policy_service):
    menu = GuestMenu(auth_service=auth_service, policy_service=policy_service)
    inputs = iter(["new_guest", "pass1234", "pass1234"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.guest_menu.print_header", lambda *_: None)
    monkeypatch.setattr("src.cli.guest_menu.pause", lambda: None)

    menu._signup()

    created = auth_service.get_user_by_username("new_guest")
    assert created.username == "new_guest"


def test_guest_menu_exit_returns_none_when_confirmed(
    monkeypatch, auth_service, policy_service
):
    menu = GuestMenu(auth_service=auth_service, policy_service=policy_service)
    inputs = iter(["0"])

    monkeypatch.setattr(menu, "_run_policy_checks", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.guest_menu.print_header", lambda *_: None)
    monkeypatch.setattr("src.cli.guest_menu.confirm", lambda _msg: True)

    assert menu.run() is None
