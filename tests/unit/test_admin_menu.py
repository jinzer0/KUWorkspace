import pytest
from src.cli.admin_menu import AdminMenu
from src.domain.models import UserRole, RoomBookingStatus, EquipmentBookingStatus


class TestAdminRoomReassignment:
    def test_reassign_active_room_booking_happy_path(
        self,
        monkeypatch,
        user_factory,
        room_factory,
        room_booking_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
    ):
        """Happy path: admin selects booking, replacement room, provides reason, confirms, service called once"""
        admin_user = user_factory(role=UserRole.ADMIN)
        booking_user = user_factory()
        
        current_room = room_factory(name="회의실 A")
        new_room = room_factory(name="회의실 B")
        
        active_booking = room_booking_factory(
            user_id=booking_user.id,
            room_id=current_room.id,
            status=RoomBookingStatus.CHECKED_IN,
            start_time="2025-03-30T09:00:00",
            end_time="2025-03-30T18:00:00",
        )
        
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )
        
        # Mock dependencies
        monkeypatch.setattr(
            menu, "_get_room_bookings_or_abort", lambda: [active_booking]
        )
        monkeypatch.setattr(
            menu, "_get_booking_user_or_abort", lambda uid: booking_user
        )
        monkeypatch.setattr(
            room_service, "get_room", 
            lambda rid: current_room if rid == current_room.id else new_room
        )
        monkeypatch.setattr(
            room_service, "get_all_rooms", lambda: [current_room, new_room]
        )
        monkeypatch.setattr(
            room_service.booking_repo, "get_conflicting", lambda *args, **kwargs: []
        )
        
        selection_calls = []
        def mock_select(items, prompt):
            selection_calls.append((items, prompt))
            if "예약 선택" in prompt:
                return active_booking.id
            elif "회의실 선택" in prompt:
                return new_room.id
            return None
        
        input_calls = []
        def mock_input(prompt):
            input_calls.append(prompt)
            if "사유" in prompt:
                return "고장으로 인한 교체"
            return ""
        
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", mock_select)
        monkeypatch.setattr("builtins.input", mock_input)
        monkeypatch.setattr("src.cli.admin_menu.confirm", lambda msg: True)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_subheader", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_success", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_info", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_warning", lambda x: None)
        monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)
        
        service_calls = []
        def mock_reassign(admin, booking_id, new_room_id, reason):
            service_calls.append((admin.id, booking_id, new_room_id, reason))
            return active_booking
        
        monkeypatch.setattr(
            room_service, "admin_reassign_active_booking", mock_reassign
        )
        
        menu._admin_reassign_active_room_booking()
        
        # Verify service called exactly once with correct args
        assert len(service_calls) == 1
        assert service_calls[0] == (
            admin_user.id,
            active_booking.id,
            new_room.id,
            "고장으로 인한 교체",
        )

    def test_reassign_no_active_bookings_shows_message_and_returns(
        self,
        monkeypatch,
        user_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
    ):
        """No CHECKED_IN bookings: shows message, returns without service call"""
        admin_user = user_factory(role=UserRole.ADMIN)
        
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )
        
        monkeypatch.setattr(menu, "_get_room_bookings_or_abort", lambda: [])
        
        info_messages = []
        monkeypatch.setattr(
            "src.cli.admin_menu.print_info", lambda msg: info_messages.append(msg)
        )
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)
        
        service_calls = []
        monkeypatch.setattr(
            room_service,
            "admin_reassign_active_booking",
            lambda *args, **kwargs: service_calls.append(args),
        )
        
        menu._admin_reassign_active_room_booking()
        
        assert len(service_calls) == 0
        assert any("진행중" in msg for msg in info_messages)

    def test_reassign_no_eligible_replacements_shows_message_and_returns(
        self,
        monkeypatch,
        user_factory,
        room_factory,
        room_booking_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
    ):
        """Active booking exists but no eligible replacements: shows message, no service call"""
        admin_user = user_factory(role=UserRole.ADMIN)
        booking_user = user_factory()
        
        current_room = room_factory(name="회의실 A")
        
        active_booking = room_booking_factory(
            user_id=booking_user.id,
            room_id=current_room.id,
            status=RoomBookingStatus.CHECKED_IN,
        )
        
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )
        
        monkeypatch.setattr(
            menu, "_get_room_bookings_or_abort", lambda: [active_booking]
        )
        monkeypatch.setattr(
            menu, "_get_booking_user_or_abort", lambda uid: booking_user
        )
        monkeypatch.setattr(room_service, "get_room", lambda rid: current_room)
        monkeypatch.setattr(room_service, "get_all_rooms", lambda: [current_room])
        
        def mock_select(items, prompt):
            if "예약 선택" in prompt:
                return active_booking.id
            return None
        
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", mock_select)
        
        info_messages = []
        monkeypatch.setattr(
            "src.cli.admin_menu.print_info", lambda msg: info_messages.append(msg)
        )
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_subheader", lambda x: None)
        monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)
        
        service_calls = []
        monkeypatch.setattr(
            room_service,
            "admin_reassign_active_booking",
            lambda *args, **kwargs: service_calls.append(args),
        )
        
        menu._admin_reassign_active_room_booking()
        
        assert len(service_calls) == 0
        assert any("교체 가능한 회의실이 없습니다" in msg for msg in info_messages)

    def test_reassign_cancel_at_booking_selection_returns_cleanly(
        self,
        monkeypatch,
        user_factory,
        room_factory,
        room_booking_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
    ):
        """Cancel at booking selection: no service call"""
        admin_user = user_factory(role=UserRole.ADMIN)
        booking_user = user_factory()
        
        current_room = room_factory(name="회의실 A")
        
        active_booking = room_booking_factory(
            user_id=booking_user.id,
            room_id=current_room.id,
            status=RoomBookingStatus.CHECKED_IN,
        )
        
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )
        
        monkeypatch.setattr(
            menu, "_get_room_bookings_or_abort", lambda: [active_booking]
        )
        monkeypatch.setattr(
            menu, "_get_booking_user_or_abort", lambda uid: booking_user
        )
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", lambda items, prompt: None)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)
        
        service_calls = []
        monkeypatch.setattr(
            room_service,
            "admin_reassign_active_booking",
            lambda *args, **kwargs: service_calls.append(args),
        )
        
        menu._admin_reassign_active_room_booking()
        
        assert len(service_calls) == 0

    def test_reassign_cancel_at_room_selection_returns_cleanly(
        self,
        monkeypatch,
        user_factory,
        room_factory,
        room_booking_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
    ):
        """Cancel at replacement room selection: no service call"""
        admin_user = user_factory(role=UserRole.ADMIN)
        booking_user = user_factory()
        
        current_room = room_factory(name="회의실 A")
        new_room = room_factory(name="회의실 B")
        
        active_booking = room_booking_factory(
            user_id=booking_user.id,
            room_id=current_room.id,
            status=RoomBookingStatus.CHECKED_IN,
        )
        
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )
        
        monkeypatch.setattr(
            menu, "_get_room_bookings_or_abort", lambda: [active_booking]
        )
        monkeypatch.setattr(
            menu, "_get_booking_user_or_abort", lambda uid: booking_user
        )
        monkeypatch.setattr(
            room_service, "get_room", lambda rid: current_room if rid == current_room.id else new_room
        )
        monkeypatch.setattr(
            room_service, "get_all_rooms", lambda: [current_room, new_room]
        )
        monkeypatch.setattr(
            room_service.booking_repo, "get_conflicting", lambda *args, **kwargs: []
        )
        
        def mock_select(items, prompt):
            if "예약 선택" in prompt:
                return active_booking.id
            elif "회의실 선택" in prompt:
                return None
            return None
        
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", mock_select)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_subheader", lambda x: None)
        monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)
        
        service_calls = []
        monkeypatch.setattr(
            room_service,
            "admin_reassign_active_booking",
            lambda *args, **kwargs: service_calls.append(args),
        )
        
        menu._admin_reassign_active_room_booking()
        
        assert len(service_calls) == 0

    def test_reassign_empty_reason_shows_error_and_returns(
        self,
        monkeypatch,
        user_factory,
        room_factory,
        room_booking_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
    ):
        """Empty reason input: shows error, no service call"""
        admin_user = user_factory(role=UserRole.ADMIN)
        booking_user = user_factory()
        
        current_room = room_factory(name="회의실 A")
        new_room = room_factory(name="회의실 B")
        
        active_booking = room_booking_factory(
            user_id=booking_user.id,
            room_id=current_room.id,
            status=RoomBookingStatus.CHECKED_IN,
        )
        
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )
        
        monkeypatch.setattr(
            menu, "_get_room_bookings_or_abort", lambda: [active_booking]
        )
        monkeypatch.setattr(
            menu, "_get_booking_user_or_abort", lambda uid: booking_user
        )
        monkeypatch.setattr(
            room_service, "get_room", lambda rid: current_room if rid == current_room.id else new_room
        )
        monkeypatch.setattr(
            room_service, "get_all_rooms", lambda: [current_room, new_room]
        )
        monkeypatch.setattr(
            room_service.booking_repo, "get_conflicting", lambda *args, **kwargs: []
        )
        
        def mock_select(items, prompt):
            if "예약 선택" in prompt:
                return active_booking.id
            elif "회의실 선택" in prompt:
                return new_room.id
            return None
        
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", mock_select)
        monkeypatch.setattr("builtins.input", lambda prompt: "")
        
        error_messages = []
        monkeypatch.setattr(
            "src.cli.admin_menu.print_error", lambda msg: error_messages.append(msg)
        )
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_subheader", lambda x: None)
        monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)
        
        service_calls = []
        monkeypatch.setattr(
            room_service,
            "admin_reassign_active_booking",
            lambda *args, **kwargs: service_calls.append(args),
        )
        
        menu._admin_reassign_active_room_booking()
        
        assert len(service_calls) == 0
        assert any("사유를 입력" in msg for msg in error_messages)

    def test_reassign_no_confirmation_returns_without_service_call(
        self,
        monkeypatch,
        user_factory,
        room_factory,
        room_booking_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
    ):
        """Final confirmation declined: no service call"""
        admin_user = user_factory(role=UserRole.ADMIN)
        booking_user = user_factory()
        
        current_room = room_factory(name="회의실 A")
        new_room = room_factory(name="회의실 B")
        
        active_booking = room_booking_factory(
            user_id=booking_user.id,
            room_id=current_room.id,
            status=RoomBookingStatus.CHECKED_IN,
        )
        
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )
        
        monkeypatch.setattr(
            menu, "_get_room_bookings_or_abort", lambda: [active_booking]
        )
        monkeypatch.setattr(
            menu, "_get_booking_user_or_abort", lambda uid: booking_user
        )
        monkeypatch.setattr(
            room_service, "get_room", lambda rid: current_room if rid == current_room.id else new_room
        )
        monkeypatch.setattr(
            room_service, "get_all_rooms", lambda: [current_room, new_room]
        )
        monkeypatch.setattr(
            room_service.booking_repo, "get_conflicting", lambda *args, **kwargs: []
        )
        
        def mock_select(items, prompt):
            if "예약 선택" in prompt:
                return active_booking.id
            elif "회의실 선택" in prompt:
                return new_room.id
            return None
        
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", mock_select)
        monkeypatch.setattr("builtins.input", lambda prompt: "설비 고장")
        monkeypatch.setattr("src.cli.admin_menu.confirm", lambda msg: False)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_subheader", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_warning", lambda x: None)
        monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)
        
        service_calls = []
        monkeypatch.setattr(
            room_service,
            "admin_reassign_active_booking",
            lambda *args, **kwargs: service_calls.append(args),
        )
        
        menu._admin_reassign_active_room_booking()
        
        assert len(service_calls) == 0


