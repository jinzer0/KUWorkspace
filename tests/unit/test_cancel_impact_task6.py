from datetime import datetime, timedelta

from src.domain.models import (
    EquipmentBookingStatus,
    PenaltyReason,
    RoomBookingStatus,
)
from src.storage.file_lock import global_lock


CURRENT_TIME = datetime(2024, 6, 15, 9, 0)


def _add_room_booking(room_booking_repo, room_booking_factory, user_id, *, days_until_start, cancelled_days_ago=None, status=RoomBookingStatus.CANCELLED, booking_id=None):
    start_time = CURRENT_TIME + timedelta(days=days_until_start)
    cancelled_at = None
    if cancelled_days_ago is not None:
        cancelled_at = (CURRENT_TIME - timedelta(days=cancelled_days_ago)).isoformat()
    booking = room_booking_factory(
        id=booking_id,
        user_id=user_id,
        room_id="room-task6",
        start_time=start_time.isoformat(),
        end_time=(start_time + timedelta(hours=1)).isoformat(),
        status=status,
        cancelled_at=cancelled_at,
    )
    with global_lock():
        room_booking_repo.add(booking)
    return booking


def _add_equipment_booking(equipment_booking_repo, equipment_booking_factory, user_id, *, days_until_start, cancelled_days_ago=None, status=EquipmentBookingStatus.CANCELLED, booking_id=None):
    start_time = CURRENT_TIME + timedelta(days=days_until_start)
    cancelled_at = None
    if cancelled_days_ago is not None:
        cancelled_at = (CURRENT_TIME - timedelta(days=cancelled_days_ago)).isoformat()
    booking = equipment_booking_factory(
        id=booking_id,
        user_id=user_id,
        equipment_id="equipment-task6",
        start_time=start_time.isoformat(),
        end_time=(start_time + timedelta(hours=1)).isoformat(),
        status=status,
        cancelled_at=cancelled_at,
    )
    with global_lock():
        equipment_booking_repo.add(booking)
    return booking


