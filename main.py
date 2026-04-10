#!/usr/bin/env python3
"""공유 오피스 예약 및 장비 대여 관리 CLI 프로그램"""

import sys
from datetime import datetime

from src.config import ensure_data_dir
from src.clock_bootstrap import get_latest_data_timestamp, load_persisted_clock
from src.runtime_clock import SystemClock, set_active_clock, ClockError
from src.cli.validators import validate_date_plan, validate_time_plan
from src.storage.integrity import DataIntegrityError, validate_all_data_files
from src.domain.models import UserRole
from src.domain.auth_service import AuthService
from src.domain.room_service import RoomService
from src.domain.equipment_service import EquipmentService
from src.domain.penalty_service import PenaltyService
from src.domain.policy_service import PolicyService
from src.cli.guest_menu import GuestMenu
from src.cli.user_menu import UserMenu
from src.cli.admin_menu import AdminMenu


def prompt_initial_clock():
    """프로그램 시작 시 운영 시작 시점을 입력받습니다."""
    latest_data_time = get_latest_data_timestamp()

    while True:
        print("\n운영 시작 시점을 설정합니다.")
        date_str = input("시작 날짜 (YYYY-MM-DD): ")
        slot_str = input("시작 슬롯 (09:00 또는 18:00): ")

        valid, base_date, error = validate_date_plan(date_str)
        if not valid or base_date is None:
            print(f"✗ {error}")
            continue

        time_valid, slot_time, time_error = validate_time_plan(slot_str)
        if not time_valid or slot_time is None:
            print(f"✗ {time_error}")
            continue

        start_time = datetime(
            base_date.year,
            base_date.month,
            base_date.day,
            slot_time.hour,
            slot_time.minute,
        )

        if latest_data_time is not None and start_time < latest_data_time:
            print(
                "✗ 시작 시점이 기존 데이터의 최신 시각보다 빠릅니다. "
                f"(최신 기록: {latest_data_time.strftime('%Y-%m-%d %H:%M')})"
            )
            continue

        try:
            return SystemClock(start_time)
        except ClockError as error:
            print(f"✗ {error}")


def main():
    """애플리케이션 메뉴 루프를 실행합니다."""
    try:
        ensure_data_dir()
        validate_all_data_files()
        persisted_clock = load_persisted_clock()
        if persisted_clock is None:
            set_active_clock(prompt_initial_clock())
        else:
            set_active_clock(SystemClock(persisted_clock))

        auth_service = AuthService()
        penalty_service = PenaltyService()
        room_service = RoomService(penalty_service=penalty_service)
        equipment_service = EquipmentService(penalty_service=penalty_service)
        policy_service = PolicyService()

        while True:
            guest_menu = GuestMenu(auth_service=auth_service, policy_service=policy_service)

            user = guest_menu.run()

            if user is None:
                break

            if user.role == UserRole.ADMIN:
                menu = AdminMenu(
                    user=user,
                    auth_service=auth_service,
                    room_service=room_service,
                    equipment_service=equipment_service,
                    penalty_service=penalty_service,
                    policy_service=policy_service,
                )
            else:
                menu = UserMenu(
                    user=user,
                    auth_service=auth_service,
                    room_service=room_service,
                    equipment_service=equipment_service,
                    penalty_service=penalty_service,
                    policy_service=policy_service,
                )

            menu.run()
    except DataIntegrityError as error:
        print(f"오류: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n프로그램이 중단되었습니다.")
        sys.exit(0)
