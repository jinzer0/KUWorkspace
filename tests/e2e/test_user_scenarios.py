"""
사용자 시나리오 E2E 테스트

테스트 대상:
- 회원가입 → 로그인 → 예약 → 체크인 → 퇴실 전체 흐름
- 예약 수정/취소 흐름
- 패널티 누적에 따른 제한
- 정상 이용 연속 보너스
"""

import pytest
from datetime import datetime, timedelta

from src.domain.auth_service import AuthError
from src.domain.room_service import RoomBookingError
from src.domain.models import (
    UserRole,
    RoomBookingStatus,
    EquipmentBookingStatus,
    MessageType,
)


class TestUserSignupLoginFlow:
    """회원가입 → 로그인 흐름"""

    def test_signup_and_login_flow(self, auth_service):
        """정상 회원가입 후 로그인"""
        # 회원가입
        user = auth_service.signup(username="e2e_user", password="securepass123")

        assert user.id is not None
        assert user.role == UserRole.USER

        # 로그인
        logged_in = auth_service.login("e2e_user", "securepass123")

        assert logged_in.id == user.id

    def test_signup_duplicate_then_login(self, auth_service):
        """중복 가입 시도 후 기존 계정 로그인"""
        auth_service.signup("existing_user", "pass1")

        # 중복 시도
        with pytest.raises(AuthError):
            auth_service.signup("existing_user", "pass2")

        # 원래 비밀번호로 로그인
        user = auth_service.login("existing_user", "pass1")
        assert user.username == "existing_user"


class TestBookingCompleteFlow:
    """예약 → 체크인 → 퇴실 전체 흐름"""

    def test_room_booking_complete_flow(
        self, auth_service, room_service, penalty_service, create_test_room, mock_now
    ):
        """회의실 예약부터 정상 퇴실까지"""
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            # 1. 회원가입
            user = auth_service.signup("booking_user", "pass")
            admin = auth_service.signup("admin_user", "pass", role=UserRole.ADMIN)

            # 2. 회의실 생성
            room = create_test_room(name="E2E Room")

            # 3. 예약 생성
            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time,
                fixed_time.replace(hour=18),
            )

            assert booking.status == RoomBookingStatus.RESERVED

            requested = room_service.request_check_in(user, booking.id)
            assert requested.status == RoomBookingStatus.CHECKIN_REQUESTED
            checked_in = room_service.check_in(admin, booking.id)
            assert checked_in.status == RoomBookingStatus.CHECKED_IN

        checkout_time = datetime(2024, 6, 15, 18, 0, 0)
        with mock_now(checkout_time):
            requested = room_service.request_checkout(user, booking.id)
            assert requested.status == RoomBookingStatus.CHECKOUT_REQUESTED
            completed, delay = room_service.approve_checkout_request(admin, booking.id)

            assert completed.status == RoomBookingStatus.COMPLETED
            assert delay == 0

            # 6. 정상 이용 기록 - check_out이 자동으로 record_normal_use 호출
            updated_user = auth_service.get_user(user.id)
            assert updated_user.normal_use_streak == 1

    def test_equipment_booking_complete_flow(
        self,
        auth_service,
        equipment_service,
        penalty_service,
        create_test_equipment,
        mock_now,
    ):
        """장비 예약부터 정상 반납까지"""
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("eq_user", "pass")
            admin = auth_service.signup("eq_admin", "pass", role=UserRole.ADMIN)

            equipment = create_test_equipment(name="E2E Laptop")

            # 예약
            booking = equipment_service.create_booking(
                user,
                equipment.id,
                fixed_time,
                fixed_time + timedelta(days=3),
            )

            requested = equipment_service.request_pickup(user, booking.id)
            assert requested.status == EquipmentBookingStatus.PICKUP_REQUESTED
            checked_out = equipment_service.checkout(admin, booking.id)
            assert checked_out.status == EquipmentBookingStatus.CHECKED_OUT

        return_time = datetime(2024, 6, 18, 9, 0, 0)
        with mock_now(return_time):
            requested = equipment_service.request_return(user, booking.id)
            assert requested.status == EquipmentBookingStatus.RETURN_REQUESTED
            returned, delay = equipment_service.approve_return_request(admin, booking.id)

            assert returned.status == EquipmentBookingStatus.RETURNED
            assert delay == 0


