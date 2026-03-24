"""
회의실 서비스 테스트

테스트 대상:
- 예약 생성: 정상, 충돌, 시간 유효성, 한도 초과
- 예약 수정: 정상, 권한 확인, 상태 확인
- 예약 취소: 정상, 직전 취소 판정
- 체크인/체크아웃: 정상, 지연 계산
- 노쇼 처리
- 관리자 기능: 예약 수정/취소, 상태 변경
"""

import pytest
from datetime import datetime, timedelta
from dataclasses import replace

from src.domain.room_service import RoomBookingError
from src.domain.models import (
    EquipmentBookingStatus,
    RoomBooking,
    RoomBookingStatus,
    ResourceStatus,
    UserRole,
)
from src.storage.file_lock import global_lock


class TestCreateBooking:
    """예약 생성 테스트"""

    def test_create_booking_success(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """정상 예약 생성"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room(status=ResourceStatus.AVAILABLE)

            # 1시간 후 시작, 2시간 후 종료
            start = fixed_time + timedelta(hours=1)
            end = fixed_time + timedelta(hours=2)

            booking = room_service.create_booking(
                user=user, room_id=room.id, start_time=start, end_time=end
            )

            assert booking.id is not None
            assert booking.user_id == user.id
            assert booking.room_id == room.id
            assert booking.status == RoomBookingStatus.RESERVED

    def test_create_booking_room_not_found(
        self, room_service, create_test_user, mock_now
    ):
        """존재하지 않는 회의실로 예약 시 실패"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.create_booking(
                    user=user,
                    room_id="nonexistent-room",
                    start_time=fixed_time + timedelta(hours=1),
                    end_time=fixed_time + timedelta(hours=2),
                )

            assert "존재하지 않는 회의실" in str(exc_info.value)

    def test_create_booking_nonexistent_user_rejected(
        self, room_service, user_factory, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = user_factory(username="ghost-user")
            room = create_test_room()

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.create_booking(
                    user=user,
                    room_id=room.id,
                    start_time=fixed_time + timedelta(hours=1),
                    end_time=fixed_time + timedelta(hours=2),
                )

            assert "존재하지 않는 사용자" in str(exc_info.value)

    def test_create_booking_room_maintenance(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """유지보수 중인 회의실 예약 시 실패"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room(status=ResourceStatus.MAINTENANCE)

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.create_booking(
                    user=user,
                    room_id=room.id,
                    start_time=fixed_time + timedelta(hours=1),
                    end_time=fixed_time + timedelta(hours=2),
                )

            assert "maintenance" in str(exc_info.value)

    def test_create_booking_time_conflict(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """시간 충돌 시 실패"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user1 = create_test_user(username="user1")
            user2 = create_test_user(username="user2")
            room = create_test_room()

            start = fixed_time + timedelta(hours=1)
            end = fixed_time + timedelta(hours=2)

            # 첫 번째 예약 성공
            room_service.create_booking(user1, room.id, start, end)

            # 같은 시간대 두 번째 예약 실패
            with pytest.raises(RoomBookingError) as exc_info:
                room_service.create_booking(user2, room.id, start, end)

            assert "이미 예약이 있습니다" in str(exc_info.value)

    def test_create_booking_overlapping_conflict(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """겹치는 시간대 충돌 감지"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user1 = create_test_user(username="user1")
            user2 = create_test_user(username="user2")
            room = create_test_room()

            # 첫 번째 예약: 11:00 ~ 13:00
            room_service.create_booking(
                user1,
                room.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=3),
            )

            # 겹치는 예약 시도: 12:00 ~ 14:00
            with pytest.raises(RoomBookingError):
                room_service.create_booking(
                    user2,
                    room.id,
                    fixed_time + timedelta(hours=2),
                    fixed_time + timedelta(hours=4),
                )

    def test_create_booking_exceeds_max_active(
        self,
        room_service,
        create_test_user,
        create_test_room,
        room_factory,
        room_repo,
        mock_now,
    ):
        """최대 활성 예약 수 초과 시 실패"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()

            # 3개의 서로 다른 회의실 생성
            rooms = []
            with global_lock():
                for i in range(4):
                    room = room_factory(name=f"Room {i}")
                    room_repo.add(room)
                    rooms.append(room)

            # 3개 예약 생성 (한도)
            for i in range(3):
                room_service.create_booking(
                    user,
                    rooms[i].id,
                    fixed_time + timedelta(hours=i + 1),
                    fixed_time + timedelta(hours=i + 2),
                )

            # 4번째 예약 시 실패
            with pytest.raises(RoomBookingError) as exc_info:
                room_service.create_booking(
                    user,
                    rooms[3].id,
                    fixed_time + timedelta(hours=5),
                    fixed_time + timedelta(hours=6),
                )

            assert "한도" in str(exc_info.value) or "초과" in str(exc_info.value)

    def test_create_booking_cannot_bypass_limit_with_large_max_active(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            rooms = [create_test_room(name=f"Bypass Room {i}") for i in range(4)]

            for i in range(3):
                room_service.create_booking(
                    user,
                    rooms[i].id,
                    fixed_time + timedelta(hours=i + 1),
                    fixed_time + timedelta(hours=i + 2),
                    max_active=99,
                )

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.create_booking(
                    user,
                    rooms[3].id,
                    fixed_time + timedelta(hours=5),
                    fixed_time + timedelta(hours=6),
                    max_active=99,
                )

            assert "3건" in str(exc_info.value)

    def test_create_booking_restricted_user_with_existing_equipment_booking_fails(
        self,
        room_service,
        create_test_user,
        create_test_room,
        equipment_booking_repo,
        equipment_booking_factory,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user(
                penalty_points=3,
                restriction_until=(fixed_time + timedelta(days=7)).isoformat(),
            )
            room = create_test_room()

            existing = equipment_booking_factory(
                user_id=user.id,
                start_time=(fixed_time + timedelta(hours=1)).isoformat(),
                end_time=(fixed_time + timedelta(days=1)).isoformat(),
                status=EquipmentBookingStatus.RESERVED,
            )
            with global_lock():
                equipment_booking_repo.add(existing)

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.create_booking(
                    user=user,
                    room_id=room.id,
                    start_time=fixed_time + timedelta(hours=2),
                    end_time=fixed_time + timedelta(hours=3),
                )

            assert "1건만 허용" in str(exc_info.value)

    def test_create_booking_banned_user_rejected(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user(
                penalty_points=6,
                restriction_until=(fixed_time + timedelta(days=30)).isoformat(),
            )
            room = create_test_room()

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.create_booking(
                    user=user,
                    room_id=room.id,
                    start_time=fixed_time + timedelta(hours=1),
                    end_time=fixed_time + timedelta(hours=2),
                )

            assert "이용이 금지된 상태" in str(exc_info.value)


class TestBookingTimeValidation:
    """예약 시간 유효성 검사 테스트"""

    def test_past_time_rejected(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """과거 시간 예약 거부"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room()

            # 1시간 전 시작
            with pytest.raises(RoomBookingError) as exc_info:
                room_service.create_booking(
                    user,
                    room.id,
                    fixed_time - timedelta(hours=1),
                    fixed_time + timedelta(hours=1),
                )

            assert "과거 시간" in str(exc_info.value)

    def test_end_before_start_rejected(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """종료 시간이 시작 시간 이전이면 거부"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room()

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.create_booking(
                    user,
                    room.id,
                    fixed_time + timedelta(hours=2),
                    fixed_time + timedelta(hours=1),
                )

            assert "시작 시간 이후" in str(exc_info.value)

    def test_beyond_14_days_rejected(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """14일 이후 예약 거부"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room()

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.create_booking(
                    user,
                    room.id,
                    fixed_time + timedelta(days=15),
                    fixed_time + timedelta(days=15, hours=1),
                )

            assert "14일 이내" in str(exc_info.value)

    def test_not_30_minute_slot_rejected(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """30분 단위가 아닌 시간 거부"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room()

            # 시작 시간이 10:15 (30분 단위 아님)
            with pytest.raises(RoomBookingError) as exc_info:
                room_service.create_booking(
                    user,
                    room.id,
                    fixed_time + timedelta(hours=1, minutes=15),
                    fixed_time + timedelta(hours=2),
                )

            assert "30분 단위" in str(exc_info.value)


class TestModifyBooking:
    """예약 수정 테스트"""

    def test_modify_booking_success(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """정상 예약 수정"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room()

            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )

            # 시간 변경
            modified = room_service.modify_booking(
                user,
                booking.id,
                fixed_time + timedelta(hours=3),
                fixed_time + timedelta(hours=4),
            )

            assert modified.id == booking.id
            assert datetime.fromisoformat(modified.start_time).hour == 13

    def test_modify_booking_not_owner(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """다른 사용자의 예약 수정 시 실패"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user1 = create_test_user(username="user1")
            user2 = create_test_user(username="user2")
            room = create_test_room()

            booking = room_service.create_booking(
                user1,
                room.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.modify_booking(
                    user2,
                    booking.id,
                    fixed_time + timedelta(hours=3),
                    fixed_time + timedelta(hours=4),
                )

            assert "본인의 예약만" in str(exc_info.value)

    def test_modify_booking_wrong_status(
        self,
        room_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        mock_now,
    ):
        """reserved 상태가 아닌 예약 수정 시 실패"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room()

            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )

            # 상태를 CHECKED_IN으로 변경
            checked_in = replace(booking, status=RoomBookingStatus.CHECKED_IN)
            with global_lock():
                room_booking_repo.update(checked_in)

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.modify_booking(
                    user,
                    booking.id,
                    fixed_time + timedelta(hours=3),
                    fixed_time + timedelta(hours=4),
                )

            assert "변경할 수 없습니다" in str(exc_info.value)

    def test_modify_booking_runs_policy_checks_before_action(
        self, room_service, auth_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room()
            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )

        with mock_now(datetime(2024, 6, 15, 11, 16, 0)):
            with pytest.raises(RoomBookingError) as exc_info:
                room_service.modify_booking(
                    user,
                    booking.id,
                    fixed_time + timedelta(hours=3),
                    fixed_time + timedelta(hours=4),
                )

            assert "no_show" in str(exc_info.value)
            assert (
                room_service.booking_repo.get_by_id(booking.id).status
                == RoomBookingStatus.NO_SHOW
            )
            assert auth_service.get_user(user.id).penalty_points == 3


class TestCancelBooking:
    """예약 취소 테스트"""

    def test_cancel_booking_success(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """정상 예약 취소"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room()

            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=2),  # 2시간 후
                fixed_time + timedelta(hours=3),
            )

            cancelled, is_late = room_service.cancel_booking(user, booking.id)

            assert cancelled.status == RoomBookingStatus.CANCELLED
            assert is_late is False  # 2시간 전이므로 직전 취소 아님

    def test_cancel_booking_late_cancel(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """직전 취소 판정 (1시간 이내)"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room()

            # 30분 후 시작 예약
            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(minutes=30),
                fixed_time + timedelta(hours=1, minutes=30),
            )

            cancelled, is_late = room_service.cancel_booking(user, booking.id)

            assert is_late is True  # 30분 전이므로 직전 취소

    def test_cancel_booking_not_owner(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """다른 사용자의 예약 취소 시 실패"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user1 = create_test_user(username="user1")
            user2 = create_test_user(username="user2")
            room = create_test_room()

            booking = room_service.create_booking(
                user1,
                room.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )

            with pytest.raises(RoomBookingError):
                room_service.cancel_booking(user2, booking.id)

    def test_cancel_booking_runs_policy_checks_before_action(
        self, room_service, auth_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room()
            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )

        with mock_now(datetime(2024, 6, 15, 11, 16, 0)):
            with pytest.raises(RoomBookingError) as exc_info:
                room_service.cancel_booking(user, booking.id)

            assert "no_show" in str(exc_info.value)
            assert (
                room_service.booking_repo.get_by_id(booking.id).status
                == RoomBookingStatus.NO_SHOW
            )
            assert auth_service.get_user(user.id).penalty_points == 3


class TestCheckInOut:
    """체크인/체크아웃 테스트"""

    def test_check_in_success(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """정상 체크인"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            room = create_test_room()

            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )

            checked_in = room_service.check_in(admin, booking.id)

            assert checked_in.status == RoomBookingStatus.CHECKED_IN
            assert checked_in.checked_in_at is not None

    def test_check_in_runs_policy_checks_before_action(
        self,
        room_service,
        auth_service,
        create_test_user,
        create_test_room,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            room = create_test_room()
            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )

        with mock_now(datetime(2024, 6, 15, 11, 16, 0)):
            with pytest.raises(RoomBookingError) as exc_info:
                room_service.check_in(admin, booking.id)

            assert "no_show" in str(exc_info.value)
            assert (
                room_service.booking_repo.get_by_id(booking.id).status
                == RoomBookingStatus.NO_SHOW
            )
            assert auth_service.get_user(user.id).penalty_points == 3

    def test_check_in_missing_booking_user_fails(
        self,
        room_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            room = create_test_room()
            booking = RoomBooking(
                id="room-missing-user-checkin",
                user_id="missing-user",
                room_id=room.id,
                start_time=(fixed_time + timedelta(hours=1)).isoformat(),
                end_time=(fixed_time + timedelta(hours=2)).isoformat(),
                status=RoomBookingStatus.RESERVED,
            )
            with global_lock():
                room_booking_repo.add(booking)

        with mock_now(fixed_time + timedelta(hours=1, minutes=10)):
            with pytest.raises(RoomBookingError) as exc_info:
                room_service.check_in(admin, booking.id)

            assert "존재하지 않는 사용자" in str(exc_info.value)

    def test_default_room_service_still_applies_no_show_policy(
        self,
        room_repo,
        room_booking_repo,
        equipment_booking_repo,
        user_repo,
        audit_repo,
        auth_service,
        create_test_user,
        create_test_room,
        mock_now,
    ):
        from src.domain.room_service import RoomService

        fixed_time = datetime(2024, 6, 15, 10, 0, 0)
        with mock_now(fixed_time):
            service = RoomService(
                room_repo=room_repo,
                booking_repo=room_booking_repo,
                equipment_booking_repo=equipment_booking_repo,
                user_repo=user_repo,
                audit_repo=audit_repo,
            )
            user = create_test_user()
            admin = create_test_user(username="admin-default", role=UserRole.ADMIN)
            room = create_test_room()
            booking = service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )

        with mock_now(datetime(2024, 6, 15, 11, 16, 0)):
            with pytest.raises(RoomBookingError):
                service.check_in(admin, booking.id)

            updated_booking = service.booking_repo.get_by_id(booking.id)
            assert updated_booking is not None
            assert updated_booking.status == RoomBookingStatus.NO_SHOW
            assert auth_service.get_user(user.id).penalty_points == 3

    def test_check_out_on_time(
        self,
        room_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        mock_now,
    ):
        """정시 퇴실 (지연 0분)"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            room = create_test_room()

            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),  # 12:00 종료
            )

            room_service.check_in(admin, booking.id)

        # 12:00에 퇴실 (종료 시간 정각)
        checkout_time = datetime(2024, 6, 15, 12, 0, 0)
        with mock_now(checkout_time):
            completed, delay = room_service.check_out(admin, booking.id)

            assert completed.status == RoomBookingStatus.COMPLETED
            assert delay == 0

    def test_check_out_late(
        self,
        room_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        mock_now,
    ):
        """지연 퇴실"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            room = create_test_room()

            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),  # 12:00 종료
            )

            room_service.check_in(admin, booking.id)

        # 12:30에 퇴실 (30분 지연)
        late_time = datetime(2024, 6, 15, 12, 30, 0)
        with mock_now(late_time):
            completed, delay = room_service.check_out(admin, booking.id)

            assert delay == 30

    def test_check_out_missing_booking_user_fails(
        self,
        room_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            room = create_test_room()
            booking = RoomBooking(
                id="room-missing-user-checkout",
                user_id="missing-user",
                room_id=room.id,
                start_time=(fixed_time + timedelta(hours=1)).isoformat(),
                end_time=(fixed_time + timedelta(hours=2)).isoformat(),
                status=RoomBookingStatus.CHECKED_IN,
            )
            with global_lock():
                room_booking_repo.add(booking)

        with mock_now(datetime(2024, 6, 15, 12, 0, 0)):
            with pytest.raises(RoomBookingError) as exc_info:
                room_service.check_out(admin, booking.id)

            assert "존재하지 않는 사용자" in str(exc_info.value)


class TestNoShow:
    """노쇼 처리 테스트"""

    def test_mark_no_show(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """노쇼 처리"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room()

            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )

            no_show = room_service.mark_no_show(booking.id)

            assert no_show.status == RoomBookingStatus.NO_SHOW
            assert room_service.user_repo.get_by_id(user.id).penalty_points == 3

    def test_mark_no_show_missing_user_fails(
        self, room_service, create_test_room, room_booking_repo, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            room = create_test_room()
            booking = RoomBooking(
                id="room-noshow-missing-user",
                user_id="missing-user",
                room_id=room.id,
                start_time=(fixed_time + timedelta(hours=1)).isoformat(),
                end_time=(fixed_time + timedelta(hours=2)).isoformat(),
                status=RoomBookingStatus.RESERVED,
            )
            with global_lock():
                room_booking_repo.add(booking)

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.mark_no_show(booking.id)

            assert "존재하지 않는 사용자" in str(exc_info.value)


class TestAdminFunctions:
    """관리자 기능 테스트"""

    def test_admin_cancel_booking(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """관리자 예약 취소"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            room = create_test_room()

            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )

            cancelled = room_service.admin_cancel_booking(
                admin, booking.id, "시설 점검"
            )

            assert cancelled.status == RoomBookingStatus.ADMIN_CANCELLED

    def test_admin_cancel_booking_missing_owner_fails(
        self,
        room_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            room = create_test_room()
            booking = RoomBooking(
                id="room-admin-cancel-missing-user",
                user_id="missing-user",
                room_id=room.id,
                start_time=(fixed_time + timedelta(hours=1)).isoformat(),
                end_time=(fixed_time + timedelta(hours=2)).isoformat(),
                status=RoomBookingStatus.RESERVED,
            )
            with global_lock():
                room_booking_repo.add(booking)

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.admin_cancel_booking(admin, booking.id, "시설 점검")

            assert "존재하지 않는 사용자" in str(exc_info.value)

    def test_admin_modify_booking(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """관리자 예약 수정"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            room = create_test_room()

            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )

            modified = room_service.admin_modify_booking(
                admin,
                booking.id,
                fixed_time + timedelta(hours=3),
                fixed_time + timedelta(hours=4),
            )

            assert datetime.fromisoformat(modified.start_time).hour == 13

    def test_admin_modify_booking_missing_owner_fails(
        self,
        room_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            room = create_test_room()
            booking = RoomBooking(
                id="room-admin-modify-missing-user",
                user_id="missing-user",
                room_id=room.id,
                start_time=(fixed_time + timedelta(hours=1)).isoformat(),
                end_time=(fixed_time + timedelta(hours=2)).isoformat(),
                status=RoomBookingStatus.RESERVED,
            )
            with global_lock():
                room_booking_repo.add(booking)

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.admin_modify_booking(
                    admin,
                    booking.id,
                    fixed_time + timedelta(hours=3),
                    fixed_time + timedelta(hours=4),
                )

            assert "존재하지 않는 사용자" in str(exc_info.value)

    def test_update_room_status_cancels_future_bookings(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """회의실 상태를 maintenance로 변경하면 미래 예약 자동 취소"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            room = create_test_room()

            # 미래 예약 2개 생성
            booking1 = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )
            booking2 = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=3),
                fixed_time + timedelta(hours=4),
            )

            # 상태 변경
            updated_room, cancelled = room_service.update_room_status(
                admin, room.id, ResourceStatus.MAINTENANCE
            )

            assert updated_room.status == ResourceStatus.MAINTENANCE
            assert len(cancelled) == 2

            for b in cancelled:
                assert b.status == RoomBookingStatus.ADMIN_CANCELLED

    def test_update_room_status_missing_booking_owner_fails(
        self,
        room_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            room = create_test_room()
            booking = RoomBooking(
                id="room-status-missing-user",
                user_id="missing-user",
                room_id=room.id,
                start_time=(fixed_time + timedelta(hours=1)).isoformat(),
                end_time=(fixed_time + timedelta(hours=2)).isoformat(),
                status=RoomBookingStatus.RESERVED,
            )
            with global_lock():
                room_booking_repo.add(booking)

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.update_room_status(
                    admin, room.id, ResourceStatus.MAINTENANCE
                )

            assert "존재하지 않는 사용자" in str(exc_info.value)


class TestBookingQueries:
    """예약 조회 테스트"""

    def test_get_user_bookings(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """사용자의 예약 조회"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room()

            room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )
            room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=3),
                fixed_time + timedelta(hours=4),
            )

            bookings = room_service.get_user_bookings(user.id)

            assert len(bookings) == 2

    def test_get_user_active_bookings(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """사용자의 활성 예약 조회"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room()

            b1 = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )
            b2 = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=3),
                fixed_time + timedelta(hours=4),
            )

            # 하나 취소
            room_service.cancel_booking(user, b1.id)

            active = room_service.get_user_active_bookings(user.id)

            assert len(active) == 1
            assert active[0].id == b2.id

    def test_get_user_bookings_nonexistent_user_fails(self, room_service):
        with pytest.raises(RoomBookingError) as exc_info:
            room_service.get_user_bookings("missing-user")

        assert "존재하지 않는 사용자" in str(exc_info.value)

    def test_get_user_active_bookings_nonexistent_user_fails(self, room_service):
        with pytest.raises(RoomBookingError) as exc_info:
            room_service.get_user_active_bookings("missing-user")

        assert "존재하지 않는 사용자" in str(exc_info.value)


class TestAdminOnlyRoomAccess:
    """관리자 전용 API 접근 제어 테스트"""

    def test_get_all_bookings_rejects_non_admin(self, room_service, create_test_user):
        """일반 사용자가 전체 예약 조회 시 거부"""
        from src.domain.room_service import AdminRequiredError

        user = create_test_user()

        with pytest.raises(AdminRequiredError) as exc_info:
            room_service.get_all_bookings(user)

        assert "관리자" in str(exc_info.value)

    def test_get_all_bookings_rejects_nonexistent_admin(
        self, room_service, user_factory
    ):
        from src.domain.room_service import AdminRequiredError

        fake_admin = user_factory(role=UserRole.ADMIN)

        with pytest.raises(AdminRequiredError) as exc_info:
            room_service.get_all_bookings(fake_admin)

        assert "관리자" in str(exc_info.value)
