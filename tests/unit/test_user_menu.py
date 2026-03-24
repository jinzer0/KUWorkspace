from src.cli.user_menu import UserMenu
from src.domain.penalty_service import PenaltyError


class TestUserMenuRefresh:
    def test_refresh_user_returns_false_when_user_missing(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        user_factory,
    ):
        user = user_factory(id="missing-user")
        menu = UserMenu(
            user=user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)
        messages = []
        monkeypatch.setattr("src.cli.user_menu.print_error", messages.append)

        result = menu._refresh_user()

        assert result is False
        assert messages == ["존재하지 않는 사용자입니다."]

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
        user = create_test_user()
        menu = UserMenu(
            user=user,
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
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)
        messages = []
        monkeypatch.setattr("src.cli.user_menu.print_error", messages.append)

        result = menu._run_policy_checks()

        assert result is False
        assert messages == ["존재하지 않는 사용자입니다."]

    def test_show_my_room_bookings_returns_early_when_refresh_fails(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        user_factory,
    ):
        user = user_factory(id="missing-user")
        menu = UserMenu(
            user=user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
        messages = []
        monkeypatch.setattr("src.cli.user_menu.print_error", messages.append)

        called = {"bookings": False}

        def fail_if_called(_user_id):
            called["bookings"] = True
            raise AssertionError("booking query should not run")

        monkeypatch.setattr(menu.room_service, "get_user_bookings", fail_if_called)

        menu._show_my_room_bookings()

        assert called["bookings"] is False
        assert messages == ["존재하지 않는 사용자입니다."]

    def test_show_my_status_handles_query_error_after_refresh(
        self,
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

        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
        messages = []
        monkeypatch.setattr("src.cli.user_menu.print_error", messages.append)
        monkeypatch.setattr(
            menu.penalty_service,
            "get_user_status",
            lambda _user: (_ for _ in ()).throw(
                PenaltyError("존재하지 않는 사용자입니다.")
            ),
        )

        menu._show_my_status()

        assert messages == ["존재하지 않는 사용자입니다."]

    def test_run_returns_true_when_status_lookup_fails_after_refresh(
        self,
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

        monkeypatch.setattr(menu, "_run_policy_checks", lambda: True)
        monkeypatch.setattr(menu, "_refresh_user", lambda: True)
        monkeypatch.setattr(
            menu.penalty_service,
            "get_user_status",
            lambda _user: (_ for _ in ()).throw(
                PenaltyError("존재하지 않는 사용자입니다.")
            ),
        )
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
        messages = []
        monkeypatch.setattr("src.cli.user_menu.print_error", messages.append)

        result = menu.run()

        assert result is True
        assert messages == ["존재하지 않는 사용자입니다."]
