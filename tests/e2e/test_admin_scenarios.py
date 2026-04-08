"""
관리자 시나리오 E2E 테스트

테스트 대상:
- 패널티 부과 (파손/오염)
- 회의실/장비 상태 변경 (maintenance → 예약 자동 취소)
- 예약 강제 취소
- 사용자 패널티 이력 조회
"""

import pytest
from datetime import datetime, timedelta

from src.domain.room_service import RoomBookingError
from src.domain.penalty_service import PenaltyError
from src.domain.models import (
    UserRole,
    RoomBookingStatus,
    EquipmentBookingStatus,
    ResourceStatus,
    PenaltyReason,
)
from src.storage.file_lock import global_lock


class TestAdminPenaltyManagement:
    """관리자 패널티 관리"""

    def test_admin_applies_damage_penalty(
        self, auth_service, room_service, penalty_service, create_test_room, mock_now
    ):
        """관리자가 파손 패널티 부과"""
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("damage_user", "pass")
            admin = auth_service.signup("damage_admin", "pass", role=UserRole.ADMIN)
            room = create_test_room()

            # 예약 및 체크인
            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time,
                fixed_time.replace(hour=18),
            )
            room_service.request_check_in(user, booking.id)
            room_service.check_in(admin, booking.id)

        checkout_time = datetime(2024, 6, 15, 18, 0, 0)
        with mock_now(checkout_time):
            room_service.check_out(admin, booking.id)

            # 파손 패널티 부과
            penalty = penalty_service.apply_damage(
                admin=admin,
                user=user,
                booking_type="room_booking",
                booking_id=booking.id,
                points=3,
                memo="책상 파손",
            )

            assert penalty.reason == PenaltyReason.DAMAGE
            assert penalty.points == 3
            assert penalty.memo == "책상 파손"

            updated = auth_service.get_user(user.id)
            assert updated.penalty_points == 3

    def test_admin_damage_penalty_range_validation(self, auth_service, penalty_service):
        """파손 패널티 범위 검증 (1~5점)"""
        user = auth_service.signup("range_user", "pass")
        admin = auth_service.signup("range_admin", "pass", role=UserRole.ADMIN)

        # 0점 불가
        with pytest.raises(PenaltyError):
            penalty_service.apply_damage(
                admin=admin,
                user=user,
                booking_type="room_booking",
                booking_id="b1",
                points=0,
                memo="test",
            )

        # 6점 불가
        with pytest.raises(PenaltyError):
            penalty_service.apply_damage(
                admin=admin,
                user=user,
                booking_type="room_booking",
                booking_id="b2",
                points=6,
                memo="test",
            )

        # 1~5점 가능
        for pts in [1, 2, 3, 4, 5]:
            penalty = penalty_service.apply_damage(
                admin=admin,
                user=user,
                booking_type="room_booking",
                booking_id=f"b{pts}",
                points=pts,
                memo=f"test {pts}",
            )
            assert penalty.points == pts


class TestAdminStatusChange:
    """관리자 상태 변경"""

    def test_room_maintenance_cancels_future_bookings(
        self, auth_service, room_service, create_test_room, mock_now
    ):
        """회의실 maintenance 시 미래 예약 자동 취소"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("maint_user", "pass")
            user2 = auth_service.signup("maint_user_2", "pass")
            admin = auth_service.signup("maint_admin", "pass", role=UserRole.ADMIN)
            room = create_test_room()

            # 서로 다른 사용자로 미래 예약 2개
            booking1 = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(days=1),
                fixed_time + timedelta(days=2),
            )
            booking2 = room_service.create_booking(
                user2,
                room.id,
                fixed_time + timedelta(days=3),
                fixed_time + timedelta(days=4),
            )

            # 상태 변경
            updated_room, cancelled = room_service.update_room_status(
                admin, room.id, ResourceStatus.MAINTENANCE
            )

            assert updated_room.status == ResourceStatus.MAINTENANCE
            assert len(cancelled) == 2

            for b in cancelled:
                assert b.status == RoomBookingStatus.ADMIN_CANCELLED

            assert auth_service.get_user(user.id).penalty_points == 0
            assert auth_service.get_user(user2.id).penalty_points == 0

    def test_equipment_disabled_cancels_future_bookings(
        self, auth_service, equipment_service, create_test_equipment, mock_now
    ):
        """장비 disabled 시 미래 예약 자동 취소"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("disabled_user", "pass")
            admin = auth_service.signup("disabled_admin", "pass", role=UserRole.ADMIN)
            equipment = create_test_equipment()

            booking = equipment_service.create_booking(
                user,
                equipment.id,
                fixed_time + timedelta(days=1),
                fixed_time + timedelta(days=3),
            )

            updated_eq, cancelled = equipment_service.update_equipment_status(
                admin, equipment.id, ResourceStatus.DISABLED
            )

            assert updated_eq.status == ResourceStatus.DISABLED
            assert len(cancelled) == 1
            assert cancelled[0].status == EquipmentBookingStatus.ADMIN_CANCELLED
            assert auth_service.get_user(user.id).penalty_points == 0


