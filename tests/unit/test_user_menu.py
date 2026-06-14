from datetime import datetime, timedelta
from types import SimpleNamespace

from src.cli.user_menu import UserMenu
from src.domain.models import (
    EquipmentBookingStatus,
    ResourceStatus,
    RoomBookingStatus,
    WaitingListEntry,
)
from src.domain.penalty_service import CancelRestrictionSummary, PenaltyError
from src.storage.file_lock import global_lock
from src.storage.repositories import WaitingListRepository


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
            lambda **_kwargs: (_ for _ in ()).throw(PenaltyError("존재하지 않는 사용자입니다.")),
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

    def test_inspect1_show_my_status_prints_cancel_restrictions_and_30_day_counts(
        self,
        monkeypatch,
        capsys,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
    ):
        user = create_test_user(
            username="InspectStatusUser",
            room_cancel_restricted_until="2024-07-15T09:00",
            equipment_cancel_restricted_until="2024-07-16T09:00",
        )
        menu = UserMenu(
            user=user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )
        monkeypatch.setattr(menu, "_refresh_user", lambda: True)
        monkeypatch.setattr(
            menu.penalty_service,
            "get_user_status",
            lambda _user: {
                "points": 0,
                "is_banned": False,
                "is_restricted": False,
                "normal_use_streak": 0,
                "restriction_until": None,
            },
        )
        monkeypatch.setattr(menu.room_service, "get_user_active_bookings", lambda _user_id: [])
        monkeypatch.setattr(menu.equipment_service, "get_user_active_bookings", lambda _user_id: [])
        monkeypatch.setattr(menu.room_service, "get_user_bookings", lambda _user_id: [])
        monkeypatch.setattr(menu.equipment_service, "get_user_bookings", lambda _user_id: [])
        monkeypatch.setattr(
            menu.penalty_service,
            "get_cancel_restriction_summary",
            lambda _user, _room_bookings, _equipment_bookings: CancelRestrictionSummary(
                room_cancel_count_30d=2,
                equipment_cancel_count_30d=1,
                max_cancel_count=3,
                room_cancel_restricted_until="2024-07-15T09:00",
                equipment_cancel_restricted_until="2024-07-16T09:00",
            ),
        )
        monkeypatch.setattr(menu.penalty_service, "get_user_penalties", lambda _user_id: [])
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)

        menu._show_my_status()

        output = capsys.readouterr().out
        assert "패널티 상태" in output
        assert "취소 제한 현황" in output
        assert "회의실 직접 취소: 2/3건" in output
        assert "장비 직접 취소: 1/3건" in output
        assert "회의실 신규 예약 제한 해제일: 2024-07-15" in output
        assert "장비 신규 예약 제한 해제일: 2024-07-16" in output
        assert "활성 예약" in output

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


