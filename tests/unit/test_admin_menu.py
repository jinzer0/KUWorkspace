import pytest
from datetime import datetime
from src.cli.admin_menu import AdminMenu
from src.domain.models import Message, MessageType, UserRole, RoomBookingStatus, EquipmentBookingStatus, generate_id
from src.cli.formatters import format_datetime


class TestAdminMessageList:
    def test_show_messages_empty_state(
        self,
        monkeypatch,
        user_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        message_service,
    ):
        """Empty state prints message and returns cleanly"""
        admin_user = user_factory(role=UserRole.ADMIN)
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
            message_service=message_service,
        )

        monkeypatch.setattr(message_service, "list_messages", lambda: [])
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)

        printed = []
        original_print = print
        
        def capture_print(*args, **kwargs):
            if args:
                printed.append(str(args[0]))
            original_print(*args, **kwargs)
        
        monkeypatch.setattr("builtins.print", capture_print)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)

        menu._show_messages()

        assert "등록된 문의/신고가 없습니다." in printed

    def test_show_messages_renders_latest_first(
        self,
        monkeypatch,
        user_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        message_service,
    ):
        """Non-empty state renders latest-first rows with Korean type labels"""
        admin_user = user_factory(role=UserRole.ADMIN)
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
            message_service=message_service,
        )

        msg1 = Message(
            id=generate_id(),
            user_id="user-1",
            type=MessageType.INQUIRY,
            content="First message",
            created_at="2025-01-01T10:00:00",
        )
        msg2 = Message(
            id=generate_id(),
            user_id="user-2",
            type=MessageType.REPORT,
            content="Second message",
            created_at="2025-01-02T10:00:00",
        )
        msg3 = Message(
            id=generate_id(),
            user_id="user-3",
            type=MessageType.INQUIRY,
            content="Third message newest",
            created_at="2025-01-03T10:00:00",
        )

        monkeypatch.setattr(message_service, "list_messages", lambda: [msg1, msg2, msg3])
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", lambda *args, **kwargs: None)

        printed_tables = []
        
        def capture_table(headers, rows):
            printed_tables.append((headers, rows))
            return "table"
        
        monkeypatch.setattr("src.cli.admin_menu.format_table", capture_table)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)

        menu._show_messages()

        assert len(printed_tables) == 1
        headers, rows = printed_tables[0]

        assert headers == ["유형", "사용자 ID", "등록 시각", "내용"]
        assert len(rows) == 3

        assert rows[0][0] == "문의"
        assert rows[0][1] == "user-3"
        assert "2025-01-03" in rows[0][2]
        assert rows[0][3] == "Third message newest"

        assert rows[1][0] == "신고"
        assert rows[1][1] == "user-2"

        assert rows[2][0] == "문의"
        assert rows[2][1] == "user-1"

    def test_show_messages_truncates_content_preview(
        self,
        monkeypatch,
        user_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        message_service,
    ):
        """Content preview truncated to 30 visible chars with ellipsis"""
        admin_user = user_factory(role=UserRole.ADMIN)
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
            message_service=message_service,
        )

        long_content = "A" * 50
        msg = Message(
            id=generate_id(),
            user_id="user-1",
            type=MessageType.INQUIRY,
            content=long_content,
            created_at="2025-01-01T10:00:00",
        )

        monkeypatch.setattr(message_service, "list_messages", lambda: [msg])
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", lambda *args, **kwargs: None)

        printed_tables = []
        
        def capture_table(headers, rows):
            printed_tables.append((headers, rows))
            return "table"
        
        monkeypatch.setattr("src.cli.admin_menu.format_table", capture_table)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)

        menu._show_messages()

        assert len(printed_tables) == 1
        _, rows = printed_tables[0]

        content_display = rows[0][3]
        assert len(content_display) == 33
        assert content_display == "A" * 30 + "..."

    def test_show_messages_displays_truncation_notice(
        self,
        monkeypatch,
        user_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        message_service,
    ):
        """When total > 30 show truncation notice"""
        admin_user = user_factory(role=UserRole.ADMIN)
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
            message_service=message_service,
        )

        messages = [
            Message(
                id=generate_id(),
                user_id=f"user-{i}",
                type=MessageType.INQUIRY,
                content=f"Message {i}",
                created_at=f"2025-01-{1 + i:02d}T10:00:00",
            )
            for i in range(35)
        ]

        monkeypatch.setattr(message_service, "list_messages", lambda: messages)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", lambda *args, **kwargs: None)
        monkeypatch.setattr("src.cli.admin_menu.format_table", lambda h, r: "table")
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)

        printed = []
        original_print = print
        
        def capture_print(*args, **kwargs):
            if args:
                printed.append(str(args[0]))
            original_print(*args, **kwargs)
        
        monkeypatch.setattr("builtins.print", capture_print)

        menu._show_messages()

        assert any("... 외 5건" in line for line in printed)

    def test_show_messages_selection_over_displayed_dataset(
        self,
        monkeypatch,
        user_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        message_service,
    ):
        """Selection step operates on same 30 displayed records"""
        admin_user = user_factory(role=UserRole.ADMIN)
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
            message_service=message_service,
        )

        messages = [
            Message(
                id=generate_id(),
                user_id=f"user-{i}",
                type=MessageType.INQUIRY,
                content=f"Message {i}",
                created_at=f"2025-01-{1 + i:02d}T10:00:00",
            )
            for i in range(35)
        ]

        monkeypatch.setattr(message_service, "list_messages", lambda: messages)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.format_table", lambda h, r: "table")
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)

        captured_items = []
        
        def capture_select(items, prompt):
            captured_items.extend(items)
            return None
        
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", capture_select)

        menu._show_messages()

        assert len(captured_items) == 30

    def test_show_messages_no_selection_returns_cleanly(
        self,
        monkeypatch,
        user_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        message_service,
    ):
        """Cancelling selection returns without error"""
        admin_user = user_factory(role=UserRole.ADMIN)
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
            message_service=message_service,
        )

        msg = Message(
            id=generate_id(),
            user_id="user-1",
            type=MessageType.INQUIRY,
            content="Test message",
            created_at="2025-01-01T10:00:00",
        )

        monkeypatch.setattr(message_service, "list_messages", lambda: [msg])
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.format_table", lambda h, r: "table")
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", lambda *args, **kwargs: None)

        menu._show_messages()

    def test_show_messages_maps_inquiry_type_to_korean(
        self,
        monkeypatch,
        user_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        message_service,
    ):
        """Type 'inquiry' maps to Korean '문의'"""
        admin_user = user_factory(role=UserRole.ADMIN)
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
            message_service=message_service,
        )

        msg = Message(
            id=generate_id(),
            user_id="user-1",
            type=MessageType.INQUIRY,
            content="Test",
            created_at="2025-01-01T10:00:00",
        )

        monkeypatch.setattr(message_service, "list_messages", lambda: [msg])
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", lambda *args, **kwargs: None)

        printed_tables = []
        
        def capture_table(headers, rows):
            printed_tables.append((headers, rows))
            return "table"
        
        monkeypatch.setattr("src.cli.admin_menu.format_table", capture_table)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)

        menu._show_messages()

        assert len(printed_tables) == 1
        _, rows = printed_tables[0]
        assert rows[0][0] == "문의"

    def test_show_messages_maps_report_type_to_korean(
        self,
        monkeypatch,
        user_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        message_service,
    ):
        """Type 'report' maps to Korean '신고'"""
        admin_user = user_factory(role=UserRole.ADMIN)
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
            message_service=message_service,
        )

        msg = Message(
            id=generate_id(),
            user_id="user-1",
            type=MessageType.REPORT,
            content="Test",
            created_at="2025-01-01T10:00:00",
        )

        monkeypatch.setattr(message_service, "list_messages", lambda: [msg])
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", lambda *args, **kwargs: None)

        printed_tables = []
        
        def capture_table(headers, rows):
            printed_tables.append((headers, rows))
            return "table"
        
        monkeypatch.setattr("src.cli.admin_menu.format_table", capture_table)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)

        menu._show_messages()

        assert len(printed_tables) == 1
        _, rows = printed_tables[0]
        assert rows[0][0] == "신고"

    def test_show_messages_detail_view_displays_all_fields(
        self,
        monkeypatch,
        user_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        message_service,
    ):
        """Detail screen displays all five required fields with full content"""
        admin_user = user_factory(role=UserRole.ADMIN)
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
            message_service=message_service,
        )

        msg = Message(
            id="msg-123-456",
            user_id="user-demo",
            type=MessageType.INQUIRY,
            content="This is a very long inquiry content that should not be truncated in detail view",
            created_at="2025-01-15T14:30:00",
        )

        monkeypatch.setattr(message_service, "list_messages", lambda: [msg])
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", lambda *args, **kwargs: msg.id)
        monkeypatch.setattr("src.cli.admin_menu.format_table", lambda h, r: "table")
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)

        printed_lines = []
        
        def capture_print(*args, **kwargs):
            if args:
                printed_lines.append(str(args[0]))
        
        monkeypatch.setattr("builtins.print", capture_print)
        monkeypatch.setattr("src.cli.admin_menu.print_subheader", lambda x: None)

        menu._show_messages()

        # Verify all required fields are printed
        combined_output = "\n".join(printed_lines)
        assert "유형: 문의" in combined_output
        assert "사용자 ID: user-demo" in combined_output
        assert "메시지 ID: msg-123-456" in combined_output
        
        # Assert exact detail line with formatted created_at using same formatter as app
        expected_detail_line = f"등록 시각: {format_datetime(msg.created_at)}"
        assert expected_detail_line in combined_output, f"Expected detail line '{expected_detail_line}' not found in output"
        
        # Verify full content is shown (not truncated)
        assert "This is a very long inquiry content that should not be truncated in detail view" in combined_output

    def test_show_messages_detail_view_shows_korean_type_labels(
        self,
        monkeypatch,
        user_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        message_service,
    ):
        """Detail screen uses Korean type mapping"""
        admin_user = user_factory(role=UserRole.ADMIN)
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
            message_service=message_service,
        )

        report_msg = Message(
            id="report-id-1",
            user_id="user-reporter",
            type=MessageType.REPORT,
            content="Report content",
            created_at="2025-01-10T09:00:00",
        )

        monkeypatch.setattr(message_service, "list_messages", lambda: [report_msg])
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", lambda *args, **kwargs: report_msg.id)
        monkeypatch.setattr("src.cli.admin_menu.format_table", lambda h, r: "table")
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)

        printed_lines = []
        
        def capture_print(*args, **kwargs):
            if args:
                printed_lines.append(str(args[0]))
        
        monkeypatch.setattr("builtins.print", capture_print)
        monkeypatch.setattr("src.cli.admin_menu.print_subheader", lambda x: None)

        menu._show_messages()

        combined_output = "\n".join(printed_lines)
        assert "유형: 신고" in combined_output

    def test_show_messages_cancel_returns_without_detail(
        self,
        monkeypatch,
        user_factory,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        message_service,
    ):
        """Cancelling selection (returning None from select_from_list) skips detail view"""
        admin_user = user_factory(role=UserRole.ADMIN)
        menu = AdminMenu(
            user=admin_user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
            message_service=message_service,
        )

        msg = Message(
            id="msg-id-1",
            user_id="user-1",
            type=MessageType.INQUIRY,
            content="Message content",
            created_at="2025-01-01T10:00:00",
        )

        # Track if print_subheader is called (should NOT be called on cancel)
        subheader_calls = []
        
        def track_subheader(x):
            subheader_calls.append(x)
        
        monkeypatch.setattr(message_service, "list_messages", lambda: [msg])
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.select_from_list", lambda *args, **kwargs: None)  # Cancel
        monkeypatch.setattr("src.cli.admin_menu.format_table", lambda h, r: "table")
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_subheader", track_subheader)
        monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)

        menu._show_messages()

        # Verify print_subheader("문의/신고 상세") was NOT called
        assert "문의/신고 상세" not in subheader_calls


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
        message_service,
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
            message_service=message_service,
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
        message_service,
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
            message_service=message_service,
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
        message_service,
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
            message_service=message_service,
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
        message_service,
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
            message_service=message_service,
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
        message_service,
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
            message_service=message_service,
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
        message_service,
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
            message_service=message_service,
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
        message_service,
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
            message_service=message_service,
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
        message_service,
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
            message_service=message_service,
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
        message_service,
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
            message_service=message_service,
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
        message_service,
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
            message_service=message_service,
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
        message_service,
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
            message_service=message_service,
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
        message_service,
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
            message_service=message_service,
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
        message_service,
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
            message_service=message_service,
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
        message_service,
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
            message_service=message_service,
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
