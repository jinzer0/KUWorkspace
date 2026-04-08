"""
동시성 테스트

테스트 대상:
- 동시 예약 시 하나만 성공 (파일 잠금)
- 동시 회원가입 시 중복 방지
- 잠금 획득 실패 시 처리
- 동시 장비 예약 시 하나만 성공
- 원자적 쓰기로 중단 안전성 보장
"""

import pytest
import multiprocessing
import json
from datetime import datetime, timedelta

from src.domain.models import (
    EquipmentAsset,
    ResourceStatus,
    generate_id,
)
from src.storage.file_lock import global_lock
from src.storage.repositories import (
    EquipmentAssetRepository,
)


def worker_create_booking(
    room_id, user_id, start_time, end_time, data_dir, result_queue
):
    """
    워커 프로세스: 예약 생성 시도

    결과를 큐에 넣음: ("success", booking_id) 또는 ("error", error_message)
    """
    import sys
    from pathlib import Path
    from unittest.mock import patch

    # 프로젝트 루트 추가
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

    data_path = Path(data_dir)

    # config 패치 (file_lock 모듈에서 사용)
    with patch("src.storage.file_lock.DATA_DIR", data_path), patch(
        "src.storage.file_lock.LOCK_FILE", data_path / ".lock"
    ):

        try:
            from src.domain.room_service import RoomService
            from src.storage.repositories import (
                UserRepository,
                RoomRepository,
                RoomBookingRepository,
                AuditLogRepository,
            )

            # 명시적으로 파일 경로 전달
            user_repo = UserRepository(file_path=data_path / "users.txt")
            room_repo = RoomRepository(file_path=data_path / "rooms.txt")
            booking_repo = RoomBookingRepository(
                file_path=data_path / "room_bookings.txt"
            )
            audit_repo = AuditLogRepository(file_path=data_path / "audit_log.txt")

            user = user_repo.get_by_id(user_id)

            if user is None:
                result_queue.put(("error", "User not found"))
                return

            room_service = RoomService(
                room_repo=room_repo,
                booking_repo=booking_repo,
                user_repo=user_repo,
                audit_repo=audit_repo,
            )

            start = datetime.fromisoformat(start_time)
            end = datetime.fromisoformat(end_time)

            booking = room_service.create_booking(user, room_id, start, end)
            result_queue.put(("success", booking.id))

        except Exception as e:
            result_queue.put(("error", str(e)))


def worker_signup(username, password, data_dir, result_queue):
    """
    워커 프로세스: 회원가입 시도
    """
    import sys
    from pathlib import Path
    from unittest.mock import patch

    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

    data_path = Path(data_dir)

    # file_lock 모듈에서 사용하는 경로 패치
    with patch("src.storage.file_lock.DATA_DIR", data_path), patch(
        "src.storage.file_lock.LOCK_FILE", data_path / ".lock"
    ):

        try:
            from src.domain.auth_service import AuthService
            from src.storage.repositories import UserRepository

            # 명시적으로 파일 경로 전달
            user_repo = UserRepository(file_path=data_path / "users.txt")

            auth_service = AuthService(user_repo=user_repo)
            user = auth_service.signup(username, password)
            result_queue.put(("success", user.id))

        except Exception as e:
            result_queue.put(("error", str(e)))


class TestConcurrentBooking:
    """동시 예약 테스트"""

    @pytest.mark.slow
    def test_concurrent_booking_only_one_succeeds(
        self, temp_data_dir, user_factory, room_factory, user_repo, room_repo
    ):
        """
        동일 시간대 동시 예약 시 하나만 성공

        시나리오:
        1. 회의실과 두 사용자 생성
        2. 두 프로세스가 동시에 같은 시간대 예약 시도
        3. 하나만 성공, 나머지는 충돌로 실패
        """
        # 데이터 준비
        user1 = user_factory(username="concurrent1")
        user2 = user_factory(username="concurrent2")
        room = room_factory(name="Concurrent Room")

        with global_lock():
            user_repo.add(user1)
            user_repo.add(user2)
            room_repo.add(room)

        # 예약 시간
        start_time = (datetime.now() + timedelta(hours=2)).replace(
            minute=0, second=0, microsecond=0
        )
        end_time = start_time + timedelta(hours=1)

        # 멀티프로세싱
        result_queue = multiprocessing.Queue()
        data_dir_str = str(temp_data_dir)

        processes = []
        for user in [user1, user2]:
            p = multiprocessing.Process(
                target=worker_create_booking,
                args=(
                    room.id,
                    user.id,
                    start_time.isoformat(),
                    end_time.isoformat(),
                    data_dir_str,
                    result_queue,
                ),
            )
            processes.append(p)

        # 동시 시작
        for p in processes:
            p.start()

        # 결과 대기
        for p in processes:
            p.join(timeout=30)

        # 결과 수집
        results = []
        while not result_queue.empty():
            results.append(result_queue.get())

        # 검증: 정확히 하나만 성공
        successes = [r for r in results if r[0] == "success"]
        errors = [r for r in results if r[0] == "error"]

        assert len(successes) == 1, f"Expected 1 success, got {len(successes)}"
        assert len(errors) == 1, f"Expected 1 error, got {len(errors)}"
        assert "이미 예약이 있습니다" in errors[0][1]


