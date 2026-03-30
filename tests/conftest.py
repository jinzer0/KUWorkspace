"""
Shared pytest fixtures for the reservation system test suite.

Provides:
- Isolated temp directories per test
- Datetime mocking utilities
- Factory fixtures for all domain models
- Service and repository fixtures with isolated storage
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.domain.models import (
    User,
    UserRole,
    Room,
    EquipmentAsset,
    RoomBooking,
    EquipmentBooking,
    Penalty,
    Message,
    MessageType,
    RoomBookingStatus,
    EquipmentBookingStatus,
    ResourceStatus,
    PenaltyReason,
    generate_id,
)
from src.storage.file_lock import global_lock
from src.runtime_clock import SystemClock, set_active_clock, clear_active_clock

# =============================================================================
# DATETIME MOCKING UTILITIES
# =============================================================================

DATETIME_PATCH_TARGETS = [
    "src.runtime_clock.datetime",
    "src.domain.room_service.datetime",
    "src.domain.equipment_service.datetime",
    "src.domain.penalty_service.datetime",
    "src.domain.policy_service.datetime",
    "src.domain.models.datetime",
    "src.domain.restriction_rules.datetime",
]


def create_datetime_mock(fixed_time):
    """
    Create a datetime mock that returns fixed_time for now() calls.
    Preserves other datetime functionality (fromisoformat, etc).
    """

    class MockDatetime:
        @classmethod
        def now(cls):
            return fixed_time

        @classmethod
        def fromisoformat(cls, date_string):
            return datetime.fromisoformat(date_string)

        @classmethod
        def strptime(cls, date_string, fmt):
            return datetime.strptime(date_string, fmt)

        @classmethod
        def combine(cls, date, time):
            return datetime.combine(date, time)

        min = datetime.min
        max = datetime.max

        def __new__(cls, *args, **kwargs):
            return datetime(*args, **kwargs)

    return MockDatetime


@pytest.fixture
def mock_now():
    """
    Fixture that returns a context manager for mocking datetime.now().

    Usage:
        def test_something(mock_now):
            fixed_time = datetime(2024, 6, 15, 10, 0, 0)
            with mock_now(fixed_time):
                # datetime.now() returns fixed_time in all patched modules
                result = service.some_method()
    """

    def _mock_now(fixed_time):
        mock_dt = create_datetime_mock(fixed_time)
        patches = [patch(target, mock_dt) for target in DATETIME_PATCH_TARGETS]

        class MockContext:
            def __enter__(self):
                for p in patches:
                    p.__enter__()
                return mock_dt

            def __exit__(self, *args):
                for p in reversed(patches):
                    p.__exit__(*args)

        return MockContext()

    return _mock_now


@pytest.fixture
def freeze_time():
    """
    Alternative fixture that patches datetime globally for the test duration.

    Usage:
        def test_something(freeze_time):
            freeze_time(datetime(2024, 6, 15, 10, 0))
            # All datetime.now() calls return this time
    """
    patches = []

    def _freeze(fixed_time):
        mock_dt = create_datetime_mock(fixed_time)
        for target in DATETIME_PATCH_TARGETS:
            p = patch(target, mock_dt)
            p.start()
            patches.append(p)
        return mock_dt

    yield _freeze

    for p in patches:
        p.stop()


@pytest.fixture
def fake_clock():
    """세션 가상 시계를 직접 제어하는 픽스처."""

    def _set(fixed_time):
        set_active_clock(SystemClock(fixed_time))
        from src.runtime_clock import get_active_clock

        return get_active_clock()

    yield _set
    clear_active_clock()


# =============================================================================
# TEMP DIRECTORY & CONFIG FIXTURES
# =============================================================================


@pytest.fixture
def temp_data_dir(tmp_path):
    """
    Create an isolated data directory for a single test.
    Patches src.config to use this directory.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Create lock file
    lock_file = data_dir / ".lock"
    lock_file.touch()

    # Data files (will be created as needed)
    users_file = data_dir / "users.txt"
    rooms_file = data_dir / "rooms.txt"
    equipment_file = data_dir / "equipment_assets.txt"
    room_bookings_file = data_dir / "room_bookings.txt"
    equipment_bookings_file = data_dir / "equipment_bookings.txt"
    penalties_file = data_dir / "penalties.txt"
    audit_log_file = data_dir / "audit_log.txt"
    message_file = data_dir / "message.txt"

    # Patch config paths AND the DATA_FILES list itself (critical for ensure_data_dir)
    isolated_data_files = [
        users_file,
        rooms_file,
        equipment_file,
        room_bookings_file,
        equipment_bookings_file,
        penalties_file,
        audit_log_file,
        message_file,
    ]

    with patch("src.config.DATA_DIR", data_dir), patch(
        "src.config.DATA_FILES", isolated_data_files
    ), patch(
        "src.config.LOCK_FILE", lock_file
    ), patch("src.config.USERS_FILE", users_file), patch(
        "src.config.ROOMS_FILE", rooms_file
    ), patch(
        "src.config.EQUIPMENT_ASSETS_FILE", equipment_file
    ), patch(
        "src.config.ROOM_BOOKINGS_FILE", room_bookings_file
    ), patch(
        "src.config.EQUIPMENT_BOOKINGS_FILE", equipment_bookings_file
    ), patch(
        "src.config.PENALTIES_FILE", penalties_file
    ), patch(
        "src.config.AUDIT_LOG_FILE", audit_log_file
    ), patch(
        "src.config.MESSAGE_FILE", message_file
    ), patch(
        "src.storage.file_lock.DATA_DIR", data_dir
    ), patch(
        "src.storage.file_lock.LOCK_FILE", lock_file
    ), patch(
        "src.storage.repositories.USERS_FILE", users_file
    ), patch(
        "src.storage.repositories.ROOMS_FILE", rooms_file
    ), patch(
        "src.storage.repositories.EQUIPMENT_ASSETS_FILE", equipment_file
    ), patch(
        "src.storage.repositories.ROOM_BOOKINGS_FILE", room_bookings_file
    ), patch(
        "src.storage.repositories.EQUIPMENT_BOOKINGS_FILE", equipment_bookings_file
    ), patch(
        "src.storage.repositories.PENALTIES_FILE", penalties_file
    ), patch(
        "src.storage.repositories.AUDIT_LOG_FILE", audit_log_file
    ):
        yield data_dir


