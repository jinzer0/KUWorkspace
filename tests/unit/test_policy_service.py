"""정책 서비스 테스트"""

import pytest
from datetime import datetime, timedelta

from src.cli.admin_menu import AdminMenu
from src.storage.integrity import DataIntegrityError
from src.domain.penalty_service import PenaltyError
from src.domain.models import (
    RoomBooking,
    EquipmentBooking,
    RoomBookingStatus,
    EquipmentBookingStatus,
    PenaltyReason,
    ResourceStatus,
    RoomMaintenanceSchedule,
    UserRole,
    encode_future_status_changes,
)
from src.storage.file_lock import global_lock


class TestClockAdvance:
    def test_prepare_advance_blocks_room_start_without_force(
        self,
        policy_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        fake_clock,
    ):
        current_time = datetime(2024, 6, 16, 9, 0, 0)
        fake_clock(current_time)
        user = create_test_user()
        room = create_test_room()

        booking = RoomBooking(
            id="booking-1",
            user_id=user.id,
            room_id=room.id,
            start_time=current_time.isoformat(),
            end_time=datetime(2024, 6, 16, 18, 0, 0).isoformat(),
            status=RoomBookingStatus.RESERVED,
        )
        with global_lock():
            room_booking_repo.add(booking)

        result = policy_service.prepare_advance(actor_id=user.id)

        assert result["can_advance"] is False
        assert any("자동 취소" in blocker for blocker in result["blockers"])
        assert "현재 사용자에게 부과" in result["force_notice"]

    def test_prepare_advance_blocks_equipment_end_without_user_request(
        self,
        policy_service,
        create_test_user,
        create_test_equipment,
        equipment_booking_repo,
        fake_clock,
    ):
        current_time = datetime(2024, 6, 16, 18, 0, 0)
        fake_clock(current_time)
        user = create_test_user()
        equipment = create_test_equipment()

        booking = EquipmentBooking(
            id="eq-booking-1",
            user_id=user.id,
            equipment_id=equipment.id,
            start_time=datetime(2024, 6, 16, 9, 0, 0).isoformat(),
            end_time=current_time.isoformat(),
            status=EquipmentBookingStatus.CHECKED_OUT,
        )
        with global_lock():
            equipment_booking_repo.add(booking)

        result = policy_service.prepare_advance(actor_id=user.id)

        assert result["can_advance"] is False
        assert any("반납 신청" in blocker for blocker in result["blockers"])

    def test_advance_time_moves_clock_and_logs_event_when_clear(
        self,
        policy_service,
        audit_repo,
        fake_clock,
    ):
        current_time = datetime(2024, 6, 16, 18, 0, 0)
        fake_clock(current_time)

        result = policy_service.advance_time(actor_id="admin-1")

        assert result["can_advance"] is True
        assert result["next_time"] == datetime(2024, 6, 17, 9, 0, 0)
        assert any("운영 시점이" in event for event in result["events"])

        logs = audit_repo.get_by_actor("admin-1")
        assert any(log.action == "clock_advance" for log in logs)

    def test_advance_time_persists_09_to_18_clock_and_audit_together(
        self,
        policy_service,
        auth_service,
        create_test_room,
        room_booking_repo,
        audit_repo,
        fake_clock,
        temp_data_dir,
    ):
        current_time = datetime(2024, 6, 16, 9, 0, 0)
        clock = fake_clock(current_time)
        clock_file = temp_data_dir / "clock.txt"
        booking_user = auth_service.signup("Atomic_success_user", "pass1")
        admin = auth_service.signup("Atomic_success_admin", "pass1", role=UserRole.ADMIN)
        room = create_test_room()

        booking = RoomBooking(
            id="atomic-success-booking",
            user_id=booking_user.id,
            room_id=room.id,
            start_time=current_time.isoformat(),
            end_time=current_time.replace(hour=18).isoformat(),
            status=RoomBookingStatus.RESERVED,
        )
        with global_lock():
            room_booking_repo.add(booking)

        result = policy_service.advance_time(actor_id=admin.id, force=True)

        assert result["can_advance"] is True
        assert result["next_time"] == datetime(2024, 6, 16, 18, 0, 0)
        assert clock.now() == datetime(2024, 6, 16, 18, 0, 0)
        assert clock_file.read_text(encoding="utf-8") == "2024-06-16T18:00"
        assert room_booking_repo.get_by_id(booking.id).status == RoomBookingStatus.ADMIN_CANCELLED
        logs = audit_repo.get_by_actor(admin.id)
        assert any(log.action == "clock_advance" for log in logs)
        assert any(log.action == "apply_late_cancel_penalty" for log in audit_repo.get_all())

    def test_clock_reads_do_not_trigger_policy_automation(
        self,
        policy_service,
        audit_repo,
        fake_clock,
    ):
        current_time = datetime(2024, 6, 16, 9, 0, 0)
        fake_clock(current_time)

        assert policy_service.clock.now() == current_time
        assert policy_service.clock.current_slot() == "09:00"
        assert policy_service.clock.next_slot() == datetime(2024, 6, 16, 18, 0, 0)
        assert audit_repo.get_all() == []

    def test_advance_time_rolls_back_clock_when_audit_replace_fails(
        self,
        policy_service,
        audit_repo,
        fake_clock,
        temp_data_dir,
        monkeypatch,
    ):
        current_time = datetime(2024, 6, 16, 9, 0, 0)
        clock = fake_clock(current_time)
        clock_file = temp_data_dir / "clock.txt"
        original_replace = __import__("os").replace
        clock_was_replaced = {"value": False}

        def fail_after_clock_replace(tmp_path, target_path):
            if str(target_path).endswith("audit_log.txt"):
                assert clock_was_replaced["value"] is True
                raise OSError("audit replace failed")
            original_replace(tmp_path, target_path)
            if str(target_path).endswith("audit_log.txt"):
                return
            if str(target_path).endswith("clock.txt"):
                clock_was_replaced["value"] = True

        monkeypatch.setattr("src.storage.atomic_writer.os.replace", fail_after_clock_replace)

        with pytest.raises(DataIntegrityError, match="audit replace failed"):
            policy_service.advance_time(actor_id="admin-1")

        assert clock.now() == current_time
        assert clock_file.read_text(encoding="utf-8") == "2024-06-16T09:00"
        assert audit_repo.get_by_actor("admin-1") == []

    def test_advance_time_applies_future_status_before_pending_promotion(
        self,
        policy_service,
        create_test_user,
        create_test_equipment,
        equipment_repo,
        equipment_booking_repo,
        equipment_booking_factory,
        fake_clock,
    ):
        current_time = datetime(2024, 6, 16, 18, 0, 0)
        fake_clock(current_time)
        user = create_test_user(username="future_user")
        next_time = datetime(2024, 6, 17, 9, 0, 0)
        end_time = datetime(2024, 6, 17, 18, 0, 0)
        equipment = create_test_equipment(
            serial_number="FP-001",
            future_status_changes=encode_future_status_changes(
                [
                    {
                        "id": "future-maintenance",
                        "start_time": next_time.isoformat(),
                        "end_time": end_time.isoformat(),
                        "status": ResourceStatus.MAINTENANCE.value,
                        "restore_status": ResourceStatus.AVAILABLE.value,
                        "state": "pending",
                    }
                ]
            ),
        )

        with global_lock():
            equipment_booking_repo.add(
                equipment_booking_factory(
                    id="future-status-pending",
                    user_id=user.id,
                    equipment_id=equipment.id,
                    start_time=next_time.isoformat(),
                    end_time=end_time.isoformat(),
                    status=EquipmentBookingStatus.PENDING,
                    created_at="2024-06-16T10:00",
                )
            )

        result = policy_service.advance_time(actor_id="system")

        assert result["can_advance"] is True
        assert result["maintenance"]["equipment_future_status_changes"] == [
            f"장비 {equipment.id} 예정 상태 시작: maintenance"
        ]
        assert result["maintenance"]["equipment_pending_promoted"] == []
        assert equipment_repo.get_by_id(equipment.id).status == ResourceStatus.MAINTENANCE
        assert (
            equipment_booking_repo.get_by_id("future-status-pending").status
            == EquipmentBookingStatus.PENDING
        )
        assert any(
            log.action == "apply_equipment_future_status_change"
            and log.target_id == equipment.id
            for log in policy_service.audit_repo.get_all()
        )


    def test_pending_resolver_writes_audit_actions(
        self,
        policy_service,
        create_test_user,
        create_test_room,
        create_test_equipment,
        room_booking_repo,
        equipment_booking_repo,
        room_booking_factory,
        equipment_booking_factory,
        fake_clock,
    ):
        current_time = datetime(2024, 6, 16, 18, 0, 0)
        fake_clock(current_time)
        first_user = create_test_user(username="resolver_first")
        second_user = create_test_user(username="resolver_second")
        room = create_test_room()
        equipment = create_test_equipment(serial_number="RS-001")
        next_time = datetime(2024, 6, 17, 9, 0, 0)
        end_time = datetime(2024, 6, 17, 18, 0, 0)

        with global_lock():
            room_booking_repo.add(
                room_booking_factory(
                    id="room-pending-winner",
                    user_id=first_user.id,
                    room_id=room.id,
                    start_time=next_time.isoformat(),
                    end_time=end_time.isoformat(),
                    status=RoomBookingStatus.PENDING,
                    created_at="2024-06-16T10:00",
                )
            )
            room_booking_repo.add(
                room_booking_factory(
                    id="room-pending-loser",
                    user_id=second_user.id,
                    room_id=room.id,
                    start_time=next_time.isoformat(),
                    end_time=end_time.isoformat(),
                    status=RoomBookingStatus.PENDING,
                    created_at="2024-06-16T10:01",
                )
            )
            equipment_booking_repo.add(
                equipment_booking_factory(
                    id="equipment-pending-winner",
                    user_id=first_user.id,
                    equipment_id=equipment.id,
                    start_time=next_time.isoformat(),
                    end_time=end_time.isoformat(),
                    status=EquipmentBookingStatus.PENDING,
                    created_at="2024-06-16T10:00",
                )
            )
            equipment_booking_repo.add(
                equipment_booking_factory(
                    id="equipment-pending-loser",
                    user_id=second_user.id,
                    equipment_id=equipment.id,
                    start_time=next_time.isoformat(),
                    end_time=end_time.isoformat(),
                    status=EquipmentBookingStatus.PENDING,
                    created_at="2024-06-16T10:01",
                )
            )

        result = policy_service.advance_time(actor_id="system")

        assert result["can_advance"] is True
        actions_by_target = {
            log.target_id: log.action for log in policy_service.audit_repo.get_all()
        }
        assert actions_by_target["room-pending-winner"] == "resolve_room_pending_booking_promote"
        assert actions_by_target["room-pending-loser"] == "resolve_room_pending_booking_cancel"
        assert actions_by_target["equipment-pending-winner"] == "resolve_equipment_pending_booking_promote"
        assert actions_by_target["equipment-pending-loser"] == "resolve_equipment_pending_booking_cancel"

    def test_advance_time_keeps_room_pending_when_maintenance_exists(
        self,
        policy_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        room_maintenance_repo,
        room_booking_factory,
        fake_clock,
    ):
        current_time = datetime(2024, 6, 16, 18, 0, 0)
        fake_clock(current_time)
        user = create_test_user(username="maint_user")
        room = create_test_room()
        next_time = datetime(2024, 6, 17, 9, 0, 0)
        end_time = datetime(2024, 6, 17, 18, 0, 0)

        with global_lock():
            room_maintenance_repo.add(
                RoomMaintenanceSchedule(
                    id="maintenance-blocks-pending",
                    room_id=room.id,
                    start_time=next_time.isoformat(),
                    end_time=end_time.isoformat(),
                    reason="정기점검",
                )
            )
            room_booking_repo.add(
                room_booking_factory(
                    id="maintenance-room-pending",
                    user_id=user.id,
                    room_id=room.id,
                    start_time=next_time.isoformat(),
                    end_time=end_time.isoformat(),
                    status=RoomBookingStatus.PENDING,
                    created_at="2024-06-16T10:00",
                )
            )

        result = policy_service.advance_time(actor_id="system")

        assert result["can_advance"] is True
        assert result["maintenance"]["room_pending_promoted"] == []
        assert (
            room_booking_repo.get_by_id("maintenance-room-pending").status
            == RoomBookingStatus.PENDING
        )

    def test_advance_time_rolls_back_automation_when_later_policy_fails(
        self,
        policy_service,
        create_test_user,
        create_test_equipment,
        equipment_repo,
        equipment_booking_repo,
        equipment_booking_factory,
        fake_clock,
        temp_data_dir,
        monkeypatch,
    ):
        current_time = datetime(2024, 6, 16, 18, 0, 0)
        clock = fake_clock(current_time)
        user = create_test_user(username="rollback_user")
        next_time = datetime(2024, 6, 17, 9, 0, 0)
        end_time = datetime(2024, 6, 17, 18, 0, 0)
        equipment = create_test_equipment(
            serial_number="RB-001",
            future_status_changes=encode_future_status_changes(
                [
                    {
                        "id": "rollback-maintenance",
                        "start_time": next_time.isoformat(),
                        "end_time": end_time.isoformat(),
                        "status": ResourceStatus.MAINTENANCE.value,
                        "restore_status": ResourceStatus.AVAILABLE.value,
                        "state": "pending",
                    }
                ]
            ),
        )

        with global_lock():
            equipment_booking_repo.add(
                equipment_booking_factory(
                    id="rollback-future-pending",
                    user_id=user.id,
                    equipment_id=equipment.id,
                    start_time=next_time.isoformat(),
                    end_time=end_time.isoformat(),
                    status=EquipmentBookingStatus.PENDING,
                    created_at="2024-06-16T10:00",
                )
            )

        def fail_after_pending_step(current_time):
            raise RuntimeError("injected later automation failure")

        monkeypatch.setattr(policy_service, "_check_penalty_resets", fail_after_pending_step)

        with pytest.raises(RuntimeError, match="injected later automation failure"):
            policy_service.advance_time(actor_id="system")

        assert clock.now() == current_time
        assert temp_data_dir.joinpath("clock.txt").read_text(encoding="utf-8") == "2024-06-16T18:00"
        assert equipment_repo.get_by_id(equipment.id).status == ResourceStatus.AVAILABLE
        assert (
            equipment_repo.get_by_id(equipment.id).future_status_changes
            == equipment.future_status_changes
        )
        assert (
            equipment_booking_repo.get_by_id("rollback-future-pending").status
            == EquipmentBookingStatus.PENDING
        )

    def test_advance_time_blocked_without_force_writes_audit_log(
        self,
        policy_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        audit_repo,
        fake_clock,
    ):
        current_time = datetime(2024, 6, 16, 9, 0, 0)
        fake_clock(current_time)
        user = create_test_user()
        room = create_test_room()

        booking = RoomBooking(
            id="blocked-booking",
            user_id=user.id,
            room_id=room.id,
            start_time=current_time.isoformat(),
            end_time=datetime(2024, 6, 16, 18, 0, 0).isoformat(),
            status=RoomBookingStatus.RESERVED,
        )
        with global_lock():
            room_booking_repo.add(booking)

        result = policy_service.advance_time(actor_id=user.id)

        assert result["can_advance"] is False
        logs = audit_repo.get_by_actor(user.id)
        assert any(log.action == "clock_advance_blocked" for log in logs)

    def test_forced_non_admin_advance_blames_advancing_user_for_start_side_penalty(
        self,
        policy_service,
        auth_service,
        create_test_room,
        room_booking_repo,
        penalty_repo,
        fake_clock,
    ):
        current_time = datetime(2024, 6, 16, 9, 0, 0)
        fake_clock(current_time)
        booking_user = auth_service.signup("Booking_user", "pass1")
        advancing_user = auth_service.signup("Advancing_user", "pass1")
        room = create_test_room()

        booking = RoomBooking(
            id="forced-room-booking",
            user_id=booking_user.id,
            room_id=room.id,
            start_time=current_time.isoformat(),
            end_time=current_time.replace(hour=18).isoformat(),
            status=RoomBookingStatus.RESERVED,
        )
        with global_lock():
            room_booking_repo.add(booking)

        result = policy_service.advance_time(actor_id=advancing_user.id, force=True)

        assert result["can_advance"] is True
        updated_booking = room_booking_repo.get_by_id(booking.id)
        assert updated_booking.status == RoomBookingStatus.ADMIN_CANCELLED
        assert auth_service.get_user(advancing_user.id).penalty_points == 2
        assert auth_service.get_user(booking_user.id).penalty_points == 0
        penalties = penalty_repo.get_by_user(advancing_user.id)
        assert penalties[0].reason == PenaltyReason.LATE_CANCEL
        penalty_logs = [
            log
            for log in policy_service.audit_repo.get_all()
            if log.action == "apply_late_cancel_penalty"
        ]
        assert penalty_logs[0].actor_id == advancing_user.id
        assert penalty_logs[0].target_id == advancing_user.id

    def test_forced_admin_advance_keeps_penalty_on_original_user(
        self,
        policy_service,
        auth_service,
        create_test_room,
        room_booking_repo,
        penalty_repo,
        fake_clock,
    ):
        current_time = datetime(2024, 6, 16, 9, 0, 0)
        fake_clock(current_time)
        booking_user = auth_service.signup("Admin_force_user", "pass1")
        admin = auth_service.signup("Clock_admin", "pass1", role=UserRole.ADMIN)
        room = create_test_room()

        booking = RoomBooking(
            id="admin-forced-room-booking",
            user_id=booking_user.id,
            room_id=room.id,
            start_time=current_time.isoformat(),
            end_time=current_time.replace(hour=18).isoformat(),
            status=RoomBookingStatus.RESERVED,
        )
        with global_lock():
            room_booking_repo.add(booking)

        result = policy_service.advance_time(actor_id=admin.id, force=True)

        assert result["can_advance"] is True
        assert auth_service.get_user(admin.id).penalty_points == 0
        assert auth_service.get_user(booking_user.id).penalty_points == 2
        penalties = penalty_repo.get_by_user(booking_user.id)
        assert penalties[0].reason == PenaltyReason.LATE_CANCEL

    def test_forced_non_admin_advance_blames_advancing_user_for_end_side_penalty(
        self,
        policy_service,
        auth_service,
        create_test_room,
        room_booking_repo,
        penalty_repo,
        fake_clock,
    ):
        current_time = datetime(2024, 6, 16, 18, 0, 0)
        fake_clock(current_time)
        booking_user = auth_service.signup("Late_checkout_owner", "pass1")
        advancing_user = auth_service.signup("Late_checkout_forcer", "pass1")
        room = create_test_room()

        booking = RoomBooking(
            id="late-room-booking",
            user_id=booking_user.id,
            room_id=room.id,
            start_time=current_time.replace(hour=9).isoformat(),
            end_time=current_time.isoformat(),
            status=RoomBookingStatus.CHECKED_IN,
            checked_in_at=current_time.replace(hour=9).isoformat(),
        )
        with global_lock():
            room_booking_repo.add(booking)

        result = policy_service.advance_time(actor_id=advancing_user.id, force=True)

        assert result["can_advance"] is True
        assert auth_service.get_user(advancing_user.id).penalty_points == 2
        assert auth_service.get_user(booking_user.id).penalty_points == 0
        penalties = penalty_repo.get_by_user(advancing_user.id)
        assert penalties[0].reason == PenaltyReason.LATE_RETURN


