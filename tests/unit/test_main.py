from datetime import datetime
from types import SimpleNamespace

import main as main_module
from main import prompt_initial_clock
from src.domain.models import UserRole


def test_prompt_initial_clock_retries_on_invalid_date(monkeypatch, capsys):
    inputs = iter(["2026/06/15", "09:00", "2026-06-15", "09:00"])

    monkeypatch.setattr("main.get_latest_data_timestamp", lambda: None)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

    clock = prompt_initial_clock()

    assert clock.now() == datetime(2026, 6, 15, 9, 0, 0)
    assert "날짜 형식이 올바르지 않습니다." in capsys.readouterr().out


def test_prompt_initial_clock_accepts_dot_separated_date(monkeypatch):
    inputs = iter(["2026.06.15", "09:00"])

    monkeypatch.setattr("main.get_latest_data_timestamp", lambda: None)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

    clock = prompt_initial_clock()

    assert clock.now() == datetime(2026, 6, 15, 9, 0, 0)


def test_prompt_initial_clock_accepts_space_separated_date(monkeypatch):
    inputs = iter(["2026 06 15", "18:00"])

    monkeypatch.setattr("main.get_latest_data_timestamp", lambda: None)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

    clock = prompt_initial_clock()

    assert clock.now() == datetime(2026, 6, 15, 18, 0, 0)


def test_prompt_initial_clock_retries_on_invalid_slot(monkeypatch, capsys):
    inputs = iter(["2026-06-15", "10:00", "2026-06-15", "18:00"])

    monkeypatch.setattr("main.get_latest_data_timestamp", lambda: None)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

    clock = prompt_initial_clock()

    assert clock.now() == datetime(2026, 6, 15, 18, 0, 0)
    assert "시작 슬롯은 09:00 또는 18:00만 가능합니다." in capsys.readouterr().out


def test_prompt_initial_clock_retries_when_earlier_than_latest_data(monkeypatch, capsys):
    latest = datetime(2026, 6, 15, 18, 0, 0)
    inputs = iter(["2026-06-15", "09:00", "2026-06-15", "18:00"])

    monkeypatch.setattr("main.get_latest_data_timestamp", lambda: latest)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

    clock = prompt_initial_clock()

    assert clock.now() == latest
    assert "기존 데이터의 최신 시각보다 빠릅니다" in capsys.readouterr().out


def test_main_routes_user_to_user_menu_and_returns_to_guest(monkeypatch):
    calls = []
    user = SimpleNamespace(id="user-1", username="user", role=UserRole.USER)
    guest_results = iter([user, None])

    class FakeGuestMenu:
        def __init__(self, **_kwargs):
            calls.append("guest_init")

        def run(self):
            calls.append("guest_run")
            return next(guest_results)

    class FakeUserMenu:
        def __init__(self, **_kwargs):
            calls.append("user_init")

        def run(self):
            calls.append("user_run")
            return True

    monkeypatch.setattr(main_module, "ensure_data_dir", lambda: calls.append("ensure_data_dir"))
    monkeypatch.setattr(main_module, "prompt_initial_clock", lambda: "clock")
    monkeypatch.setattr(main_module, "set_active_clock", lambda clock: calls.append(("set_active_clock", clock)))
    monkeypatch.setattr(main_module, "AuthService", lambda: object())
    monkeypatch.setattr(main_module, "PenaltyService", lambda: object())
    monkeypatch.setattr(main_module, "RoomService", lambda penalty_service=None: object())
    monkeypatch.setattr(main_module, "EquipmentService", lambda penalty_service=None: object())
    monkeypatch.setattr(main_module, "PolicyService", lambda: object())
    monkeypatch.setattr(main_module, "GuestMenu", FakeGuestMenu)
    monkeypatch.setattr(main_module, "UserMenu", FakeUserMenu)
    monkeypatch.setattr(
        main_module,
        "AdminMenu",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("admin menu should not be used")),
    )

    main_module.main()

    assert calls == [
        "ensure_data_dir",
        ("set_active_clock", "clock"),
        "guest_init",
        "guest_run",
        "user_init",
        "user_run",
        "guest_init",
        "guest_run",
    ]


def test_main_routes_admin_to_admin_menu(monkeypatch):
    calls = []
    admin = SimpleNamespace(id="admin-1", username="admin", role=UserRole.ADMIN)
    guest_results = iter([admin, None])

    class FakeGuestMenu:
        def __init__(self, **_kwargs):
            calls.append("guest_init")

        def run(self):
            calls.append("guest_run")
            return next(guest_results)

    class FakeAdminMenu:
        def __init__(self, **_kwargs):
            calls.append("admin_init")

        def run(self):
            calls.append("admin_run")
            return True

    monkeypatch.setattr(main_module, "ensure_data_dir", lambda: calls.append("ensure_data_dir"))
    monkeypatch.setattr(main_module, "prompt_initial_clock", lambda: "clock")
    monkeypatch.setattr(main_module, "set_active_clock", lambda clock: calls.append(("set_active_clock", clock)))
    monkeypatch.setattr(main_module, "AuthService", lambda: object())
    monkeypatch.setattr(main_module, "PenaltyService", lambda: object())
    monkeypatch.setattr(main_module, "RoomService", lambda penalty_service=None: object())
    monkeypatch.setattr(main_module, "EquipmentService", lambda penalty_service=None: object())
    monkeypatch.setattr(main_module, "PolicyService", lambda: object())
    monkeypatch.setattr(main_module, "GuestMenu", FakeGuestMenu)
    monkeypatch.setattr(
        main_module,
        "UserMenu",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("user menu should not be used")),
    )
    monkeypatch.setattr(main_module, "AdminMenu", FakeAdminMenu)

    main_module.main()

    assert calls == [
        "ensure_data_dir",
        ("set_active_clock", "clock"),
        "guest_init",
        "guest_run",
        "admin_init",
        "admin_run",
        "guest_init",
        "guest_run",
    ]
