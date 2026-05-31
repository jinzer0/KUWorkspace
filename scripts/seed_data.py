#!/usr/bin/env python
"""
시드 데이터 생성 스크립트

초기 데이터: 관리자 1명, 회의실 9개, 장비 12개
"""

import sys
from pathlib import Path
from datetime import datetime

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config import (
    ensure_data_dir,
    DATA_DIR,
    USERS_FILE,
    ROOMS_FILE,
    EQUIPMENTS_FILE,
    ROOM_BOOKINGS_FILE,
    EQUIPMENT_BOOKING_FILE,
    PENALTIES_FILE,
    AUDIT_LOG_FILE,
    CLOCK_FILE,
    CLOCK_SENTINEL,
)
from src.clock_bootstrap import read_clock_marker
from src.domain.models import (
    User,
    Room,
    EquipmentAsset,
    UserRole,
    ResourceStatus,
)
from src.storage.repositories import (
    UserRepository,
    RoomRepository,
    EquipmentAssetRepository,
    UnitOfWork,
)
from src.storage.file_lock import global_lock
from src.storage.integrity import DataIntegrityError


LEGACY_DATA_FILES = [
    DATA_DIR / "equipment_assets.txt",
    DATA_DIR / "equipment_bookings.txt",
    DATA_DIR / "message.txt",
]

CURRENT_DATA_FILES = [
    USERS_FILE,
    ROOMS_FILE,
    EQUIPMENTS_FILE,
    ROOM_BOOKINGS_FILE,
    EQUIPMENT_BOOKING_FILE,
    PENALTIES_FILE,
    AUDIT_LOG_FILE,
    CLOCK_FILE,
]


def reset_clock_file():
    ensure_data_dir()
    CLOCK_FILE.write_text(CLOCK_SENTINEL, encoding="utf-8")


def get_seed_timestamp():
    marker = read_clock_marker()
    if marker == CLOCK_SENTINEL:
        return marker

    try:
        return datetime.fromisoformat(marker).replace(second=0, microsecond=0).isoformat(
            timespec="minutes"
        )
    except ValueError as error:
        raise DataIntegrityError(
            f"시드 타임스탬프 형식이 올바르지 않습니다: {CLOCK_FILE} ({marker})"
        ) from error


def create_admin():
    """관리자 계정 생성"""
    seed_timestamp = get_seed_timestamp()
    return User(
        id="admin",
        username="admin",
        password="admin123",
        role=UserRole.ADMIN,
        created_at=seed_timestamp,
        updated_at=seed_timestamp,
    )


def reset_data_files():
    for file_path in CURRENT_DATA_FILES + LEGACY_DATA_FILES:
        if file_path.exists():
            file_path.unlink()
    ensure_data_dir()


def create_rooms():
    """회의실 9개 생성"""
    seed_timestamp = get_seed_timestamp()
    rooms_data = [
        ("회의실 4A", 4, "1층", "4인 회의실"),
        ("회의실 4B", 4, "1층", "4인 회의실"),
        ("회의실 4C", 4, "1층", "4인 회의실"),
        ("회의실 6A", 6, "2층", "6인 회의실"),
        ("회의실 6B", 6, "2층", "6인 회의실"),
        ("회의실 6C", 6, "2층", "6인 회의실"),
        ("회의실 8A", 8, "3층", "8인 회의실"),
        ("회의실 8B", 8, "3층", "8인 회의실"),
        ("회의실 8C", 8, "3층", "8인 회의실"),
    ]

    return [
        Room(
            id=name,
            name=name,
            capacity=capacity,
            location=location,
            description=description,
            status=ResourceStatus.AVAILABLE,
            created_at=seed_timestamp,
            updated_at=seed_timestamp,
        )
        for name, capacity, location, description in rooms_data
    ]


def create_equipment():
    """장비 12개 생성"""
    seed_timestamp = get_seed_timestamp()
    equipment_data = [
        ("프로젝터", "projector", "PJ-001"),
        ("프로젝터", "projector", "PJ-002"),
        ("프로젝터", "projector", "PJ-003"),
        ("노트북", "laptop", "NB-001"),
        ("노트북", "laptop", "NB-002"),
        ("노트북", "laptop", "NB-003"),
        ("케이블", "cable", "CB-001"),
        ("케이블", "cable", "CB-002"),
        ("케이블", "cable", "CB-003"),
        ("웹캠", "webcam", "WC-001"),
        ("웹캠", "webcam", "WC-002"),
        ("웹캠", "webcam", "WC-003"),
    ]

    return [
        EquipmentAsset(
            name=name,
            asset_type=asset_type,
            serial_number=serial,
            status=ResourceStatus.AVAILABLE,
            description=name,
            created_at=seed_timestamp,
            updated_at=seed_timestamp,
        )
        for name, asset_type, serial in equipment_data
    ]


def seed(reset=False):
    """시드 데이터 생성"""
    print("시드 데이터 생성 시작...")

    if reset:
        reset_data_files()
        print("  기존 데이터 파일을 현재 포맷으로 초기화했습니다.")
    else:
        ensure_data_dir()

    reset_clock_file()

    # 기존 데이터 확인
    user_repo = UserRepository()
    room_repo = RoomRepository()
    equipment_repo = EquipmentAssetRepository()

    with global_lock(), UnitOfWork():
        # 관리자 생성
        if not user_repo.get_by_username("admin"):
            admin = create_admin()
            user_repo.add(admin)
            print(f"  관리자 계정 생성: admin / admin123")
        else:
            print(f"  관리자 계정 이미 존재")

        # 회의실 생성
        existing_rooms = room_repo.get_all()
        if not existing_rooms:
            rooms = create_rooms()
            for room in rooms:
                room_repo.add(room)
            print(f"  회의실 {len(rooms)}개 생성")
        else:
            print(f"  회의실 이미 존재: {len(existing_rooms)}개")

        # 장비 생성
        existing_equipment = equipment_repo.get_all()
        if not existing_equipment:
            equipment = create_equipment()
            for eq in equipment:
                equipment_repo.add(eq)
            print(f"  장비 {len(equipment)}개 생성")
        else:
            print(f"  장비 이미 존재: {len(existing_equipment)}개")

    print("시드 데이터 생성 완료!")
    print(f"\n데이터 디렉토리: {DATA_DIR}")
    print("\n=== 로그인 정보 ===")
    print("관리자: admin / admin123")


if __name__ == "__main__":
    seed(reset="--reset" in sys.argv)
