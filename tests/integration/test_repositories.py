"""
저장소(Repository) 통합 테스트

테스트 대상:
- JSONL 파일 읽기/쓰기
- CRUD 무결성 (add, get, update, delete)
- 파일이 없을 때 빈 리스트 반환
- 데이터 영속성 확인
"""

import pytest

from src.storage.integrity import DataIntegrityError
from src.storage.file_lock import global_lock
from src.storage.repositories import (
    UserRepository,
    RoomRepository,
    RoomBookingRepository,
    EquipmentBookingRepository,
)
from src.domain.models import (
    EquipmentBookingStatus,
    ResourceStatus,
    RoomBookingStatus,
    generate_id,
)


@pytest.fixture(autouse=True)
def repository_write_lock():
    """저장소 통합 테스트를 전역 잠금 아래에서 실행합니다."""
    with global_lock():
        yield


class TestUserRepository:
    """UserRepository 테스트"""

    def test_add_and_get_user(self, user_repo, user_factory):
        """사용자 추가 및 조회"""
        user = user_factory(username="repotest")

        user_repo.add(user)

        found = user_repo.get_by_id(user.id)
        assert found is not None
        assert found.username == "repotest"

    def test_get_by_username(self, user_repo, user_factory):
        """username으로 조회"""
        user = user_factory(username="unique_name")
        user_repo.add(user)

        found = user_repo.get_by_username("unique_name")
        assert found is not None
        assert found.id == user.id

    def test_username_exists(self, user_repo, user_factory):
        """username 존재 여부 확인"""
        user = user_factory(username="exists_test")
        user_repo.add(user)

        assert user_repo.username_exists("exists_test") is True
        assert user_repo.username_exists("nonexistent") is False

    def test_update_user(self, user_repo, user_factory):
        """사용자 업데이트"""
        user = user_factory(username="update_test", penalty_points=0)
        user_repo.add(user)

        from dataclasses import replace

        updated = replace(user, penalty_points=5)
        user_repo.update(updated)

        found = user_repo.get_by_id(user.id)
        assert found.penalty_points == 5

    def test_get_all_users(self, user_repo, user_factory):
        """모든 사용자 조회"""
        user_repo.add(user_factory(username="all1"))
        user_repo.add(user_factory(username="all2"))
        user_repo.add(user_factory(username="all3"))

        all_users = user_repo.get_all()
        assert len(all_users) == 3


class TestRoomRepository:
    """RoomRepository 테스트"""

    def test_add_and_get_room(self, room_repo, room_factory):
        """회의실 추가 및 조회"""
        room = room_factory(name="회의실9A")

        room_repo.add(room)

        found = room_repo.get_by_id(room.id)
        assert found is not None
        assert found.name == "회의실9A"

    def test_get_available_rooms(self, room_repo, room_factory):
        """예약 가능한 회의실만 조회"""
        room_repo.add(room_factory(name="회의실9E", status=ResourceStatus.AVAILABLE))
        room_repo.add(
            room_factory(name="회의실9F", status=ResourceStatus.MAINTENANCE)
        )
        room_repo.add(room_factory(name="회의실9G", status=ResourceStatus.DISABLED))

        available = room_repo.get_available()

        assert len(available) == 1
        assert available[0].name == "회의실9E"


class TestRoomBookingRepository:
    """RoomBookingRepository 테스트"""

    def test_get_active_by_user(
        self, room_booking_repo, room_booking_factory, user_factory
    ):
        """사용자의 활성 예약 조회"""
        user_id = generate_id()

        # 활성 예약
        room_booking_repo.add(
            room_booking_factory(user_id=user_id, status=RoomBookingStatus.RESERVED)
        )
        room_booking_repo.add(
            room_booking_factory(user_id=user_id, status=RoomBookingStatus.CHECKED_IN)
        )
        # 비활성 예약
        room_booking_repo.add(
            room_booking_factory(user_id=user_id, status=RoomBookingStatus.COMPLETED)
        )
        room_booking_repo.add(
            room_booking_factory(user_id=user_id, status=RoomBookingStatus.CANCELLED)
        )

        active = room_booking_repo.get_active_by_user(user_id)

        assert len(active) == 2

    def test_get_conflicting(self, room_booking_repo, room_booking_factory):
        """시간 충돌 예약 조회"""
        room_id = generate_id()

        # 11:00 ~ 13:00 예약
        room_booking_repo.add(
            room_booking_factory(
                room_id=room_id,
                start_time="2024-06-15T11:00:00",
                end_time="2024-06-15T13:00:00",
                status=RoomBookingStatus.RESERVED,
            )
        )

        # 12:00 ~ 14:00 충돌 확인
        conflicts = room_booking_repo.get_conflicting(
            room_id, "2024-06-15T12:00:00", "2024-06-15T14:00:00"
        )

        assert len(conflicts) == 1

    def test_get_conflicting_no_conflict(self, room_booking_repo, room_booking_factory):
        """충돌 없는 경우"""
        room_id = generate_id()

        # 11:00 ~ 12:00 예약
        room_booking_repo.add(
            room_booking_factory(
                room_id=room_id,
                start_time="2024-06-15T11:00:00",
                end_time="2024-06-15T12:00:00",
                status=RoomBookingStatus.RESERVED,
            )
        )

        # 13:00 ~ 14:00 (충돌 없음)
        conflicts = room_booking_repo.get_conflicting(
            room_id, "2024-06-15T13:00:00", "2024-06-15T14:00:00"
        )

        assert len(conflicts) == 0


