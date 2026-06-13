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
        def prepare_advance(self, actor_id="system"):
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
    monkeypatch.setattr(menu, "_advance", lambda: calls.__setitem__("advance", calls["advance"] + 1))
    monkeypatch.setattr(
        menu,
        "_show_blockers",
        lambda _preview: calls.__setitem__("blockers", calls["blockers"] + 1),
    )

    menu.run()

    assert calls["advance"] == 0
    assert calls["blockers"] == 1


def test_clock_menu_current_view_shows_next_slot_and_zero_return(monkeypatch, capsys):
    class StubPolicyService:
        def prepare_advance(self, actor_id="system"):
            return {
                "current_time": datetime(2026, 6, 15, 18, 0, 0),
                "next_time": datetime(2026, 6, 16, 9, 0, 0),
                "events": ["2026-06-16 09:00로 이동 준비"],
                "blockers": [],
                "can_advance": True,
                "force_notice": "",
            }

    menu = ClockMenu(StubPolicyService(), actor_id="guest", allow_advance=False)
    preview = menu.policy_service.prepare_advance(actor_id="guest")

    monkeypatch.setattr("src.cli.clock_menu.print_header", lambda title: print(title))
    monkeypatch.setattr("src.cli.clock_menu.pause", lambda: print("0. 돌아가기"))

    menu._show_preview(preview)

    output = capsys.readouterr().out
    assert "운영 시점 정보" in output
    assert "현재 운영 시점: 2026-06-15 18:00" in output
    assert "다음 시점: 2026-06-16 09:00" in output
    assert "2026-06-16 09:00로 이동 준비" in output
    assert "0. 돌아가기" in output


def test_clock_menu_requires_force_confirmation_before_forced_advance(monkeypatch):
    class StubPolicyService:
        def __init__(self):
            self.calls = []

        def prepare_advance(self, actor_id="system"):
            self.calls.append(("prepare", actor_id))
            return {
                "current_time": datetime(2024, 6, 15, 9, 0, 0),
                "next_time": datetime(2024, 6, 15, 18, 0, 0),
                "events": [],
                "blockers": ["pending"],
                "can_advance": False,
                "force_notice": "penalty on actor",
            }

        def advance_time(self, actor_id="system", force=False):
            self.calls.append(("advance", actor_id, force))
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
    monkeypatch.setattr("src.cli.clock_menu.review_action", lambda *_args, **_kwargs: "confirm")
    monkeypatch.setattr("src.cli.clock_menu.pause", lambda: None)
    monkeypatch.setattr("builtins.print", lambda *_args, **_kwargs: None)

    menu._advance()

    assert ("advance", "user-1", True) in service.calls


