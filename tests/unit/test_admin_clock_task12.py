from datetime import date, datetime

from src.cli.admin_menu import AdminMenu
from src.cli.clock_menu import ClockMenu
from src.domain.models import ResourceStatus, UserRole, decode_future_status_changes


def _admin_menu(admin, auth_service, room_service, equipment_service, penalty_service, policy_service):
    return AdminMenu(
        user=admin,
        auth_service=auth_service,
        room_service=room_service,
        equipment_service=equipment_service,
        penalty_service=penalty_service,
        policy_service=policy_service,
    )


def test_admin_creates_and_cancels_room_maintenance_through_service(
    monkeypatch,
    auth_service,
    room_service,
    equipment_service,
    penalty_service,
    policy_service,
    create_test_user,
    create_test_room,
    room_maintenance_repo,
    mock_now,
):
    with mock_now(datetime(2024, 6, 15, 8, 0, 0)):
        admin = create_test_user(role=UserRole.ADMIN)
        room = create_test_room()
        menu = _admin_menu(admin, auth_service, room_service, equipment_service, penalty_service, policy_service)
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", lambda items, prompt: items[0][0])
        monkeypatch.setattr("src.cli.admin_menu.get_daily_date_range_input", lambda *_args: (date(2024, 6, 16), date(2024, 6, 17)))
        monkeypatch.setattr("builtins.input", lambda _prompt="": "정기점검")
        monkeypatch.setattr("src.cli.admin_menu.input_start_gate", lambda _title: True)
        monkeypatch.setattr("src.cli.admin_menu.review_action", lambda *_args, **_kwargs: "confirm")
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.admin_menu.print_success", lambda *_: None)

        menu._create_room_maintenance()
        schedules = room_maintenance_repo.get_all()
        assert len(schedules) == 1
        assert schedules[0].room_id == room.id
        assert schedules[0].start_time == "2024-06-16T18:00"
        assert schedules[0].end_time == "2024-06-17T09:00"

        menu._cancel_room_maintenance()
        [cancelled] = room_maintenance_repo.get_all()
        assert cancelled.status == "cancelled"
        assert cancelled.cancelled_at != "-"


def test_admin_equipment_future_status_flow_schedules_maintenance(
    monkeypatch,
    auth_service,
    room_service,
    equipment_service,
    penalty_service,
    policy_service,
    create_test_user,
    create_test_equipment,
    equipment_repo,
    mock_now,
):
    with mock_now(datetime(2024, 6, 15, 8, 0, 0)):
        admin = create_test_user(role=UserRole.ADMIN)
        equipment = create_test_equipment()
        menu = _admin_menu(admin, auth_service, room_service, equipment_service, penalty_service, policy_service)
        inputs = iter(["1", "2", "y", "0"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
        monkeypatch.setattr(
            "src.cli.admin_menu.CalendarOverlay",
            lambda *_args, **_kwargs: type("FakeCalendar", (), {"show": lambda _self: "2024-06-16"})(),
        )
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.admin_menu.print_success", lambda *_: None)

        menu._change_equipment_status()
        updated = equipment_repo.get_by_id(equipment.id)
        items = decode_future_status_changes(updated.future_status_changes)
        assert len(items) == 1
        assert items[0]["status"] == ResourceStatus.MAINTENANCE.value


def test_inspect1_equipment_future_status_reachable_from_resource_status_flow(
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
    create_test_equipment(name="노트북A")
    menu = _admin_menu(admin, auth_service, room_service, equipment_service, penalty_service, policy_service)
    calls = []
    inputs = iter(["1", "0", "0"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
    monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
    monkeypatch.setattr(
        "src.cli.admin_menu.CalendarOverlay",
        lambda *_args, **_kwargs: type("FakeCalendar", (), {"show": lambda _self: calls.append("calendar") or None})(),
    )

    menu._change_equipment_status()

    assert calls == ["calendar"]


def test_clock_advance_prints_task11_maintenance_summary(monkeypatch, capsys):
    class StubPolicyService:
        def prepare_advance(self, actor_id="system"):
            return {
                "current_time": datetime(2024, 6, 15, 9, 0),
                "next_time": datetime(2024, 6, 15, 18, 0),
                "events": [],
                "blockers": [],
                "can_advance": True,
            }

        def advance_time(self, actor_id="system", force=False):
            return {
                "current_time": datetime(2024, 6, 15, 9, 0),
                "next_time": datetime(2024, 6, 15, 18, 0),
                "events": ["moved"],
                "blockers": [],
                "can_advance": True,
                "maintenance": {
                    "room_maintenance_expired": ["m1"],
                    "equipment_future_status_changes": ["f1", "f2"],
                    "room_pending_promoted": ["r1"],
                    "room_pending_cancelled": [],
                    "equipment_pending_promoted": [],
                    "equipment_pending_cancelled": ["e1"],
                    "penalty_reset_users": ["u1"],
                    "restriction_expired_users": ["u2"],
                    "banned_user_cancelled_bookings": ["b1"],
                },
            }

    menu = ClockMenu(StubPolicyService(), actor_id="admin")
    monkeypatch.setattr("src.cli.clock_menu.review_action", lambda *_args, **_kwargs: "confirm")
    monkeypatch.setattr("src.cli.clock_menu.pause", lambda: None)
    menu._advance()
    output = capsys.readouterr().out
    assert "정책 점검 요약" in output
    assert "장비 미래 상태 적용: 2건" in output
    assert "장비 대기 취소: 1건" in output