class TestAdminBookingCancellation:
    """관리자 예약 취소"""

    def test_admin_cancels_user_booking(
        self, auth_service, room_service, create_test_room, mock_now
    ):
        """관리자가 사용자 예약 취소"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("cancel_target", "pass")
            admin = auth_service.signup("cancel_admin", "pass", role=UserRole.ADMIN)
            room = create_test_room()

            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(days=1),
                fixed_time + timedelta(days=2),
            )

            # 관리자 취소
            cancelled = room_service.admin_cancel_booking(
                admin, booking.id, "시설 긴급 점검"
            )

            assert cancelled.status == RoomBookingStatus.ADMIN_CANCELLED

    def test_admin_cannot_cancel_checked_in_booking(
        self, auth_service, room_service, create_test_room, mock_now
    ):
        """관리자 취소는 reserved -> admin_cancelled만 허용하고 checked_in 상태는 취소 불가"""
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("checkin_cancel", "pass")
            admin = auth_service.signup("checkin_admin", "pass", role=UserRole.ADMIN)
            room = create_test_room()

            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time,
                fixed_time.replace(hour=18),
            )

            room_service.request_check_in(user, booking.id)
            room_service.check_in(admin, booking.id)

            # 체크인 상태에서는 관리자 취소 불가
            with pytest.raises(RoomBookingError) as exc_info:
                room_service.admin_cancel_booking(admin, booking.id, "긴급 상황")

            assert "reserved" in str(exc_info.value)


class TestAdminModifyBooking:
    """관리자 예약 수정"""

    def test_admin_modifies_user_booking(
        self, auth_service, room_service, create_test_room, mock_now
    ):
        """관리자가 사용자 예약 시간 변경"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("modify_target", "pass")
            admin = auth_service.signup("modify_admin", "pass", role=UserRole.ADMIN)
            room = create_test_room()

            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(days=1),
                fixed_time + timedelta(days=2),
            )

            modified = room_service.admin_modify_booking(
                admin,
                booking.id,
                fixed_time + timedelta(days=3),
                fixed_time + timedelta(days=4),
            )

            assert datetime.fromisoformat(modified.start_time).hour == 9


class TestAdminPenaltyHistory:
    """관리자 패널티 이력 조회"""

    def test_admin_views_user_penalty_history(self, auth_service, penalty_service):
        """관리자가 사용자의 패널티 이력 조회"""
        user = auth_service.signup("history_user", "pass")
        admin = auth_service.signup("history_admin", "pass", role=UserRole.ADMIN)

        # 여러 패널티
        penalty_service.apply_no_show(user, "room_booking", "b1")
        penalty_service.apply_late_cancel(user, "room_booking", "b2")
        penalty_service.apply_damage(
            admin=admin,
            user=user,
            booking_type="equipment_booking",
            booking_id="b3",
            points=2,
            memo="화면 손상",
        )

        # 이력 조회
        history = penalty_service.get_user_penalties(user.id)

        assert len(history) == 3

        reasons = {p.reason for p in history}
        assert PenaltyReason.OTHER in reasons
        assert PenaltyReason.LATE_CANCEL in reasons
        assert PenaltyReason.DAMAGE in reasons


