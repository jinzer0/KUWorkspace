from datetime import datetime
from src.cli.guest_menu import GuestMenu
from src.cli.admin_menu import AdminMenu
from src.domain.penalty_service import PenaltyError
from src.domain.room_service import RoomBookingError, RoomOperationalOverview
from src.domain.models import UserRole, EquipmentBookingStatus, RoomBooking, RoomBookingStatus
from src.storage.file_lock import global_lock


class TestGuestMenuPolicyChecks:
    def test_run_policy_checks_returns_false_on_penalty_error(
        self, monkeypatch, auth_service, policy_service
    ):
        menu = GuestMenu(auth_service=auth_service, policy_service=policy_service)

        monkeypatch.setattr(
            menu.policy_service,
            "run_all_checks",
            lambda **_kwargs: (_ for _ in ()).throw(PenaltyError("존재하지 않는 사용자입니다.")),
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
        user = auth_service.signup("Guestuser1", "pass1234")
        menu = GuestMenu(auth_service=auth_service, policy_service=policy_service)

        inputs = iter(["1", "Guestuser1", "pass1234"])
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
            lambda **_kwargs: (_ for _ in ()).throw(PenaltyError("존재하지 않는 사용자입니다.")),
        )
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: print("0. 돌아가기"))
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
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: print("0. 돌아가기"))
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
            "get_room_operational_overview",
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
            "get_room_operational_overview",
            lambda _admin: [
                RoomOperationalOverview(
                    room_name="회의실4A",
                    capacity=4,
                    location="1층",
                    operational_status="예약있음",
                    reservation_summary="2026-06-15 ~ 2026-06-15\n2026-06-16 ~ 2026-06-17",
                ),
                RoomOperationalOverview(
                    room_name="회의실4B",
                    capacity=6,
                    location="2층",
                    operational_status="예약없음",
                    reservation_summary="X",
                ),
            ],
        )
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: print("0. 돌아가기"))
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda title: print(title))

        menu._show_all_room_bookings()

        output = capsys.readouterr().out
        assert "이름" in output
        assert "수용인원" in output
        assert "위치" in output
        assert "현황" in output
        assert "예약일" in output
        assert "회의실4A" in output
        assert "예약있음" in output
        assert "2026-06-15 ~ 2026-06-15" in output
        assert "2026-06-16 ~ 2026-06-17" in output
        assert "외" not in output
        assert "회의실4B" in output
        assert "예약없음" in output
        assert "X" in output
        assert output.count("0. 돌아가기") == 1

    def test_show_all_room_bookings_with_real_repos_renders_overview_without_writes(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        create_test_room,
        temp_data_dir,
        mock_now,
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
        fixed_time = datetime(2026, 6, 13, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user(username="room_user")
            room_in_use = create_test_room(name="회의실6B", capacity=6, location="2층")
            room_reserved = create_test_room(name="회의실6C", capacity=6, location="2층")
            room_empty = create_test_room(name="회의실4A", capacity=4, location="1층")
            with global_lock():
                room_service.booking_repo.add(
                    RoomBooking(
                        id="menu-current-room-booking",
                        user_id=user.id,
                        room_id=room_in_use.id,
                        start_time=fixed_time.replace(hour=9).isoformat(),
                        end_time=fixed_time.replace(hour=18).isoformat(),
                        status=RoomBookingStatus.CHECKED_IN,
                    )
                )
                room_service.booking_repo.add(
                    RoomBooking(
                        id="menu-current-room-future-booking",
                        user_id=user.id,
                        room_id=room_in_use.id,
                        start_time=fixed_time.replace(day=15, hour=9).isoformat(),
                        end_time=fixed_time.replace(day=15, hour=18).isoformat(),
                        status=RoomBookingStatus.RESERVED,
                    )
                )
                room_service.booking_repo.add(
                    RoomBooking(
                        id="menu-reserved-room-future-booking",
                        user_id=user.id,
                        room_id=room_reserved.id,
                        start_time=fixed_time.replace(day=14, hour=9).isoformat(),
                        end_time=fixed_time.replace(day=14, hour=18).isoformat(),
                        status=RoomBookingStatus.RESERVED,
                    )
                )

            watched_files = [
                temp_data_dir / "users.txt",
                temp_data_dir / "rooms.txt",
                temp_data_dir / "room_bookings.txt",
                temp_data_dir / "audit_log.txt",
            ]
            before = {
                path.name: path.read_text(encoding="utf-8") if path.exists() else None
                for path in watched_files
            }
            monkeypatch.setattr("src.cli.admin_menu.pause", lambda: print("0. 돌아가기"))
            monkeypatch.setattr("src.cli.admin_menu.print_header", lambda title: print(title))

            menu._show_all_room_bookings()

            after = {
                path.name: path.read_text(encoding="utf-8") if path.exists() else None
                for path in watched_files
            }

        output = capsys.readouterr().out
        assert "이름" in output
        assert "수용인원" in output
        assert "위치" in output
        assert "현황" in output
        assert "예약일" in output
        assert "회의실6B" in output
        assert "사용중" in output
        assert "2026-06-13 ~ 2026-06-13" in output
        assert "2026-06-15 ~ 2026-06-15" in output
        assert "회의실6C" in output
        assert "예약있음" in output
        assert "2026-06-14 ~ 2026-06-14" in output
        assert room_empty.name in output
        assert "예약없음" in output
        assert "X" in output
        assert output.count("0. 돌아가기") == 1
        assert before == after

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
        monkeypatch.setattr("src.cli.admin_menu.review_action", lambda *_: "confirm")
        messages = []
        monkeypatch.setattr("src.cli.admin_menu.print_error", messages.append)

        menu._equipment_checkout()

        assert messages == ["사용자를 찾을 수 없습니다."]

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
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.admin_menu.print_success", lambda *_: None)
        monkeypatch.setattr("src.cli.admin_menu.print_info", lambda *_: None)
        monkeypatch.setattr("src.cli.admin_menu.review_action", lambda *_: "confirm")
        messages = []
        monkeypatch.setattr("src.cli.admin_menu.print_error", messages.append)

        menu._room_checkout()

        assert messages == []