class TestBookingModificationFlow:
    """예약 수정/취소 흐름"""

    def test_modify_booking_flow(
        self, auth_service, room_service, create_test_room, mock_now
    ):
        """예약 수정 흐름"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("modify_user", "pass")
            room = create_test_room()

            # 원래 예약
            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )

            # 수정
            modified = room_service.modify_booking(
                user,
                booking.id,
                fixed_time + timedelta(hours=3),
                fixed_time + timedelta(hours=4),
            )

            assert modified.id == booking.id
            assert datetime.fromisoformat(modified.start_time).hour == 13

    def test_cancel_booking_normal_flow(
        self, auth_service, room_service, create_test_room, mock_now
    ):
        """정상 취소 흐름 (직전 취소 아님)"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("cancel_user", "pass")
            room = create_test_room()

            # 2시간 후 예약
            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=2),
                fixed_time + timedelta(hours=3),
            )

            # 취소
            cancelled, is_late = room_service.cancel_booking(user, booking.id)

            assert cancelled.status == RoomBookingStatus.CANCELLED
            assert is_late is False


class TestPenaltyAccumulationFlow:
    """패널티 누적 흐름"""

    def test_penalty_accumulation_restricts_booking(
        self,
        auth_service,
        room_service,
        penalty_service,
        policy_service,
        create_test_room,
        mock_now,
    ):
        """패널티 누적으로 인한 예약 제한"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("penalty_user", "pass")

            # 노쇼로 3점 부여
            penalty_service.apply_no_show(user, "room_booking", "fake-booking-1")

            # 상태 확인
            status = penalty_service.get_user_status(user)

            assert status["points"] == 3
            assert status["is_restricted"] is True
            assert status["max_active_bookings"] == 1

    def test_penalty_6_points_bans_user(
        self, auth_service, penalty_service, policy_service, mock_now
    ):
        """6점 이상 시 이용 금지"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("banned_user", "pass")

            # 노쇼 2번 = 6점
            penalty_service.apply_no_show(user, "room_booking", "b1")
            penalty_service.apply_no_show(user, "room_booking", "b2")

            can_book, max_total, message = policy_service.check_user_can_book(user)

            assert can_book is False
            assert max_total == 0
            assert "금지" in message


