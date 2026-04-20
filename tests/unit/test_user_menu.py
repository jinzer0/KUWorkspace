from datetime import datetime, timedelta
from types import SimpleNamespace

from src.cli.user_menu import UserMenu
from src.domain.models import EquipmentBookingStatus, RoomBookingStatus
from src.domain.penalty_service import PenaltyError
from src.storage.file_lock import global_lock


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


class TestUserMenuRequestableLists:
    def _make_menu(
        self,
        user,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
    ):
        return UserMenu(
            user=user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

    def _capture_menu_items(self, monkeypatch):
        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)
        captured = {}

        def fake_select(items, _prompt):
            captured["items"] = items
            return None

        monkeypatch.setattr("src.cli.user_menu.select_from_list", fake_select)
        return captured

    def _capture_empty_state(self, monkeypatch):
        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)
        monkeypatch.setattr(
            "src.cli.user_menu.select_from_list",
            lambda *_: (_ for _ in ()).throw(
                AssertionError("select_from_list should not run")
            ),
        )
        messages = []
        monkeypatch.setattr("src.cli.user_menu.print_info", messages.append)
        return messages

    def test_room_checkin_lists_only_currently_requestable_bookings(
        self,
        monkeypatch,
        fake_clock,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        room_booking_factory,
    ):
        fixed_time = datetime(2026, 4, 15, 9, 0, 0)
        fake_clock(fixed_time)
        user = create_test_user(username="room_ckin_user")
        room = create_test_room(name="회의실2A")

        eligible = room_booking_factory(
            user_id=user.id,
            room_id=room.id,
            start_time=fixed_time.isoformat(),
            end_time=fixed_time.replace(hour=18).isoformat(),
            status=RoomBookingStatus.RESERVED,
        )
        ineligible = room_booking_factory(
            user_id=user.id,
            room_id=room.id,
            start_time=(fixed_time + timedelta(days=1)).isoformat(),
            end_time=(fixed_time + timedelta(days=1, hours=9)).isoformat(),
            status=RoomBookingStatus.RESERVED,
        )
        with global_lock():
            room_booking_repo.add(eligible)
            room_booking_repo.add(ineligible)

        menu = self._make_menu(
            user,
            auth_service,
            room_service,
            equipment_service,
            penalty_service,
            policy_service,
        )

        captured = self._capture_menu_items(monkeypatch)

        menu._request_room_checkin()

        assert [item[0] for item in captured["items"]] == [eligible.id]

    def test_room_checkin_shows_empty_state_when_no_booking_is_requestable_now(
        self,
        monkeypatch,
        fake_clock,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        room_booking_factory,
    ):
        fixed_time = datetime(2026, 4, 15, 9, 0, 0)
        fake_clock(fixed_time)
        user = create_test_user(username="room_ckin_empty")
        room = create_test_room(name="회의실2C")

        future_booking = room_booking_factory(
            user_id=user.id,
            room_id=room.id,
            start_time=(fixed_time + timedelta(days=1)).isoformat(),
            end_time=(fixed_time + timedelta(days=1, hours=9)).isoformat(),
            status=RoomBookingStatus.RESERVED,
        )
        with global_lock():
            room_booking_repo.add(future_booking)

        menu = self._make_menu(
            user,
            auth_service,
            room_service,
            equipment_service,
            penalty_service,
            policy_service,
        )

        messages = self._capture_empty_state(monkeypatch)

        menu._request_room_checkin()

        assert messages == ["체크인 요청 가능한 회의실 예약이 없습니다."]

    def test_room_checkout_lists_only_currently_requestable_bookings(
        self,
        monkeypatch,
        fake_clock,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        room_booking_factory,
    ):
        fixed_time = datetime(2026, 4, 15, 18, 0, 0)
        fake_clock(fixed_time)
        user = create_test_user(username="room_ckout_user")
        room = create_test_room(name="회의실2B")

        eligible = room_booking_factory(
            user_id=user.id,
            room_id=room.id,
            start_time=fixed_time.replace(hour=9).isoformat(),
            end_time=fixed_time.isoformat(),
            status=RoomBookingStatus.CHECKED_IN,
        )
        ineligible = room_booking_factory(
            user_id=user.id,
            room_id=room.id,
            start_time=fixed_time.replace(hour=9).isoformat(),
            end_time=(fixed_time + timedelta(days=1)).isoformat(),
            status=RoomBookingStatus.CHECKED_IN,
        )
        with global_lock():
            room_booking_repo.add(eligible)
            room_booking_repo.add(ineligible)

        menu = self._make_menu(
            user,
            auth_service,
            room_service,
            equipment_service,
            penalty_service,
            policy_service,
        )

        captured = self._capture_menu_items(monkeypatch)

        menu._request_room_checkout()

        assert [item[0] for item in captured["items"]] == [eligible.id]

    def test_room_checkout_shows_empty_state_when_no_booking_is_requestable_now(
        self,
        monkeypatch,
        fake_clock,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        room_booking_factory,
    ):
        fixed_time = datetime(2026, 4, 15, 18, 0, 0)
        fake_clock(fixed_time)
        user = create_test_user(username="room_ckout_empty")
        room = create_test_room(name="회의실2D")

        not_yet_due = room_booking_factory(
            user_id=user.id,
            room_id=room.id,
            start_time=fixed_time.replace(hour=9).isoformat(),
            end_time=(fixed_time + timedelta(days=1)).isoformat(),
            status=RoomBookingStatus.CHECKED_IN,
        )
        with global_lock():
            room_booking_repo.add(not_yet_due)

        menu = self._make_menu(
            user,
            auth_service,
            room_service,
            equipment_service,
            penalty_service,
            policy_service,
        )

        messages = self._capture_empty_state(monkeypatch)

        menu._request_room_checkout()

        assert messages == ["퇴실 신청 가능한 회의실 예약이 없습니다."]

    def test_equipment_pickup_lists_only_currently_requestable_bookings(
        self,
        monkeypatch,
        fake_clock,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        create_test_equipment,
        equipment_booking_repo,
        equipment_booking_factory,
    ):
        fixed_time = datetime(2026, 4, 15, 9, 0, 0)
        fake_clock(fixed_time)
        user = create_test_user(username="equip_pickup_usr")
        equipment = create_test_equipment(name="프로젝터A")

        eligible = equipment_booking_factory(
            user_id=user.id,
            equipment_id=equipment.id,
            start_time=fixed_time.isoformat(),
            end_time=fixed_time.replace(hour=18).isoformat(),
            status=EquipmentBookingStatus.RESERVED,
        )
        ineligible = equipment_booking_factory(
            user_id=user.id,
            equipment_id=equipment.id,
            start_time=(fixed_time + timedelta(days=1)).isoformat(),
            end_time=(fixed_time + timedelta(days=1, hours=9)).isoformat(),
            status=EquipmentBookingStatus.RESERVED,
        )
        with global_lock():
            equipment_booking_repo.add(eligible)
            equipment_booking_repo.add(ineligible)

        menu = self._make_menu(
            user,
            auth_service,
            room_service,
            equipment_service,
            penalty_service,
            policy_service,
        )

        captured = self._capture_menu_items(monkeypatch)

        menu._request_equipment_pickup()

        assert [item[0] for item in captured["items"]] == [eligible.id]

    def test_equipment_pickup_shows_empty_state_when_no_booking_is_requestable_now(
        self,
        monkeypatch,
        fake_clock,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        create_test_equipment,
        equipment_booking_repo,
        equipment_booking_factory,
    ):
        fixed_time = datetime(2026, 4, 15, 9, 0, 0)
        fake_clock(fixed_time)
        user = create_test_user(username="equip_pickup_emp")
        equipment = create_test_equipment(name="프로젝터B")

        future_booking = equipment_booking_factory(
            user_id=user.id,
            equipment_id=equipment.id,
            start_time=(fixed_time + timedelta(days=1)).isoformat(),
            end_time=(fixed_time + timedelta(days=1, hours=9)).isoformat(),
            status=EquipmentBookingStatus.RESERVED,
        )
        with global_lock():
            equipment_booking_repo.add(future_booking)

        menu = self._make_menu(
            user,
            auth_service,
            room_service,
            equipment_service,
            penalty_service,
            policy_service,
        )

        messages = self._capture_empty_state(monkeypatch)

        menu._request_equipment_pickup()

        assert messages == ["픽업 요청 가능한 장비 예약이 없습니다."]

    def test_equipment_return_lists_only_currently_requestable_bookings(
        self,
        monkeypatch,
        fake_clock,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        create_test_equipment,
        equipment_booking_repo,
        equipment_booking_factory,
    ):
        fixed_time = datetime(2026, 4, 15, 18, 0, 0)
        fake_clock(fixed_time)
        user = create_test_user(username="equip_return_usr")
        equipment = create_test_equipment(name="노트북A")

        eligible = equipment_booking_factory(
            user_id=user.id,
            equipment_id=equipment.id,
            start_time=fixed_time.replace(hour=9).isoformat(),
            end_time=fixed_time.isoformat(),
            status=EquipmentBookingStatus.CHECKED_OUT,
        )
        ineligible = equipment_booking_factory(
            user_id=user.id,
            equipment_id=equipment.id,
            start_time=fixed_time.replace(hour=9).isoformat(),
            end_time=(fixed_time + timedelta(days=1)).isoformat(),
            status=EquipmentBookingStatus.CHECKED_OUT,
        )
        with global_lock():
            equipment_booking_repo.add(eligible)
            equipment_booking_repo.add(ineligible)

        menu = self._make_menu(
            user,
            auth_service,
            room_service,
            equipment_service,
            penalty_service,
            policy_service,
        )

        captured = self._capture_menu_items(monkeypatch)

        menu._request_equipment_return()

        assert [item[0] for item in captured["items"]] == [eligible.id]

    def test_equipment_return_shows_empty_state_when_no_booking_is_requestable_now(
        self,
        monkeypatch,
        fake_clock,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        create_test_equipment,
        equipment_booking_repo,
        equipment_booking_factory,
    ):
        fixed_time = datetime(2026, 4, 15, 18, 0, 0)
        fake_clock(fixed_time)
        user = create_test_user(username="equip_return_emp")
        equipment = create_test_equipment(name="노트북B")

        not_yet_due = equipment_booking_factory(
            user_id=user.id,
            equipment_id=equipment.id,
            start_time=fixed_time.replace(hour=9).isoformat(),
            end_time=(fixed_time + timedelta(days=1)).isoformat(),
            status=EquipmentBookingStatus.CHECKED_OUT,
        )
        with global_lock():
            equipment_booking_repo.add(not_yet_due)

        menu = self._make_menu(
            user,
            auth_service,
            room_service,
            equipment_service,
            penalty_service,
            policy_service,
        )

        messages = self._capture_empty_state(monkeypatch)

        menu._request_equipment_return()

        assert messages == ["반납 신청 가능한 장비 예약이 없습니다."]


