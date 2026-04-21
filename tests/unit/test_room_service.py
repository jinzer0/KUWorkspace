"""
회의실 서비스 테스트

테스트 대상:
- 예약 생성: 정상, 충돌, 시간 유효성, 한도 초과
- 예약 수정: 정상, 권한 확인, 상태 확인
- 예약 취소: 정상, 직전 취소 판정
- 체크인/체크아웃: 정상, 지연 계산
- 자동 시작 패널티 미적용
- 관리자 기능: 예약 수정/취소, 상태 변경
"""

import pytest
from datetime import datetime, timedelta
from uuid import uuid4
from dataclasses import replace

from src.domain.room_service import AdminRequiredError, RoomBookingError
from src.domain.models import (
    EquipmentBookingStatus,
    RoomBooking,
    RoomBookingStatus,
    ResourceStatus,
    UserRole,
)
from src.storage.file_lock import global_lock
from src.storage.integrity import DataIntegrityError


class TestCreateBooking:
    """예약 생성 테스트"""

    def test_create_booking_success(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """정상 예약 생성"""
        fixed_time = datetime(2024, 6, 15, 8, 0, 0)

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
            user = user_factory(username="ghost_user")
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
        """정상 사용자는 회의실 활성 예약 1건을 초과할 수 없다."""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()

            # 서로 다른 회의실 생성
            rooms = []
            with global_lock():
                for i in range(2):
                    room = room_factory(name=f"회의실 {i}C")
                    room_repo.add(room)
                    rooms.append(room)

            room_service.create_booking(
                user,
                rooms[0].id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )

            # 2번째 예약 시 실패
            with pytest.raises(RoomBookingError) as exc_info:
                room_service.create_booking(
                    user,
                    rooms[1].id,
                    fixed_time + timedelta(hours=3),
                    fixed_time + timedelta(hours=4),
                )

            assert "한도" in str(exc_info.value) or "초과" in str(exc_info.value)

    def test_create_booking_cannot_bypass_limit_with_large_max_active(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            rooms = [create_test_room(name=f"회의실 {i}D") for i in range(2)]

            room_service.create_booking(
                user,
                rooms[0].id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
                max_active=99,
            )

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.create_booking(
                    user,
                    rooms[1].id,
                    fixed_time + timedelta(hours=3),
                    fixed_time + timedelta(hours=4),
                    max_active=99,
                )

            assert "1건" in str(exc_info.value)

    def test_create_booking_restricted_user_with_existing_equipment_booking_succeeds(
        self,
        room_service,
        create_test_user,
        create_test_room,
        equipment_booking_repo,
        equipment_booking_factory,
        create_test_equipment,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user(
                penalty_points=3,
                restriction_until=(fixed_time + timedelta(days=7)).isoformat(),
            )
            room = create_test_room()
            equipment = create_test_equipment()

            existing = equipment_booking_factory(
                user_id=user.id,
                equipment_id=equipment.id,
                start_time=(fixed_time + timedelta(hours=1)).isoformat(),
                end_time=(fixed_time + timedelta(days=1)).isoformat(),
                status=EquipmentBookingStatus.RESERVED,
            )
            with global_lock():
                equipment_booking_repo.add(existing)

            booking = room_service.create_booking(
                user=user,
                room_id=room.id,
                start_time=fixed_time + timedelta(hours=2),
                end_time=fixed_time + timedelta(hours=3),
            )

            assert booking.status == RoomBookingStatus.RESERVED

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

            assert "시작 시간보다 늦어야" in str(exc_info.value)

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
                    fixed_time + timedelta(days=30),
                )

            assert "최대 14일" in str(exc_info.value)

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
            assert datetime.fromisoformat(modified.start_time) == fixed_time + timedelta(hours=3)
            assert datetime.fromisoformat(modified.end_time) == fixed_time + timedelta(hours=4)

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
        fixed_time = datetime(2024, 6, 15, 8, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room()
            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )

        with mock_now(datetime(2024, 6, 15, 8, 16, 0)):
            modified = room_service.modify_booking(
                user,
                booking.id,
                fixed_time + timedelta(hours=3),
                fixed_time + timedelta(hours=4),
            )

            assert modified.status == RoomBookingStatus.RESERVED
            assert auth_service.get_user(user.id).penalty_points == 0


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
                fixed_time + timedelta(days=1),
                fixed_time + timedelta(days=2),
            )

            cancelled, is_late = room_service.cancel_booking(user, booking.id)

            assert cancelled.status == RoomBookingStatus.CANCELLED
            assert is_late is False

    def test_cancel_booking_late_cancel(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
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

            assert is_late is True

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
                fixed_time + timedelta(days=1),
                fixed_time + timedelta(days=2),
            )

        with mock_now(datetime(2024, 6, 15, 11, 16, 0)):
            cancelled, is_late = room_service.cancel_booking(user, booking.id)

            assert cancelled.status == RoomBookingStatus.CANCELLED
            assert is_late is False
            assert auth_service.get_user(user.id).penalty_points == 0


class TestCheckInOut:
    """체크인/체크아웃 테스트"""

    def test_check_in_success(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """정상 체크인"""
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            room = create_test_room()

            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time,
                fixed_time.replace(hour=18),
            )

            requested = room_service.request_check_in(user, booking.id)
            assert requested.status == RoomBookingStatus.CHECKIN_REQUESTED

            checked_in = room_service.check_in(admin, booking.id)

            assert checked_in.status == RoomBookingStatus.CHECKED_IN
            assert checked_in.checked_in_at is not None

    def test_check_in_runs_policy_checks_before_action(
        self,
        room_service,
        auth_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 8, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            room = create_test_room()
            booking = RoomBooking(
                id=str(uuid4()),
                user_id=user.id,
                room_id=room.id,
                start_time=datetime(2024, 6, 15, 9, 0, 0).isoformat(),
                end_time=datetime(2024, 6, 15, 18, 0, 0).isoformat(),
                status=RoomBookingStatus.CHECKIN_REQUESTED,
                requested_checkin_at=datetime(2024, 6, 15, 9, 0, 0).isoformat(),
            )
            with global_lock():
                room_booking_repo.add(booking)

        with mock_now(datetime(2024, 6, 15, 11, 16, 0)):
            with pytest.raises(RoomBookingError) as exc_info:
                room_service.check_in(admin, booking.id)
            assert "현재 운영 시점" in str(exc_info.value)
            assert auth_service.get_user(user.id).penalty_points == 0

    def test_check_in_missing_booking_user_fails(
        self,
        room_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            room = create_test_room()
            booking = RoomBooking(
                id=str(uuid4()),
                user_id="missing-user",
                room_id=room.id,
                start_time=fixed_time.isoformat(),
                end_time=fixed_time.replace(hour=18).isoformat(),
                status=RoomBookingStatus.CHECKIN_REQUESTED,
                requested_checkin_at=fixed_time.isoformat(),
            )
            with global_lock():
                room_booking_repo.add(booking)

        with mock_now(fixed_time):
            with pytest.raises(DataIntegrityError) as exc_info:
                room_service.check_in(admin, booking.id)

            assert "users.txt" in str(exc_info.value)

    def test_default_room_service_keeps_reserved_booking_without_auto_start_penalty(
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
            admin = create_test_user(username="admin_default", role=UserRole.ADMIN)
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
            assert updated_booking.status == RoomBookingStatus.RESERVED
            assert auth_service.get_user(user.id).penalty_points == 0

    def test_check_out_on_time(
        self,
        room_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        mock_now,
    ):
        """정시 퇴실 (지연 0분)"""
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            room = create_test_room()

            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time,
                fixed_time.replace(hour=18),
            )

            requested = room_service.request_check_in(user, booking.id)
            assert requested.status == RoomBookingStatus.CHECKIN_REQUESTED

            room_service.check_in(admin, booking.id)

        # 12:00에 퇴실 (종료 시간 정각)
        checkout_time = datetime(2024, 6, 15, 18, 0, 0)
        with mock_now(checkout_time):
            room_service.request_checkout(user, booking.id)
            completed, delay = room_service.approve_checkout_request(admin, booking.id)

            assert completed.status == RoomBookingStatus.COMPLETED
            assert delay == 0

    def test_check_out_requires_exact_boundary(
        self,
        room_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        mock_now,
    ):
        """종료 경계를 벗어나면 퇴실 처리 불가"""
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            room = create_test_room()

            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time,
                fixed_time.replace(hour=18),
            )

            requested = room_service.request_check_in(user, booking.id)
            assert requested.status == RoomBookingStatus.CHECKIN_REQUESTED

            room_service.check_in(admin, booking.id)

        late_time = datetime(2024, 6, 15, 18, 30, 0)
        with mock_now(late_time):
            room_service.request_checkout(user, booking.id)
            with pytest.raises(RoomBookingError) as exc_info:
                room_service.approve_checkout_request(admin, booking.id)
            assert "현재 운영 시점" in str(exc_info.value)

    def test_check_out_missing_booking_user_fails(
        self,
        room_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            room = create_test_room()
            booking = RoomBooking(
                id="room-missing-user-checkout",
                user_id="missing-user",
                room_id=room.id,
                start_time=fixed_time.isoformat(),
                end_time=fixed_time.replace(hour=18).isoformat(),
                status=RoomBookingStatus.CHECKOUT_REQUESTED,
                requested_checkout_at=fixed_time.replace(hour=18).isoformat(),
            )
            with global_lock():
                room_booking_repo.add(booking)

        with mock_now(datetime(2024, 6, 15, 18, 0, 0)):
            with pytest.raises(RoomBookingError) as exc_info:
                room_service.approve_checkout_request(admin, booking.id)

            assert "존재하지 않는 사용자" in str(exc_info.value)

    def test_force_complete_room_checkout_applies_late_penalty(
        self, room_service, auth_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin_force", role=UserRole.ADMIN)
            room = create_test_room()
            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time,
                fixed_time.replace(hour=18),
            )
            room_service.request_check_in(user, booking.id)
            room_service.check_in(admin, booking.id)

        with mock_now(datetime(2024, 6, 15, 18, 0, 0)):
            completed, delay = room_service.force_complete_checkout(admin, booking.id)

            assert completed.status == RoomBookingStatus.COMPLETED
            assert delay == 60
            assert auth_service.get_user(user.id).penalty_points == 2


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
                fixed_time + timedelta(days=1),
                fixed_time + timedelta(days=2),
            )

            cancelled = room_service.admin_cancel_booking(
                admin, booking.id, "시설 점검"
            )

            assert cancelled.status == RoomBookingStatus.ADMIN_CANCELLED

    def test_admin_cancel_booking_blocks_same_day_booking(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin_same_day", role=UserRole.ADMIN)
            room = create_test_room()

            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time.replace(hour=18),
                fixed_time + timedelta(days=1),
            )

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.admin_cancel_booking(admin, booking.id, "시설 점검")

            assert "당일 예약은 취소할 수 없습니다." in str(exc_info.value)

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
                id=str(uuid4()),
                user_id="missing-user",
                room_id=room.id,
                start_time=(fixed_time + timedelta(hours=1)).isoformat(),
                end_time=(fixed_time + timedelta(hours=2)).isoformat(),
                status=RoomBookingStatus.RESERVED,
            )
            with global_lock():
                room_booking_repo.add(booking)

            with pytest.raises(DataIntegrityError) as exc_info:
                room_service.admin_cancel_booking(admin, booking.id, "시설 점검")

            assert "users.txt" in str(exc_info.value)

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
                fixed_time + timedelta(days=1),
                fixed_time + timedelta(days=2),
            )

            modified = room_service.admin_modify_booking(
                admin,
                booking.id,
                fixed_time + timedelta(days=3),
                fixed_time + timedelta(days=4),
            )

            assert datetime.fromisoformat(modified.start_time) == fixed_time + timedelta(days=3)
            assert datetime.fromisoformat(modified.end_time) == fixed_time + timedelta(days=4)

    def test_admin_modify_daily_booking_blocks_started_booking(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        with mock_now(datetime(2024, 6, 15, 10, 0, 0)):
            user = create_test_user()
            admin = create_test_user(username="admin_daily_started", role=UserRole.ADMIN)
            room = create_test_room()
            booking = room_service.create_daily_booking(
                user=user,
                room_id=room.id,
                start_date=datetime(2024, 6, 16).date(),
                end_date=datetime(2024, 6, 16).date(),
                attendee_count=4,
            )

        with mock_now(datetime(2024, 6, 16, 9, 0, 0)):
            with pytest.raises(RoomBookingError) as exc_info:
                room_service.admin_modify_daily_booking(
                    admin,
                    booking.id,
                    datetime(2024, 6, 17).date(),
                    datetime(2024, 6, 17).date(),
                )

            assert "이미 시작된 예약은 변경할 수 없습니다." in str(exc_info.value)

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
                id=str(uuid4()),
                user_id="missing-user",
                room_id=room.id,
                start_time=(fixed_time + timedelta(hours=1)).isoformat(),
                end_time=(fixed_time + timedelta(hours=2)).isoformat(),
                status=RoomBookingStatus.RESERVED,
            )
            with global_lock():
                room_booking_repo.add(booking)

            with pytest.raises(DataIntegrityError) as exc_info:
                room_service.admin_modify_booking(
                    admin,
                    booking.id,
                    fixed_time + timedelta(hours=3),
                    fixed_time + timedelta(hours=4),
                )

            assert "users.txt" in str(exc_info.value)

    def test_admin_modify_booking_rejects_checked_in_status(
        self,
        room_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        mock_now,
    ):
        """관리자 예약 수정은 CHECKED_IN 상태 예약을 거부한다 (regression for reassignment segregation)"""
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            room = create_test_room()

            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time,
                fixed_time.replace(hour=18),
            )
            room_service.request_check_in(user, booking.id)
            room_service.check_in(admin, booking.id)

            # admin_modify_booking은 CHECKED_IN 예약을 거부해야 함
            with pytest.raises(RoomBookingError) as exc_info:
                room_service.admin_modify_booking(
                    admin,
                    booking.id,
                    fixed_time + timedelta(hours=1),
                    fixed_time.replace(hour=17),
                )

            assert "checked_in" in str(exc_info.value)
            
            # 예약은 변경되지 않음
            unchanged = room_service.booking_repo.get_by_id(booking.id)
            assert unchanged.status == RoomBookingStatus.CHECKED_IN
            assert unchanged.start_time == fixed_time.isoformat(timespec="minutes")
            assert unchanged.end_time == fixed_time.replace(hour=18).isoformat(timespec="minutes")

    def test_update_room_status_cancels_future_bookings(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        """회의실 상태를 maintenance로 변경하면 미래 예약 자동 취소"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user(username="room_user_1")
            user2 = create_test_user(username="room_user_2")
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            room = create_test_room()

            # 서로 다른 사용자로 미래 예약 2개 생성
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

    def test_get_room_operational_overview_marks_in_use_reserved_and_empty(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            user = create_test_user(username="user1")
            room_in_use = create_test_room(name="회의실 4A")
            room_reserved = create_test_room(name="회의실 4B")
            room_empty = create_test_room(name="회의실 4C")

            with global_lock():
                room_service.booking_repo.add(
                    RoomBooking(
                        id="in-use-booking",
                        user_id=user.id,
                        room_id=room_in_use.id,
                        start_time=(fixed_time - timedelta(hours=1)).isoformat(),
                        end_time=(fixed_time + timedelta(hours=1)).isoformat(),
                        status=RoomBookingStatus.CHECKED_IN,
                    )
                )
                room_service.booking_repo.add(
                    RoomBooking(
                        id="reserved-booking-1",
                        user_id=user.id,
                        room_id=room_reserved.id,
                        start_time=(fixed_time + timedelta(days=1)).isoformat(),
                        end_time=(fixed_time + timedelta(days=2)).isoformat(),
                        status=RoomBookingStatus.RESERVED,
                    )
                )
                room_service.booking_repo.add(
                    RoomBooking(
                        id="reserved-booking-2",
                        user_id=user.id,
                        room_id=room_reserved.id,
                        start_time=(fixed_time + timedelta(days=3)).isoformat(),
                        end_time=(fixed_time + timedelta(days=4)).isoformat(),
                        status=RoomBookingStatus.RESERVED,
                    )
                )

            overview = room_service.get_room_operational_overview(admin)

            by_name = {item.room_name: item for item in overview}
            assert by_name[room_in_use.name].operational_status == "사용중"
            assert by_name[room_in_use.name].reservation_summary == "2024-06-15 ~ 2024-06-15"
            assert by_name[room_reserved.name].operational_status == "예약있음"
            assert by_name[room_reserved.name].reservation_summary == "2024-06-16 ~ 2024-06-17 외 1건"
            assert by_name[room_empty.name].operational_status == "예약없음"
            assert by_name[room_empty.name].reservation_summary == "X"

    def test_get_room_operational_overview_rejects_non_admin(
        self, room_service, create_test_user, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user(username="user1")

            with pytest.raises(AdminRequiredError):
                room_service.get_room_operational_overview(user)

    def test_get_room_operational_overview_marks_start_boundary_items_as_reserved(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            user = create_test_user(username="user1")
            room = create_test_room(name="회의실 4D")

            with global_lock():
                room_service.booking_repo.add(
                    RoomBooking(
                        id="reserved-now-booking",
                        user_id=user.id,
                        room_id=room.id,
                        start_time=fixed_time.isoformat(),
                        end_time=fixed_time.replace(hour=18).isoformat(),
                        status=RoomBookingStatus.RESERVED,
                    )
                )

            overview = room_service.get_room_operational_overview(admin)
            by_name = {item.room_name: item for item in overview}

            assert by_name[room.name].operational_status == "예약있음"
            assert by_name[room.name].reservation_summary == "2024-06-15 ~ 2024-06-15"

    def test_get_room_operational_overview_marks_start_boundary_checkin_requested_as_reserved(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            user = create_test_user(username="user1")
            room = create_test_room(name="회의실 4E")

            with global_lock():
                room_service.booking_repo.add(
                    RoomBooking(
                        id="checkin-requested-now-booking",
                        user_id=user.id,
                        room_id=room.id,
                        start_time=fixed_time.isoformat(),
                        end_time=fixed_time.replace(hour=18).isoformat(),
                        status=RoomBookingStatus.CHECKIN_REQUESTED,
                    )
                )

            overview = room_service.get_room_operational_overview(admin)
            by_name = {item.room_name: item for item in overview}

            assert by_name[room.name].operational_status == "예약있음"
            assert by_name[room.name].reservation_summary == "2024-06-15 ~ 2024-06-15"


class TestAuditLogging:
    def test_create_room_booking_logs_audit_action(
        self, room_service, create_test_user, create_test_room, audit_repo, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 8, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room(status=ResourceStatus.AVAILABLE)
            booking = room_service.create_booking(
                user=user,
                room_id=room.id,
                start_time=fixed_time + timedelta(hours=1),
                end_time=fixed_time + timedelta(hours=2),
            )

        logs = audit_repo.get_by_actor(user.id)
        assert any(
            log.action == "create_room_booking" and log.target_id == booking.id
            for log in logs
        )

    def test_request_room_checkin_logs_audit_action(
        self, room_service, create_test_user, create_test_room, audit_repo, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room(status=ResourceStatus.AVAILABLE)
            booking = room_service.create_booking(
                user=user,
                room_id=room.id,
                start_time=fixed_time,
                end_time=fixed_time.replace(hour=18),
            )
            room_service.request_check_in(user, booking.id)

        logs = audit_repo.get_by_actor(user.id)
        assert any(
            log.action == "request_room_check_in" and log.target_id == booking.id
            for log in logs
        )

    def test_update_room_status_logs_admin_action(
        self,
        room_service,
        create_test_user,
        create_test_room,
        audit_repo,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin_audit", role=UserRole.ADMIN)
            room = create_test_room()
            room_service.update_room_status(admin, room.id, ResourceStatus.MAINTENANCE)

        logs = audit_repo.get_by_actor(admin.id)
        assert any(
            log.action == "update_room_status" and log.target_id == room.id
            for log in logs
        )


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

            first_booking = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )
            room_service.cancel_booking(user, first_booking.id)

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

            # 하나 취소
            room_service.cancel_booking(user, b1.id)

            b2 = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=3),
                fixed_time + timedelta(hours=4),
            )

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
