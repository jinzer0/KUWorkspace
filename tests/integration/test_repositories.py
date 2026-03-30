"""
저장소(Repository) 통합 테스트

테스트 대상:
- JSONL 파일 읽기/쓰기
- CRUD 무결성 (add, get, update, delete)
- 파일이 없을 때 빈 리스트 반환
- 데이터 영속성 확인
"""

import pytest

from src.storage.file_lock import global_lock
from src.storage.repositories import (
    UserRepository,
    MessageRepository,
)
from src.domain.models import (
    ResourceStatus,
    RoomBookingStatus,
    MessageType,
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
        room = room_factory(name="Test Room")

        room_repo.add(room)

        found = room_repo.get_by_id(room.id)
        assert found is not None
        assert found.name == "Test Room"

    def test_get_available_rooms(self, room_repo, room_factory):
        """예약 가능한 회의실만 조회"""
        room_repo.add(room_factory(name="Available", status=ResourceStatus.AVAILABLE))
        room_repo.add(
            room_factory(name="Maintenance", status=ResourceStatus.MAINTENANCE)
        )
        room_repo.add(room_factory(name="Disabled", status=ResourceStatus.DISABLED))

        available = room_repo.get_available()

        assert len(available) == 1
        assert available[0].name == "Available"


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


class TestMessageRepository:
    """MessageRepository 테스트"""

    def test_add_and_get_message(self, message_repo, message_factory):
        """메시지 추가 및 조회"""
        message = message_factory(content="Test inquiry content")

        message_repo.add(message)

        all_messages = message_repo.get_all()
        assert len(all_messages) == 1
        assert all_messages[0].content == "Test inquiry content"

    def test_get_by_user(self, message_repo, message_factory):
        """사용자별 메시지 조회"""
        user_id = generate_id()
        message_repo.add(message_factory(user_id=user_id, content="User msg 1"))
        message_repo.add(message_factory(user_id=user_id, content="User msg 2"))
        message_repo.add(message_factory(user_id=generate_id(), content="Other user"))

        user_messages = message_repo.get_by_user(user_id)

        assert len(user_messages) == 2
        assert all(m.user_id == user_id for m in user_messages)

    def test_message_type_persistence(self, message_repo, message_factory):
        """메시지 유형 영속성 확인"""
        message_repo.add(
            message_factory(type=MessageType.INQUIRY, content="Question")
        )
        message_repo.add(message_factory(type=MessageType.REPORT, content="Report"))

        all_messages = message_repo.get_all()

        assert len(all_messages) == 2
        assert all_messages[0].type == MessageType.INQUIRY
        assert all_messages[1].type == MessageType.REPORT

    def test_data_persists_across_message_repository_instances(
        self, temp_data_dir, message_factory
    ):
        """저장소 인스턴스를 다시 만들어도 메시지 데이터 유지"""
        repo1 = MessageRepository(file_path=temp_data_dir / "message.txt")
        msg1 = message_factory(content="First message")
        msg2 = message_factory(content="Second message")
        repo1.add(msg1)
        repo1.add(msg2)

        repo2 = MessageRepository(file_path=temp_data_dir / "message.txt")
        all_messages = repo2.get_all()

        assert len(all_messages) == 2
        assert all_messages[0].content == "First message"
        assert all_messages[1].content == "Second message"

    def test_inquiry_and_report_exact_keys_in_persisted_file(
        self, temp_data_dir, message_factory
    ):
        """문의와 신고 제출이 정확히 5개 키만 가진 JSON Lines 레코드로 저장됨"""
        import json

        repo = MessageRepository(file_path=temp_data_dir / "message.txt")

        # 문의 저장
        inquiry = message_factory(
            user_id="user-1", type=MessageType.INQUIRY, content="Test inquiry"
        )
        repo.add(inquiry)

        # 신고 저장
        report = message_factory(
            user_id="user-1", type=MessageType.REPORT, content="Test report"
        )
        repo.add(report)

        # 파일 직접 읽기 - 정확한 JSON 구조 검증
        message_file = temp_data_dir / "message.txt"
        lines = message_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

        # 각 라인이 정확히 5개 키를 가진 JSON 객체
        expected_keys = {"id", "user_id", "created_at", "type", "content"}

        for idx, line in enumerate(lines):
            record = json.loads(line)
            actual_keys = set(record.keys())
            assert (
                actual_keys == expected_keys
            ), f"Line {idx}: Expected keys {expected_keys}, got {actual_keys}"

            # 각 필드 타입 검증
            assert isinstance(record["id"], str)
            assert isinstance(record["user_id"], str)
            assert isinstance(record["created_at"], str)
            assert isinstance(record["type"], str)
            assert isinstance(record["content"], str)

        # 타입 값 검증 (inquiry/report만 허용)
        assert json.loads(lines[0])["type"] == "inquiry"
        assert json.loads(lines[1])["type"] == "report"

    def test_multiple_submissions_preserve_all_records_append_only(
        self, temp_data_dir, message_factory
    ):
        """여러 제출이 모두 보존되고 순서대로 append 됨"""
        import json

        repo = MessageRepository(file_path=temp_data_dir / "message.txt")

        messages = [
            message_factory(user_id="user-1", content="Message 1"),
            message_factory(user_id="user-1", content="Message 2"),
            message_factory(user_id="user-1", content="Message 3"),
            message_factory(user_id="user-2", content="Message 4"),
        ]

        for msg in messages:
            repo.add(msg)

        # 파일에서 모든 레코드 검증
        message_file = temp_data_dir / "message.txt"
        lines = message_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 4

        # 순서 보존 검증
        for idx, line in enumerate(lines):
            record = json.loads(line)
            assert record["content"] == f"Message {idx + 1}"

        # 저장소를 새로 만들어도 모든 레코드 조회
        repo2 = MessageRepository(file_path=temp_data_dir / "message.txt")
        all_records = repo2.get_all()
        assert len(all_records) == 4

        user1_records = repo2.get_by_user("user-1")
        assert len(user1_records) == 3
        assert [m.content for m in user1_records] == [
            "Message 1",
            "Message 2",
            "Message 3",
        ]

    def test_newline_content_never_reaches_persistence_regression(
        self, temp_data_dir, message_service, message_factory, create_test_user
    ):
        """줄바꿈 포함 내용은 거부되어 파일에 기록되지 않음"""
        repo = MessageRepository(file_path=temp_data_dir / "message.txt")
        user = create_test_user()

        # 정상 메시지 먼저 저장
        valid = message_factory(user_id=user.id, content="Valid content")
        repo.add(valid)

        # 줄바꿈 내용 시도 - 서비스 레벨에서 거부되어 저장되지 않음
        with pytest.raises(Exception):
            message_service.create_message(
                user_id=user.id,
                message_type="inquiry",
                content="Content with\nnewline",
            )

        # 파일에는 1개 레코드만 존재
        message_file = temp_data_dir / "message.txt"
        lines = message_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1

        # 유일한 레코드가 정상 메시지
        import json

        record = json.loads(lines[0])
        assert record["content"] == "Valid content"
        assert "\n" not in record["content"]
        assert "\r" not in record["content"]