class TestPenaltyResetAutomation:
    def test_penalty_reset_after_90_days(
        self, policy_service, create_test_user, penalty_repo, mock_now
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user(penalty_points=5)

        from src.domain.models import Penalty, generate_id

        old_penalty = Penalty(
            id=generate_id(),
            user_id=user.id,
            reason=PenaltyReason.OTHER,
            points=3,
            related_type="room_booking",
            related_id="old-booking",
            created_at=(fixed_time - timedelta(days=91)).isoformat(),
        )
        with global_lock():
            penalty_repo.add(old_penalty)

        with mock_now(fixed_time):
            results = policy_service.run_all_checks(fixed_time)
            assert user.id in results["penalty_reset_users"]


class TestRestrictionExpiry:
    def test_restriction_expires(
        self, policy_service, create_test_user, user_repo, mock_now
    ):
        expired_time = datetime(2024, 6, 10, 10, 0, 0)
        check_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(check_time):
            user = create_test_user(
                penalty_points=3, restriction_until=expired_time.isoformat()
            )

            results = policy_service.run_all_checks(check_time)

            assert user.id in results["restriction_expired_users"]
            updated = user_repo.get_by_id(user.id)
            assert updated.restriction_until is None


class TestBannedUserBookingCancellation:
    def test_banned_user_future_bookings_cancelled(
        self,
        policy_service,
        create_test_user,
        create_test_room,
        room_booking_repo,
        mock_now,
    ):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user(
                penalty_points=6,
                restriction_until=(fixed_time + timedelta(days=30)).isoformat(),
            )
            room = create_test_room()

            future_booking = RoomBooking(
                id="future-booking",
                user_id=user.id,
                room_id=room.id,
                start_time=(fixed_time + timedelta(hours=2)).isoformat(),
                end_time=(fixed_time + timedelta(hours=3)).isoformat(),
                status=RoomBookingStatus.RESERVED,
            )
            with global_lock():
                room_booking_repo.add(future_booking)

            results = policy_service.run_all_checks(fixed_time)

            assert "future-booking" in results["banned_user_cancelled_bookings"]
            updated = room_booking_repo.get_by_id("future-booking")
            assert updated.status == RoomBookingStatus.ADMIN_CANCELLED


class TestCheckUserCanBook:
    def test_inspect1_pending_bookings_do_not_count_toward_active_quota(
        self,
        policy_service,
        create_test_user,
        room_booking_repo,
        equipment_booking_repo,
        room_booking_factory,
        equipment_booking_factory,
    ):
        user = create_test_user(username="InspectQuotaUser")
        with global_lock():
            for index in range(3):
                room_booking_repo.add(
                    room_booking_factory(
                        id=f"inspect1-room-pending-{index}",
                        user_id=user.id,
                        room_id=f"room-{index}",
                        status=RoomBookingStatus.PENDING,
                    )
                )
                equipment_booking_repo.add(
                    equipment_booking_factory(
                        id=f"inspect1-equipment-pending-{index}",
                        user_id=user.id,
                        equipment_id=f"equipment-{index}",
                        status=EquipmentBookingStatus.PENDING,
                    )
                )

        limits = policy_service.get_user_flow_limits(user)

        assert room_booking_repo.get_quota_active_by_user(user.id) == []
        assert equipment_booking_repo.get_quota_active_by_user(user.id) == []
        assert limits["room_limit"] == 3
        assert limits["equipment_limit"] == 3

    def test_inspect1_confirmed_statuses_still_count_toward_active_quota(
        self,
        policy_service,
        create_test_user,
        room_booking_repo,
        equipment_booking_repo,
        room_booking_factory,
        equipment_booking_factory,
    ):
        user = create_test_user(username="InspectConfirmedQuotaUser")
        with global_lock():
            for status in (
                RoomBookingStatus.RESERVED,
                RoomBookingStatus.CHECKIN_REQUESTED,
                RoomBookingStatus.CHECKED_IN,
                RoomBookingStatus.CHECKOUT_REQUESTED,
            ):
                room_booking_repo.add(
                    room_booking_factory(
                        id=f"inspect1-room-{status.value}",
                        user_id=user.id,
                        status=status,
                    )
                )
            for status in (
                EquipmentBookingStatus.RESERVED,
                EquipmentBookingStatus.PICKUP_REQUESTED,
                EquipmentBookingStatus.CHECKED_OUT,
                EquipmentBookingStatus.RETURN_REQUESTED,
            ):
                equipment_booking_repo.add(
                    equipment_booking_factory(
                        id=f"inspect1-equipment-{status.value}",
                        user_id=user.id,
                        status=status,
                    )
                )

        limits = policy_service.get_user_flow_limits(user)

        assert len(room_booking_repo.get_quota_active_by_user(user.id)) == 4
        assert len(equipment_booking_repo.get_quota_active_by_user(user.id)) == 4
        assert limits["room_limit"] == 0
        assert limits["equipment_limit"] == 0

    def test_inspect1_restricted_user_pending_bookings_do_not_consume_one_each_limit(
        self,
        policy_service,
        create_test_user,
        room_booking_repo,
        equipment_booking_repo,
        room_booking_factory,
        equipment_booking_factory,
        fake_clock,
    ):
        fixed_time = datetime(2024, 6, 15, 9, 0, 0)
        fake_clock(fixed_time)
        user = create_test_user(
            username="InspectRestrictedPendingQuotaUser",
            penalty_points=3,
            restriction_until=(fixed_time + timedelta(days=7)).isoformat(),
        )
        with global_lock():
            room_booking_repo.add(
                room_booking_factory(
                    id="inspect1-restricted-room-pending",
                    user_id=user.id,
                    status=RoomBookingStatus.PENDING,
                )
            )
            equipment_booking_repo.add(
                equipment_booking_factory(
                    id="inspect1-restricted-equipment-pending",
                    user_id=user.id,
                    status=EquipmentBookingStatus.PENDING,
                )
            )

        can_book, max_total, message = policy_service.check_user_can_book(user)
        limits = policy_service.get_user_flow_limits(user)

        assert can_book is True
        assert max_total == 2
        assert "1건" in message
        assert limits["room_limit"] == 1
        assert limits["equipment_limit"] == 1

    def test_normal_user_can_book(self, policy_service, create_test_user):
        user = create_test_user(penalty_points=0)

        can_book, max_total, message = policy_service.check_user_can_book(user)

        assert can_book is True
        assert max_total == 6
        assert message == ""

    def test_plan0001_admin_dispatch_renumbers_resource_menus(
        self,
        monkeypatch,
        auth_service,
        room_service,
        equipment_service,
        penalty_service,
        policy_service,
        create_test_user,
        capsys,
    ):
        admin = create_test_user(username="DispatchAdmin", role=UserRole.ADMIN)
        menu = AdminMenu(
            user=admin,
            auth_service=auth_service,
            room_service=room_service,
            equipment_service=equipment_service,
            penalty_service=penalty_service,
            policy_service=policy_service,
        )
        inputs = iter(["0"])

        monkeypatch.setattr(menu, "_run_policy_checks", lambda: True)
        monkeypatch.setattr(menu, "_refresh_admin", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
        monkeypatch.setattr("src.cli.admin_menu.confirm", lambda _msg: True)
        monkeypatch.setattr("src.cli.admin_menu.print_success", lambda *_: None)

        assert menu.run() is True
        output = capsys.readouterr().out
        assert "7. 회의실 수정 (관리자)" in output
        assert "8. 전체 장비 예약 조회" in output
        assert "20. 운영 시계" in output
        assert "21." not in output
        assert "잘못된 선택입니다." in output

    def test_banned_user_cannot_book(self, policy_service, create_test_user, mock_now):
        fixed_time = datetime(2024, 6, 15, 10, 0, 0)

        with mock_now(fixed_time):
            user = create_test_user(
                penalty_points=6,
                restriction_until=(fixed_time + timedelta(days=30)).isoformat(),
            )

            can_book, max_total, message = policy_service.check_user_can_book(user)

            assert can_book is False
            assert max_total == 0
            assert "금지" in message

    def test_nonexistent_user_cannot_book(self, policy_service, user_factory):
        fake_user = user_factory(id="missing-user")

        with pytest.raises(PenaltyError) as exc_info:
            policy_service.check_user_can_book(fake_user)

        assert "존재하지 않는 사용자" in str(exc_info.value)
