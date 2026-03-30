from src.cli.user_menu import UserMenu
from src.domain.penalty_service import PenaltyError
from src.domain.message_service import MessageError


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


class TestUserMenuMessageSubmission:
    def test_submit_inquiry_saves_exactly_one_record(
        self,
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

        inputs = iter(["1", "문의내용입니다", "y"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.print_success", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)

        menu._submit_message()

        messages = message_service.message_repo.get_by_user(user.id)
        assert len(messages) == 1
        assert messages[0].type.value == "inquiry"
        assert messages[0].content == "문의내용입니다"

    def test_submit_report_saves_exactly_one_record(
        self,
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

        inputs = iter(["2", "신고내용입니다", "y"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.print_success", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)

        menu._submit_message()

        messages = message_service.message_repo.get_by_user(user.id)
        assert len(messages) == 1
        assert messages[0].type.value == "report"
        assert messages[0].content == "신고내용입니다"

    def test_submit_message_saves_nothing_when_user_cancels_with_n(
        self,
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

        inputs = iter(["1", "문의내용입니다", "n"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.print_info", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)

        menu._submit_message()

        messages = message_service.message_repo.get_by_user(user.id)
        assert len(messages) == 0

    def test_submit_message_saves_nothing_when_user_cancels_choice(
        self,
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

        inputs = iter(["0"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)

        menu._submit_message()

        messages = message_service.message_repo.get_by_user(user.id)
        assert len(messages) == 0

    def test_submit_message_reprompts_on_invalid_content(
        self,
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

        inputs = iter(["1", "", "   ", "a" * 101, "유효한내용", "y"])
        errors = []
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.print_error", errors.append)
        monkeypatch.setattr("src.cli.user_menu.print_success", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)

        menu._submit_message()

        assert len(errors) == 3
        messages = message_service.message_repo.get_by_user(user.id)
        assert len(messages) == 1
        assert messages[0].content == "유효한내용"

    def test_submit_message_strict_confirm_loop_only_y_or_n(
        self,
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

        inputs = iter(["1", "내용", "yes", "예", "ㅇ", "y"])
        errors = []
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.print_error", errors.append)
        monkeypatch.setattr("src.cli.user_menu.print_success", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)

        menu._submit_message()

        assert len(errors) == 3
        messages = message_service.message_repo.get_by_user(user.id)
        assert len(messages) == 1

    def test_submit_message_preserves_leading_and_trailing_spaces(
        self,
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

        inputs = iter(["1", "  spaced content  ", "y"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.print_success", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)

        menu._submit_message()

        messages = message_service.message_repo.get_by_user(user.id)
        assert len(messages) == 1
        assert messages[0].content == "  spaced content  "

    def test_submit_message_rejects_whitespace_only_content(
        self,
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

        inputs = iter(["1", "   ", "valid", "y"])
        errors = []
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.print_error", errors.append)
        monkeypatch.setattr("src.cli.user_menu.print_success", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)

        menu._submit_message()

        assert len(errors) == 1
        assert "공백" in errors[0]
        messages = message_service.message_repo.get_by_user(user.id)
        assert len(messages) == 1
        assert messages[0].content == "valid"

    def test_submit_message_strict_confirm_rejects_uppercase_Y(
        self,
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

        inputs = iter(["1", "content", "Y", "y"])
        errors = []
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.print_error", errors.append)
        monkeypatch.setattr("src.cli.user_menu.print_success", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)

        menu._submit_message()

        assert len(errors) == 1
        assert errors[0] == "y 또는 n을 입력해주세요."
        messages = message_service.message_repo.get_by_user(user.id)
        assert len(messages) == 1

    def test_submit_message_strict_confirm_rejects_uppercase_N(
        self,
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

        inputs = iter(["1", "content", "N", "n"])
        errors = []
        infos = []
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.print_error", errors.append)
        monkeypatch.setattr("src.cli.user_menu.print_info", infos.append)
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)

        menu._submit_message()

        assert len(errors) == 1
        assert errors[0] == "y 또는 n을 입력해주세요."
        assert len(infos) == 1
        assert "취소" in infos[0]
        messages = message_service.message_repo.get_by_user(user.id)
        assert len(messages) == 0