# =============================================================================
# FACTORY FIXTURES
# =============================================================================


@pytest.fixture
def user_factory():
    """Factory for creating User instances with sensible defaults."""
    _counter = [0]

    def _create(
        id=None,
        username=None,
        password="testpass123",
        role=UserRole.USER,
        penalty_points=0,
        normal_use_streak=0,
        restriction_until=None,
        **overrides,
    ):
        _counter[0] += 1
        return User(
            id=id or generate_id(),
            username=username or f"testuser{_counter[0]}",
            password=password,
            role=role,
            penalty_points=penalty_points,
            normal_use_streak=normal_use_streak,
            restriction_until=restriction_until,
            **overrides,
        )

    return _create


@pytest.fixture
def room_factory():
    """Factory for creating Room instances with sensible defaults."""
    _counter = [0]

    def _create(
        id=None,
        name=None,
        capacity=10,
        location="Building A",
        status=ResourceStatus.AVAILABLE,
        description="",
        **overrides,
    ):
        _counter[0] += 1
        return Room(
            id=id or generate_id(),
            name=name or f"Room {_counter[0]}",
            capacity=capacity,
            location=location,
            status=status,
            description=description,
            **overrides,
        )

    return _create


@pytest.fixture
def equipment_factory():
    """Factory for creating EquipmentAsset instances with sensible defaults."""
    _counter = [0]

    def _create(
        id=None,
        name=None,
        asset_type="노트북",
        serial_number=None,
        status=ResourceStatus.AVAILABLE,
        description="",
        **overrides,
    ):
        _counter[0] += 1
        return EquipmentAsset(
            id=id or generate_id(),
            name=name or f"Equipment {_counter[0]}",
            asset_type=asset_type,
            serial_number=serial_number or f"SN-{_counter[0]:05d}",
            status=status,
            description=description,
            **overrides,
        )

    return _create