def test_guest_menu_signup_creates_user(monkeypatch, auth_service, policy_service):
    menu = GuestMenu(auth_service=auth_service, policy_service=policy_service)
    inputs = iter(["NewGuest1", "pass1234", "pass1234"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.guest_menu.input_start_gate", lambda _title: True)
    monkeypatch.setattr("src.cli.guest_menu.review_action", lambda *_args, **_kwargs: "confirm")
    monkeypatch.setattr("src.cli.guest_menu.print_header", lambda *_: None)
    monkeypatch.setattr("src.cli.guest_menu.pause", lambda: None)

    menu._signup()

    created = auth_service.get_user_by_username("NewGuest1")
    assert created.username == "NewGuest1"


def test_guest_signup_start_gate_zero_returns_without_credentials_or_user_write(
    monkeypatch, auth_service, policy_service, capsys
):
    menu = GuestMenu(auth_service=auth_service, policy_service=policy_service)
    inputs = iter(["0"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.guest_menu.print_header", lambda title: print(title))
    monkeypatch.setattr("src.cli.guest_menu.pause", lambda: None)

    menu._signup()

    output = capsys.readouterr().out
    assert "회원가입 입력" in output
    assert "0. 돌아가기" in output
    assert "사용자명" not in output
    assert "비밀번호" not in output
    assert auth_service.user_repo.get_all() == []


def test_guest_signup_review_cancel_does_not_write_user(
    monkeypatch, auth_service, policy_service, capsys
):
    menu = GuestMenu(auth_service=auth_service, policy_service=policy_service)
    inputs = iter(["1", "CancelUser1", "pass1234", "pass1234", "0", "0"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.guest_menu.print_header", lambda title: print(title))

    menu._signup()

    output = capsys.readouterr().out
    assert "회원가입 검토" in output
    assert "0. 취소" in output
    assert "회원가입을 취소했습니다." in output
    assert auth_service.user_repo.get_all() == []


def test_guest_signup_review_retry_restarts_input_and_writes_final_user(
    monkeypatch, auth_service, policy_service, capsys
):
    menu = GuestMenu(auth_service=auth_service, policy_service=policy_service)
    inputs = iter([
        "1",
        "RetryFirst1",
        "pass1234",
        "pass1234",
        "2",
        "1",
        "RetryFinal1",
        "final1234",
        "final1234",
        "1",
        "0",
    ])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.guest_menu.print_header", lambda title: print(title))

    menu._signup()

    output = capsys.readouterr().out
    assert output.count("회원가입 입력") == 2
    assert output.count("회원가입 검토") == 2
    assert "회원가입이 완료되었습니다. (사용자명: RetryFinal1)" in output
    assert auth_service.user_repo.get_by_username("RetryFirst1") is None
    created = auth_service.user_repo.get_by_username("RetryFinal1")
    assert created is not None
    assert created.password == "final1234"


def test_guest_signup_success_writes_one_ten_field_user_row(
    monkeypatch, auth_service, policy_service, temp_data_dir, capsys
):
    menu = GuestMenu(auth_service=auth_service, policy_service=policy_service)
    inputs = iter(["1", "SuccessUser1", "pass1234", "pass1234", "1", "0"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.guest_menu.print_header", lambda title: print(title))

    menu._signup()

    output = capsys.readouterr().out
    raw = (temp_data_dir / "users.txt").read_text(encoding="utf-8").strip()
    assert "회원가입이 완료되었습니다. (사용자명: SuccessUser1)" in output
    assert len(auth_service.user_repo.get_all()) == 1
    assert len(raw.split("|")) == 10


def test_guest_login_returns_to_main_when_start_gate_cancelled(
    monkeypatch, auth_service, policy_service, capsys
):
    menu = GuestMenu(auth_service=auth_service, policy_service=policy_service)
    inputs = iter(["0"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.guest_menu.print_header", lambda title: print(title))
    monkeypatch.setattr("src.cli.guest_menu.pause", lambda: None)

    assert menu._login() is None
    output = capsys.readouterr().out
    assert "로그인 정보 입력" in output
    assert "0. 돌아가기" in output


def test_guest_login_unknown_user_shows_member_not_found_screen(
    monkeypatch, auth_service, policy_service, capsys
):
    menu = GuestMenu(auth_service=auth_service, policy_service=policy_service)
    inputs = iter(["1", "MissingUser1", "pass1234", "0"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.guest_menu.print_header", lambda title: print(title))
    monkeypatch.setattr("src.cli.guest_menu.pause", lambda: print("0. 돌아가기"))

    assert menu._login() is None

    output = capsys.readouterr().out
    assert "로그인" in output
    assert "로그인 정보 입력" in output
    assert "0. 돌아가기" in output
    assert "존재하지 않는 사용자입니다." in output


def test_guest_login_bad_password_shows_bad_password_screen(
    monkeypatch, auth_service, policy_service, create_test_user, capsys
):
    create_test_user(username="LoginUser1", password="pass1234")
    menu = GuestMenu(auth_service=auth_service, policy_service=policy_service)
    inputs = iter(["1", "LoginUser1", "wrong1234", "0"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.guest_menu.print_header", lambda title: print(title))
    monkeypatch.setattr("src.cli.guest_menu.pause", lambda: print("0. 돌아가기"))

    assert menu._login() is None

    output = capsys.readouterr().out
    assert "로그인" in output
    assert "로그인 정보 입력" in output
    assert "0. 돌아가기" in output
    assert "비밀번호가 일치하지 않습니다." in output


def test_guest_login_success_shows_success_screen_with_zero_return(
    monkeypatch, auth_service, policy_service, create_test_user, capsys
):
    user = create_test_user(username="LoginUser2", password="pass1234")
    menu = GuestMenu(auth_service=auth_service, policy_service=policy_service)
    inputs = iter(["1", "LoginUser2", "pass1234", "0"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.guest_menu.print_header", lambda title: print(title))
    monkeypatch.setattr("src.cli.guest_menu.pause", lambda: print("0. 돌아가기"))

    result = menu._login()

    output = capsys.readouterr().out
    assert result is not None
    assert result.id == user.id
    assert result.username == user.username
    assert "로그인" in output
    assert "로그인 정보 입력" in output
    assert "0. 돌아가기" in output
    assert "LoginUser2님, 환영합니다!" in output


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
