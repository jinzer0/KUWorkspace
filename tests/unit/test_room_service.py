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
from datetime import date, datetime, timedelta
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
from src.storage.repositories import RoomBookingRepository


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

            # 같은 시간대 두 번째 예약은 우선권 대기 상태로 생성
            pending = room_service.create_booking(user2, room.id, start, end)

            assert pending.status == RoomBookingStatus.PENDING

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
            pending = room_service.create_booking(
                user2,
                room.id,
                fixed_time + timedelta(hours=2),
                fixed_time + timedelta(hours=4),
            )

            assert pending.status == RoomBookingStatus.PENDING

    def test_create_booking_exceeds_max_active(
        self,
        room_service,
        create_test_user,
        create_test_room,
        room_factory,
        room_repo,
        mock_now,
    ):
        """정상 사용자는 회의실 활성 예약 3건까지 유지할 수 있다."""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()

            # 서로 다른 회의실 생성
            rooms = []
            with global_lock():
                for i in range(4):
                    room = room_factory(name=f"회의실{i}C")
                    room_repo.add(room)
                    rooms.append(room)

            room_service.create_booking(
                user,
                rooms[0].id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )

            for index in range(1, 3):
                room_service.create_booking(
                    user,
                    rooms[index].id,
                    fixed_time + timedelta(days=index, hours=1),
                    fixed_time + timedelta(days=index, hours=2),
                )

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.create_booking(
                    user,
                    rooms[3].id,
                    fixed_time + timedelta(days=3, hours=1),
                    fixed_time + timedelta(days=3, hours=2),
                )

            assert "3건" in str(exc_info.value) or "한도" in str(exc_info.value) or "초과" in str(exc_info.value)

    def test_plan0001_normal_user_room_limit_is_three(
        self,
        room_service,
        create_test_user,
        room_factory,
        room_repo,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user(username="RoomLimitUser")
            rooms = []
            with global_lock():
                for index in range(4):
                    room = room_factory(name=f"회의실{index + 1}A")
                    room_repo.add(room)
                    rooms.append(room)

            bookings = [
                room_service.create_booking(
                    user,
                    rooms[index].id,
                    fixed_time + timedelta(days=index + 1),
                    fixed_time + timedelta(days=index + 1, hours=9),
                )
                for index in range(3)
            ]

            assert [booking.status for booking in bookings] == [RoomBookingStatus.RESERVED] * 3
            with pytest.raises(RoomBookingError, match="3건|한도|초과"):
                room_service.create_booking(
                    user,
                    rooms[3].id,
                    fixed_time + timedelta(days=4),
                    fixed_time + timedelta(days=4, hours=9),
                )

    def test_room_daily_booking_eighteen_next_day_rejects_later_request_without_write(
        self,
        room_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        fake_clock,
    ):
        current_time = datetime(2026, 5, 15, 18, 0, 0)
        fake_clock(current_time)
        first_user = create_test_user(username="RoomFirstNext")
        later_user = create_test_user(username="RoomLaterNext")
        room = create_test_room(name="회의실5A", capacity=4)
        target_date = date(2026, 5, 16)

        first = room_service.create_daily_booking(
            first_user,
            room.id,
            target_date,
            target_date,
            attendee_count=2,
        )
        before = room_booking_repo.get_by_room(room.id)

        with pytest.raises(RoomBookingError, match="18:00|선착순|거부"):
            room_service.create_daily_booking(
                later_user,
                room.id,
                target_date,
                target_date,
                attendee_count=2,
            )

        after = room_booking_repo.get_by_room(room.id)
        assert first.status == RoomBookingStatus.RESERVED
        assert [booking.id for booking in before] == [first.id]
        assert [booking.id for booking in after] == [first.id]
        assert after[0].user_id == first_user.id
        assert after[0].status == RoomBookingStatus.RESERVED

    def test_inspect1_pending_room_bookings_do_not_consume_active_quota(
        self,
        room_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        room_booking_factory,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user(username="InspectRoomPendingQuotaUser")
            owner = create_test_user(username="InspectRoomPendingOwner")
            conflict_room = create_test_room(name="회의실1P")
            target_rooms = [
                create_test_room(name=f"회의실{index + 2}P") for index in range(3)
            ]
            conflict_start = fixed_time + timedelta(days=10)
            conflict_end = fixed_time + timedelta(days=10, hours=9)
            with global_lock():
                room_booking_repo.add(
                    room_booking_factory(
                        id="inspect1-room-quota-conflict",
                        user_id=owner.id,
                        room_id=conflict_room.id,
                        start_time=conflict_start.isoformat(),
                        end_time=conflict_end.isoformat(),
                        status=RoomBookingStatus.RESERVED,
                    )
                )
                for index in range(3):
                    room_booking_repo.add(
                        room_booking_factory(
                            id=f"inspect1-room-quota-pending-{index}",
                            user_id=user.id,
                            room_id=conflict_room.id,
                            start_time=conflict_start.isoformat(),
                            end_time=conflict_end.isoformat(),
                            status=RoomBookingStatus.PENDING,
                        )
                    )

            bookings = [
                room_service.create_booking(
                    user,
                    room.id,
                    fixed_time + timedelta(days=index + 1),
                    fixed_time + timedelta(days=index + 1, hours=9),
                )
                for index, room in enumerate(target_rooms)
            ]

            assert [booking.status for booking in bookings] == [RoomBookingStatus.RESERVED] * 3
            assert all(
                room_booking_repo.get_by_id(f"inspect1-room-quota-pending-{index}").status
                == RoomBookingStatus.PENDING
                for index in range(3)
            )

    def test_create_booking_cannot_bypass_limit_with_large_max_active(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            rooms = [create_test_room(name=f"회의실{i}D") for i in range(4)]

            room_service.create_booking(
                user,
                rooms[0].id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
                max_active=99,
            )

            for index in range(1, 3):
                room_service.create_booking(
                    user,
                    rooms[index].id,
                    fixed_time + timedelta(days=index, hours=1),
                    fixed_time + timedelta(days=index, hours=2),
                    max_active=99,
                )

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.create_booking(
                    user,
                    rooms[3].id,
                    fixed_time + timedelta(days=3, hours=1),
                    fixed_time + timedelta(days=3, hours=2),
                    max_active=99,
                )

            assert "3건" in str(exc_info.value)

    def test_create_booking_restricted_user_with_existing_equipment_booking_succeeds(
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
            assert datetime.fromisoformat(modified.start_time).hour == 9

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

    def test_request_check_in_before_start_rejects_without_write(
        self,
        room_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 8, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room()
            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time.replace(hour=9),
                fixed_time.replace(hour=18),
            )
            before = room_booking_repo.get_by_id(booking.id)

            with pytest.raises(RoomBookingError) as exc_info:
                room_service.request_check_in(user, booking.id)

            after = room_booking_repo.get_by_id(booking.id)
            assert "현재 운영 시점" in str(exc_info.value)
            assert before.status == RoomBookingStatus.RESERVED
            assert after.status == RoomBookingStatus.RESERVED
            assert after.requested_checkin_at is None

    def test_request_check_in_at_start_records_request_timestamp(
        self, room_service, create_test_user, create_test_room, room_booking_repo, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room()
            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time,
                fixed_time.replace(hour=18),
            )

            requested = room_service.request_check_in(user, booking.id)
            persisted = room_booking_repo.get_by_id(booking.id)

            assert requested.status == RoomBookingStatus.CHECKIN_REQUESTED
            assert datetime.fromisoformat(requested.requested_checkin_at) == fixed_time
            assert datetime.fromisoformat(requested.updated_at) == fixed_time
            assert persisted.status == RoomBookingStatus.CHECKIN_REQUESTED
            assert datetime.fromisoformat(persisted.requested_checkin_at) == fixed_time

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
                id="room-checkin-boundary",
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
                id="room-missing-user-checkin",
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
            with pytest.raises(RoomBookingError) as exc_info:
                room_service.check_in(admin, booking.id)

            assert "존재하지 않는 사용자" in str(exc_info.value)

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
            completed, delay = room_service.check_out(admin, booking.id)

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
            with pytest.raises(RoomBookingError) as exc_info:
                room_service.check_out(admin, booking.id)
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
                status=RoomBookingStatus.CHECKED_IN,
            )
            with global_lock():
                room_booking_repo.add(booking)

        with mock_now(datetime(2024, 6, 15, 18, 0, 0)):
            with pytest.raises(RoomBookingError) as exc_info:
                room_service.check_out(admin, booking.id)

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

    def test_request_checkout_before_end_from_checked_in_records_request_timestamp(
        self,
        room_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin_early_checkout", role=UserRole.ADMIN)
            room = create_test_room()
            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time,
                fixed_time.replace(hour=18),
            )
            room_service.request_check_in(user, booking.id)
            room_service.check_in(admin, booking.id)

            requested = room_service.request_checkout(user, booking.id)
            persisted = room_booking_repo.get_by_id(booking.id)

            assert requested.status == RoomBookingStatus.CHECKOUT_REQUESTED
            assert datetime.fromisoformat(requested.requested_checkout_at) == fixed_time
            assert datetime.fromisoformat(requested.updated_at) == fixed_time
            assert persisted.status == RoomBookingStatus.CHECKOUT_REQUESTED
            assert datetime.fromisoformat(persisted.requested_checkout_at) == fixed_time


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
            room_in_use = create_test_room(name="회의실4A")
            room_reserved = create_test_room(name="회의실4B")
            room_empty = create_test_room(name="회의실4C")

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
            assert by_name[room_reserved.name].reservation_summary == (
                "2024-06-16 ~ 2024-06-17\n2024-06-18 ~ 2024-06-19"
            )
            assert "외" not in by_name[room_reserved.name].reservation_summary
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
            room = create_test_room(name="회의실4D")

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

    def test_get_room_operational_overview_lists_current_and_future_ranges_when_in_use(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            user = create_test_user(username="user1")
            room = create_test_room(name="회의실6B")

            bookings = [
                RoomBooking(
                    id="overview-current-checked-in",
                    user_id=user.id,
                    room_id=room.id,
                    start_time=fixed_time.replace(hour=9).isoformat(),
                    end_time=fixed_time.replace(hour=18).isoformat(),
                    status=RoomBookingStatus.CHECKED_IN,
                ),
                RoomBooking(
                    id="overview-future-reserved-1",
                    user_id=user.id,
                    room_id=room.id,
                    start_time=(fixed_time + timedelta(days=2)).replace(hour=9).isoformat(),
                    end_time=(fixed_time + timedelta(days=2)).replace(hour=18).isoformat(),
                    status=RoomBookingStatus.RESERVED,
                ),
                RoomBooking(
                    id="overview-future-reserved-2",
                    user_id=user.id,
                    room_id=room.id,
                    start_time=(fixed_time + timedelta(days=5)).replace(hour=9).isoformat(),
                    end_time=(fixed_time + timedelta(days=6)).replace(hour=18).isoformat(),
                    status=RoomBookingStatus.RESERVED,
                ),
            ]
            with global_lock():
                for booking in bookings:
                    room_service.booking_repo.add(booking)

            overview = room_service.get_room_operational_overview(admin)
            room_overview = {item.room_name: item for item in overview}[room.name]

            assert room_overview.operational_status == "사용중"
            assert room_overview.reservation_summary == (
                "2024-06-15 ~ 2024-06-15\n"
                "2024-06-17 ~ 2024-06-17\n"
                "2024-06-20 ~ 2024-06-21"
            )
            assert "외" not in room_overview.reservation_summary

    def test_get_room_operational_overview_marks_start_boundary_checkin_requested_as_reserved(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            user = create_test_user(username="user1")
            room = create_test_room(name="회의실4E")

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


class TestRoomBookingMemo:
    def test_create_booking_persists_pipe_backslash_memo_after_reload(
        self,
        room_service,
        temp_data_dir,
        create_test_user,
        create_test_room,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 8, 0, 0)
        memo = "회의 준비 자료"

        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room(status=ResourceStatus.AVAILABLE)
            booking = room_service.create_booking(
                user=user,
                room_id=room.id,
                start_time=fixed_time + timedelta(hours=1),
                end_time=fixed_time + timedelta(hours=2),
                memo=memo,
            )

        reloaded_repo = RoomBookingRepository(file_path=temp_data_dir / "room_bookings.txt")
        reloaded = reloaded_repo.get_by_id(booking.id)

        assert booking.memo == memo
        assert reloaded is not None
        assert reloaded.memo == memo

    def test_create_daily_booking_persists_empty_and_sentinel_memo_after_reload(
        self,
        room_service,
        temp_data_dir,
        create_test_user,
        create_test_room,
        mock_now,
    ):
        with mock_now(datetime(2024, 6, 15, 8, 0, 0)):
            user = create_test_user()
            empty_room = create_test_room(name="회의실2A", capacity=4)
            sentinel_room = create_test_room(name="회의실2B", capacity=4)
            empty_booking = room_service.create_daily_booking(
                user=user,
                room_id=empty_room.id,
                start_date=date(2024, 6, 16),
                end_date=date(2024, 6, 16),
                attendee_count=2,
                max_active=2,
                memo="",
            )
            sentinel_booking = room_service.create_daily_booking(
                user=user,
                room_id=sentinel_room.id,
                start_date=date(2024, 6, 17),
                end_date=date(2024, 6, 17),
                attendee_count=2,
                max_active=2,
                memo="-",
            )

        reloaded_repo = RoomBookingRepository(file_path=temp_data_dir / "room_bookings.txt")
        reloaded_empty = reloaded_repo.get_by_id(empty_booking.id)
        reloaded_sentinel = reloaded_repo.get_by_id(sentinel_booking.id)

        assert reloaded_empty is not None
        assert reloaded_sentinel is not None
        assert reloaded_empty.memo == ""
        assert reloaded_sentinel.memo == "-"

    def test_modify_booking_updates_memo_after_reload(
        self,
        room_service,
        temp_data_dir,
        create_test_user,
        create_test_room,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 8, 0, 0)
        memo = "회의 준비 자료"

        with mock_now(fixed_time):
            user = create_test_user()
            room = create_test_room()
            booking = room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )
            modified = room_service.modify_booking(
                user,
                booking.id,
                fixed_time + timedelta(days=1),
                fixed_time + timedelta(days=1, hours=2),
                memo=memo,
            )

        reloaded_repo = RoomBookingRepository(file_path=temp_data_dir / "room_bookings.txt")
        reloaded = reloaded_repo.get_by_id(booking.id)

        assert modified.memo == memo
        assert reloaded is not None
        assert reloaded.memo == memo

    def test_invalid_memo_leaves_room_repositories_unchanged(
        self,
        room_service,
        room_booking_repo,
        create_test_user,
        create_test_room,
        mock_now,
    ):
        with mock_now(datetime(2024, 6, 15, 8, 0, 0)):
            user = create_test_user()
            room = create_test_room(name="회의실3A", capacity=4)
            with pytest.raises(ValueError, match="줄바꿈"):
                room_service.create_booking(
                    user=user,
                    room_id=room.id,
                    start_time=datetime(2024, 6, 15, 9, 0, 0),
                    end_time=datetime(2024, 6, 15, 10, 0, 0),
                    memo="회의\n준비",
                )

            booking = room_service.create_daily_booking(
                user=user,
                room_id=room.id,
                start_date=date(2024, 6, 16),
                end_date=date(2024, 6, 16),
                attendee_count=2,
                memo="기존메모",
            )
            with global_lock():
                room_booking_repo.update(
                    replace(booking, status=RoomBookingStatus.RESERVED)
                )
            with pytest.raises(ValueError, match="줄바꿈"):
                room_service.modify_daily_booking(
                    user=user,
                    booking_id=booking.id,
                    start_date=date(2024, 6, 17),
                    end_date=date(2024, 6, 17),
                    memo="변경\n메모",
                )

        unchanged = room_booking_repo.get_by_id(booking.id)
        assert len(room_booking_repo.get_all()) == 1
        assert unchanged.memo == "기존메모"
        assert datetime.fromisoformat(unchanged.start_time) == datetime.fromisoformat(
            booking.start_time
        )


class TestAdminRoomResourceManagement:
    def test_add_edit_delete_room_resource_through_service(
        self, room_service, create_test_user
    ):
        admin = create_test_user(role=UserRole.ADMIN)

        room = room_service.add_room_resource(admin, "회의실4A", 8, "4층")
        edited = room_service.edit_room_resource(admin, room.id, 10, "5층")
        deleted = room_service.delete_room_resource(admin, room.id)

        assert room.status == ResourceStatus.AVAILABLE
        assert edited.capacity == 10
        assert edited.location == "5층"
        assert deleted.id == room.id
        assert room_service.get_room(room.id) is None

    def test_delete_room_resource_with_future_booking_leaves_room_unchanged(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 8, 0, 0)
        with mock_now(fixed_time):
            admin = create_test_user(role=UserRole.ADMIN)
            user = create_test_user(username="FutureUser")
            room = create_test_room(name="회의실4B", capacity=4)
            room_service.create_booking(
                user,
                room.id,
                fixed_time + timedelta(days=1),
                fixed_time + timedelta(days=1, hours=2),
            )

            with pytest.raises(RoomBookingError, match="예약"):
                room_service.delete_room_resource(admin, room.id)

        unchanged = room_service.get_room(room.id)
        assert unchanged is not None
        assert unchanged.name == room.name

    def test_edit_room_resource_with_active_maintenance_leaves_room_unchanged(
        self, room_service, create_test_user, create_test_room, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 8, 0, 0)
        with mock_now(fixed_time):
            admin = create_test_user(role=UserRole.ADMIN)
            room = create_test_room(name="회의실4C", capacity=4, location="4층")
            room_service.create_maintenance_schedule(
                admin,
                room.id,
                fixed_time + timedelta(days=1),
                fixed_time + timedelta(days=2),
                "정기점검",
            )

            with pytest.raises(RoomBookingError, match="점검"):
                room_service.edit_room_resource(admin, room.id, 6, "5층")

        unchanged = room_service.get_room(room.id)
        assert unchanged.capacity == 4
        assert unchanged.location == "4층"
