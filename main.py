#!/usr/bin/env python3
"""공유 오피스 예약 및 장비 대여 관리 CLI 프로그램"""

import sys
from datetime import datetime

from src.config import ensure_data_dir
from src.clock_bootstrap import get_latest_data_timestamp
from src.runtime_clock import SystemClock, set_active_clock, ClockError
from src.domain.models import UserRole
from src.domain.auth_service import AuthService
from src.domain.room_service import RoomService
from src.domain.equipment_service import EquipmentService
from src.domain.penalty_service import PenaltyService
from src.domain.policy_service import PolicyService
from src.domain.message_service import MessageService
from src.cli.guest_menu import GuestMenu
from src.cli.user_menu import UserMenu
from src.cli.admin_menu import AdminMenu


def prompt_initial_clock():
    """프로그램 시작 시 운영 시작 시점을 입력받습니다."""
    latest_data_time = get_latest_data_timestamp()

    while True:
        print("\n운영 시작 시점을 설정합니다.")
        date_str = input("시작 날짜 (YYYY-MM-DD): ").strip()
        slot_str = input("시작 슬롯 (09:00 또는 18:00): ").strip()

        try:
            base_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            print("✗ 날짜 형식이 올바르지 않습니다.")
            continue

        if slot_str not in ("09:00", "18:00"):
            print("✗ 시작 슬롯은 09:00 또는 18:00만 가능합니다.")
            continue

        hour, minute = [int(part) for part in slot_str.split(":")]
        start_time = base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)

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
    ensure_data_dir()
    set_active_clock(prompt_initial_clock())

    auth_service = AuthService()
    penalty_service = PenaltyService()
    room_service = RoomService(penalty_service=penalty_service)
    equipment_service = EquipmentService(penalty_service=penalty_service)
    policy_service = PolicyService()
    message_service = MessageService()

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
                message_service=message_service,
            )
        else:
            menu = UserMenu(
                user=user,
                auth_service=auth_service,
                room_service=room_service,
                equipment_service=equipment_service,
                penalty_service=penalty_service,
                policy_service=policy_service,
                message_service=message_service,
            )

        menu.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n프로그램이 중단되었습니다.")
        sys.exit(0)