class TestTask6CancelImpact:
    def test_third_frequent_cancel_preview_reports_restriction_without_mutation(
        self,
        fake_clock,
        create_test_user,
        room_service,
        room_booking_repo,
        room_booking_factory,
        penalty_repo,
    ):
        fake_clock(CURRENT_TIME)
        user = create_test_user()
        _add_room_booking(room_booking_repo, room_booking_factory, user.id, days_until_start=-8, cancelled_days_ago=10)
        _add_room_booking(room_booking_repo, room_booking_factory, user.id, days_until_start=-3, cancelled_days_ago=5)
        current = _add_room_booking(
            room_booking_repo,
            room_booking_factory,
            user.id,
            days_until_start=13,
            status=RoomBookingStatus.RESERVED,
            booking_id="room-third-preview",
        )

        impact = room_service.preview_cancel_booking_impact(user, current.id)

        assert impact.qualifies_frequent_cancel is True
        assert impact.frequent_cancel_count == 3
        assert impact.applies_cancel_restriction is True
        assert impact.cancel_restriction_field == "room_cancel_restricted_until"
        assert impact.applies_frequent_cancel_penalty is True
        assert impact.penalty_reasons == (PenaltyReason.FREQUENT_CANCEL,)
        assert penalty_repo.get_by_user(user.id) == []
        unchanged_user = room_service.user_repo.get_by_id(user.id)
        assert unchanged_user.room_cancel_restricted_until is None
        assert room_booking_repo.get_by_id(current.id).status == RoomBookingStatus.RESERVED

    def test_confirm_third_frequent_cancel_sets_room_restriction_only(
        self,
        fake_clock,
        create_test_user,
        room_service,
        room_booking_repo,
        room_booking_factory,
        penalty_repo,
    ):
        fake_clock(CURRENT_TIME)
        user = create_test_user()
        _add_room_booking(room_booking_repo, room_booking_factory, user.id, days_until_start=-8, cancelled_days_ago=10)
        _add_room_booking(room_booking_repo, room_booking_factory, user.id, days_until_start=-3, cancelled_days_ago=5)
        current = _add_room_booking(
            room_booking_repo,
            room_booking_factory,
            user.id,
            days_until_start=13,
            status=RoomBookingStatus.RESERVED,
        )

        cancelled, is_late = room_service.cancel_booking(user, current.id)

        assert cancelled.status == RoomBookingStatus.CANCELLED
        assert is_late is False
        updated_user = room_service.user_repo.get_by_id(user.id)
        assert updated_user.room_cancel_restricted_until is not None
        assert updated_user.equipment_cancel_restricted_until is None
        penalties = penalty_repo.get_by_user(user.id)
        assert [(penalty.reason, penalty.points) for penalty in penalties] == [
            (PenaltyReason.FREQUENT_CANCEL, 1)
        ]

    def test_fourth_frequent_cancel_adds_frequent_cancel_penalty(
        self,
        fake_clock,
        create_test_user,
        room_service,
        room_booking_repo,
        room_booking_factory,
        penalty_repo,
    ):
        fake_clock(CURRENT_TIME)
        user = create_test_user()
        for cancelled_days_ago in (12, 8, 4):
            _add_room_booking(
                room_booking_repo,
                room_booking_factory,
                user.id,
                days_until_start=-cancelled_days_ago + 2,
                cancelled_days_ago=cancelled_days_ago,
            )
        current = _add_room_booking(
            room_booking_repo,
            room_booking_factory,
            user.id,
            days_until_start=13,
            status=RoomBookingStatus.RESERVED,
            booking_id="room-fourth-frequent",
        )

        room_service.cancel_booking(user, current.id)

        penalties = penalty_repo.get_by_user(user.id)
        assert [penalty.reason for penalty in penalties] == [PenaltyReason.FREQUENT_CANCEL]
        assert penalties[0].related_id == current.id
        assert penalties[0].points == 1
        assert room_service.user_repo.get_by_id(user.id).room_cancel_restricted_until is None

    def test_cancel_at_least_fourteen_days_before_start_is_excluded(
        self,
        fake_clock,
        create_test_user,
        room_service,
        room_booking_repo,
        room_booking_factory,
    ):
        fake_clock(CURRENT_TIME)
        user = create_test_user()
        _add_room_booking(room_booking_repo, room_booking_factory, user.id, days_until_start=5, cancelled_days_ago=20)
        _add_room_booking(room_booking_repo, room_booking_factory, user.id, days_until_start=6, cancelled_days_ago=20)
        current = _add_room_booking(
            room_booking_repo,
            room_booking_factory,
            user.id,
            days_until_start=13,
            status=RoomBookingStatus.RESERVED,
        )

        impact = room_service.preview_cancel_booking_impact(user, current.id)

        assert impact.frequent_cancel_count == 1
        assert impact.applies_cancel_restriction is False

    def test_last_thirty_days_count_excludes_older_cancels(
        self,
        fake_clock,
        create_test_user,
        room_service,
        room_booking_repo,
        room_booking_factory,
    ):
        fake_clock(CURRENT_TIME)
        user = create_test_user()
        _add_room_booking(room_booking_repo, room_booking_factory, user.id, days_until_start=-29, cancelled_days_ago=31)
        _add_room_booking(room_booking_repo, room_booking_factory, user.id, days_until_start=-5, cancelled_days_ago=7)
        current = _add_room_booking(
            room_booking_repo,
            room_booking_factory,
            user.id,
            days_until_start=13,
            status=RoomBookingStatus.RESERVED,
        )

        impact = room_service.preview_cancel_booking_impact(user, current.id)

        assert impact.frequent_cancel_count == 2
        assert impact.applies_cancel_restriction is False

    def test_room_and_equipment_restrictions_are_independent(
        self,
        fake_clock,
        create_test_user,
        room_service,
        equipment_service,
        room_booking_repo,
        equipment_booking_repo,
        room_booking_factory,
        equipment_booking_factory,
    ):
        fake_clock(CURRENT_TIME)
        user = create_test_user()
        _add_room_booking(room_booking_repo, room_booking_factory, user.id, days_until_start=-8, cancelled_days_ago=10)
        _add_room_booking(room_booking_repo, room_booking_factory, user.id, days_until_start=-3, cancelled_days_ago=5)
        room_current = _add_room_booking(
            room_booking_repo,
            room_booking_factory,
            user.id,
            days_until_start=13,
            status=RoomBookingStatus.RESERVED,
        )
        equipment_current = _add_equipment_booking(
            equipment_booking_repo,
            equipment_booking_factory,
            user.id,
            days_until_start=13,
            status=EquipmentBookingStatus.RESERVED,
        )

        room_service.cancel_booking(user, room_current.id)
        equipment_impact = equipment_service.preview_cancel_booking_impact(user, equipment_current.id)

        updated_user = room_service.user_repo.get_by_id(user.id)
        assert updated_user.room_cancel_restricted_until is not None
        assert updated_user.equipment_cancel_restricted_until is None
        assert equipment_impact.frequent_cancel_count == 1
        assert equipment_impact.applies_cancel_restriction is False

    def test_late_and_frequent_cancel_central_path_has_no_duplicate_append(
        self,
        fake_clock,
        create_test_user,
        room_service,
        room_booking_repo,
        room_booking_factory,
        penalty_repo,
    ):
        fake_clock(CURRENT_TIME)
        user = create_test_user()
        for cancelled_days_ago in (12, 8, 4):
            _add_room_booking(
                room_booking_repo,
                room_booking_factory,
                user.id,
                days_until_start=-cancelled_days_ago + 2,
                cancelled_days_ago=cancelled_days_ago,
            )
        start_time = CURRENT_TIME + timedelta(minutes=30)
        current = room_booking_factory(
            id="room-late-frequent-no-duplicate",
            user_id=user.id,
            room_id="room-task6",
            start_time=start_time.isoformat(),
            end_time=(start_time + timedelta(hours=1)).isoformat(),
            status=RoomBookingStatus.RESERVED,
        )
        with global_lock():
            room_booking_repo.add(current)

        room_service.cancel_booking(user, current.id)
        penalties = penalty_repo.get_by_user(user.id)
        reasons = [penalty.reason for penalty in penalties]
        assert reasons.count(PenaltyReason.LATE_CANCEL) == 1
        assert reasons.count(PenaltyReason.FREQUENT_CANCEL) == 0
        assert len(penalties) == 1
        assert {penalty.related_id for penalty in penalties} == {current.id}
