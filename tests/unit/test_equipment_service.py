"""
장비 서비스 테스트

테스트 대상:
- 예약 생성/수정/취소
- 시간 충돌 감지
- 대여(checkout)/반납(return)
- 지연 시간 계산
- 관리자 기능
"""

import pytest
from datetime import datetime, timedelta

from src.domain.equipment_service import EquipmentBookingError
from src.domain.models import (
    EquipmentBooking,
    EquipmentBookingStatus,
    RoomBookingStatus,
    ResourceStatus,
    UserRole,
)
from src.storage.file_lock import global_lock


class TestCreateEquipmentBooking:
    """장비 예약 생성 테스트"""

    def test_create_booking_success(
        self, equipment_service, create_test_user, create_test_equipment, mock_now
    ):
        """정상 장비 예약 생성"""
        fixed_time = datetime(2024, 6, 15, 8, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            equipment = create_test_equipment(status=ResourceStatus.AVAILABLE)

            start = fixed_time + timedelta(hours=1)
            end = fixed_time + timedelta(days=3)

            booking = equipment_service.create_booking(
                user=user, equipment_id=equipment.id, start_time=start, end_time=end
            )

            assert booking.id is not None
            assert booking.user_id == user.id
            assert booking.equipment_id == equipment.id
            assert booking.status == EquipmentBookingStatus.RESERVED

    def test_create_booking_equipment_not_found(
        self, equipment_service, create_test_user, mock_now
    ):
        """존재하지 않는 장비 예약 시 실패"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()

            with pytest.raises(EquipmentBookingError) as exc_info:
                equipment_service.create_booking(
                    user=user,
                    equipment_id="nonexistent",
                    start_time=fixed_time + timedelta(hours=1),
                    end_time=fixed_time + timedelta(days=1),
                )

            assert "존재하지 않는 장비" in str(exc_info.value)

    def test_create_booking_nonexistent_user_rejected(
        self, equipment_service, user_factory, create_test_equipment, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = user_factory(username="ghost-user")
            equipment = create_test_equipment()

            with pytest.raises(EquipmentBookingError) as exc_info:
                equipment_service.create_booking(
                    user=user,
                    equipment_id=equipment.id,
                    start_time=fixed_time + timedelta(hours=1),
                    end_time=fixed_time + timedelta(days=1),
                )

            assert "존재하지 않는 사용자" in str(exc_info.value)

    def test_create_booking_disabled_equipment(
        self, equipment_service, create_test_user, create_test_equipment, mock_now
    ):
        """비활성화된 장비 예약 시 실패"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            equipment = create_test_equipment(status=ResourceStatus.DISABLED)

            with pytest.raises(EquipmentBookingError):
                equipment_service.create_booking(
                    user=user,
                    equipment_id=equipment.id,
                    start_time=fixed_time + timedelta(hours=1),
                    end_time=fixed_time + timedelta(days=1),
                )

    def test_create_booking_time_conflict(
        self, equipment_service, create_test_user, create_test_equipment, mock_now
    ):
        """시간 충돌 시 실패"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user1 = create_test_user(username="user1")
            user2 = create_test_user(username="user2")
            equipment = create_test_equipment()

            start = fixed_time + timedelta(hours=1)
            end = fixed_time + timedelta(days=3)

            # 첫 번째 예약 성공
            equipment_service.create_booking(user1, equipment.id, start, end)

            # 겹치는 시간대 예약 실패
            with pytest.raises(EquipmentBookingError) as exc_info:
                equipment_service.create_booking(
                    user2,
                    equipment.id,
                    fixed_time + timedelta(days=1),
                    fixed_time + timedelta(days=4),
                )

            assert "이미 예약이 있습니다" in str(exc_info.value)

    def test_create_booking_cannot_bypass_limit_with_large_max_active(
        self, equipment_service, create_test_user, create_test_equipment, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            equipment_items = [
                create_test_equipment(name=f"Bypass Equipment {i}") for i in range(2)
            ]

            equipment_service.create_booking(
                user,
                equipment_items[0].id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(days=1),
                max_active=99,
            )

            with pytest.raises(EquipmentBookingError) as exc_info:
                equipment_service.create_booking(
                    user,
                    equipment_items[1].id,
                    fixed_time + timedelta(hours=3),
                    fixed_time + timedelta(days=2),
                    max_active=99,
                )

            assert "1건" in str(exc_info.value)

    def test_create_booking_restricted_user_with_existing_room_booking_fails(
        self,
        equipment_service,
        create_test_user,
        create_test_equipment,
        room_booking_repo,
        room_booking_factory,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user(
                penalty_points=4,
                restriction_until=(fixed_time + timedelta(days=7)).isoformat(),
            )
            equipment = create_test_equipment()

            existing = room_booking_factory(
                user_id=user.id,
                start_time=(fixed_time + timedelta(hours=1)).isoformat(),
                end_time=(fixed_time + timedelta(hours=2)).isoformat(),
                status=RoomBookingStatus.RESERVED,
            )
            with global_lock():
                room_booking_repo.add(existing)

            with pytest.raises(EquipmentBookingError) as exc_info:
                equipment_service.create_booking(
                    user=user,
                    equipment_id=equipment.id,
                    start_time=fixed_time + timedelta(hours=3),
                    end_time=fixed_time + timedelta(days=1),
                )

            assert "1건만 허용" in str(exc_info.value)

    def test_create_booking_banned_user_rejected(
        self, equipment_service, create_test_user, create_test_equipment, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user(
                penalty_points=6,
                restriction_until=(fixed_time + timedelta(days=30)).isoformat(),
            )
            equipment = create_test_equipment()

            with pytest.raises(EquipmentBookingError) as exc_info:
                equipment_service.create_booking(
                    user=user,
                    equipment_id=equipment.id,
                    start_time=fixed_time + timedelta(hours=1),
                    end_time=fixed_time + timedelta(days=1),
                )

            assert "이용이 금지된 상태" in str(exc_info.value)


class TestModifyEquipmentBooking:
    """장비 예약 수정 테스트"""

    def test_modify_booking_success(
        self, equipment_service, create_test_user, create_test_equipment, mock_now
    ):
        """정상 예약 수정"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            equipment = create_test_equipment()

            booking = equipment_service.create_booking(
                user,
                equipment.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(days=2),
            )

            modified = equipment_service.modify_booking(
                user,
                booking.id,
                fixed_time + timedelta(hours=2),
                fixed_time + timedelta(days=3),
            )

            assert modified.id == booking.id

    def test_modify_booking_not_owner(
        self, equipment_service, create_test_user, create_test_equipment, mock_now
    ):
        """다른 사용자의 예약 수정 시 실패"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user1 = create_test_user(username="user1")
            user2 = create_test_user(username="user2")
            equipment = create_test_equipment()

            booking = equipment_service.create_booking(
                user1,
                equipment.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(days=2),
            )

            with pytest.raises(EquipmentBookingError):
                equipment_service.modify_booking(
                    user2,
                    booking.id,
                    fixed_time + timedelta(hours=2),
                    fixed_time + timedelta(days=3),
                )

    def test_modify_booking_runs_policy_checks_before_action(
        self,
        equipment_service,
        auth_service,
        create_test_user,
        create_test_equipment,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            equipment = create_test_equipment()
            booking = equipment_service.create_booking(
                user,
                equipment.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(days=1),
            )

        with mock_now(datetime(2024, 6, 15, 11, 16, 0)):
            modified = equipment_service.modify_booking(
                user,
                booking.id,
                fixed_time + timedelta(hours=3),
                fixed_time + timedelta(days=2),
            )

            assert modified.status == EquipmentBookingStatus.RESERVED
            assert auth_service.get_user(user.id).penalty_points == 0


class TestCancelEquipmentBooking:
    """장비 예약 취소 테스트"""

    def test_cancel_booking_success(
        self, equipment_service, create_test_user, create_test_equipment, mock_now
    ):
        """정상 예약 취소"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            equipment = create_test_equipment()

            booking = equipment_service.create_booking(
                user,
                equipment.id,
                fixed_time + timedelta(hours=2),
                fixed_time + timedelta(days=2),
            )

            cancelled, is_late = equipment_service.cancel_booking(user, booking.id)

            assert cancelled.status == EquipmentBookingStatus.CANCELLED
            assert is_late is False

    def test_cancel_booking_late_cancel(
        self, equipment_service, create_test_user, create_test_equipment, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            equipment = create_test_equipment()

            # 30분 후 시작
            booking = equipment_service.create_booking(
                user,
                equipment.id,
                fixed_time + timedelta(minutes=30),
                fixed_time + timedelta(days=1),
            )

            cancelled, is_late = equipment_service.cancel_booking(user, booking.id)

            assert is_late is True

    def test_cancel_booking_runs_policy_checks_before_action(
        self,
        equipment_service,
        auth_service,
        create_test_user,
        create_test_equipment,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            equipment = create_test_equipment()
            booking = equipment_service.create_booking(
                user,
                equipment.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(days=1),
            )

        with mock_now(datetime(2024, 6, 15, 11, 16, 0)):
            cancelled, is_late = equipment_service.cancel_booking(user, booking.id)

            assert cancelled.status == EquipmentBookingStatus.CANCELLED
            assert is_late is False
            assert auth_service.get_user(user.id).penalty_points == 0


class TestCheckoutReturn:
    """대여/반납 테스트"""

    def test_checkout_success(
        self, equipment_service, create_test_user, create_test_equipment, mock_now
    ):
        """정상 대여"""
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            equipment = create_test_equipment()

            booking = equipment_service.create_booking(
                user,
                equipment.id,
                fixed_time,
                fixed_time + timedelta(days=2),
            )

            requested = equipment_service.request_pickup(user, booking.id)
            assert requested.status == EquipmentBookingStatus.PICKUP_REQUESTED

            checked_out = equipment_service.checkout(admin, booking.id)

            assert checked_out.status == EquipmentBookingStatus.CHECKED_OUT
            assert checked_out.checked_out_at is not None

    def test_checkout_runs_policy_checks_before_action(
        self,
        equipment_service,
        auth_service,
        create_test_user,
        create_test_equipment,
        equipment_booking_repo,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 8, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            equipment = create_test_equipment()
            booking = EquipmentBooking(
                id="equipment-checkout-boundary",
                user_id=user.id,
                equipment_id=equipment.id,
                start_time=datetime(2024, 6, 15, 9, 0, 0).isoformat(),
                end_time=datetime(2024, 6, 16, 9, 0, 0).isoformat(),
                status=EquipmentBookingStatus.PICKUP_REQUESTED,
                requested_pickup_at=datetime(2024, 6, 15, 9, 0, 0).isoformat(),
            )
            with global_lock():
                equipment_booking_repo.add(booking)

        with mock_now(datetime(2024, 6, 15, 11, 16, 0)):
            with pytest.raises(EquipmentBookingError) as exc_info:
                equipment_service.checkout(admin, booking.id)

            assert "현재 운영 시점" in str(exc_info.value)
            assert equipment_service.booking_repo.get_by_id(booking.id).status == EquipmentBookingStatus.PICKUP_REQUESTED
            assert auth_service.get_user(user.id).penalty_points == 0

    def test_checkout_missing_booking_user_fails(
        self,
        equipment_service,
        create_test_user,
        create_test_equipment,
        equipment_booking_repo,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            equipment = create_test_equipment()
            booking = EquipmentBooking(
                id="equipment-missing-user-checkout",
                user_id="missing-user",
                equipment_id=equipment.id,
                start_time=fixed_time.isoformat(),
                end_time=(fixed_time + timedelta(days=1)).isoformat(),
                status=EquipmentBookingStatus.PICKUP_REQUESTED,
                requested_pickup_at=fixed_time.isoformat(),
            )
            with global_lock():
                equipment_booking_repo.add(booking)

        with mock_now(fixed_time):
            with pytest.raises(EquipmentBookingError) as exc_info:
                equipment_service.checkout(admin, booking.id)

            assert "존재하지 않는 사용자" in str(exc_info.value)

    def test_default_equipment_service_no_longer_applies_auto_no_show_policy(
        self,
        equipment_repo,
        equipment_booking_repo,
        room_booking_repo,
        user_repo,
        audit_repo,
        auth_service,
        create_test_user,
        create_test_equipment,
        mock_now,
    ):
        from src.domain.equipment_service import EquipmentService

        fixed_time = datetime(2024, 6, 15, 10, 0, 0)
        with mock_now(fixed_time):
            service = EquipmentService(
                equipment_repo=equipment_repo,
                booking_repo=equipment_booking_repo,
                room_booking_repo=room_booking_repo,
                user_repo=user_repo,
                audit_repo=audit_repo,
            )
            user = create_test_user()
            admin = create_test_user(username="admin-default", role=UserRole.ADMIN)
            equipment = create_test_equipment()
            booking = service.create_booking(
                user,
                equipment.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(days=1),
            )

        with mock_now(datetime(2024, 6, 15, 11, 16, 0)):
            with pytest.raises(EquipmentBookingError):
                service.checkout(admin, booking.id)

            updated_booking = service.booking_repo.get_by_id(booking.id)
            assert updated_booking is not None
            assert updated_booking.status == EquipmentBookingStatus.RESERVED
            assert auth_service.get_user(user.id).penalty_points == 0

    def test_return_on_time(
        self, equipment_service, create_test_user, create_test_equipment, mock_now
    ):
        """정시 반납"""
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            equipment = create_test_equipment()

            booking = equipment_service.create_booking(
                user,
                equipment.id,
                fixed_time,
                fixed_time + timedelta(days=2),
            )

            requested = equipment_service.request_pickup(user, booking.id)
            assert requested.status == EquipmentBookingStatus.PICKUP_REQUESTED

            equipment_service.checkout(admin, booking.id)

        # 종료 시간 정각에 반납
        return_time = datetime(2024, 6, 17, 9, 0, 0)
        with mock_now(return_time):
            returned, delay = equipment_service.return_equipment(admin, booking.id)

            assert returned.status == EquipmentBookingStatus.RETURNED
            assert delay == 0

    def test_return_requires_exact_boundary(
        self, equipment_service, create_test_user, create_test_equipment, mock_now
    ):
        """종료 경계를 벗어나면 반납 처리 불가"""
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            equipment = create_test_equipment()

            booking = equipment_service.create_booking(
                user,
                equipment.id,
                fixed_time,
                fixed_time + timedelta(days=2),
            )

            requested = equipment_service.request_pickup(user, booking.id)
            assert requested.status == EquipmentBookingStatus.PICKUP_REQUESTED

            equipment_service.checkout(admin, booking.id)

        late_time = datetime(2024, 6, 17, 11, 30, 0)
        with mock_now(late_time):
            with pytest.raises(EquipmentBookingError) as exc_info:
                equipment_service.return_equipment(admin, booking.id)

            assert "현재 운영 시점" in str(exc_info.value)

    def test_return_missing_booking_user_fails(
        self,
        equipment_service,
        create_test_user,
        create_test_equipment,
        equipment_booking_repo,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            equipment = create_test_equipment()
            booking = EquipmentBooking(
                id="equipment-missing-user-return",
                user_id="missing-user",
                equipment_id=equipment.id,
                start_time=fixed_time.isoformat(),
                end_time=(fixed_time + timedelta(days=1)).isoformat(),
                status=EquipmentBookingStatus.CHECKED_OUT,
            )
            with global_lock():
                equipment_booking_repo.add(booking)

        with mock_now(datetime(2024, 6, 16, 9, 0, 0)):
            with pytest.raises(EquipmentBookingError) as exc_info:
                equipment_service.return_equipment(admin, booking.id)

            assert "존재하지 않는 사용자" in str(exc_info.value)

    def test_force_complete_equipment_return_applies_late_penalty(
        self,
        equipment_service,
        auth_service,
        create_test_user,
        create_test_equipment,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin-force", role=UserRole.ADMIN)
            equipment = create_test_equipment()
            booking = equipment_service.create_booking(
                user,
                equipment.id,
                fixed_time,
                fixed_time + timedelta(days=1),
            )
            equipment_service.request_pickup(user, booking.id)
            equipment_service.checkout(admin, booking.id)

        with mock_now(datetime(2024, 6, 16, 9, 0, 0)):
            returned, delay = equipment_service.force_complete_return(admin, booking.id)

            assert returned.status == EquipmentBookingStatus.RETURNED
            assert delay == 60
            assert auth_service.get_user(user.id).penalty_points == 2


class TestNoShowEquipment:
    """장비 노쇼 처리 테스트"""

    def test_mark_no_show(
        self, equipment_service, create_test_user, create_test_equipment, mock_now
    ):
        """노쇼 처리"""
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            equipment = create_test_equipment()

            booking = equipment_service.create_booking(
                user,
                equipment.id,
                fixed_time,
                fixed_time + timedelta(days=2),
            )

            no_show = equipment_service.mark_no_show(booking.id, admin=admin)

            assert no_show.status == EquipmentBookingStatus.NO_SHOW
            assert equipment_service.user_repo.get_by_id(user.id).penalty_points == 3

    def test_mark_no_show_missing_user_fails(
        self,
        equipment_service,
        create_test_user,
        create_test_equipment,
        equipment_booking_repo,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            equipment = create_test_equipment()
            booking = EquipmentBooking(
                id="equipment-noshow-missing-user",
                user_id="missing-user",
                equipment_id=equipment.id,
                start_time=fixed_time.isoformat(),
                end_time=(fixed_time + timedelta(days=1)).isoformat(),
                status=EquipmentBookingStatus.RESERVED,
            )
            with global_lock():
                equipment_booking_repo.add(booking)

            with pytest.raises(EquipmentBookingError) as exc_info:
                equipment_service.mark_no_show(booking.id, admin=admin)

            assert "존재하지 않는 사용자" in str(exc_info.value)


class TestAdminEquipmentFunctions:
    """관리자 장비 기능 테스트"""

    def test_admin_cancel_booking(
        self, equipment_service, create_test_user, create_test_equipment, mock_now
    ):
        """관리자 예약 취소"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            equipment = create_test_equipment()

            booking = equipment_service.create_booking(
                user,
                equipment.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(days=2),
            )

            cancelled = equipment_service.admin_cancel_booking(
                admin, booking.id, "장비 점검"
            )

            assert cancelled.status == EquipmentBookingStatus.ADMIN_CANCELLED

    def test_admin_cancel_booking_missing_owner_fails(
        self,
        equipment_service,
        create_test_user,
        create_test_equipment,
        equipment_booking_repo,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            equipment = create_test_equipment()
            booking = EquipmentBooking(
                id="equipment-admin-cancel-missing-user",
                user_id="missing-user",
                equipment_id=equipment.id,
                start_time=(fixed_time + timedelta(hours=1)).isoformat(),
                end_time=(fixed_time + timedelta(days=1)).isoformat(),
                status=EquipmentBookingStatus.RESERVED,
            )
            with global_lock():
                equipment_booking_repo.add(booking)

            with pytest.raises(EquipmentBookingError) as exc_info:
                equipment_service.admin_cancel_booking(admin, booking.id, "장비 점검")

            assert "존재하지 않는 사용자" in str(exc_info.value)

    def test_admin_modify_booking_missing_owner_fails(
        self,
        equipment_service,
        create_test_user,
        create_test_equipment,
        equipment_booking_repo,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            equipment = create_test_equipment()
            booking = EquipmentBooking(
                id="equipment-admin-modify-missing-user",
                user_id="missing-user",
                equipment_id=equipment.id,
                start_time=(fixed_time + timedelta(hours=1)).isoformat(),
                end_time=(fixed_time + timedelta(days=1)).isoformat(),
                status=EquipmentBookingStatus.RESERVED,
            )
            with global_lock():
                equipment_booking_repo.add(booking)

            with pytest.raises(EquipmentBookingError) as exc_info:
                equipment_service.admin_modify_booking(
                    admin,
                    booking.id,
                    fixed_time + timedelta(hours=3),
                    fixed_time + timedelta(days=2),
                )

            assert "존재하지 않는 사용자" in str(exc_info.value)

    def test_update_equipment_status_cancels_future_bookings(
        self, equipment_service, create_test_user, create_test_equipment, mock_now
    ):
        """장비 상태 변경 시 미래 예약 자동 취소"""
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user()
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            equipment = create_test_equipment()

            # 미래 예약 생성
            booking = equipment_service.create_booking(
                user,
                equipment.id,
                fixed_time + timedelta(hours=1),
                fixed_time + timedelta(days=2),
            )

            # 상태 변경
            updated, cancelled = equipment_service.update_equipment_status(
                admin, equipment.id, ResourceStatus.MAINTENANCE
            )

            assert updated.status == ResourceStatus.MAINTENANCE
            assert len(cancelled) == 1
            assert cancelled[0].status == EquipmentBookingStatus.ADMIN_CANCELLED

    def test_update_equipment_status_missing_booking_owner_fails(
        self,
        equipment_service,
        create_test_user,
        create_test_equipment,
        equipment_booking_repo,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            admin = create_test_user(username="admin", role=UserRole.ADMIN)
            equipment = create_test_equipment()
            booking = EquipmentBooking(
                id="equipment-status-missing-user",
                user_id="missing-user",
                equipment_id=equipment.id,
                start_time=(fixed_time + timedelta(hours=1)).isoformat(),
                end_time=(fixed_time + timedelta(days=1)).isoformat(),
                status=EquipmentBookingStatus.RESERVED,
            )
            with global_lock():
                equipment_booking_repo.add(booking)

            with pytest.raises(EquipmentBookingError) as exc_info:
                equipment_service.update_equipment_status(
                    admin, equipment.id, ResourceStatus.MAINTENANCE
                )

            assert "존재하지 않는 사용자" in str(exc_info.value)


class TestAdminOnlyEquipmentAccess:
    """관리자 전용 API 접근 제어 테스트"""

    def test_get_all_bookings_rejects_non_admin(
        self, equipment_service, create_test_user
    ):
        """일반 사용자가 전체 예약 조회 시 거부"""
        from src.domain.equipment_service import AdminRequiredError

        user = create_test_user()

        with pytest.raises(AdminRequiredError) as exc_info:
            equipment_service.get_all_bookings(user)

        assert "관리자" in str(exc_info.value)

    def test_get_all_bookings_rejects_nonexistent_admin(
        self, equipment_service, user_factory
    ):
        from src.domain.equipment_service import AdminRequiredError

        fake_admin = user_factory(role=UserRole.ADMIN)

        with pytest.raises(AdminRequiredError) as exc_info:
            equipment_service.get_all_bookings(fake_admin)

        assert "관리자" in str(exc_info.value)


class TestEquipmentBookingQueries:
    def test_get_user_bookings_nonexistent_user_fails(self, equipment_service):
        with pytest.raises(EquipmentBookingError) as exc_info:
            equipment_service.get_user_bookings("missing-user")

        assert "존재하지 않는 사용자" in str(exc_info.value)

    def test_get_user_active_bookings_nonexistent_user_fails(self, equipment_service):
        with pytest.raises(EquipmentBookingError) as exc_info:
            equipment_service.get_user_active_bookings("missing-user")

        assert "존재하지 않는 사용자" in str(exc_info.value)