class TestBookingQuerySemantics:
    """예약 quota/conflict/pending competition 조회 의미 테스트"""

    def test_room_pending_counts_for_quota_but_not_confirmed_conflict(
        self, room_booking_repo, room_booking_factory
    ):
        user_id = "room-quota-user"
        room_id = "room-quota-room"
        room_booking_repo.add(
            room_booking_factory(
                id="room-pending",
                user_id=user_id,
                room_id=room_id,
                start_time="2024-06-15T10:00:00",
                end_time="2024-06-15T11:00:00",
                status=RoomBookingStatus.PENDING,
            )
        )
        room_booking_repo.add(
            room_booking_factory(
                id="room-reserved",
                user_id=user_id,
                room_id=room_id,
                start_time="2024-06-15T12:00:00",
                end_time="2024-06-15T13:00:00",
                status=RoomBookingStatus.RESERVED,
            )
        )

        quota = room_booking_repo.get_quota_active_by_user(user_id)
        conflicts = room_booking_repo.get_confirmed_conflicting(
            room_id, "2024-06-15T10:30:00", "2024-06-15T10:45:00"
        )

        assert [booking.id for booking in quota] == ["room-pending", "room-reserved"]
        assert conflicts == []

    def test_equipment_pending_counts_for_quota_but_not_confirmed_conflict(
        self, equipment_booking_repo, equipment_booking_factory
    ):
        user_id = "equipment-quota-user"
        equipment_id = "equipment-quota-asset"
        equipment_booking_repo.add(
            equipment_booking_factory(
                id="equipment-pending",
                user_id=user_id,
                equipment_id=equipment_id,
                start_time="2024-06-15T10:00:00",
                end_time="2024-06-15T11:00:00",
                status=EquipmentBookingStatus.PENDING,
            )
        )
        equipment_booking_repo.add(
            equipment_booking_factory(
                id="equipment-reserved",
                user_id=user_id,
                equipment_id=equipment_id,
                start_time="2024-06-15T12:00:00",
                end_time="2024-06-15T13:00:00",
                status=EquipmentBookingStatus.RESERVED,
            )
        )

        quota = equipment_booking_repo.get_quota_active_by_user(user_id)
        conflicts = equipment_booking_repo.get_confirmed_conflicting(
            equipment_id, "2024-06-15T10:30:00", "2024-06-15T10:45:00"
        )

        assert [booking.id for booking in quota] == [
            "equipment-pending",
            "equipment-reserved",
        ]
        assert conflicts == []

    def test_room_pending_competition_sorts_by_penalty_created_at_booking_id(
        self, user_repo, room_booking_repo, user_factory, room_booking_factory
    ):
        room_id = "room-competition"
        user_repo.add(user_factory(username="room_low_old", penalty_points=1))
        user_repo.add(user_factory(username="room_low_new", penalty_points=1))
        user_repo.add(user_factory(username="room_high", penalty_points=3))
        user_repo.add(user_factory(username="room_tie", penalty_points=1))
        for booking in [
            room_booking_factory(
                id="room-c",
                user_id="room_high",
                room_id=room_id,
                start_time="2024-06-15T10:00:00",
                end_time="2024-06-15T11:00:00",
                status=RoomBookingStatus.PENDING,
                created_at="2024-06-15T08:00:00",
            ),
            room_booking_factory(
                id="room-b",
                user_id="room_low_new",
                room_id=room_id,
                start_time="2024-06-15T10:15:00",
                end_time="2024-06-15T11:15:00",
                status=RoomBookingStatus.PENDING,
                created_at="2024-06-15T09:00:00",
            ),
            room_booking_factory(
                id="room-a",
                user_id="room_tie",
                room_id=room_id,
                start_time="2024-06-15T10:15:00",
                end_time="2024-06-15T11:15:00",
                status=RoomBookingStatus.PENDING,
                created_at="2024-06-15T09:00:00",
            ),
            room_booking_factory(
                id="room-d",
                user_id="room_low_old",
                room_id=room_id,
                start_time="2024-06-15T09:45:00",
                end_time="2024-06-15T10:15:00",
                status=RoomBookingStatus.PENDING,
                created_at="2024-06-15T07:00:00",
            ),
            room_booking_factory(
                id="room-reserved-excluded",
                user_id="room_low_old",
                room_id=room_id,
                start_time="2024-06-15T10:00:00",
                end_time="2024-06-15T11:00:00",
                status=RoomBookingStatus.RESERVED,
            ),
            room_booking_factory(
                id="room-pending-nonoverlap",
                user_id="room_low_old",
                room_id=room_id,
                start_time="2024-06-15T12:00:00",
                end_time="2024-06-15T13:00:00",
                status=RoomBookingStatus.PENDING,
            ),
        ]:
            room_booking_repo.add(booking)

        competition = room_booking_repo.get_pending_competition(
            room_id, "2024-06-15T10:00:00", "2024-06-15T11:00:00", user_repo=user_repo
        )

        assert [booking.id for booking in competition] == [
            "room-d",
            "room-a",
            "room-b",
            "room-c",
        ]

    def test_equipment_pending_competition_sorts_by_penalty_created_at_booking_id(
        self, user_repo, equipment_booking_repo, user_factory, equipment_booking_factory
    ):
        equipment_id = "equipment-competition"
        user_repo.add(user_factory(username="equipment_low_old", penalty_points=1))
        user_repo.add(user_factory(username="equipment_low_new", penalty_points=1))
        user_repo.add(user_factory(username="equipment_high", penalty_points=3))
        user_repo.add(user_factory(username="equipment_tie", penalty_points=1))
        for booking in [
            equipment_booking_factory(
                id="equipment-c",
                user_id="equipment_high",
                equipment_id=equipment_id,
                start_time="2024-06-15T10:00:00",
                end_time="2024-06-15T11:00:00",
                status=EquipmentBookingStatus.PENDING,
                created_at="2024-06-15T08:00:00",
            ),
            equipment_booking_factory(
                id="equipment-b",
                user_id="equipment_low_new",
                equipment_id=equipment_id,
                start_time="2024-06-15T10:15:00",
                end_time="2024-06-15T11:15:00",
                status=EquipmentBookingStatus.PENDING,
                created_at="2024-06-15T09:00:00",
            ),
            equipment_booking_factory(
                id="equipment-a",
                user_id="equipment_tie",
                equipment_id=equipment_id,
                start_time="2024-06-15T10:15:00",
                end_time="2024-06-15T11:15:00",
                status=EquipmentBookingStatus.PENDING,
                created_at="2024-06-15T09:00:00",
            ),
            equipment_booking_factory(
                id="equipment-d",
                user_id="equipment_low_old",
                equipment_id=equipment_id,
                start_time="2024-06-15T09:45:00",
                end_time="2024-06-15T10:15:00",
                status=EquipmentBookingStatus.PENDING,
                created_at="2024-06-15T07:00:00",
            ),
            equipment_booking_factory(
                id="equipment-reserved-excluded",
                user_id="equipment_low_old",
                equipment_id=equipment_id,
                start_time="2024-06-15T10:00:00",
                end_time="2024-06-15T11:00:00",
                status=EquipmentBookingStatus.RESERVED,
            ),
            equipment_booking_factory(
                id="equipment-pending-nonoverlap",
                user_id="equipment_low_old",
                equipment_id=equipment_id,
                start_time="2024-06-15T12:00:00",
                end_time="2024-06-15T13:00:00",
                status=EquipmentBookingStatus.PENDING,
            ),
        ]:
            equipment_booking_repo.add(booking)

        competition = equipment_booking_repo.get_pending_competition(
            equipment_id,
            "2024-06-15T10:00:00",
            "2024-06-15T11:00:00",
            user_repo=user_repo,
        )

        assert [booking.id for booking in competition] == [
            "equipment-d",
            "equipment-a",
            "equipment-b",
            "equipment-c",
        ]