class TestUserMenuRoomHistoryDisplay:
    def test_room_history_shows_empty_state_with_zero_return(
        self,
        monkeypatch,
        capsys,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
    ):
        user = create_test_user(username="RoomHistoryEmpty1")
        menu = UserMenu(
            user=user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr("src.cli.user_menu.print_header", lambda title: print(title))
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: print("0. 돌아가기"))

        menu._show_my_room_bookings()

        output = capsys.readouterr().out
        assert "내 회의실 예약" in output
        assert "예약 내역이 없습니다." in output
        assert "0. 돌아가기" in output

    def test_room_history_sorts_caps_overflow_and_displays_only_present_memos(
        self,
        monkeypatch,
        capsys,
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
        user = create_test_user(username="RoomHistoryUser1")
        room = create_test_room(name="회의실6A")
        base_time = datetime(2026, 7, 1, 9, 0, 0)
        bookings = []
        with global_lock():
            for index in range(21):
                start_time = base_time + timedelta(days=index)
                booking = room_booking_factory(
                    id=f"ur06-{index:02d}-booking",
                    user_id=user.id,
                    room_id=room.id,
                    start_time=start_time.isoformat(),
                    end_time=start_time.replace(hour=18).isoformat(),
                    status=RoomBookingStatus.RESERVED,
                    memo="팀 주간 회의" if index == 20 else "",
                )
                room_booking_repo.add(booking)
                bookings.append(booking)

        before_rows = [booking.id for booking in room_booking_repo.get_all()]
        menu = UserMenu(
            user=user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr("src.cli.user_menu.print_header", lambda title: print(title))
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: print("0. 돌아가기"))

        menu._show_my_room_bookings()

        output = capsys.readouterr().out
        after_rows = [booking.id for booking in room_booking_repo.get_all()]
        assert before_rows == after_rows
        assert output.index("ur06-20-") < output.index("ur06-19-")
        assert "ur06-00-" not in output
        assert "... 외 1건" in output
        assert "메모: 팀 주간 회의" in output
        assert "메모: -" not in output
        assert "0. 돌아가기" in output


class TestUserMenuEquipmentListDisplay:
    def test_equipment_list_shows_empty_state_with_zero_return(
        self,
        monkeypatch,
        capsys,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
    ):
        user = create_test_user(username="EquipListEmpty1")
        menu = UserMenu(
            user=user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr("src.cli.user_menu.print_header", lambda title: print(title))
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: print("0. 돌아가기"))

        menu._show_equipment()

        output = capsys.readouterr().out
        assert "장비 목록" in output
        assert "등록된 장비가 없습니다." in output
        assert "0. 돌아가기" in output

    def test_equipment_list_sorts_by_seed_type_order_labels_status_and_preserves_rows(
        self,
        monkeypatch,
        capsys,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        create_test_equipment,
        equipment_repo,
    ):
        user = create_test_user(username="EquipListUser1")
        for name, asset_type, serial_number, status in [
            ("웹캠1", "webcam", "WC-001", ResourceStatus.AVAILABLE),
            ("노트북3", "laptop", "NB-003", ResourceStatus.DISABLED),
            ("케이블1", "cable", "CB-001", ResourceStatus.AVAILABLE),
            ("프로젝터3", "projector", "PJ-003", ResourceStatus.MAINTENANCE),
            ("프로젝터1", "projector", "PJ-001", ResourceStatus.AVAILABLE),
            ("노트북1", "laptop", "NB-001", ResourceStatus.AVAILABLE),
        ]:
            create_test_equipment(
                name=name,
                asset_type=asset_type,
                serial_number=serial_number,
                status=status,
            )
        before_rows = [equipment.to_record() for equipment in equipment_repo.get_all()]
        menu = UserMenu(
            user=user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr("src.cli.user_menu.print_header", lambda title: print(title))
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: print("0. 돌아가기"))

        menu._show_equipment()

        output = capsys.readouterr().out
        after_rows = [equipment.to_record() for equipment in equipment_repo.get_all()]
        assert before_rows == after_rows
        assert output.index("프로젝터1") < output.index("프로젝터3")
        assert output.index("프로젝터3") < output.index("노트북1")
        assert output.index("노트북1") < output.index("노트북3")
        assert output.index("노트북3") < output.index("케이블1")
        assert output.index("케이블1") < output.index("웹캠1")
        assert "이름" in output
        assert "종류" in output
        assert "시리얼번호" in output
        assert "상태" in output
        assert "[사용가능]" in output
        assert "[점검중]" in output
        assert "[사용불가]" in output
        assert "0. 돌아가기" in output


class TestUserMenuEquipmentHistoryDisplay:
    def test_equipment_history_shows_empty_state_with_zero_return(
        self,
        monkeypatch,
        capsys,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
    ):
        user = create_test_user(username="EquipHistoryEmpty1")
        menu = UserMenu(
            user=user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr("src.cli.user_menu.print_header", lambda title: print(title))
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: print("0. 돌아가기"))

        menu._show_my_equipment_bookings()

        output = capsys.readouterr().out
        assert "내 장비 예약" in output
        assert "예약 내역이 없습니다." in output
        assert "0. 돌아가기" in output

    def test_equipment_history_collapses_group_statuses_memos_and_preserves_rows(
        self,
        monkeypatch,
        capsys,
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
        user = create_test_user(username="EquipHistoryUser1")
        assets = [
            create_test_equipment(name="케이블A", asset_type="cable", serial_number="CB-001"),
            create_test_equipment(name="노트북A", asset_type="laptop", serial_number="NB-001"),
            create_test_equipment(name="프로젝터A", asset_type="projector", serial_number="PJ-001"),
            create_test_equipment(name="웹캠A", asset_type="webcam", serial_number="WC-001"),
            create_test_equipment(name="노트북B", asset_type="laptop", serial_number="NB-002"),
            create_test_equipment(name="케이블B", asset_type="cable", serial_number="CB-002"),
            create_test_equipment(name="프로젝터B", asset_type="projector", serial_number="PJ-002"),
            create_test_equipment(name="웹캠B", asset_type="webcam", serial_number="WC-002"),
        ]
        base_time = datetime(2026, 8, 1, 9, 0, 0)
        statuses = [
            EquipmentBookingStatus.PENDING,
            EquipmentBookingStatus.RESERVED,
            EquipmentBookingStatus.PICKUP_REQUESTED,
            EquipmentBookingStatus.CHECKED_OUT,
            EquipmentBookingStatus.RETURN_REQUESTED,
            EquipmentBookingStatus.RETURNED,
            EquipmentBookingStatus.CANCELLED,
            EquipmentBookingStatus.ADMIN_CANCELLED,
        ]
        group_id = "ue06-group-1"
        with global_lock():
            for index, status in enumerate(statuses):
                start_time = base_time + timedelta(days=index)
                equipment_booking_repo.add(
                    equipment_booking_factory(
                        id=f"ue06-status-{index}",
                        user_id=user.id,
                        equipment_id=assets[index].id,
                        start_time=start_time.isoformat(),
                        end_time=start_time.replace(hour=18).isoformat(),
                        status=status,
                        memo="발표 준비" if status == EquipmentBookingStatus.RESERVED else "",
                    )
                )
            group_start = base_time + timedelta(days=20)
            equipment_booking_repo.add(
                equipment_booking_factory(
                    id="ue06-group-laptop",
                    user_id=user.id,
                    equipment_id=assets[1].id,
                    start_time=group_start.isoformat(),
                    end_time=group_start.replace(hour=18).isoformat(),
                    status=EquipmentBookingStatus.RESERVED,
                    group_id=group_id,
                    memo="묶음 메모",
                )
            )
            equipment_booking_repo.add(
                equipment_booking_factory(
                    id="ue06-group-cable",
                    user_id=user.id,
                    equipment_id=assets[0].id,
                    start_time=group_start.isoformat(),
                    end_time=group_start.replace(hour=18).isoformat(),
                    status=EquipmentBookingStatus.RESERVED,
                    group_id=group_id,
                    memo="묶음 메모",
                )
            )

        before_rows = [booking.id for booking in equipment_booking_repo.get_all()]
        menu = UserMenu(
            user=user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        monkeypatch.setattr("src.cli.user_menu.print_header", lambda title: print(title))
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: print("0. 돌아가기"))

        menu._show_my_equipment_bookings()

        output = capsys.readouterr().out
        after_rows = [booking.id for booking in equipment_booking_repo.get_all()]
        assert before_rows == after_rows
        assert output.count("[묶음]") == 1
        assert "ue06-group-laptop" not in output
        assert "ue06-group-cable" not in output
        assert output.index("케이블A") < output.index("노트북A")
        assert "[예약 대기중]" in output
        for label in [
            "[예약됨]",
            "[픽업요청]",
            "[대여중]",
            "[반납승인대기]",
            "[반납완료]",
            "[취소]",
            "[관리자취소]",
        ]:
            assert label in output
        assert "메모: 발표 준비" in output
        assert "메모: 묶음 메모" in output
        assert "메모: -" not in output
        assert "0. 돌아가기" in output


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
        user = create_test_user(username="RoomCkinUser1")
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
        user = create_test_user(username="RoomCkinEmpty1")
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

    def test_room_checkout_lists_all_checked_in_bookings_for_early_checkout(
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
        user = create_test_user(username="RoomCkoutUser1")
        room = create_test_room(name="회의실2B")

        ending_now = room_booking_factory(
            user_id=user.id,
            room_id=room.id,
            start_time=fixed_time.replace(hour=9).isoformat(),
            end_time=fixed_time.isoformat(),
            status=RoomBookingStatus.CHECKED_IN,
        )
        early_checkout = room_booking_factory(
            user_id=user.id,
            room_id=room.id,
            start_time=fixed_time.replace(hour=9).isoformat(),
            end_time=(fixed_time + timedelta(days=1)).isoformat(),
            status=RoomBookingStatus.CHECKED_IN,
        )
        already_requested = room_booking_factory(
            user_id=user.id,
            room_id=room.id,
            start_time=fixed_time.replace(hour=9).isoformat(),
            end_time=fixed_time.isoformat(),
            status=RoomBookingStatus.CHECKOUT_REQUESTED,
        )
        with global_lock():
            room_booking_repo.add(ending_now)
            room_booking_repo.add(early_checkout)
            room_booking_repo.add(already_requested)

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

        assert [item[0] for item in captured["items"]] == [ending_now.id, early_checkout.id]

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
        user = create_test_user(username="RoomCkoutEmpty1")
        room = create_test_room(name="회의실2D")

        already_requested = room_booking_factory(
            user_id=user.id,
            room_id=room.id,
            start_time=fixed_time.replace(hour=9).isoformat(),
            end_time=(fixed_time + timedelta(days=1)).isoformat(),
            status=RoomBookingStatus.CHECKOUT_REQUESTED,
        )
        with global_lock():
            room_booking_repo.add(already_requested)

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

    def test_room_checkout_review_cancel_leaves_booking_unchanged(
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
        user = create_test_user(username="RoomCkoutCancel1")
        room = create_test_room(name="회의실2E")
        booking = room_booking_factory(
            user_id=user.id,
            room_id=room.id,
            start_time=fixed_time.isoformat(),
            end_time=fixed_time.replace(hour=18).isoformat(),
            status=RoomBookingStatus.CHECKED_IN,
        )
        with global_lock():
            room_booking_repo.add(booking)

        menu = self._make_menu(
            user,
            auth_service,
            room_service,
            equipment_service,
            penalty_service,
            policy_service,
        )

        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.select_from_list", lambda _items, _prompt: booking.id)
        monkeypatch.setattr("src.cli.user_menu.review_action", lambda *_args, **_kwargs: "cancel")
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)

        menu._request_room_checkout()

        unchanged = room_booking_repo.get_by_id(booking.id)
        assert unchanged.status == RoomBookingStatus.CHECKED_IN
        assert unchanged.requested_checkout_at is None

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
        user = create_test_user(username="EquipPickupUser1")
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
        user = create_test_user(username="EquipPickupEmpty1")
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

    def test_equipment_pickup_collapses_group_booking_in_request_list(
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
        user = create_test_user(username="EquipPickupGroup1")
        later_serial = create_test_equipment(
            name="노트북A", asset_type="laptop", serial_number="NB-002"
        )
        earlier_serial = create_test_equipment(
            name="케이블A", asset_type="cable", serial_number="CB-001"
        )
        group_id = "ue09-pickup-group"
        with global_lock():
            equipment_booking_repo.add(
                equipment_booking_factory(
                    id="ue09-pickup-group-1",
                    user_id=user.id,
                    equipment_id=later_serial.id,
                    start_time=fixed_time.isoformat(),
                    end_time=fixed_time.replace(hour=18).isoformat(),
                    status=EquipmentBookingStatus.RESERVED,
                    group_id=group_id,
                )
            )
            equipment_booking_repo.add(
                equipment_booking_factory(
                    id="ue09-pickup-group-2",
                    user_id=user.id,
                    equipment_id=earlier_serial.id,
                    start_time=fixed_time.isoformat(),
                    end_time=fixed_time.replace(hour=18).isoformat(),
                    status=EquipmentBookingStatus.RESERVED,
                    group_id=group_id,
                )
            )

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

        assert len(captured["items"]) == 1
        assert captured["items"][0][0] == "ue09-pickup-group-1"
        label = captured["items"][0][1]
        assert "[묶음]" in label
        assert label.index("케이블A") < label.index("노트북A")
        assert "CB-001" in label
        assert "NB-002" in label

    def test_equipment_return_lists_all_checked_out_bookings_for_early_return(
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
        user = create_test_user(username="EquipReturnUser1")
        equipment = create_test_equipment(name="노트북A")

        ending_now = equipment_booking_factory(
            user_id=user.id,
            equipment_id=equipment.id,
            start_time=fixed_time.replace(hour=9).isoformat(),
            end_time=fixed_time.isoformat(),
            status=EquipmentBookingStatus.CHECKED_OUT,
        )
        early_return = equipment_booking_factory(
            user_id=user.id,
            equipment_id=equipment.id,
            start_time=fixed_time.replace(hour=9).isoformat(),
            end_time=(fixed_time + timedelta(days=1)).isoformat(),
            status=EquipmentBookingStatus.CHECKED_OUT,
        )
        already_requested = equipment_booking_factory(
            user_id=user.id,
            equipment_id=equipment.id,
            start_time=fixed_time.replace(hour=9).isoformat(),
            end_time=fixed_time.isoformat(),
            status=EquipmentBookingStatus.RETURN_REQUESTED,
        )
        with global_lock():
            equipment_booking_repo.add(ending_now)
            equipment_booking_repo.add(early_return)
            equipment_booking_repo.add(already_requested)

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

        assert [item[0] for item in captured["items"]] == [ending_now.id, early_return.id]

    def test_equipment_return_collapses_group_booking_in_request_list(
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
        user = create_test_user(username="EquipReturnGroup1")
        later_serial = create_test_equipment(
            name="노트북B", asset_type="laptop", serial_number="NB-003"
        )
        earlier_serial = create_test_equipment(
            name="케이블B", asset_type="cable", serial_number="CB-002"
        )
        group_id = "ue09-return-group"
        with global_lock():
            equipment_booking_repo.add(
                equipment_booking_factory(
                    id="ue09-return-group-1",
                    user_id=user.id,
                    equipment_id=later_serial.id,
                    start_time=fixed_time.isoformat(),
                    end_time=fixed_time.replace(hour=18).isoformat(),
                    status=EquipmentBookingStatus.CHECKED_OUT,
                    group_id=group_id,
                )
            )
            equipment_booking_repo.add(
                equipment_booking_factory(
                    id="ue09-return-group-2",
                    user_id=user.id,
                    equipment_id=earlier_serial.id,
                    start_time=fixed_time.isoformat(),
                    end_time=fixed_time.replace(hour=18).isoformat(),
                    status=EquipmentBookingStatus.CHECKED_OUT,
                    group_id=group_id,
                )
            )

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

        assert len(captured["items"]) == 1
        assert captured["items"][0][0] == "ue09-return-group-1"
        label = captured["items"][0][1]
        assert "[묶음]" in label
        assert label.index("케이블B") < label.index("노트북B")
        assert "CB-002" in label
        assert "NB-003" in label

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
        user = create_test_user(username="EquipReturnEmpty1")
        equipment = create_test_equipment(name="노트북B")

        already_requested = equipment_booking_factory(
            user_id=user.id,
            equipment_id=equipment.id,
            start_time=fixed_time.replace(hour=9).isoformat(),
            end_time=(fixed_time + timedelta(days=1)).isoformat(),
            status=EquipmentBookingStatus.RETURN_REQUESTED,
        )
        with global_lock():
            equipment_booking_repo.add(already_requested)

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

    def test_equipment_return_review_cancel_leaves_booking_unchanged(
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
        user = create_test_user(username="EquipReturnCancel1")
        equipment = create_test_equipment(name="노트북C")
        booking = equipment_booking_factory(
            user_id=user.id,
            equipment_id=equipment.id,
            start_time=fixed_time.isoformat(),
            end_time=fixed_time.replace(hour=18).isoformat(),
            status=EquipmentBookingStatus.CHECKED_OUT,
        )
        with global_lock():
            equipment_booking_repo.add(booking)

        menu = self._make_menu(
            user,
            auth_service,
            room_service,
            equipment_service,
            penalty_service,
            policy_service,
        )

        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.select_from_list", lambda _items, _prompt: booking.id)
        monkeypatch.setattr("src.cli.user_menu.review_action", lambda *_args, **_kwargs: "cancel")
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)

        menu._request_equipment_return()

        unchanged = equipment_booking_repo.get_by_id(booking.id)
        assert unchanged.status == EquipmentBookingStatus.CHECKED_OUT
        assert unchanged.requested_return_at is None


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
        impact = SimpleNamespace(
            is_late_cancel=True,
            applies_cancel_restriction=False,
            cancel_restriction_until=None,
            applies_frequent_cancel_penalty=False,
            total_penalty_points=2,
            penalty_reasons=("late_cancel",),
        )
        monkeypatch.setattr(menu.room_service, "preview_cancel_booking_impact", lambda _user, _booking_id: impact)
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
            "src.cli.user_menu.review_action",
            lambda title, action_label="저장/처리": call_order.append(("review", title)) or "confirm",
        )

        menu._cancel_room_booking()

        assert call_order[0][0] == "warning"
        assert call_order[1][0] == "review"

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
        impact = SimpleNamespace(
            is_late_cancel=True,
            applies_cancel_restriction=False,
            cancel_restriction_until=None,
            applies_frequent_cancel_penalty=False,
            total_penalty_points=2,
            penalty_reasons=("late_cancel",),
        )
        monkeypatch.setattr(menu.equipment_service, "preview_cancel_booking_impact", lambda _user, _booking_id: impact)
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
            "src.cli.user_menu.review_action",
            lambda title, action_label="저장/처리": call_order.append(("review", title)) or "confirm",
        )

        menu._cancel_equipment_booking()

        assert call_order[0][0] == "warning"
        assert call_order[1][0] == "review"


class TestUserMenuCancelPreview:
    def test_room_cancel_review_retry_then_cancel_never_writes(
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
            id="room-booking-review-1",
            room_id="room-1",
            start_time="2026-04-16T09:00",
            end_time="2026-04-16T18:00",
            status=RoomBookingStatus.RESERVED,
        )
        impact = SimpleNamespace(
            is_late_cancel=False,
            applies_cancel_restriction=False,
            cancel_restriction_until=None,
            applies_frequent_cancel_penalty=False,
            total_penalty_points=0,
            penalty_reasons=(),
        )
        decisions = iter(["retry", "cancel"])
        selections = []

        monkeypatch.setattr(menu, "_run_policy_checks", lambda: True)
        monkeypatch.setattr(menu, "_refresh_user", lambda: True)
        monkeypatch.setattr(menu.room_service, "get_user_bookings", lambda _user_id: [booking])
        monkeypatch.setattr(menu.room_service, "get_room", lambda _room_id: type("Room", (), {"name": "회의실 A"})())
        monkeypatch.setattr(menu.room_service, "preview_cancel_booking_impact", lambda _user, _booking_id: impact)
        monkeypatch.setattr(
            menu.room_service,
            "cancel_booking",
            lambda *_args: (_ for _ in ()).throw(AssertionError("cancel_booking should not run")),
        )
        monkeypatch.setattr("src.cli.user_menu.select_from_list", lambda _items, _prompt: selections.append(booking.id) or booking.id)
        monkeypatch.setattr("src.cli.user_menu.review_action", lambda *_args, **_kwargs: next(decisions))
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)

        menu._cancel_room_booking()

        assert selections == [booking.id, booking.id]

    def test_room_cancel_preview_confirm_no_leaves_booking_and_penalties_unchanged(
        self,
        monkeypatch,
        capsys,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        room_booking_factory,
        penalty_repo,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 8, 30, 0)
        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room()
            booking = room_booking_factory(
                user_id=user.id,
                room_id=room.id,
                start_time=datetime(2024, 6, 15, 9, 0, 0).isoformat(),
                end_time=datetime(2024, 6, 15, 18, 0, 0).isoformat(),
                status=RoomBookingStatus.RESERVED,
            )
            with global_lock():
                room_booking_repo.add(booking)

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
            monkeypatch.setattr("src.cli.user_menu.select_from_list", lambda _items, _prompt: booking.id)
            monkeypatch.setattr("src.cli.user_menu.review_action", lambda *_args, **_kwargs: "cancel")
            monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)

            menu._cancel_room_booking()

        output = capsys.readouterr().out
        assert "취소 영향 미리보기" in output
        assert "직전 취소 패널티 2점" in output
        assert "예약 취소를 취소했습니다." in output
        assert room_booking_repo.get_by_id(booking.id).status == RoomBookingStatus.RESERVED
        assert penalty_repo.get_all() == []

    def test_user_menu_invalid_inputs_loop_until_zero_without_mutation(
        self,
        monkeypatch,
        capsys,
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
        inputs = iter(["", "abc", "99", "0"])

        monkeypatch.setattr(menu, "_run_policy_checks", lambda: True)
        monkeypatch.setattr(menu, "_refresh_user", lambda: True)
        monkeypatch.setattr(menu.penalty_service, "get_user_status", lambda _user: {})
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
        monkeypatch.setattr("src.cli.user_menu.confirm", lambda _message: True)
        monkeypatch.setattr("src.cli.user_menu.print_success", lambda message: print(message))

        result = menu.run()

        output = capsys.readouterr().out
        assert result is True
        assert output.count("잘못된 선택입니다.") == 3
        assert "로그아웃 되었습니다." in output


class TestUserMenuGroupBookingTask12:
    def test_equipment_booking_cli_hides_confirmed_conflicts_before_selection(
        self,
        monkeypatch,
        capsys,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        create_test_equipment,
        mock_now,
    ):
        from datetime import date

        fixed_time = datetime(2024, 6, 15, 8, 0, 0)
        with mock_now(fixed_time):
            owner = create_test_user(username="InspectCliOwner")
            user = create_test_user(username="InspectCliGroup")
            first = create_test_equipment(name="노트북A", asset_type="laptop", serial_number="NB-001")
            second = create_test_equipment(name="웹캠A", asset_type="webcam", serial_number="WC-001")
            equipment_service.create_booking(
                owner,
                first.id,
                fixed_time + timedelta(days=1),
                fixed_time + timedelta(days=1, hours=9),
            )
            menu = UserMenu(
                user=user,
                auth_service=auth_service,
                room_service=room_service,
                equipment_service=equipment_service,
                penalty_service=penalty_service,
                policy_service=policy_service,
            )
            inputs = iter(["1", "웹캠예약"])

            monkeypatch.setattr(menu, "_run_policy_checks", lambda: True)
            monkeypatch.setattr(menu, "_refresh_user", lambda: True)
            monkeypatch.setattr(menu.policy_service, "check_user_can_book", lambda _user: (True, 2, ""))
            monkeypatch.setattr(menu.policy_service, "get_user_flow_limits", lambda _user: {"equipment_limit": 2})
            monkeypatch.setattr("src.cli.user_menu.get_daily_date_range_input", lambda *_args: (date(2024, 6, 16), date(2024, 6, 16)))
            monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
            monkeypatch.setattr("src.cli.user_menu.input_start_gate", lambda _title: True)
            monkeypatch.setattr("src.cli.user_menu.review_action", lambda *_args, **_kwargs: "confirm")
            monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)
            monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
            monkeypatch.setattr(
                "src.cli.user_menu.select_from_list",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("type-first selection should not run")),
            )
            menu._create_equipment_booking()

        output = capsys.readouterr().out
        assert "노트북A" not in output
        assert "웹캠A" in output
        assert "예약 요청이 접수되었습니다." in output

    def test_equipment_booking_cli_reports_no_available_equipment_when_all_conflict(
        self,
        monkeypatch,
        capsys,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        create_test_equipment,
        mock_now,
    ):
        from datetime import date

        fixed_time = datetime(2024, 6, 15, 8, 0, 0)
        with mock_now(fixed_time):
            owner = create_test_user(username="AllConflictOwner")
            user = create_test_user(username="AllConflictRequester")
            first = create_test_equipment(name="노트북A", asset_type="laptop", serial_number="NB-001")
            equipment_service.create_booking(
                owner,
                first.id,
                fixed_time + timedelta(days=1),
                fixed_time + timedelta(days=1, hours=9),
            )
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
            monkeypatch.setattr(menu.policy_service, "check_user_can_book", lambda _user: (True, 2, ""))
            monkeypatch.setattr("src.cli.user_menu.get_daily_date_range_input", lambda *_args: (date(2024, 6, 16), date(2024, 6, 16)))
            monkeypatch.setattr("src.cli.user_menu.input_start_gate", lambda _title: True)
            monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)
            monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
            monkeypatch.setattr(
                "builtins.input",
                lambda _prompt="": (_ for _ in ()).throw(AssertionError("selection input should not run")),
            )

            menu._create_equipment_booking()

        output = capsys.readouterr().out
        assert "해당 기간에 예약 가능한 장비가 없습니다." in output

    def test_equipment_group_booking_uses_service_and_persists_memo(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        create_test_equipment,
        equipment_booking_repo,
        mock_now,
    ):
        from datetime import date

        fixed_time = datetime(2024, 6, 15, 8, 0, 0)
        with mock_now(fixed_time):
            user = create_test_user()
            first = create_test_equipment(name="노트북A", asset_type="laptop", serial_number="NB-001")
            second = create_test_equipment(name="웹캠A", asset_type="webcam", serial_number="WC-001")
            menu = UserMenu(
                user=user,
                auth_service=auth_service,
                room_service=room_service,
                equipment_service=equipment_service,
                penalty_service=penalty_service,
                policy_service=policy_service,
            )
            inputs = iter(["1 2", "수업 촬영"])

            monkeypatch.setattr(menu, "_run_policy_checks", lambda: True)
            monkeypatch.setattr(menu, "_refresh_user", lambda: True)
            monkeypatch.setattr(menu.policy_service, "check_user_can_book", lambda _user: (True, 2, ""))
            monkeypatch.setattr(menu.policy_service, "get_user_flow_limits", lambda _user: {"equipment_limit": 2})
            monkeypatch.setattr("src.cli.user_menu.get_daily_date_range_input", lambda *_args: (date(2024, 6, 16), date(2024, 6, 16)))
            monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
            monkeypatch.setattr("src.cli.user_menu.input_start_gate", lambda _title: True)
            monkeypatch.setattr("src.cli.user_menu.review_action", lambda *_args, **_kwargs: "confirm")
            monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)
            monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
            monkeypatch.setattr("src.cli.user_menu.print_success", lambda *_: None)
            monkeypatch.setattr("src.cli.user_menu.print_warning", lambda *_: None)
            monkeypatch.setattr("src.cli.user_menu.print_info", lambda *_: None)

            monkeypatch.setattr(
                "src.cli.user_menu.select_from_list",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("type-first selection should not run")),
            )
            menu._create_equipment_booking()

        bookings = equipment_booking_repo.get_by_user(user.id)
        assert len(bookings) == 2
        assert {booking.equipment_id for booking in bookings} == {first.id, second.id}
        assert {booking.memo for booking in bookings} == {"수업 촬영"}
        assert bookings[0].group_id == bookings[1].group_id

    def test_equipment_booking_review_retry_reenters_input_and_cancel_does_not_write(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        create_test_equipment,
        equipment_booking_repo,
        mock_now,
    ):
        from datetime import date

        fixed_time = datetime(2024, 6, 15, 8, 0, 0)
        with mock_now(fixed_time):
            user = create_test_user(username="RetryEquipmentUser")
            create_test_equipment(name="노트북A", asset_type="laptop", serial_number="NB-001")
            menu = UserMenu(
                user=user,
                auth_service=auth_service,
                room_service=room_service,
                equipment_service=equipment_service,
                penalty_service=penalty_service,
                policy_service=policy_service,
            )
            gate_titles = []
            date_calls = []
            inputs = iter(["1", "첫 입력", "1", "재입력 후 취소"])
            decisions = iter(["retry", "cancel"])

            monkeypatch.setattr(menu, "_run_policy_checks", lambda: True)
            monkeypatch.setattr(menu, "_refresh_user", lambda: True)
            monkeypatch.setattr(menu.policy_service, "check_user_can_book", lambda _user: (True, 2, ""))
            monkeypatch.setattr(
                "src.cli.user_menu.input_start_gate",
                lambda title: gate_titles.append(title) or True,
            )

            def get_dates(*_args):
                date_calls.append("called")
                return date(2024, 6, 16), date(2024, 6, 16)

            monkeypatch.setattr("src.cli.user_menu.get_daily_date_range_input", get_dates)
            monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
            monkeypatch.setattr("src.cli.user_menu.review_action", lambda *_args, **_kwargs: next(decisions))
            monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)
            monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
            monkeypatch.setattr("src.cli.user_menu.print_info", lambda *_: None)
            monkeypatch.setattr("src.cli.user_menu.print_warning", lambda *_: None)

            menu._create_equipment_booking()

        assert gate_titles == ["장비 예약 입력", "장비 예약 입력"]
        assert date_calls == ["called", "called"]
        assert equipment_booking_repo.get_by_user(user.id) == []