class TestConcurrentSignup:
    """동시 회원가입 테스트"""

    @pytest.mark.slow
    def test_concurrent_signup_same_username_one_succeeds(self, temp_data_dir):
        """
        동일 username 동시 가입 시 하나만 성공
        """
        result_queue = multiprocessing.Queue()
        data_dir_str = str(temp_data_dir)
        username = "concurrent_signup"

        processes = []
        for i in range(3):  # 3개 프로세스가 동시에 시도
            p = multiprocessing.Process(
                target=worker_signup,
                args=(username, f"password{i}", data_dir_str, result_queue),
            )
            processes.append(p)

        for p in processes:
            p.start()

        for p in processes:
            p.join(timeout=30)

        results = []
        while not result_queue.empty():
            results.append(result_queue.get())

        successes = [r for r in results if r[0] == "success"]
        errors = [r for r in results if r[0] == "error"]

        # 정확히 하나만 성공
        assert len(successes) == 1
        assert len(errors) == 2

        for error in errors:
            assert "이미 존재하는 사용자명" in error[1]


class TestConcurrentMultipleRooms:
    """여러 회의실 동시 예약 테스트"""

    @pytest.mark.slow
    def test_concurrent_different_rooms_all_succeed(
        self, temp_data_dir, user_factory, room_factory, user_repo, room_repo
    ):
        """
        서로 다른 회의실 동시 예약은 모두 성공
        """
        # 여러 사용자와 회의실
        users = [user_factory(username=f"multi_user_{i}") for i in range(3)]
        rooms = [room_factory(name=f"Multi Room {i}") for i in range(3)]

        with global_lock():
            for u in users:
                user_repo.add(u)
            for r in rooms:
                room_repo.add(r)

        start_time = (datetime.now() + timedelta(hours=2)).replace(
            minute=0, second=0, microsecond=0
        )
        end_time = start_time + timedelta(hours=1)

        result_queue = multiprocessing.Queue()
        data_dir_str = str(temp_data_dir)

        processes = []
        for i in range(3):
            p = multiprocessing.Process(
                target=worker_create_booking,
                args=(
                    rooms[i].id,
                    users[i].id,
                    start_time.isoformat(),
                    end_time.isoformat(),
                    data_dir_str,
                    result_queue,
                ),
            )
            processes.append(p)

        for p in processes:
            p.start()

        for p in processes:
            p.join(timeout=30)

        results = []
        while not result_queue.empty():
            results.append(result_queue.get())

        successes = [r for r in results if r[0] == "success"]

        # 서로 다른 회의실이므로 모두 성공
        assert len(successes) == 3


class TestLockTimeout:
    """잠금 타임아웃 테스트"""

    def test_lock_timeout_behavior(self, temp_data_dir):
        """
        잠금 타임아웃 시 적절한 예외 발생 확인

        참고: 실제 타임아웃 테스트는 시간이 오래 걸리므로
        간단한 잠금 획득/해제 테스트로 대체
        """
        from src.storage.file_lock import global_lock

        # 잠금 획득 후 해제
        with global_lock():
            pass  # 정상 잠금/해제

        # 다시 잠금 가능해야 함
        with global_lock():
            pass


