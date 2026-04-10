from datetime import datetime
from types import SimpleNamespace
import pytest
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


def test_prompt_initial_clock_accepts_hhmm_slot(monkeypatch):
    inputs = iter(["2026-06-15", "0900"])

    monkeypatch.setattr("main.get_latest_data_timestamp", lambda: None)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

    clock = prompt_initial_clock()

    assert clock.now() == datetime(2026, 6, 15, 9, 0, 0)


def test_prompt_initial_clock_retries_on_invalid_slot(monkeypatch, capsys):
    inputs = iter(["2026-06-15", "10:00", "2026-06-15", "18:00"])

    monkeypatch.setattr("main.get_latest_data_timestamp", lambda: None)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

    clock = prompt_initial_clock()

    assert clock.now() == datetime(2026, 6, 15, 18, 0, 0)
    assert "09 또는 18" in capsys.readouterr().out


def test_prompt_initial_clock_retries_on_outer_whitespace(monkeypatch, capsys):
    inputs = iter([" 2026-06-15", "0900", "2026-06-15", "0900"])

    monkeypatch.setattr("main.get_latest_data_timestamp", lambda: None)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

    clock = prompt_initial_clock()

    assert clock.now() == datetime(2026, 6, 15, 9, 0, 0)
    assert "공백" in capsys.readouterr().out


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
    monkeypatch.setattr(main_module, "load_persisted_clock", lambda: None)
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


def test_main_uses_persisted_clock_without_prompt(monkeypatch):
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

    persisted = datetime(2026, 6, 15, 18, 0, 0)

    monkeypatch.setattr(main_module, "ensure_data_dir", lambda: calls.append("ensure_data_dir"))
    monkeypatch.setattr(main_module, "load_persisted_clock", lambda: persisted)
    monkeypatch.setattr(
        main_module,
        "prompt_initial_clock",
        lambda: (_ for _ in ()).throw(AssertionError("prompt should not be used")),
    )
    monkeypatch.setattr(main_module, "set_active_clock", lambda clock: calls.append(("set_active_clock", clock.now())))
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

    assert calls[0] == "ensure_data_dir"
    assert calls[1] == ("set_active_clock", persisted)


def test_main_prompts_when_clock_file_is_sentinel(tmp_path, monkeypatch):
    sentinel_file = tmp_path / "clock.txt"
    sentinel_file.write_text("0000-00-00T00:00", encoding="utf-8")

    monkeypatch.setattr("src.config.CLOCK_FILE", sentinel_file)
    monkeypatch.setattr("src.clock_bootstrap.config.CLOCK_FILE", sentinel_file)

    inputs = iter(["2026-06-15", "09:00"])
    monkeypatch.setattr("main.get_latest_data_timestamp", lambda: None)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

    clock = prompt_initial_clock()

    assert clock.now() == datetime(2026, 6, 15, 9, 0, 0)
    assert sentinel_file.read_text(encoding="utf-8").strip() == "2026-06-15T09:00"


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
    monkeypatch.setattr(main_module, "load_persisted_clock", lambda: None)
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


def test_main_exits_on_corrupted_data_file(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    users = data_dir / "users.txt"
    rooms = data_dir / "rooms.txt"
    equips = data_dir / "equipments.txt"
    room_bookings = data_dir / "room_bookings.txt"
    equipment_booking = data_dir / "equipment_booking.txt"
    penalties = data_dir / "penalties.txt"
    audit = data_dir / "audit_log.txt"
    clock = data_dir / "clock.txt"

    users.write_text("admin|admin123|user|0|0|\\-|2026-03-20T09:00\n", encoding="utf-8")
    rooms.touch()
    equips.touch()
    room_bookings.touch()
    equipment_booking.touch()
    penalties.touch()
    audit.touch()
    clock.write_text("0000-00-00T00:00", encoding="utf-8")

    monkeypatch.setattr("src.config.DATA_DIR", data_dir)
    monkeypatch.setattr("src.config.USERS_FILE", users)
    monkeypatch.setattr("src.config.ROOMS_FILE", rooms)
    monkeypatch.setattr("src.config.EQUIPMENTS_FILE", equips)
    monkeypatch.setattr("src.config.ROOM_BOOKINGS_FILE", room_bookings)
    monkeypatch.setattr("src.config.EQUIPMENT_BOOKING_FILE", equipment_booking)
    monkeypatch.setattr("src.config.PENALTIES_FILE", penalties)
    monkeypatch.setattr("src.config.AUDIT_LOG_FILE", audit)
    monkeypatch.setattr("src.config.CLOCK_FILE", clock)
    monkeypatch.setattr(
        "src.config.DATA_FILES",
        [users, rooms, equips, room_bookings, equipment_booking, penalties, audit, clock],
    )
    monkeypatch.setattr("src.clock_bootstrap.config.DATA_DIR", data_dir)
    monkeypatch.setattr("src.clock_bootstrap.config.USERS_FILE", users)
    monkeypatch.setattr("src.clock_bootstrap.config.ROOMS_FILE", rooms)
    monkeypatch.setattr("src.clock_bootstrap.config.EQUIPMENTS_FILE", equips)
    monkeypatch.setattr("src.clock_bootstrap.config.ROOM_BOOKINGS_FILE", room_bookings)
    monkeypatch.setattr("src.clock_bootstrap.config.EQUIPMENT_BOOKING_FILE", equipment_booking)
    monkeypatch.setattr("src.clock_bootstrap.config.PENALTIES_FILE", penalties)
    monkeypatch.setattr("src.clock_bootstrap.config.AUDIT_LOG_FILE", audit)
    monkeypatch.setattr("src.clock_bootstrap.config.CLOCK_FILE", clock)
    monkeypatch.setattr(
        "src.clock_bootstrap.config.DATA_FILES",
        [users, rooms, equips, room_bookings, equipment_booking, penalties, audit, clock],
    )
    monkeypatch.setattr("src.storage.repositories.USERS_FILE", users)
    monkeypatch.setattr("src.storage.repositories.ROOMS_FILE", rooms)
    monkeypatch.setattr("src.storage.repositories.EQUIPMENTS_FILE", equips)
    monkeypatch.setattr("src.storage.repositories.ROOM_BOOKINGS_FILE", room_bookings)
    monkeypatch.setattr("src.storage.repositories.EQUIPMENT_BOOKING_FILE", equipment_booking)
    monkeypatch.setattr("src.storage.repositories.PENALTIES_FILE", penalties)
    monkeypatch.setattr("src.storage.repositories.AUDIT_LOG_FILE", audit)

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 1
    assert "데이터 파일 형식이 올바르지 않습니다" in capsys.readouterr().err