class TestUserMenuWaitlistTask8:
    def test_waitlist_start_gate_zero_returns_without_write(
        self,
        monkeypatch,
        capsys,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        temp_data_dir,
        create_test_user,
    ):
        user = create_test_user(username="WaitGateUser")
        waiting_list_repo = WaitingListRepository(file_path=temp_data_dir / "waiting_list.txt")
        menu = UserMenu(
            user=user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
            waiting_list_repo=waiting_list_repo,
        )
        inputs = iter(["0"])

        monkeypatch.setattr(menu, "_refresh_user", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

        menu._create_waiting_list_request()

        output = capsys.readouterr().out
        assert "대기 예약 신청 입력" in output
        assert "0. 돌아가기" in output
        assert "회의실" not in output
        assert waiting_list_repo.get_all() == []

    def test_waitlist_room_flow_validates_capacity_and_prints_sequence(
        self,
        monkeypatch,
        capsys,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        temp_data_dir,
        create_test_user,
        create_test_room,
        room_booking_repo,
        room_booking_factory,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)
        with mock_now(fixed_time):
            owner = create_test_user(username="WaitOwner1")
            user = create_test_user(username="WaitUser1")
            room = create_test_room(name="회의실4W", capacity=4)
            booking = room_booking_factory(
                user_id=owner.id,
                room_id=room.id,
                start_time=(fixed_time + timedelta(days=3)).isoformat(),
                end_time=(fixed_time + timedelta(days=3, hours=9)).isoformat(),
                status=RoomBookingStatus.RESERVED,
            )
            waiting_list_repo = WaitingListRepository(file_path=temp_data_dir / "waiting_list.txt")
            existing = WaitingListEntry(
                id="wait-earlier",
                username="EarlierUser",
                related_type="room_booking",
                related_id=booking.id,
                user_count=2,
                created_at="2024-06-15T08:00:00",
                updated_at="2024-06-15T08:00:00",
            )
            with global_lock():
                room_booking_repo.add(booking)
                waiting_list_repo.add(existing)

            menu = UserMenu(
                user=user,
                auth_service=auth_service,
                room_service=room_service,
                equipment_service=equipment_service,
                penalty_service=penalty_service,
                policy_service=policy_service,
                waiting_list_repo=waiting_list_repo,
            )

            monkeypatch.setattr(menu, "_refresh_user", lambda: True)
            monkeypatch.setattr("src.cli.user_menu.input_start_gate", lambda _title: True)
            monkeypatch.setattr("builtins.input", lambda _prompt="": "1")
            monkeypatch.setattr("src.cli.user_menu.select_from_list", lambda _items, _prompt: booking.id)
            monkeypatch.setattr("src.cli.user_menu.get_positive_int_input", lambda _label, _min_value, max_value: max_value)
            monkeypatch.setattr("src.cli.user_menu.review_action", lambda *_args, **_kwargs: "confirm")
            monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)
            monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)

            menu._create_waiting_list_request()

        output = capsys.readouterr().out
        entries = waiting_list_repo.get_ordered_by_related("room_booking", booking.id)
        assert len(entries) == 2
        assert entries[-1].username == user.username
        assert entries[-1].user_count == room.capacity
        assert "현재 대기 순번: 2번" in output

    def test_waitlist_equipment_flow_prints_sequence(
        self,
        monkeypatch,
        capsys,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        temp_data_dir,
        create_test_user,
        create_test_equipment,
        equipment_booking_repo,
        equipment_booking_factory,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)
        with mock_now(fixed_time):
            owner = create_test_user(username="WaitEquipOwner")
            user = create_test_user(username="WaitEquipUser")
            equipment = create_test_equipment(name="웹캠B", asset_type="webcam", serial_number="WC-101")
            booking = equipment_booking_factory(
                user_id=owner.id,
                equipment_id=equipment.id,
                start_time=(fixed_time + timedelta(days=3)).isoformat(),
                end_time=(fixed_time + timedelta(days=3, hours=9)).isoformat(),
                status=EquipmentBookingStatus.RESERVED,
            )
            waiting_list_repo = WaitingListRepository(file_path=temp_data_dir / "waiting_list.txt")
            existing = WaitingListEntry(
                id="wait-equipment-earlier",
                username="EarlierEquipUser",
                related_type="equipment_booking",
                related_id=booking.id,
                user_count=1,
                created_at="2024-06-15T08:00:00",
                updated_at="2024-06-15T08:00:00",
            )
            with global_lock():
                equipment_booking_repo.add(booking)
                waiting_list_repo.add(existing)

            menu = UserMenu(
                user=user,
                auth_service=auth_service,
                room_service=room_service,
                equipment_service=equipment_service,
                penalty_service=penalty_service,
                policy_service=policy_service,
                waiting_list_repo=waiting_list_repo,
            )

            monkeypatch.setattr(menu, "_refresh_user", lambda: True)
            monkeypatch.setattr("src.cli.user_menu.input_start_gate", lambda _title: True)
            monkeypatch.setattr("builtins.input", lambda _prompt="": "2")
            monkeypatch.setattr("src.cli.user_menu.select_from_list", lambda _items, _prompt: booking.id)
            monkeypatch.setattr("src.cli.user_menu.get_positive_int_input", lambda _label, _min_value, _max_value: 1)
            monkeypatch.setattr("src.cli.user_menu.review_action", lambda *_args, **_kwargs: "confirm")
            monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)
            monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)

            menu._create_waiting_list_request()

        output = capsys.readouterr().out
        entries = waiting_list_repo.get_ordered_by_related("equipment_booking", booking.id)
        assert len(entries) == 2
        assert entries[-1].username == user.username
        assert entries[-1].user_count == 1
        assert "현재 대기 순번: 2번" in output

    def test_waitlist_review_cancel_does_not_write(
        self,
        monkeypatch,
        capsys,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        temp_data_dir,
        create_test_user,
        create_test_room,
        room_booking_repo,
        room_booking_factory,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)
        with mock_now(fixed_time):
            owner = create_test_user(username="WaitCancelOwner")
            user = create_test_user(username="WaitCancelUser")
            room = create_test_room(name="회의실5W", capacity=5)
            booking = room_booking_factory(
                user_id=owner.id,
                room_id=room.id,
                start_time=(fixed_time + timedelta(days=3)).isoformat(),
                end_time=(fixed_time + timedelta(days=3, hours=9)).isoformat(),
                status=RoomBookingStatus.RESERVED,
            )
            waiting_list_repo = WaitingListRepository(file_path=temp_data_dir / "waiting_list.txt")
            with global_lock():
                room_booking_repo.add(booking)

            menu = UserMenu(
                user=user,
                auth_service=auth_service,
                room_service=room_service,
                equipment_service=equipment_service,
                penalty_service=penalty_service,
                policy_service=policy_service,
                waiting_list_repo=waiting_list_repo,
            )

            monkeypatch.setattr(menu, "_refresh_user", lambda: True)
            monkeypatch.setattr("src.cli.user_menu.input_start_gate", lambda _title: True)
            monkeypatch.setattr("builtins.input", lambda _prompt="": "1")
            monkeypatch.setattr("src.cli.user_menu.select_from_list", lambda _items, _prompt: booking.id)
            monkeypatch.setattr("src.cli.user_menu.get_positive_int_input", lambda _label, _min_value, _max_value: 2)
            monkeypatch.setattr("src.cli.user_menu.review_action", lambda *_args, **_kwargs: "cancel")
            monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)
            monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)

            menu._create_waiting_list_request()

        output = capsys.readouterr().out
        assert "대기 예약 신청을 취소했습니다." in output
        assert waiting_list_repo.get_all() == []

    def test_waitlist_duplicate_rejection_does_not_write_extra_row(
        self,
        monkeypatch,
        capsys,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        temp_data_dir,
        create_test_user,
        create_test_room,
        room_booking_repo,
        room_booking_factory,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)
        with mock_now(fixed_time):
            owner = create_test_user(username="WaitDupOwner")
            user = create_test_user(username="WaitDupUser")
            room = create_test_room(name="회의실6W", capacity=6)
            booking = room_booking_factory(
                user_id=owner.id,
                room_id=room.id,
                start_time=(fixed_time + timedelta(days=3)).isoformat(),
                end_time=(fixed_time + timedelta(days=3, hours=9)).isoformat(),
                status=RoomBookingStatus.RESERVED,
            )
            waiting_list_repo = WaitingListRepository(file_path=temp_data_dir / "waiting_list.txt")
            existing = WaitingListEntry(
                id="wait-duplicate",
                username=user.username,
                related_type="room_booking",
                related_id=booking.id,
                user_count=2,
                created_at="2024-06-15T08:00:00",
                updated_at="2024-06-15T08:00:00",
            )
            with global_lock():
                room_booking_repo.add(booking)
                waiting_list_repo.add(existing)

            menu = UserMenu(
                user=user,
                auth_service=auth_service,
                room_service=room_service,
                equipment_service=equipment_service,
                penalty_service=penalty_service,
                policy_service=policy_service,
                waiting_list_repo=waiting_list_repo,
            )

            monkeypatch.setattr(menu, "_refresh_user", lambda: True)
            monkeypatch.setattr("src.cli.user_menu.input_start_gate", lambda _title: True)
            monkeypatch.setattr("builtins.input", lambda _prompt="": "1")
            monkeypatch.setattr("src.cli.user_menu.select_from_list", lambda _items, _prompt: booking.id)
            monkeypatch.setattr("src.cli.user_menu.get_positive_int_input", lambda _label, _min_value, _max_value: 2)
            monkeypatch.setattr("src.cli.user_menu.review_action", lambda *_args, **_kwargs: "confirm")
            monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)
            monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)

            menu._create_waiting_list_request()

        output = capsys.readouterr().out
        assert "중복" in output
        entries = waiting_list_repo.get_ordered_by_related("room_booking", booking.id)
        assert [entry.id for entry in entries] == [existing.id]
        assert [entry.username for entry in entries] == [user.username]

    def test_waitlist_type_limit_rejection_does_not_write_fourth_row(
        self,
        monkeypatch,
        capsys,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        temp_data_dir,
        create_test_user,
        create_test_room,
        room_booking_repo,
        room_booking_factory,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)
        with mock_now(fixed_time):
            owner = create_test_user(username="WaitLimitOwner")
            user = create_test_user(username="WaitLimitUser")
            room = create_test_room(name="회의실7W", capacity=7)
            bookings = [
                room_booking_factory(
                    id=f"wait-limit-target-{index}",
                    user_id=owner.id,
                    room_id=room.id,
                    start_time=(fixed_time + timedelta(days=index + 3)).isoformat(),
                    end_time=(fixed_time + timedelta(days=index + 3, hours=9)).isoformat(),
                    status=RoomBookingStatus.RESERVED,
                )
                for index in range(4)
            ]
            waiting_list_repo = WaitingListRepository(file_path=temp_data_dir / "waiting_list.txt")
            with global_lock():
                for booking in bookings:
                    room_booking_repo.add(booking)
                for index, booking in enumerate(bookings[:3]):
                    waiting_list_repo.add(
                        WaitingListEntry(
                            id=f"wait-limit-existing-{index}",
                            username=user.username,
                            related_type="room_booking",
                            related_id=booking.id,
                            user_count=2,
                            created_at=f"2024-06-15T08:0{index}:00",
                            updated_at=f"2024-06-15T08:0{index}:00",
                        )
                    )

            menu = UserMenu(
                user=user,
                auth_service=auth_service,
                room_service=room_service,
                equipment_service=equipment_service,
                penalty_service=penalty_service,
                policy_service=policy_service,
                waiting_list_repo=waiting_list_repo,
            )

            monkeypatch.setattr(menu, "_refresh_user", lambda: True)
            monkeypatch.setattr("src.cli.user_menu.input_start_gate", lambda _title: True)
            monkeypatch.setattr("builtins.input", lambda _prompt="": "1")
            monkeypatch.setattr("src.cli.user_menu.select_from_list", lambda _items, _prompt: bookings[3].id)
            monkeypatch.setattr("src.cli.user_menu.get_positive_int_input", lambda _label, _min_value, _max_value: 2)
            monkeypatch.setattr("src.cli.user_menu.review_action", lambda *_args, **_kwargs: "confirm")
            monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)
            monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)

            menu._create_waiting_list_request()

        output = capsys.readouterr().out
        assert "최대 3건" in output
        assert waiting_list_repo.count_by_username_and_related_type(user.username, "room_booking") == 3
        assert waiting_list_repo.get_by_related("room_booking", bookings[3].id) == []

    def test_waitlist_day_before_target_is_hidden_without_write(
        self,
        monkeypatch,
        capsys,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        temp_data_dir,
        create_test_user,
        create_test_room,
        room_booking_repo,
        room_booking_factory,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)
        with mock_now(fixed_time):
            owner = create_test_user(username="WaitDayOwner")
            user = create_test_user(username="WaitDayUser")
            room = create_test_room(name="회의실8W", capacity=8)
            booking = room_booking_factory(
                user_id=owner.id,
                room_id=room.id,
                start_time=(fixed_time + timedelta(days=1)).isoformat(),
                end_time=(fixed_time + timedelta(days=1, hours=9)).isoformat(),
                status=RoomBookingStatus.RESERVED,
            )
            waiting_list_repo = WaitingListRepository(file_path=temp_data_dir / "waiting_list.txt")
            with global_lock():
                room_booking_repo.add(booking)

            menu = UserMenu(
                user=user,
                auth_service=auth_service,
                room_service=room_service,
                equipment_service=equipment_service,
                penalty_service=penalty_service,
                policy_service=policy_service,
                waiting_list_repo=waiting_list_repo,
            )

            monkeypatch.setattr(menu, "_refresh_user", lambda: True)
            monkeypatch.setattr("src.cli.user_menu.input_start_gate", lambda _title: True)
            monkeypatch.setattr("builtins.input", lambda _prompt="": "1")
            monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)
            monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)

            menu._create_waiting_list_request()

        output = capsys.readouterr().out
        assert "대기 신청 가능한 예약 건이 없습니다." in output
        assert waiting_list_repo.get_all() == []
