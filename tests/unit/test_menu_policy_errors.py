from datetime import datetime
from types import SimpleNamespace

from src.cli.guest_menu import GuestMenu
from src.cli.admin_menu import AdminMenu
from src.domain.penalty_service import PenaltyError
from src.domain.room_service import RoomBookingError
from src.domain.models import UserRole, EquipmentBookingStatus, RoomBookingStatus


class TestGuestMenuPolicyChecks:
    def test_run_policy_checks_returns_false_on_penalty_error(
        self, monkeypatch, auth_service, policy_service
    ):
        menu = GuestMenu(auth_service=auth_service, policy_service=policy_service)

        monkeypatch.setattr(
            menu.policy_service,
            "run_all_checks",
            lambda: (_ for _ in ()).throw(PenaltyError("존재하지 않는 사용자입니다.")),
        )
        monkeypatch.setattr("src.cli.guest_menu.pause", lambda: None)
        messages = []
        monkeypatch.setattr("src.cli.guest_menu.print_error", messages.append)

        result = menu._run_policy_checks()

        assert result is False
        assert messages == ["존재하지 않는 사용자입니다."]

    def test_login_handles_penalty_error_from_status_lookup(
        self, monkeypatch, auth_service, policy_service
    ):
        user = auth_service.signup("guestuser", "pass1234")
        menu = GuestMenu(auth_service=auth_service, policy_service=policy_service)

        inputs = iter(["guestuser", "pass1234"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
        monkeypatch.setattr(menu, "_run_policy_checks", lambda: True)
        monkeypatch.setattr(
            menu.policy_service.penalty_service,
            "get_user_status",
            lambda _user: (_ for _ in ()).throw(
                PenaltyError("존재하지 않는 사용자입니다.")
            ),
        )
        monkeypatch.setattr("src.cli.guest_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.guest_menu.print_header", lambda *_: None)
        messages = []
        monkeypatch.setattr("src.cli.guest_menu.print_error", messages.append)
        monkeypatch.setattr("src.cli.guest_menu.print_success", lambda *_: None)

        result = menu._login()

        assert result is None
        assert messages == ["존재하지 않는 사용자입니다."]


class TestAdminMenuPolicyChecks:
    def test_run_policy_checks_returns_false_on_penalty_error(
        self,
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

        monkeypatch.setattr(
            menu.policy_service,
            "run_all_checks",
            lambda: (_ for _ in ()).throw(PenaltyError("존재하지 않는 사용자입니다.")),
        )
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        messages = []
        monkeypatch.setattr("src.cli.admin_menu.print_error", messages.append)

        result = menu._run_policy_checks()

        assert result is False
        assert messages == ["존재하지 않는 사용자입니다."]

    def test_refresh_admin_returns_false_when_user_is_no_longer_admin(
        self,
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

        monkeypatch.setattr(menu.auth_service, "is_admin", lambda user: False)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        messages = []
        monkeypatch.setattr("src.cli.admin_menu.print_error", messages.append)

        result = menu._refresh_admin()

        assert result is False
        assert messages == ["관리자 권한이 필요합니다."]

    def test_show_user_detail_handles_stale_selected_user_queries(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
    ):
        admin = create_test_user(role=UserRole.ADMIN)
        target = create_test_user(username="target_user")
        menu = AdminMenu(
            user=admin,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr(menu, "_get_all_users_or_abort", lambda: [target])
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", lambda *_: target.id)
        monkeypatch.setattr(menu, "_safe_get_user", lambda _user_id: target)
        monkeypatch.setattr(
            menu.penalty_service,
            "get_user_status",
            lambda _user: (_ for _ in ()).throw(
                RoomBookingError("존재하지 않는 사용자입니다.")
            ),
        )
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
        messages = []
        monkeypatch.setattr("src.cli.admin_menu.print_error", messages.append)

        menu._show_user_detail()

        assert messages == ["존재하지 않는 사용자입니다."]

    def test_show_users_handles_stale_listed_user_queries(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
    ):
        admin = create_test_user(role=UserRole.ADMIN)
        target = create_test_user(username="target_user")
        menu = AdminMenu(
            user=admin,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr(menu, "_get_all_users_or_abort", lambda: [target])
        monkeypatch.setattr(
            menu.penalty_service,
            "get_user_status",
            lambda _user: (_ for _ in ()).throw(
                PenaltyError("존재하지 않는 사용자입니다.")
            ),
        )
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
        messages = []
        monkeypatch.setattr("src.cli.admin_menu.print_error", messages.append)

        menu._show_users()

        assert messages == ["존재하지 않는 사용자입니다."]

    def test_show_all_room_bookings_handles_room_overview_error(
        self,
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

        monkeypatch.setattr(
            menu.room_service,
            "get_all_rooms",
            lambda: [SimpleNamespace(id="room-1", name="회의실 4A", capacity=4, location="1층")],
        )
        monkeypatch.setattr(
            menu.room_service,
            "get_all_bookings",
            lambda _admin: (_ for _ in ()).throw(RoomBookingError("존재하지 않는 사용자입니다.")),
        )
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
        messages = []
        monkeypatch.setattr("src.cli.admin_menu.print_error", messages.append)

        menu._show_all_room_bookings()

        assert messages == ["존재하지 않는 사용자입니다."]

    def test_show_all_room_bookings_renders_room_operational_overview(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        capsys,
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

        monkeypatch.setattr(
            menu.room_service,
            "get_all_rooms",
            lambda: [
                SimpleNamespace(id="room-1", name="회의실 4A", capacity=4, location="1층"),
                SimpleNamespace(id="room-2", name="회의실 4B", capacity=6, location="2층"),
            ],
        )
        monkeypatch.setattr(
            menu,
            "_get_room_bookings_or_abort",
            lambda: [
                SimpleNamespace(
                    room_id="room-1",
                    start_time="2026-06-15T09:00:00",
                    end_time="2026-06-15T18:00:00",
                    status=RoomBookingStatus.RESERVED,
                ),
                SimpleNamespace(
                    room_id="room-1",
                    start_time="2026-06-16T09:00:00",
                    end_time="2026-06-16T18:00:00",
                    status=RoomBookingStatus.RESERVED,
                ),
            ],
        )
        monkeypatch.setattr(menu.policy_service.clock, "now", lambda: datetime(2026, 6, 14, 9, 0, 0))
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda title: print(title))

        menu._show_all_room_bookings()

        output = capsys.readouterr().out
        assert "이름" in output
        assert "현황" in output
        assert "예약일" in output
        assert "회의실 4A" in output
        assert "예약있음" in output
        assert "2026.06.15 ~ 2026.06.15" in output
        assert "2026.06.16 ~ 2026.06.16" in output
        assert "회의실 4B" in output
        assert "예약없음" in output

    def test_equipment_checkout_handles_stale_booking_owner(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        equipment_booking_factory,
    ):
        admin = create_test_user(role=UserRole.ADMIN)
        booking = equipment_booking_factory(
            user_id="missing-user", status=EquipmentBookingStatus.PICKUP_REQUESTED
        )
        menu = AdminMenu(
            user=admin,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr(menu, "_get_equipment_bookings_or_abort", lambda: [booking])
        monkeypatch.setattr(menu, "_safe_get_user", lambda _user_id: None)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.admin_menu.print_info", lambda *_: None)
        messages = []
        monkeypatch.setattr("src.cli.admin_menu.print_error", messages.append)

        menu._equipment_checkout()

        assert messages == ["사용자를 찾을 수 없습니다."]

    def test_room_checkin_requires_confirmation_before_approval(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        room_booking_factory,
        user_factory,
    ):
        admin = create_test_user(role=UserRole.ADMIN)
        booking = room_booking_factory(user_id="user-1", status=RoomBookingStatus.CHECKIN_REQUESTED)
        menu = AdminMenu(
            user=admin,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr(menu, "_get_room_bookings_or_abort", lambda: [booking])
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", lambda *_: booking.id)
        monkeypatch.setattr(menu, "_get_booking_user_or_abort", lambda _user_id: user_factory(username="user1"))
        monkeypatch.setattr("src.cli.admin_menu.confirm", lambda _msg: False)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)

        called = {"value": False}
        monkeypatch.setattr(menu.room_service, "check_in", lambda *_: called.__setitem__("value", True))

        menu._room_checkin()

        assert called["value"] is False

    def test_room_checkout_requires_confirmation_before_approval(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        room_booking_factory,
        user_factory,
    ):
        admin = create_test_user(role=UserRole.ADMIN)
        booking = room_booking_factory(user_id="user-1", status=RoomBookingStatus.CHECKOUT_REQUESTED)
        menu = AdminMenu(
            user=admin,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr(menu, "_get_room_bookings_or_abort", lambda: [booking])
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", lambda *_: booking.id)
        monkeypatch.setattr(menu, "_get_booking_user_or_abort", lambda _user_id: user_factory(username="user1"))
        monkeypatch.setattr("src.cli.admin_menu.confirm", lambda _msg: False)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)

        called = {"value": False}
        monkeypatch.setattr(menu.room_service, "approve_checkout_request", lambda *_: called.__setitem__("value", True))

        menu._room_checkout()

        assert called["value"] is False

    def test_admin_cancel_room_booking_blocks_same_day_reservations(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        room_booking_factory,
        user_factory,
    ):
        admin = create_test_user(role=UserRole.ADMIN)
        booking = room_booking_factory(
            user_id="user-1",
            start_time="2026-06-15T09:00:00",
            end_time="2026-06-15T18:00:00",
            status=RoomBookingStatus.RESERVED,
        )
        menu = AdminMenu(
            user=admin,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr(menu, "_get_room_bookings_or_abort", lambda: [booking])
        monkeypatch.setattr(menu, "_get_booking_user_or_abort", lambda _user_id: user_factory(username="user1"))
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", lambda *_: booking.id)
        monkeypatch.setattr(menu.policy_service.clock, "now", lambda: datetime(2026, 6, 15, 9, 0, 0))
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
        messages = []
        monkeypatch.setattr("src.cli.admin_menu.print_error", messages.append)

        called = {"value": False}
        monkeypatch.setattr(menu.room_service, "admin_cancel_booking", lambda *_: called.__setitem__("value", True))

        menu._admin_cancel_room_booking()

        assert called["value"] is False
        assert messages == ["당일 예약은 취소할 수 없습니다."]

    def test_admin_cancel_room_booking_selection_shows_booking_period(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        room_booking_factory,
        user_factory,
    ):
        admin = create_test_user(role=UserRole.ADMIN)
        booking = room_booking_factory(
            user_id="user-1",
            room_id="room-1",
            start_time="2026-06-16T09:00:00",
            end_time="2026-06-16T18:00:00",
            status=RoomBookingStatus.RESERVED,
        )
        menu = AdminMenu(
            user=admin,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr(menu, "_get_room_bookings_or_abort", lambda: [booking])
        monkeypatch.setattr(
            menu.room_service,
            "get_room",
            lambda _room_id: SimpleNamespace(name="회의실 4A"),
        )
        monkeypatch.setattr(menu, "_get_booking_user_or_abort", lambda _user_id: user_factory(username="user1"))
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
        captured = {}

        def fake_select(items, _prompt):
            captured["items"] = items
            return None

        monkeypatch.setattr("src.cli.admin_menu.select_from_list", fake_select)

        menu._admin_cancel_room_booking()

        assert captured["items"] == [
            (
                booking.id,
                "회의실 4A / user1 / 2026-06-16 09:00~18:00",
            )
        ]

    def test_admin_modify_room_booking_excludes_already_started_reserved_bookings(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        room_booking_factory,
        user_factory,
    ):
        admin = create_test_user(role=UserRole.ADMIN)
        started = room_booking_factory(
            user_id="user-1",
            room_id="room-1",
            start_time="2026-06-15T09:00:00",
            end_time="2026-06-15T18:00:00",
            status=RoomBookingStatus.RESERVED,
        )
        future = room_booking_factory(
            user_id="user-1",
            room_id="room-1",
            start_time="2026-06-16T09:00:00",
            end_time="2026-06-16T18:00:00",
            status=RoomBookingStatus.RESERVED,
        )
        menu = AdminMenu(
            user=admin,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr(menu, "_get_room_bookings_or_abort", lambda: [started, future])
        monkeypatch.setattr(menu.policy_service.clock, "now", lambda: datetime(2026, 6, 15, 9, 0, 0))
        monkeypatch.setattr(
            menu.room_service,
            "get_room",
            lambda _room_id: SimpleNamespace(name="회의실 4A"),
        )
        monkeypatch.setattr(menu, "_get_booking_user_or_abort", lambda _user_id: user_factory(username="user1"))
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
        captured = {}

        def fake_select(items, _prompt):
            captured["items"] = items
            return None

        monkeypatch.setattr("src.cli.admin_menu.select_from_list", fake_select)

        menu._admin_modify_room_booking_time()

        assert captured["items"] == [
            (
                future.id,
                "회의실 4A / user1 / 2026-06-16 09:00~18:00",
            )
        ]

    def test_show_all_equipment_bookings_maps_pickup_requested_as_reserved(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        equipment_booking_factory,
        user_factory,
        capsys,
    ):
        admin = create_test_user(role=UserRole.ADMIN)
        booking = equipment_booking_factory(
            user_id="user-1",
            equipment_id="eq-1",
            status=EquipmentBookingStatus.PICKUP_REQUESTED,
        )
        menu = AdminMenu(
            user=admin,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr(menu, "_get_equipment_bookings_or_abort", lambda: [booking])
        monkeypatch.setattr(
            menu.equipment_service,
            "get_equipment",
            lambda _equipment_id: SimpleNamespace(serial_number="EQ-001", name="노트북1"),
        )
        monkeypatch.setattr(menu, "_get_booking_user_or_abort", lambda _user_id: user_factory(username="user1"))
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda title: print(title))

        menu._show_all_equipment_bookings()

        output = capsys.readouterr().out
        assert "[예약있음]" in output
        assert "[사용중]" not in output

    def test_show_all_equipment_bookings_maps_return_requested_as_in_use(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        equipment_booking_factory,
        user_factory,
        capsys,
    ):
        admin = create_test_user(role=UserRole.ADMIN)
        booking = equipment_booking_factory(
            user_id="user-1",
            equipment_id="eq-1",
            status=EquipmentBookingStatus.RETURN_REQUESTED,
        )
        menu = AdminMenu(
            user=admin,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr(menu, "_get_equipment_bookings_or_abort", lambda: [booking])
        monkeypatch.setattr(
            menu.equipment_service,
            "get_equipment",
            lambda _equipment_id: SimpleNamespace(serial_number="EQ-001", name="노트북1"),
        )
        monkeypatch.setattr(menu, "_get_booking_user_or_abort", lambda _user_id: user_factory(username="user1"))
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda title: print(title))

        menu._show_all_equipment_bookings()

        output = capsys.readouterr().out
        assert "[사용중]" in output

    def test_show_users_uses_username_without_id_column(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        capsys,
    ):
        admin = create_test_user(role=UserRole.ADMIN)
        normal_user = create_test_user(username="member01")
        menu = AdminMenu(
            user=admin,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr(menu, "_get_all_users_or_abort", lambda: [normal_user])
        monkeypatch.setattr(
            menu.penalty_service,
            "get_user_status",
            lambda _user: {"points": 0, "is_banned": False, "is_restricted": False},
        )
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda title: print(title))

        menu._show_users()

        output = capsys.readouterr().out
        assert "사용자명" in output
        assert "member01" in output
        assert " ID " not in output

    def test_apply_damage_penalty_uses_selected_booking_without_fixed_penalty_filtering(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        room_booking_factory,
    ):
        admin = create_test_user(role=UserRole.ADMIN)
        target = create_test_user(username="target1")
        booking = room_booking_factory(user_id=target.id, status=RoomBookingStatus.COMPLETED)
        menu = AdminMenu(
            user=admin,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr(menu, "_get_all_users_or_abort", lambda: [target])
        monkeypatch.setattr(menu, "_safe_get_user", lambda _user_id: target)
        monkeypatch.setattr(menu.room_service, "get_user_bookings", lambda _user_id: [booking])
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", lambda items, _prompt: target.id if items and items[0][0] == target.id else booking.id)
        monkeypatch.setattr("src.cli.admin_menu.confirm", lambda _msg: True)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.admin_menu.print_success", lambda *_: None)
        monkeypatch.setattr("src.cli.admin_menu.print_info", lambda *_: None)
        monkeypatch.setattr("src.cli.admin_menu.print_warning", lambda *_: None)

        called = {}

        def fake_apply_damage(**kwargs):
            called.update(kwargs)
            return SimpleNamespace(points=kwargs["points"])

        monkeypatch.setattr(menu.penalty_service, "apply_damage", fake_apply_damage)

        inputs = iter(["1", "3", "사유"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

        menu._apply_damage_penalty()

        assert called["booking_type"] == "room_booking"
        assert called["booking_id"] == booking.id

    def test_force_late_cancel_penalty_filters_candidates_to_actual_late_cancellations(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        room_booking_factory,
    ):
        admin = create_test_user(role=UserRole.ADMIN)
        target = create_test_user(username="target2")
        cancelled = room_booking_factory(
            user_id=target.id,
            status=RoomBookingStatus.CANCELLED,
            start_time="2026-06-16T09:00:00",
            end_time="2026-06-16T18:00:00",
            cancelled_at="2026-06-16T08:30:00",
        )
        admin_cancelled = room_booking_factory(user_id=target.id, status=RoomBookingStatus.ADMIN_CANCELLED)
        early_cancelled = room_booking_factory(
            user_id=target.id,
            status=RoomBookingStatus.CANCELLED,
            start_time="2026-06-20T09:00:00",
            end_time="2026-06-20T18:00:00",
            cancelled_at="2026-06-18T09:00:00",
        )
        menu = AdminMenu(
            user=admin,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        admin_user = create_test_user(username="another_admin", role=UserRole.ADMIN)
        monkeypatch.setattr(menu.auth_service, "get_all_users", lambda _admin: [target, admin_user])
        monkeypatch.setattr(menu, "_safe_get_user", lambda _user_id: target)
        monkeypatch.setattr(menu.room_service, "get_user_bookings", lambda _user_id: [cancelled, admin_cancelled, early_cancelled])
        monkeypatch.setattr(menu.equipment_service, "get_user_bookings", lambda _user_id: [])
        monkeypatch.setattr("src.cli.admin_menu.confirm", lambda _msg: True)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.admin_menu.print_success", lambda *_: None)
        monkeypatch.setattr("src.cli.admin_menu.print_info", lambda *_: None)
        monkeypatch.setattr("src.cli.admin_menu.print_warning", lambda *_: None)

        captured = {}
        selections = iter([target.id, cancelled.id])

        def fake_select(items, _prompt):
            captured.setdefault("items", []).append(items)
            return next(selections)

        monkeypatch.setattr("src.cli.admin_menu.select_from_list", fake_select)

        called = {}

        monkeypatch.setattr(menu.penalty_service, "apply_late_cancel", lambda **kwargs: called.update(kwargs))

        menu._force_late_cancel_penalty()

        assert len(captured["items"][0]) == 1
        assert captured["items"][0][0][0] == target.id
        assert len(captured["items"][1]) == 1
        assert captured["items"][1][0][0] == cancelled.id
        assert called["booking_id"] == cancelled.id

    def test_apply_fixed_penalty_filters_late_checkout_candidates_to_room_lifecycle(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        room_booking_factory,
    ):
        admin = create_test_user(role=UserRole.ADMIN)
        target = create_test_user(username="target3")
        completed = room_booking_factory(
            user_id=target.id,
            status=RoomBookingStatus.CHECKED_IN,
            end_time="2026-06-15T18:00:00",
        )
        reserved = room_booking_factory(user_id=target.id, status=RoomBookingStatus.RESERVED)
        menu = AdminMenu(
            user=admin,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr(menu.auth_service, "get_all_users", lambda _admin: [target])
        monkeypatch.setattr(menu, "_safe_get_user", lambda _user_id: target)
        monkeypatch.setattr(menu.room_service, "get_user_bookings", lambda _user_id: [completed, reserved])
        monkeypatch.setattr(menu.policy_service.clock, "now", lambda: datetime(2026, 6, 15, 18, 0, 0))
        monkeypatch.setattr("src.cli.admin_menu.confirm", lambda _msg: True)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.admin_menu.print_success", lambda *_: None)
        monkeypatch.setattr("src.cli.admin_menu.print_info", lambda *_: None)
        monkeypatch.setattr("src.cli.admin_menu.print_warning", lambda *_: None)

        captured = {}
        selections = iter([target.id, completed.id])

        def fake_select(items, _prompt):
            captured.setdefault("items", []).append(items)
            return next(selections)

        monkeypatch.setattr("src.cli.admin_menu.select_from_list", fake_select)
        monkeypatch.setattr(menu.penalty_service, "apply_fixed_penalty", lambda **kwargs: SimpleNamespace(points=kwargs["points"]))
        monkeypatch.setattr("builtins.input", lambda _prompt="": "사유")

        menu._apply_fixed_penalty("late_checkout")

        assert len(captured["items"][1]) == 1
        assert captured["items"][1][0][0] == completed.id

    def test_apply_fixed_penalty_filters_late_return_candidates_to_equipment_lifecycle(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        equipment_booking_factory,
    ):
        admin = create_test_user(role=UserRole.ADMIN)
        target = create_test_user(username="target4")
        returned = equipment_booking_factory(
            user_id=target.id,
            status=EquipmentBookingStatus.CHECKED_OUT,
            end_time="2026-06-15T18:00:00",
        )
        reserved = equipment_booking_factory(user_id=target.id, status=EquipmentBookingStatus.RESERVED)
        menu = AdminMenu(
            user=admin,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr(menu.auth_service, "get_all_users", lambda _admin: [target])
        monkeypatch.setattr(menu, "_safe_get_user", lambda _user_id: target)
        monkeypatch.setattr(menu.equipment_service, "get_user_bookings", lambda _user_id: [returned, reserved])
        monkeypatch.setattr(menu.policy_service.clock, "now", lambda: datetime(2026, 6, 15, 18, 0, 0))
        monkeypatch.setattr("src.cli.admin_menu.confirm", lambda _msg: True)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.admin_menu.print_success", lambda *_: None)
        monkeypatch.setattr("src.cli.admin_menu.print_info", lambda *_: None)
        monkeypatch.setattr("src.cli.admin_menu.print_warning", lambda *_: None)

        captured = {}
        selections = iter([target.id, returned.id])

        def fake_select(items, _prompt):
            captured.setdefault("items", []).append(items)
            return next(selections)

        monkeypatch.setattr("src.cli.admin_menu.select_from_list", fake_select)
        monkeypatch.setattr(menu.penalty_service, "apply_fixed_penalty", lambda **kwargs: SimpleNamespace(points=kwargs["points"]))
        monkeypatch.setattr("builtins.input", lambda _prompt="": "사유")

        menu._apply_fixed_penalty("late_return")

        assert len(captured["items"][1]) == 1
        assert captured["items"][1][0][0] == returned.id

    def test_change_equipment_status_blocks_maintenance_outside_1800(
        self,
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

        monkeypatch.setattr(
            menu,
            "_show_equipment",
            lambda: [SimpleNamespace(serial_number="EQ-001", name="노트북1", asset_type="laptop", status=SimpleNamespace(value="available"))],
        )
        inputs = iter(["1", "2"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
        monkeypatch.setattr(menu.policy_service.clock, "now", lambda: datetime(2026, 6, 15, 9, 0, 0))
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        messages = []
        monkeypatch.setattr("src.cli.admin_menu.print_error", messages.append)

        called = {"value": False}
        monkeypatch.setattr(
            menu.equipment_service,
            "update_equipment_status",
            lambda **_kwargs: called.__setitem__("value", True),
        )

        menu._change_equipment_status()

        assert called["value"] is False
        assert messages == ["관리자가 장비를 [점검중] 으로 변경할 수 있는 시점은 18:00 입니다."]

    def test_room_checkout_handles_stale_owner_after_success(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        room_booking_factory,
        user_factory,
    ):
        admin = create_test_user(role=UserRole.ADMIN)
        booking = room_booking_factory(
            user_id="missing-user", status="checkout_requested"
        )
        menu = AdminMenu(
            user=admin,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr(menu, "_get_room_bookings_or_abort", lambda: [booking])
        monkeypatch.setattr(
            "src.cli.admin_menu.select_from_list", lambda *_: booking.id
        )
        monkeypatch.setattr(
            menu.room_service, "approve_checkout_request", lambda *_: (booking, 0)
        )

        lookup_count = {"count": 0}

        def stale_on_second_lookup(_user_id):
            lookup_count["count"] += 1
            if lookup_count["count"] == 1:
                return user_factory(username="temp_user")
            return None

        monkeypatch.setattr(menu, "_safe_get_user", stale_on_second_lookup)
        monkeypatch.setattr("src.cli.admin_menu.confirm", lambda _msg: True)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.admin_menu.print_success", lambda *_: None)
        monkeypatch.setattr("src.cli.admin_menu.print_info", lambda *_: None)
        messages = []
        monkeypatch.setattr("src.cli.admin_menu.print_error", messages.append)

        menu._room_checkout()

        assert messages == []