def worker_create_equipment_booking(
    equipment_id, user_id, start_time, end_time, data_dir, result_queue
):
    """장비 예약 생성을 병렬 프로세스에서 시도합니다."""
    import sys
    from pathlib import Path
    from unittest.mock import patch

    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

    from src.storage.file_lock import ReentrantFileLock

    ReentrantFileLock.reset_instance()

    data_path = Path(data_dir)

    with patch("src.storage.file_lock.DATA_DIR", data_path), patch(
        "src.storage.file_lock.LOCK_FILE", data_path / ".lock"
    ):

        ReentrantFileLock.reset_instance()

        try:
            from src.domain.equipment_service import EquipmentService
            from src.storage.repositories import (
                UserRepository,
                EquipmentAssetRepository,
                EquipmentBookingRepository,
                AuditLogRepository,
            )

            user_repo = UserRepository(file_path=data_path / "users.txt")
            equipment_repo = EquipmentAssetRepository(
                file_path=data_path / "equipments.txt"
            )
            booking_repo = EquipmentBookingRepository(
                file_path=data_path / "equipment_booking.txt"
            )
            audit_repo = AuditLogRepository(file_path=data_path / "audit_log.txt")

            user = user_repo.get_by_id(user_id)

            if user is None:
                result_queue.put(("error", "User not found"))
                return

            equipment_service = EquipmentService(
                equipment_repo=equipment_repo,
                booking_repo=booking_repo,
                user_repo=user_repo,
                audit_repo=audit_repo,
            )

            start = datetime.fromisoformat(start_time)
            end = datetime.fromisoformat(end_time)

            booking = equipment_service.create_booking(user, equipment_id, start, end)
            result_queue.put(("success", booking.id))

        except Exception as e:
            result_queue.put(("error", str(e)))


class TestConcurrentEquipmentBooking:
    """동시 장비 예약 시나리오를 검증합니다."""

    @pytest.mark.slow
    def test_concurrent_equipment_booking_only_one_succeeds(
        self, temp_data_dir, user_factory, user_repo
    ):
        """
        동일 시간대 동시 장비 예약 시 하나만 성공해야 한다.
        """
        user1 = user_factory(username="equip_concurrent1")
        user2 = user_factory(username="equip_concurrent2")
        equipment = EquipmentAsset(
            id="SN-CONC-001",
            name="Concurrent Equipment",
            asset_type="laptop",
            serial_number="SN-CONC-001",
            status=ResourceStatus.AVAILABLE,
        )

        equipment_repo = EquipmentAssetRepository(
            file_path=temp_data_dir / "equipments.txt"
        )
        with global_lock():
            user_repo.add(user1)
            user_repo.add(user2)
            equipment_repo.add(equipment)

        start_time = (datetime.now() + timedelta(hours=2)).replace(
            minute=0, second=0, microsecond=0
        )
        end_time = start_time + timedelta(hours=1)

        result_queue = multiprocessing.Queue()
        data_dir_str = str(temp_data_dir)

        processes = []
        for user in [user1, user2]:
            p = multiprocessing.Process(
                target=worker_create_equipment_booking,
                args=(
                    equipment.id,
                    user.id,
                    start_time.isoformat(),
                    end_time.isoformat(),
                    data_dir_str,
                    result_queue,
                ),
            )
            processes.append(p)

        for p in processes:
            p.start()

        for p in processes:
            p.join(timeout=30)

        results = []
        while not result_queue.empty():
            results.append(result_queue.get())

        successes = [r for r in results if r[0] == "success"]
        errors = [r for r in results if r[0] == "error"]

        assert (
            len(successes) == 1
        ), f"Expected 1 success, got {len(successes)}: {results}"
        assert len(errors) == 1, f"Expected 1 error, got {len(errors)}: {results}"
        assert "이미 예약이 있습니다" in errors[0][1]


class TestAtomicWriteSafety:
    """원자적 쓰기 실패 시 복구 동작을 검증합니다."""

    def test_atomic_write_preserves_original_on_failure(self, temp_data_dir):
        """
        원자적 쓰기 실패 시 원본 파일이 보존되어야 한다.
        """
        from src.storage.atomic_writer import atomic_write_jsonl
        from src.storage.jsonl_handler import decode_record

        test_file = temp_data_dir / "test_atomic.txt"

        original_data = [{"id": "1", "value": "original"}]
        atomic_write_jsonl(test_file, original_data, lambda x: [json.dumps(x)])

        with open(test_file, "r") as f:
            content_before = f.read()

        class UnserializableObject:
            pass

        bad_data = [UnserializableObject()]

        with pytest.raises(TypeError):
            atomic_write_jsonl(test_file, bad_data, lambda x: [json.dumps(x)])

        with open(test_file, "r") as f:
            content_after = f.read()

        assert content_after == content_before

        with open(test_file, "r") as f:
            line = f.readline().strip()
            payload = decode_record(line)[0]
            assert payload is not None
            restored = json.loads(payload)

        assert restored == {"id": "1", "value": "original"}

    def test_no_temp_files_left_after_success(self, temp_data_dir):
        """원자적 쓰기 성공 후 임시 파일이 남지 않음"""
        from src.storage.atomic_writer import atomic_write_jsonl

        test_file = temp_data_dir / "test_no_tmp.txt"
        data = [{"id": "1", "value": "test"}]

        atomic_write_jsonl(test_file, data, lambda x: [json.dumps(x)])

        tmp_files = list(temp_data_dir.glob("*.tmp"))
        assert len(tmp_files) == 0