class TestPenaltyRepository:
    """PenaltyRepository 테스트"""

    def test_get_by_user(self, penalty_repo, penalty_factory):
        """사용자의 패널티 이력 조회"""
        user_id = generate_id()

        penalty_repo.add(penalty_factory(user_id=user_id, points=3))
        penalty_repo.add(penalty_factory(user_id=user_id, points=2))
        penalty_repo.add(
            penalty_factory(user_id=generate_id(), points=1)
        )  # 다른 사용자

        user_penalties = penalty_repo.get_by_user(user_id)

        assert len(user_penalties) == 2

    def test_get_last_penalty_date(self, penalty_repo, penalty_factory):
        """마지막 패널티 날짜 조회"""

        user_id = generate_id()

        old_penalty = penalty_factory(user_id=user_id)
        # created_at 수동 설정
        from dataclasses import replace

        old_penalty = replace(old_penalty, created_at="2024-01-01T10:00:00")
        penalty_repo.add(old_penalty)

        recent_penalty = penalty_factory(user_id=user_id)
        recent_penalty = replace(recent_penalty, created_at="2024-06-15T10:00:00")
        penalty_repo.add(recent_penalty)

        last_date = penalty_repo.get_last_penalty_date(user_id)

        assert last_date is not None
        assert last_date.year == 2024
        assert last_date.month == 6