class TestAdminPolicyExecution:
    """관리자 정책 실행"""

    def test_admin_clock_advance_is_blocked_by_unprocessed_start_booking(
        self,
        auth_service,
        policy_service,
        create_test_room,
        room_booking_repo,
        fake_clock,
    ):
        """관리자가 시점 이동을 시도하면 시작 미처리 예약 때문에 차단됨"""
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)
        fake_clock(fixed_time)
        user = auth_service.signup("noshow_user", "pass")
        auth_service.signup("noshow_admin", "pass", role=UserRole.ADMIN)
        room = create_test_room()

        from src.domain.models import RoomBooking, RoomBookingStatus

        booking = RoomBooking(
            id="noshow-booking",
            user_id=user.id,
            room_id=room.id,
            start_time=fixed_time.isoformat(),
            end_time=fixed_time.replace(hour=18).isoformat(),
            status=RoomBookingStatus.RESERVED,
        )
        with global_lock():
            room_booking_repo.add(booking)

        result = policy_service.advance_time(actor_id="noshow-admin")

        assert result["can_advance"] is True


class TestAdminUserManagement:
    """관리자 사용자 관리"""

    def test_admin_views_all_users(self, auth_service):
        """관리자가 모든 사용자 조회"""
        auth_service.signup("user1", "pass")
        auth_service.signup("user2", "pass")
        auth_service.signup("user3", "pass")
        admin = auth_service.signup("admin_viewer", "pass", role=UserRole.ADMIN)

        all_users = auth_service.get_all_users(admin)

        assert len(all_users) == 4

    def test_admin_views_user_status(self, auth_service, penalty_service):
        """관리자가 사용자 패널티 상태 조회"""
        user = auth_service.signup("status_user", "pass")

        # 패널티 부여
        penalty_service.apply_no_show(user, "room_booking", "b1")

        status = penalty_service.get_user_status(user)

        assert status["points"] == 2
        assert status["is_restricted"] is False