@pytest.fixture
def room_booking_factory(user_factory, room_factory):
    """Factory for creating RoomBooking instances with sensible defaults."""
    _counter = [0]

    def _create(
        id=None,
        user_id=None,
        room_id=None,
        start_time=None,
        end_time=None,
        status=RoomBookingStatus.RESERVED,
        checked_in_at=None,
        completed_at=None,
        cancelled_at=None,
        **overrides,
    ):
        _counter[0] += 1
        now = datetime.now()
        _start = start_time or (now + timedelta(hours=1)).isoformat()
        _end = end_time or (now + timedelta(hours=2)).isoformat()

        return RoomBooking(
            id=id or generate_id(),
            user_id=user_id or generate_id(),
            room_id=room_id or generate_id(),
            start_time=_start,
            end_time=_end,
            status=status,
            checked_in_at=checked_in_at,
            completed_at=completed_at,
            cancelled_at=cancelled_at,
            **overrides,
        )

    return _create


@pytest.fixture
def equipment_booking_factory(user_factory, equipment_factory):
    """Factory for creating EquipmentBooking instances with sensible defaults."""
    _counter = [0]

    def _create(
        id=None,
        user_id=None,
        equipment_id=None,
        start_time=None,
        end_time=None,
        status=EquipmentBookingStatus.RESERVED,
        checked_out_at=None,
        returned_at=None,
        cancelled_at=None,
        **overrides,
    ):
        _counter[0] += 1
        now = datetime.now()
        _start = start_time or now.isoformat()
        _end = end_time or (now + timedelta(days=3)).isoformat()

        return EquipmentBooking(
            id=id or generate_id(),
            user_id=user_id or generate_id(),
            equipment_id=equipment_id or generate_id(),
            start_time=_start,
            end_time=_end,
            status=status,
            checked_out_at=checked_out_at,
            returned_at=returned_at,
            cancelled_at=cancelled_at,
            **overrides,
        )

    return _create


@pytest.fixture
def penalty_factory():
    """Factory for creating Penalty instances with sensible defaults."""
    _counter = [0]

    def _create(
        id=None,
        user_id=None,
        reason=PenaltyReason.NO_SHOW,
        points=3,
        related_type="room_booking",
        related_id=None,
        memo="",
        **overrides,
    ):
        _counter[0] += 1
        return Penalty(
            id=id or generate_id(),
            user_id=user_id or generate_id(),
            reason=reason,
            points=points,
            related_type=related_type,
            related_id=related_id or generate_id(),
            memo=memo,
            **overrides,
        )

    return _create


@pytest.fixture
def message_factory():
    """Factory for creating Message instances with sensible defaults."""
    _counter = [0]

    def _create(
        user_id=None,
        type=MessageType.INQUIRY,
        content="",
        id=None,
        created_at=None,
        **overrides,
    ):
        _counter[0] += 1
        msg = Message(
            user_id=user_id or generate_id(),
            type=type,
            content=content or f"Test message {_counter[0]}",
            **overrides,
        )
        if id:
            object.__setattr__(msg, "id", id)
        if created_at:
            object.__setattr__(msg, "created_at", created_at)
        return msg

    return _create


# =============================================================================
# REPOSITORY FIXTURES
# =============================================================================


@pytest.fixture
def user_repo(temp_data_dir):
    """UserRepository with isolated temp directory."""
    from src.storage.repositories import UserRepository

    return UserRepository(file_path=temp_data_dir / "users.txt")


@pytest.fixture
def room_repo(temp_data_dir):
    """RoomRepository with isolated temp directory."""
    from src.storage.repositories import RoomRepository

    return RoomRepository(file_path=temp_data_dir / "rooms.txt")


@pytest.fixture
def equipment_repo(temp_data_dir):
    """EquipmentAssetRepository with isolated temp directory."""
    from src.storage.repositories import EquipmentAssetRepository

    return EquipmentAssetRepository(file_path=temp_data_dir / "equipment_assets.txt")


@pytest.fixture
def room_booking_repo(temp_data_dir):
    """RoomBookingRepository with isolated temp directory."""
    from src.storage.repositories import RoomBookingRepository

    return RoomBookingRepository(file_path=temp_data_dir / "room_bookings.txt")


@pytest.fixture
def equipment_booking_repo(temp_data_dir):
    """EquipmentBookingRepository with isolated temp directory."""
    from src.storage.repositories import EquipmentBookingRepository

    return EquipmentBookingRepository(
        file_path=temp_data_dir / "equipment_bookings.txt"
    )


