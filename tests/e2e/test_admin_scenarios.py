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
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )
            booking2 = room_service.create_booking(
                user2,
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
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(days=3),
            )

            updated_eq, cancelled = equipment_service.update_equipment_status(
                admin, equipment.id, ResourceStatus.DISABLED
            )

            assert updated_eq.status == ResourceStatus.DISABLED
            assert len(cancelled) == 1
            assert cancelled[0].status == EquipmentBookingStatus.ADMIN_CANCELLED


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
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(hours=2),
            )

            # 관리자 취소
            cancelled = room_service.admin_cancel_booking(
                admin, booking.id, "시설 긴급 점검"
            )

            assert cancelled.status == RoomBookingStatus.ADMIN_CANCELLED

    def test_admin_cannot_cancel_checked_in_booking(
        self, auth_service, room_service, create_test_room, mock_now
    ):
        """PLAN2.md: 관리자 취소는 reserved -> admin_cancelled만 허용, checked_in 상태는 취소 불가"""
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

            room_service.check_in(admin, booking.id)

            # PLAN2.md: 체크인 상태에서는 관리자 취소 불가
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
        assert PenaltyReason.NO_SHOW in reasons
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

        assert result["can_advance"] is False
        assert any("체크인 또는 노쇼" in blocker for blocker in result["blockers"])


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

        assert status["points"] == 3
        assert status["is_restricted"] is True
        assert status["warning_message"] is not None