class TestAuditLogRepository:
    """AuditLogRepository 테스트"""

    def test_log_action(self, audit_repo):
        """감사 로그 기록"""
        audit_repo.log_action(
            actor_id="user-123",
            action="test_action",
            target_type="test_target",
            target_id="target-456",
            details="테스트 세부사항",
        )

        all_logs = audit_repo.get_all()

        assert len(all_logs) == 1
        assert all_logs[0].action == "test_action"
        assert all_logs[0].details == "테스트 세부사항"

    def test_get_by_actor(self, audit_repo):
        """수행자별 로그 조회"""
        audit_repo.log_action("user-1", "action1", "type", "id1")
        audit_repo.log_action("user-1", "action2", "type", "id2")
        audit_repo.log_action("user-2", "action3", "type", "id3")

        user1_logs = audit_repo.get_by_actor("user-1")

        assert len(user1_logs) == 2

    def test_log_action_sanitizes_and_truncates_persisted_details(self, audit_repo):
        audit_repo.log_action(
            actor_id="user-123",
            action="test_action",
            target_type="test_target",
            target_id="target-456",
            details="첫줄\n둘째줄-" + ("x" * 50),
        )

        all_logs = audit_repo.get_all()

        assert len(all_logs) == 1
        assert "\n" not in all_logs[0].details
        assert "\r" not in all_logs[0].details
        assert len(all_logs[0].details) == 20


class TestDataPersistence:
    """데이터 영속성 테스트"""

    def test_data_persists_across_repository_instances(
        self, temp_data_dir, user_factory
    ):
        """저장소 인스턴스를 다시 만들어도 데이터 유지"""
        # 첫 번째 인스턴스로 저장
        repo1 = UserRepository(file_path=temp_data_dir / "users.txt")
        user = user_factory(username="persist_test")
        repo1.add(user)

        # 새 인스턴스로 조회
        repo2 = UserRepository(file_path=temp_data_dir / "users.txt")
        found = repo2.get_by_username("persist_test")

        assert found is not None
        assert found.id == user.id

    def test_empty_file_returns_empty_list(self, temp_data_dir):
        """파일이 없으면 빈 리스트 반환"""
        repo = UserRepository(file_path=temp_data_dir / "users.txt")

        all_users = repo.get_all()

        assert all_users == []


class TestRepositoryIntegrity:
    def test_room_repository_fails_fast_on_invalid_enum(self, temp_data_dir):
        room_file = temp_data_dir / "rooms.txt"
        room_file.write_text(
            "회의실4A|4|1층|broken_status|설명|2026-06-15T09:00|2026-06-15T09:00\n",
            encoding="utf-8",
        )

        repo = RoomRepository(file_path=room_file)

        with pytest.raises(DataIntegrityError, match="rooms.txt"):
            repo.get_all()

    def test_room_booking_repository_fails_fast_on_malformed_datetime(self, temp_data_dir):
        booking_file = temp_data_dir / "room_bookings.txt"
        booking_file.write_text(
            "bad-booking|user01|회의실4A|not-a-date|2026-06-15T18:00|reserved|\\-|\\-|\\-|\\-|\\-|2026-06-15T09:00|2026-06-15T09:00\n",
            encoding="utf-8",
        )

        repo = RoomBookingRepository(file_path=booking_file)

        with pytest.raises(DataIntegrityError, match="room_bookings.txt"):
            repo.get_all()