class TestStreakBonusFlow:
    """정상 이용 연속 보너스 흐름"""

    def test_streak_10_reduces_penalty(self, auth_service, penalty_service, mock_now):
        """10회 연속 정상 이용 시 1점 감소"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("streak_user", "pass")

            # 처음에 패널티 부여
            penalty_service.apply_late_cancel(user, "room_booking", "b1")  # +2점

            updated = auth_service.get_user(user.id)
            assert updated.penalty_points == 2

            # 9회 정상 이용
            for _ in range(9):
                penalty_service.record_normal_use(user)

            updated = auth_service.get_user(user.id)
            assert updated.normal_use_streak == 9
            assert updated.penalty_points == 2  # 아직 변화 없음

            # 10회째 정상 이용
            reduced = penalty_service.record_normal_use(user)

            assert reduced is True

            updated = auth_service.get_user(user.id)
            assert updated.normal_use_streak == 0  # 리셋
            assert updated.penalty_points == 1  # 1점 감소


class TestLateReturnPenaltyFlow:
    """지연 반납 패널티 흐름"""

    def test_checkout_requires_exact_boundary(
        self, auth_service, room_service, penalty_service, create_test_room, mock_now
    ):
        """종료 경계를 벗어나면 퇴실 처리할 수 없음"""
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("late_user", "pass")
            admin = auth_service.signup("late_admin", "pass", role=UserRole.ADMIN)
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

        late_time = datetime(2024, 6, 15, 18, 25, 0)
        with mock_now(late_time):
            with pytest.raises(RoomBookingError) as exc_info:
                room_service.check_out(admin, booking.id)

            assert "현재 운영 시점" in str(exc_info.value)
            updated = auth_service.get_user(user.id)
            assert updated.penalty_points == 0


class TestMultipleBookingsFlow:
    """여러 예약 관리 흐름"""

    def test_user_max_1_room_booking(
        self,
        auth_service,
        room_service,
        create_test_room,
        room_factory,
        room_repo,
        mock_now,
    ):
        """사용자는 최대 1개의 회의실 활성 예약만 가질 수 있다."""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("multi_booking_user", "pass")

            rooms = [create_test_room(name=f"Room {i}") for i in range(2)]

            room_service.create_booking(
                user,
                rooms[0].id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )

            # 2번째 예약 실패
            with pytest.raises(RoomBookingError) as exc_info:
                room_service.create_booking(
                    user,
                    rooms[1].id,
                    fixed_time + timedelta(hours=3),
                    fixed_time + timedelta(hours=4),
                )

            assert "한도" in str(exc_info.value) or "초과" in str(exc_info.value)


class TestInquiryReportSubmissionFlow:
    """사용자 문의/신고 제출 E2E 테스트 - 정확한 JSON Lines 레코드 키 검증"""

    def test_inquiry_submission_persists_exact_keys(
        self,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        message_service,
        monkeypatch,
    ):
        """문의 제출이 정확히 5개 키를 가진 JSON Lines 레코드로 저장됨 (사용자 메뉴 흐름)"""
        from src.cli.user_menu import UserMenu

        user = auth_service.signup("inquiry_user", "pass123")
        menu = UserMenu(
            user=user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
            message_service=message_service,
        )

        inputs = iter(["1", "회의실 예약 문의입니다", "y"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.print_success", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)

        menu._submit_message()

        saved_messages = message_service.message_repo.get_by_user(user.id)
        assert len(saved_messages) == 1

        persisted = saved_messages[0]
        persisted_dict = persisted.to_dict()
        expected_keys = {"id", "user_id", "created_at", "type", "content"}
        actual_keys = set(persisted_dict.keys())

        assert (
            actual_keys == expected_keys
        ), f"Expected keys {expected_keys}, but got {actual_keys}"

        assert persisted_dict["user_id"] == user.id
        assert persisted_dict["type"] == "inquiry"
        assert persisted_dict["content"] == "회의실 예약 문의입니다"
        assert persisted_dict["created_at"] is not None

    def test_report_submission_persists_exact_keys(
        self,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        message_service,
        monkeypatch,
    ):
        """신고 제출이 정확히 5개 키를 가진 JSON Lines 레코드로 저장됨 (사용자 메뉴 흐름)"""
        from src.cli.user_menu import UserMenu

        user = auth_service.signup("report_user", "pass123")
        menu = UserMenu(
            user=user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
            message_service=message_service,
        )

        inputs = iter(["2", "부정한 예약 신고합니다", "y"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.print_success", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)

        menu._submit_message()

        saved_messages = message_service.message_repo.get_by_user(user.id)
        assert len(saved_messages) == 1

        persisted = saved_messages[0]
        persisted_dict = persisted.to_dict()
        expected_keys = {"id", "user_id", "created_at", "type", "content"}
        actual_keys = set(persisted_dict.keys())

        assert actual_keys == expected_keys

        assert persisted_dict["type"] == "report"
        assert persisted_dict["content"] == "부정한 예약 신고합니다"

    def test_multiple_submissions_append_as_separate_records(
        self,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        message_service,
        monkeypatch,
    ):
        """여러 제출이 별도의 레코드로 추가됨 (append-only, 사용자 메뉴 흐름)"""
        from src.cli.user_menu import UserMenu

        user = auth_service.signup("multi_submit_user", "pass123")
        menu = UserMenu(
            user=user,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
            message_service=message_service,
        )

        monkeypatch.setattr("src.cli.user_menu.print_header", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.print_success", lambda *_: None)
        monkeypatch.setattr("src.cli.user_menu.pause", lambda: None)

        inputs = iter(["1", "첫번째 문의", "y"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
        menu._submit_message()

        inputs = iter(["2", "첫번째 신고", "y"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
        menu._submit_message()

        inputs = iter(["1", "두번째 문의", "y"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
        menu._submit_message()

        saved_messages = message_service.message_repo.get_by_user(user.id)
        assert len(saved_messages) == 3

        assert saved_messages[0].content == "첫번째 문의"
        assert saved_messages[0].type == MessageType.INQUIRY

        assert saved_messages[1].content == "첫번째 신고"
        assert saved_messages[1].type == MessageType.REPORT

        assert saved_messages[2].content == "두번째 문의"
        assert saved_messages[2].type == MessageType.INQUIRY

        for message in saved_messages:
            keys = set(message.to_dict().keys())
            assert keys == {"id", "user_id", "created_at", "type", "content"}

    def test_newline_content_never_persists(
        self, auth_service, message_service, message_repo
    ):
        """줄바꿈이 포함된 내용은 거부되고 저장되지 않음 (regression)"""
        user = auth_service.signup("newline_test_user", "pass123")

        # 줄바꿈을 포함한 내용들 시도
        invalid_contents = [
            "line1\nline2",  # LF
            "line1\rline2",  # CR
            "line1\r\nline2",  # CRLF
            "\n",  # 줄바꿈만
            "content\n",  # 끝에 줄바꿈
        ]

        for invalid_content in invalid_contents:
            with pytest.raises(Exception):
                message_service.create_message(
                    user_id=user.id,
                    message_type="inquiry",
                    content=invalid_content,
                )

        # 어떤 메시지도 저장되지 않았는지 확인
        saved_messages = message_repo.get_by_user(user.id)
        assert len(saved_messages) == 0