class TestAdminEquipmentReassignment:
    """Tests for equipment active booking reassignment CLI flow"""

    def test_reassign_active_equipment_booking_happy_path(
        self,
        monkeypatch,
        user_factory,
        equipment_factory,
        equipment_booking_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
    ):
        """Happy path: admin selects booking, replacement equipment, provides reason, confirms, service called once"""
        admin_user = user_factory(role=UserRole.ADMIN)
        booking_user = user_factory()
        
        current_equipment = equipment_factory(name="프로젝터 A")
        new_equipment = equipment_factory(name="프로젝터 B")
        
        active_booking = equipment_booking_factory(
            user_id=booking_user.id,
            equipment_id=current_equipment.id,
            status=EquipmentBookingStatus.CHECKED_OUT,
            start_time="2025-03-30T09:00:00",
            end_time="2025-03-30T18:00:00",
        )
        
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )
        
        monkeypatch.setattr(
            menu, "_get_equipment_bookings_or_abort", lambda: [active_booking]
        )
        monkeypatch.setattr(
            menu, "_get_booking_user_or_abort", lambda uid: booking_user
        )
        monkeypatch.setattr(
            equipment_service, "get_equipment", 
            lambda eid: current_equipment if eid == current_equipment.id else new_equipment
        )
        monkeypatch.setattr(
            equipment_service, "get_all_equipment", lambda: [current_equipment, new_equipment]
        )
        monkeypatch.setattr(
            equipment_service.booking_repo, "get_conflicting", lambda *args, **kwargs: []
        )
        
        selection_calls = []
        def mock_select(items, prompt):
            selection_calls.append((items, prompt))
            if "예약 선택" in prompt:
                return active_booking.id
            elif "장비 선택" in prompt:
                return new_equipment.id
            return None
        
        input_calls = []
        def mock_input(prompt):
            input_calls.append(prompt)
            if "사유" in prompt:
                return "고장으로 인한 교체"
            return ""
        
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", mock_select)
        monkeypatch.setattr("builtins.input", mock_input)
        monkeypatch.setattr("src.cli.admin_menu.confirm", lambda msg: True)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_subheader", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_success", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_info", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_warning", lambda x: None)
        monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)
        
        service_calls = []
        def mock_reassign(admin, booking_id, new_equipment_id, reason):
            service_calls.append((admin.id, booking_id, new_equipment_id, reason))
            return active_booking
        
        monkeypatch.setattr(
            equipment_service, "admin_reassign_active_booking", mock_reassign
        )
        
        menu._admin_reassign_active_equipment_booking()
        
        assert len(service_calls) == 1
        assert service_calls[0] == (
            admin_user.id,
            active_booking.id,
            new_equipment.id,
            "고장으로 인한 교체",
        )

    def test_reassign_no_active_bookings_shows_message_and_returns(
        self,
        monkeypatch,
        user_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
    ):
        """No CHECKED_OUT bookings: shows message, returns without service call"""
        admin_user = user_factory(role=UserRole.ADMIN)
        
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )
        
        monkeypatch.setattr(menu, "_get_equipment_bookings_or_abort", lambda: [])
        
        info_messages = []
        monkeypatch.setattr(
            "src.cli.admin_menu.print_info", lambda msg: info_messages.append(msg)
        )
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)
        
        service_calls = []
        monkeypatch.setattr(
            equipment_service,
            "admin_reassign_active_booking",
            lambda *args, **kwargs: service_calls.append(args),
        )
        
        menu._admin_reassign_active_equipment_booking()
        
        assert len(service_calls) == 0
        assert any("진행중" in msg for msg in info_messages)

    def test_reassign_no_eligible_replacements_shows_message_and_returns(
        self,
        monkeypatch,
        user_factory,
        equipment_factory,
        equipment_booking_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
    ):
        """Active booking exists but no eligible replacements: shows message, no service call"""
        admin_user = user_factory(role=UserRole.ADMIN)
        booking_user = user_factory()
        
        current_equipment = equipment_factory(name="프로젝터 A")
        
        active_booking = equipment_booking_factory(
            user_id=booking_user.id,
            equipment_id=current_equipment.id,
            status=EquipmentBookingStatus.CHECKED_OUT,
        )
        
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )
        
        monkeypatch.setattr(
            menu, "_get_equipment_bookings_or_abort", lambda: [active_booking]
        )
        monkeypatch.setattr(
            menu, "_get_booking_user_or_abort", lambda uid: booking_user
        )
        monkeypatch.setattr(equipment_service, "get_equipment", lambda eid: current_equipment)
        monkeypatch.setattr(equipment_service, "get_all_equipment", lambda: [current_equipment])
        
        def mock_select(items, prompt):
            if "예약 선택" in prompt:
                return active_booking.id
            return None
        
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", mock_select)
        
        info_messages = []
        monkeypatch.setattr(
            "src.cli.admin_menu.print_info", lambda msg: info_messages.append(msg)
        )
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_subheader", lambda x: None)
        monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)
        
        service_calls = []
        monkeypatch.setattr(
            equipment_service,
            "admin_reassign_active_booking",
            lambda *args, **kwargs: service_calls.append(args),
        )
        
        menu._admin_reassign_active_equipment_booking()
        
        assert len(service_calls) == 0
        assert any("교체 가능한 장비가 없습니다" in msg for msg in info_messages)

    def test_reassign_cancel_at_booking_selection_returns_cleanly(
        self,
        monkeypatch,
        user_factory,
        equipment_factory,
        equipment_booking_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
    ):
        """Cancel at booking selection: no service call"""
        admin_user = user_factory(role=UserRole.ADMIN)
        booking_user = user_factory()
        
        current_equipment = equipment_factory(name="프로젝터 A")
        
        active_booking = equipment_booking_factory(
            user_id=booking_user.id,
            equipment_id=current_equipment.id,
            status=EquipmentBookingStatus.CHECKED_OUT,
        )
        
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )
        
        monkeypatch.setattr(
            menu, "_get_equipment_bookings_or_abort", lambda: [active_booking]
        )
        monkeypatch.setattr(
            menu, "_get_booking_user_or_abort", lambda uid: booking_user
        )
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", lambda items, prompt: None)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)
        
        service_calls = []
        monkeypatch.setattr(
            equipment_service,
            "admin_reassign_active_booking",
            lambda *args, **kwargs: service_calls.append(args),
        )
        
        menu._admin_reassign_active_equipment_booking()
        
        assert len(service_calls) == 0

    def test_reassign_cancel_at_equipment_selection_returns_cleanly(
        self,
        monkeypatch,
        user_factory,
        equipment_factory,
        equipment_booking_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
    ):
        """Cancel at replacement equipment selection: no service call"""
        admin_user = user_factory(role=UserRole.ADMIN)
        booking_user = user_factory()
        
        current_equipment = equipment_factory(name="프로젝터 A")
        new_equipment = equipment_factory(name="프로젝터 B")
        
        active_booking = equipment_booking_factory(
            user_id=booking_user.id,
            equipment_id=current_equipment.id,
            status=EquipmentBookingStatus.CHECKED_OUT,
        )
        
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )
        
        monkeypatch.setattr(
            menu, "_get_equipment_bookings_or_abort", lambda: [active_booking]
        )
        monkeypatch.setattr(
            menu, "_get_booking_user_or_abort", lambda uid: booking_user
        )
        monkeypatch.setattr(
            equipment_service, "get_equipment", 
            lambda eid: current_equipment if eid == current_equipment.id else new_equipment
        )
        monkeypatch.setattr(
            equipment_service, "get_all_equipment", lambda: [current_equipment, new_equipment]
        )
        monkeypatch.setattr(
            equipment_service.booking_repo, "get_conflicting", lambda *args, **kwargs: []
        )
        
        def mock_select(items, prompt):
            if "예약 선택" in prompt:
                return active_booking.id
            elif "장비 선택" in prompt:
                return None
            return None
        
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", mock_select)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_subheader", lambda x: None)
        monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)
        
        service_calls = []
        monkeypatch.setattr(
            equipment_service,
            "admin_reassign_active_booking",
            lambda *args, **kwargs: service_calls.append(args),
        )
        
        menu._admin_reassign_active_equipment_booking()
        
        assert len(service_calls) == 0

    def test_reassign_empty_reason_shows_error_and_returns(
        self,
        monkeypatch,
        user_factory,
        equipment_factory,
        equipment_booking_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
    ):
        """Empty reason input: shows error, no service call"""
        admin_user = user_factory(role=UserRole.ADMIN)
        booking_user = user_factory()
        
        current_equipment = equipment_factory(name="프로젝터 A")
        new_equipment = equipment_factory(name="프로젝터 B")
        
        active_booking = equipment_booking_factory(
            user_id=booking_user.id,
            equipment_id=current_equipment.id,
            status=EquipmentBookingStatus.CHECKED_OUT,
        )
        
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )
        
        monkeypatch.setattr(
            menu, "_get_equipment_bookings_or_abort", lambda: [active_booking]
        )
        monkeypatch.setattr(
            menu, "_get_booking_user_or_abort", lambda uid: booking_user
        )
        monkeypatch.setattr(
            equipment_service, "get_equipment", 
            lambda eid: current_equipment if eid == current_equipment.id else new_equipment
        )
        monkeypatch.setattr(
            equipment_service, "get_all_equipment", lambda: [current_equipment, new_equipment]
        )
        monkeypatch.setattr(
            equipment_service.booking_repo, "get_conflicting", lambda *args, **kwargs: []
        )
        
        def mock_select(items, prompt):
            if "예약 선택" in prompt:
                return active_booking.id
            elif "장비 선택" in prompt:
                return new_equipment.id
            return None
        
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", mock_select)
        monkeypatch.setattr("builtins.input", lambda prompt: "")
        
        error_messages = []
        monkeypatch.setattr(
            "src.cli.admin_menu.print_error", lambda msg: error_messages.append(msg)
        )
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_subheader", lambda x: None)
        monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)
        
        service_calls = []
        monkeypatch.setattr(
            equipment_service,
            "admin_reassign_active_booking",
            lambda *args, **kwargs: service_calls.append(args),
        )
        
        menu._admin_reassign_active_equipment_booking()
        
        assert len(service_calls) == 0
        assert any("사유를 입력" in msg for msg in error_messages)

    def test_reassign_no_confirmation_returns_without_service_call(
        self,
        monkeypatch,
        user_factory,
        equipment_factory,
        equipment_booking_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
    ):
        """Final confirmation declined: no service call"""
        admin_user = user_factory(role=UserRole.ADMIN)
        booking_user = user_factory()
        
        current_equipment = equipment_factory(name="프로젝터 A")
        new_equipment = equipment_factory(name="프로젝터 B")
        
        active_booking = equipment_booking_factory(
            user_id=booking_user.id,
            equipment_id=current_equipment.id,
            status=EquipmentBookingStatus.CHECKED_OUT,
        )
        
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )
        
        monkeypatch.setattr(
            menu, "_get_equipment_bookings_or_abort", lambda: [active_booking]
        )
        monkeypatch.setattr(
            menu, "_get_booking_user_or_abort", lambda uid: booking_user
        )
        monkeypatch.setattr(
            equipment_service, "get_equipment", 
            lambda eid: current_equipment if eid == current_equipment.id else new_equipment
        )
        monkeypatch.setattr(
            equipment_service, "get_all_equipment", lambda: [current_equipment, new_equipment]
        )
        monkeypatch.setattr(
            equipment_service.booking_repo, "get_conflicting", lambda *args, **kwargs: []
        )
        
        def mock_select(items, prompt):
            if "예약 선택" in prompt:
                return active_booking.id
            elif "장비 선택" in prompt:
                return new_equipment.id
            return None
        
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", mock_select)
        monkeypatch.setattr("builtins.input", lambda prompt: "설비 고장")
        monkeypatch.setattr("src.cli.admin_menu.confirm", lambda msg: False)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_subheader", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_warning", lambda x: None)
        monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)
        
        service_calls = []
        monkeypatch.setattr(
            equipment_service,
            "admin_reassign_active_booking",
            lambda *args, **kwargs: service_calls.append(args),
        )
        
        menu._admin_reassign_active_equipment_booking()
        
        assert len(service_calls) == 0