class TestCancellationWarnings:
    def test_room_cancel_warns_before_final_confirmation(
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
        booking = SimpleNamespace(
            id="room-booking-1",
            room_id="room-1",
            start_time="2026-04-16T09:00",
            end_time="2026-04-16T18:00",
            status=RoomBookingStatus.RESERVED,
        )

        monkeypatch.setattr(menu, "_run_policy_checks", lambda: True)
        monkeypatch.setattr(menu, "_refresh_user", lambda: True)
        monkeypatch.setattr(menu.room_service, "get_user_bookings", lambda _user_id: [booking])
        monkeypatch.setattr(menu.room_service, "get_room", lambda _room_id: type("Room", (), {"name": "회의실 A"})())
        monkeypatch.setattr(menu.room_service, "will_apply_late_cancel_penalty", lambda _user, _booking_id: True)
        monkeypatch.setattr(menu.room_service, "cancel_booking", lambda _user, _booking_id: (booking, True))
        monkeypatch.setattr("src.cli.user_menu.select_from_list", lambda items, prompt: booking.id)
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.print_success", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.print_info", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.print_error", lambda *_: None)

        call_order = []
        monkeypatch.setattr(
            "src.cli.user_menu.print_warning",
            lambda msg: call_order.append(("warning", msg)),
        )
        monkeypatch.setattr(
            "src.cli.user_menu.confirm",
            lambda msg: call_order.append(("confirm", msg)) or True,
        )

        menu._cancel_room_booking()

        assert call_order[0][0] == "warning"
        assert call_order[1][0] == "confirm"

    def test_equipment_cancel_warns_before_final_confirmation(
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
        booking = SimpleNamespace(
            id="equipment-booking-1",
            equipment_id="equipment-1",
            start_time="2026-04-16T09:00",
            end_time="2026-04-16T18:00",
            status=EquipmentBookingStatus.RESERVED,
        )

        monkeypatch.setattr(menu, "_run_policy_checks", lambda: True)
        monkeypatch.setattr(menu, "_refresh_user", lambda: True)
        monkeypatch.setattr(menu.equipment_service, "get_user_bookings", lambda _user_id: [booking])
        monkeypatch.setattr(menu.equipment_service, "get_equipment", lambda _equipment_id: type("Equipment", (), {"name": "노트북 A"})())
        monkeypatch.setattr(menu.equipment_service, "will_apply_late_cancel_penalty", lambda _user, _booking_id: True)
        monkeypatch.setattr(menu.equipment_service, "cancel_booking", lambda _user, _booking_id: (booking, True))
        monkeypatch.setattr("src.cli.user_menu.select_from_list", lambda items, prompt: booking.id)
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.print_success", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.print_info", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.print_error", lambda *_: None)

        call_order = []
        monkeypatch.setattr(
            "src.cli.user_menu.print_warning",
            lambda msg: call_order.append(("warning", msg)),
        )
        monkeypatch.setattr(
            "src.cli.user_menu.confirm",
            lambda msg: call_order.append(("confirm", msg)) or True,
        )

        menu._cancel_equipment_booking()

        assert call_order[0][0] == "warning"
        assert call_order[1][0] == "confirm"