class TestAdminActiveBookingReassignment:
    """관리자 진행중 예약 교체 E2E 시나리오"""

    def test_admin_room_reassign_no_eligible_replacement_shows_warning(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_room,
        mock_now,
    ):
        """교체 가능한 회의실이 없을 때 경고 메시지 출력 및 AdminMenu.run() 경로"""
        from src.cli.admin_menu import AdminMenu

        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("no_replacement_user", "pass")
            admin = auth_service.signup("no_replacement_admin", "pass", role=UserRole.ADMIN)

            only_room = create_test_room(name="유일한 회의실")

            booking = room_service.create_booking(
                user,
                only_room.id,
                fixed_time,
                fixed_time.replace(hour=18),
            )
            room_service.request_check_in(user, booking.id)
            room_service.check_in(admin, booking.id)

        printed_info = []

        def capture_print_info(msg):
            printed_info.append(msg)

        input_sequence = ["6", "2", "0"]
        input_index = [0]

        def mock_input(prompt):
            if input_index[0] < len(input_sequence):
                result = input_sequence[input_index[0]]
                input_index[0] += 1
                return result
            return "0"

        def mock_select(items, prompt):
            if "교체할 예약" in prompt:
                return booking.id
            return None

        def mock_confirm(prompt):
            if "로그아웃" in prompt:
                return True
            return False

        monkeypatch.setattr("src.cli.admin_menu.select_from_list", mock_select)
        monkeypatch.setattr("builtins.input", mock_input)
        monkeypatch.setattr("src.cli.admin_menu.confirm", mock_confirm)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_subheader", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_info", capture_print_info)
        monkeypatch.setattr("src.cli.admin_menu.print_warning", capture_print_info)
        monkeypatch.setattr("src.cli.admin_menu.print_success", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_error", lambda x: None)
        monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)

        admin_menu = AdminMenu(
            user=admin,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        service_called = []
        original_reassign = room_service.admin_reassign_active_booking

        def track_reassign(*args, **kwargs):
            service_called.append(True)
            return original_reassign(*args, **kwargs)

        monkeypatch.setattr(room_service, "admin_reassign_active_booking", track_reassign)

        admin_menu.run()

        assert "교체 가능한 회의실이 없습니다." in printed_info
        assert len(service_called) == 0

    def test_admin_equipment_reassign_no_eligible_replacement_shows_warning(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_equipment,
        mock_now,
    ):
        """교체 가능한 장비가 없을 때 경고 메시지 출력 및 AdminMenu.run() 경로"""
        from src.cli.admin_menu import AdminMenu

        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("no_equip_user", "pass")
            admin = auth_service.signup("no_equip_admin", "pass", role=UserRole.ADMIN)

            only_equipment = create_test_equipment(name="유일한 프로젝터")

            booking = equipment_service.create_booking(
                user,
                only_equipment.id,
                fixed_time,
                fixed_time + timedelta(days=3),
            )
            equipment_service.request_pickup(user, booking.id)
            equipment_service.checkout(admin, booking.id)

        printed_info = []

        def capture_print_info(msg):
            printed_info.append(msg)

        input_sequence = ["13", "2", "0"]
        input_index = [0]

        def mock_input(prompt):
            if input_index[0] < len(input_sequence):
                result = input_sequence[input_index[0]]
                input_index[0] += 1
                return result
            return "0"

        def mock_select(items, prompt):
            if "교체할 예약" in prompt:
                return booking.id
            return None

        def mock_confirm(prompt):
            if "로그아웃" in prompt:
                return True
            return False

        monkeypatch.setattr("src.cli.admin_menu.select_from_list", mock_select)
        monkeypatch.setattr("builtins.input", mock_input)
        monkeypatch.setattr("src.cli.admin_menu.confirm", mock_confirm)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_subheader", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_info", capture_print_info)
        monkeypatch.setattr("src.cli.admin_menu.print_warning", capture_print_info)
        monkeypatch.setattr("src.cli.admin_menu.print_success", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_error", lambda x: None)
        monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)

        admin_menu = AdminMenu(
            user=admin,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        service_called = []
        original_reassign = equipment_service.admin_reassign_active_booking

        def track_reassign(*args, **kwargs):
            service_called.append(True)
            return original_reassign(*args, **kwargs)

        monkeypatch.setattr(equipment_service, "admin_reassign_active_booking", track_reassign)

        admin_menu.run()

        assert "교체 가능한 장비가 없습니다." in printed_info
        assert len(service_called) == 0

    def test_admin_room_reassign_happy_path_changes_room_and_preserves_fields(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_room,
        mock_now,
    ):
        """Happy path: admin reassigns active room booking through menu, verifies room changed and fields preserved"""
        from src.cli.admin_menu import AdminMenu

        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("room_happy_user", "pass")
            admin = auth_service.signup("room_happy_admin", "pass", role=UserRole.ADMIN)

            room_a = create_test_room(name="회의실 A")
            room_b = create_test_room(name="회의실 B")

            booking = room_service.create_booking(
                user,
                room_a.id,
                fixed_time,
                fixed_time.replace(hour=18),
            )
            room_service.request_check_in(user, booking.id)
            room_service.check_in(admin, booking.id)

            original_booking = room_service.booking_repo.get_by_id(booking.id)
            original_user_id = original_booking.user_id
            original_start_time = original_booking.start_time
            original_end_time = original_booking.end_time
            original_status = original_booking.status

        printed_info = []

        def capture_print_info(msg):
            printed_info.append(msg)

        input_sequence = ["6", "2", "1", "고장 수리 완료"]
        input_index = [0]

        def mock_input(prompt):
            if input_index[0] < len(input_sequence):
                result = input_sequence[input_index[0]]
                input_index[0] += 1
                return result
            return "0"

        call_count = [0]

        def mock_select(items, prompt):
            call_count[0] += 1
            if "교체할 예약" in prompt:
                return booking.id
            elif "새 회의실" in prompt or "회의실 선택" in prompt:
                return room_b.id
            return None

        def mock_confirm(prompt):
            if "로그아웃" in prompt:
                return True
            elif "교체하시겠습니까" in prompt:
                return True
            return False

        monkeypatch.setattr("src.cli.admin_menu.select_from_list", mock_select)
        monkeypatch.setattr("builtins.input", mock_input)
        monkeypatch.setattr("src.cli.admin_menu.confirm", mock_confirm)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_subheader", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_info", capture_print_info)
        monkeypatch.setattr("src.cli.admin_menu.print_warning", capture_print_info)
        monkeypatch.setattr("src.cli.admin_menu.print_success", capture_print_info)
        monkeypatch.setattr("src.cli.admin_menu.print_error", lambda x: None)
        monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)

        admin_menu = AdminMenu(
            user=admin,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        service_called = []
        original_reassign = room_service.admin_reassign_active_booking

        def track_reassign(*args, **kwargs):
            service_called.append(True)
            return original_reassign(*args, **kwargs)

        monkeypatch.setattr(room_service, "admin_reassign_active_booking", track_reassign)

        admin_menu.run()

        assert len(service_called) == 1
        assert any("교체되었습니다" in msg for msg in printed_info)

        updated_booking = room_service.booking_repo.get_by_id(booking.id)
        assert updated_booking.room_id == room_b.id
        assert updated_booking.user_id == original_user_id
        assert updated_booking.start_time == original_start_time
        assert updated_booking.end_time == original_end_time
        assert updated_booking.status == original_status

    def test_admin_equipment_reassign_happy_path_changes_equipment_and_preserves_fields(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_equipment,
        mock_now,
    ):
        """Happy path: admin reassigns active equipment booking through menu, verifies equipment changed and fields preserved"""
        from src.cli.admin_menu import AdminMenu

        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("equip_happy_user", "pass")
            admin = auth_service.signup("equip_happy_admin", "pass", role=UserRole.ADMIN)

            equipment_a = create_test_equipment(name="프로젝터 1")
            equipment_b = create_test_equipment(name="프로젝터 2")

            booking = equipment_service.create_booking(
                user,
                equipment_a.id,
                fixed_time,
                fixed_time + timedelta(days=3),
            )
            equipment_service.request_pickup(user, booking.id)
            equipment_service.checkout(admin, booking.id)

            original_booking = equipment_service.booking_repo.get_by_id(booking.id)
            original_user_id = original_booking.user_id
            original_start_time = original_booking.start_time
            original_end_time = original_booking.end_time
            original_status = original_booking.status

        printed_info = []

        def capture_print_info(msg):
            printed_info.append(msg)

        input_sequence = ["13", "2", "1", "기계 오류로 교체"]
        input_index = [0]

        def mock_input(prompt):
            if input_index[0] < len(input_sequence):
                result = input_sequence[input_index[0]]
                input_index[0] += 1
                return result
            return "0"

        call_count = [0]

        def mock_select(items, prompt):
            call_count[0] += 1
            if "교체할 예약" in prompt:
                return booking.id
            elif "새 장비" in prompt or "장비 선택" in prompt:
                return equipment_b.id
            return None

        def mock_confirm(prompt):
            if "로그아웃" in prompt:
                return True
            elif "교체하시겠습니까" in prompt:
                return True
            return False

        monkeypatch.setattr("src.cli.admin_menu.select_from_list", mock_select)
        monkeypatch.setattr("builtins.input", mock_input)
        monkeypatch.setattr("src.cli.admin_menu.confirm", mock_confirm)
        monkeypatch.setattr("src.cli.admin_menu.pause", lambda: None)
        monkeypatch.setattr("src.cli.admin_menu.print_header", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_subheader", lambda x: None)
        monkeypatch.setattr("src.cli.admin_menu.print_info", capture_print_info)
        monkeypatch.setattr("src.cli.admin_menu.print_warning", capture_print_info)
        monkeypatch.setattr("src.cli.admin_menu.print_success", capture_print_info)
        monkeypatch.setattr("src.cli.admin_menu.print_error", lambda x: None)
        monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)

        admin_menu = AdminMenu(
            user=admin,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )

        service_called = []
        original_reassign = equipment_service.admin_reassign_active_booking

        def track_reassign(*args, **kwargs):
            service_called.append(True)
            return original_reassign(*args, **kwargs)

        monkeypatch.setattr(equipment_service, "admin_reassign_active_booking", track_reassign)

        admin_menu.run()

        assert len(service_called) == 1
        assert any("교체되었습니다" in msg for msg in printed_info)

        updated_booking = equipment_service.booking_repo.get_by_id(booking.id)
        assert updated_booking.equipment_id == equipment_b.id
        assert updated_booking.user_id == original_user_id
        assert updated_booking.start_time == original_start_time
        assert updated_booking.end_time == original_end_time
        assert updated_booking.status == original_status
