#!/usr/bin/env python3
"""공유 오피스 예약 및 장비 대여 관리 CLI 프로그램"""

import sys

from src.config import ensure_data_dir
from src.clock_bootstrap import (
    initialize_runtime_clock,
    get_latest_data_timestamp,
    prompt_initial_clock as _prompt_initial_clock,
    load_persisted_clock,
)
from src.runtime_clock import ClockError, SystemClock, clear_active_clock, set_active_clock
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
    return SystemClock(
        _prompt_initial_clock(
            latest_data_time_getter=get_latest_data_timestamp,
            saved_clock_time_getter=load_persisted_clock,
        )
    )


def main():
    """애플리케이션 메뉴 루프를 실행합니다."""
    try:
        ensure_data_dir()
        validate_all_data_files()
        persisted_clock = load_persisted_clock()
        if persisted_clock is None:
            active_clock = prompt_initial_clock()
        else:
            active_clock = SystemClock(persisted_clock)
        set_active_clock(active_clock)
        initialize_runtime_clock(active_clock)

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
    except ClockError as error:
        print(f"시계 오류: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    finally:
        clear_active_clock()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n프로그램이 중단되었습니다.")
        sys.exit(0)
