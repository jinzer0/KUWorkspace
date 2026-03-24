#!/usr/bin/env python3
"""
공유 오피스 예약 및 장비 대여 관리 CLI 프로그램
"""

import sys

from src.config import ensure_data_dir
from src.domain.models import UserRole
from src.domain.auth_service import AuthService
from src.domain.room_service import RoomService
from src.domain.equipment_service import EquipmentService
from src.domain.penalty_service import PenaltyService
from src.domain.policy_service import PolicyService
from src.cli.guest_menu import GuestMenu
from src.cli.user_menu import UserMenu
from src.cli.admin_menu import AdminMenu


def main():
    """애플리케이션 메뉴 루프를 실행합니다."""
    ensure_data_dir()

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


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n프로그램이 중단되었습니다.")
        sys.exit(0)
