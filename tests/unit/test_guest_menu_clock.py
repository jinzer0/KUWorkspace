from datetime import datetime

from src.cli.clock_menu import ClockMenu
from src.cli.guest_menu import GuestMenu


def test_guest_menu_opens_clock_in_read_only_mode(
    monkeypatch, auth_service, policy_service
):
    menu = GuestMenu(auth_service=auth_service, policy_service=policy_service)
    created = {}

    class FakeClockMenu:
        def __init__(
            self,
            policy_service,
            actor_id="system",
            actor_role="user",
            allow_advance=True,
        ):
            created["policy_service"] = policy_service
            created["actor_id"] = actor_id
            created["actor_role"] = actor_role
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
    assert created["actor_role"] == "guest"
    assert created["allow_advance"] is False
    assert created["ran"] is True


def test_clock_menu_read_only_mode_does_not_offer_blockers(monkeypatch):
    messages = []

    class StubPolicyService:
        def prepare_advance(self, actor_id="system", actor_role="user"):
            return {
                "current_time": datetime(2024, 6, 15, 9, 0, 0),
                "next_time": datetime(2024, 6, 15, 18, 0, 0),
                "events": [],
                "blockers": ["pending"],
                "can_advance": False,
                "force_notice": "",
            }

    menu = ClockMenu(StubPolicyService(), actor_id="guest", allow_advance=False)
    inputs = iter(["2", "0"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.clock_menu.print_header", lambda *_: None)
    monkeypatch.setattr("src.cli.clock_menu.pause", lambda: None)
    monkeypatch.setattr("src.cli.clock_menu.print_error", messages.append)

    menu.run()

    assert messages == ["잘못된 선택입니다."]


def test_clock_menu_admin_preview_uses_admin_title(monkeypatch, capsys):
    class StubPolicyService:
        def prepare_advance(self, actor_id="system", actor_role="user"):
            return {
                "current_time": datetime(2024, 6, 15, 9, 0, 0),
                "next_time": datetime(2024, 6, 15, 18, 0, 0),
                "events": [],
                "blockers": [],
                "can_advance": True,
                "force_notice": "",
            }

    menu = ClockMenu(StubPolicyService(), actor_id="admin-1", actor_role="admin")

    monkeypatch.setattr("src.cli.clock_menu.print_header", lambda title: print(title))
    monkeypatch.setattr("src.cli.clock_menu.pause", lambda: None)

    menu._show_preview(StubPolicyService().prepare_advance())

    output = capsys.readouterr().out
    assert "운영 시점 정보 (관리자)" in output


def test_clock_menu_requires_force_confirmation_before_forced_advance(monkeypatch):
    class StubPolicyService:
        def __init__(self):
            self.calls = []

        def prepare_advance(self, actor_id="system", actor_role="user"):
            self.calls.append(("prepare", actor_id, actor_role))
            return {
                "current_time": datetime(2024, 6, 15, 9, 0, 0),
                "next_time": datetime(2024, 6, 15, 18, 0, 0),
                "events": [],
                "blockers": ["pending"],
                "can_advance": False,
                "force_notice": "penalty on actor",
            }

        def advance_time(self, actor_id="system", actor_role="user", force=False):
            self.calls.append(("advance", actor_id, actor_role, force))
            return {
                "current_time": datetime(2024, 6, 15, 9, 0, 0),
                "next_time": datetime(2024, 6, 15, 18, 0, 0),
                "events": ["moved"],
                "blockers": [],
                "can_advance": True,
            }

    service = StubPolicyService()
    menu = ClockMenu(service, actor_id="user-1", allow_advance=True)
    inputs = iter(["FORCE"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.clock_menu.print_header", lambda *_: None)
    monkeypatch.setattr("src.cli.clock_menu.print_warning", lambda *_: None)
    monkeypatch.setattr("src.cli.clock_menu.print_success", lambda *_: None)
    monkeypatch.setattr("src.cli.clock_menu.print_info", lambda *_: None)
    monkeypatch.setattr("src.cli.clock_menu.pause", lambda: None)
    monkeypatch.setattr("builtins.print", lambda *_args, **_kwargs: None)

    menu._advance()

    assert ("advance", "user-1", "user", True) in service.calls


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