@pytest.fixture
def penalty_repo(temp_data_dir):
    """PenaltyRepository with isolated temp directory."""
    from src.storage.repositories import PenaltyRepository

    return PenaltyRepository(file_path=temp_data_dir / "penalties.txt")


@pytest.fixture
def audit_repo(temp_data_dir):
    """AuditLogRepository with isolated temp directory."""
    from src.storage.repositories import AuditLogRepository

    return AuditLogRepository(file_path=temp_data_dir / "audit_log.txt")


@pytest.fixture
def message_repo(temp_data_dir):
    """MessageRepository with isolated temp directory."""
    from src.storage.repositories import MessageRepository

    return MessageRepository(file_path=temp_data_dir / "message.txt")


# =============================================================================
# SERVICE FIXTURES
# =============================================================================


@pytest.fixture
def auth_service(user_repo):
    """AuthService with isolated repository."""
    from src.domain.auth_service import AuthService

    return AuthService(user_repo=user_repo)


@pytest.fixture
def penalty_service(user_repo, penalty_repo, audit_repo):
    """PenaltyService with isolated repositories."""
    from src.domain.penalty_service import PenaltyService

    return PenaltyService(
        user_repo=user_repo, penalty_repo=penalty_repo, audit_repo=audit_repo
    )


@pytest.fixture
def room_service(
    room_repo,
    room_booking_repo,
    equipment_booking_repo,
    user_repo,
    audit_repo,
    penalty_service,
):
    """RoomService with isolated repositories."""
    from src.domain.room_service import RoomService

    return RoomService(
        room_repo=room_repo,
        booking_repo=room_booking_repo,
        equipment_booking_repo=equipment_booking_repo,
        user_repo=user_repo,
        audit_repo=audit_repo,
        penalty_service=penalty_service,
    )


@pytest.fixture
def equipment_service(
    equipment_repo,
    equipment_booking_repo,
    room_booking_repo,
    user_repo,
    audit_repo,
    penalty_service,
):
    """EquipmentService with isolated repositories."""
    from src.domain.equipment_service import EquipmentService

    return EquipmentService(
        equipment_repo=equipment_repo,
        booking_repo=equipment_booking_repo,
        room_booking_repo=room_booking_repo,
        user_repo=user_repo,
        audit_repo=audit_repo,
        penalty_service=penalty_service,
    )


@pytest.fixture
def policy_service(
    user_repo, room_booking_repo, equipment_booking_repo, penalty_repo, audit_repo
):
    """PolicyService with isolated repositories."""
    from src.domain.policy_service import PolicyService
    from src.domain.penalty_service import PenaltyService

    penalty_service = PenaltyService(
        user_repo=user_repo, penalty_repo=penalty_repo, audit_repo=audit_repo
    )

    return PolicyService(
        user_repo=user_repo,
        room_booking_repo=room_booking_repo,
        equipment_booking_repo=equipment_booking_repo,
        penalty_repo=penalty_repo,
        audit_repo=audit_repo,
        penalty_service=penalty_service,
    )


@pytest.fixture
def message_service(message_repo):
    """MessageService with isolated repository."""
    from src.domain.message_service import MessageService

    return MessageService(message_repo=message_repo)


# =============================================================================
# HELPER FIXTURES
# =============================================================================


@pytest.fixture
def create_test_user(user_repo, user_factory):
    """Helper to create and persist a test user."""

    def _create(**kwargs):
        user = user_factory(**kwargs)
        with global_lock():
            user_repo.add(user)
        return user

    return _create


@pytest.fixture
def create_test_room(room_repo, room_factory):
    """Helper to create and persist a test room."""

    def _create(**kwargs):
        room = room_factory(**kwargs)
        with global_lock():
            room_repo.add(room)
        return room

    return _create


@pytest.fixture
def create_test_equipment(equipment_repo, equipment_factory):
    """Helper to create and persist test equipment."""

    def _create(**kwargs):
        equipment = equipment_factory(**kwargs)
        with global_lock():
            equipment_repo.add(equipment)
        return equipment

    return _create


@pytest.fixture
def sample_datetime():
    """Standard datetime for tests: 2024-06-15 10:00:00 (Saturday)."""
    return datetime(2024, 6, 15, 10, 0, 0)
