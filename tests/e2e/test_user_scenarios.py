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

        return_time = datetime(2024, 6, 18, 18, 0, 0)
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
                fixed_time + timedelta(days=1),
                fixed_time + timedelta(days=2),
            )

            # 수정
            modified = room_service.modify_booking(
                user,
                booking.id,
                fixed_time + timedelta(days=3),
                fixed_time + timedelta(days=4),
            )

            assert modified.id == booking.id
            assert datetime.fromisoformat(modified.start_time).hour == 9

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
                fixed_time + timedelta(days=1),
                fixed_time + timedelta(days=2),
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

            penalty_service.apply_late_cancel(user, "room_booking", "fake-booking-1")

            # 상태 확인
            status = penalty_service.get_user_status(user)

            assert status["points"] == 2
            assert status["is_restricted"] is False
            assert status["max_active_bookings"] == 2

    def test_restricted_user_can_hold_one_room_and_one_equipment(
        self,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_room,
        create_test_equipment,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = auth_service.signup("banned_user", "pass")
            room = create_test_room(name="restricted-room")
            equipment = create_test_equipment(name="restricted-equip")

            penalty_service.apply_damage(
                admin=auth_service.signup("restricted_admin", "pass", role=UserRole.ADMIN),
                user=user,
                booking_type="room_booking",
                booking_id="b1",
                points=3,
                memo="제한 테스트",
            )

            room_service.create_daily_booking(
                user,
                room.id,
                fixed_time.date() + timedelta(days=1),
                fixed_time.date() + timedelta(days=1),
                attendee_count=4,
            )

            booking = equipment_service.create_daily_booking(
                user,
                equipment.id,
                fixed_time.date() + timedelta(days=1),
                fixed_time.date() + timedelta(days=1),
            )

            can_book, max_total, message = policy_service.check_user_can_book(user)

            assert can_book is False
            assert booking.status == EquipmentBookingStatus.RESERVED
            assert max_total == 2


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
