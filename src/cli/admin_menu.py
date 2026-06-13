"""
관리자 메뉴 - 회의실/장비 관리, 예약 관리, 사용자 관리
"""

from typing import Any, cast

from src.domain.models import (
    RoomBookingStatus,
    EquipmentBookingStatus,
    ResourceStatus,
    UserRole,
    decode_future_status_changes,
)
from src.domain.auth_service import AuthService, AuthError
from src.domain.room_service import (
    RoomService,
    RoomBookingError,
    AdminRequiredError as RoomAdminRequiredError,
)
from src.domain.equipment_service import (
    EquipmentService,
    EquipmentBookingError,
    AdminRequiredError as EquipmentAdminRequiredError,
)
from src.domain.penalty_service import (
    PenaltyService,
    PenaltyError,
    AdminRequiredError,
)
from src.domain.policy_service import PolicyService
from src.config import (
    FIXED_BOOKING_END_HOUR,
    FIXED_BOOKING_END_MINUTE,
    FIXED_BOOKING_START_HOUR,
    FIXED_BOOKING_START_MINUTE,
)
from src.cli.menu import confirm, input_start_gate, pause, review_action, select_from_list
from src.cli.clock_menu import ClockMenu
from src.cli.formatters import (
    print_header,
    print_subheader,
    print_success,
    print_error,
    print_warning,
    print_info,
    format_table,
    format_status_badge,
    format_booking_time_range,
    format_datetime,
    format_penalty_status,
)
from src.cli.validators import (
    get_daily_date_range_input,
    validate_positive_int,
    validate_reason,
)


class AdminMenu:
    """관리자 메뉴"""

    def __init__(
        self,
        user,
        auth_service=None,
        room_service=None,
        equipment_service=None,
        penalty_service=None,
        policy_service=None,
    ):
        self.user = user
        self.auth_service = auth_service or AuthService()
        self.penalty_service = penalty_service or PenaltyService()
        self.room_service = room_service or RoomService(
            penalty_service=self.penalty_service
        )
        self.equipment_service = equipment_service or EquipmentService(
            penalty_service=self.penalty_service
        )
        self.policy_service = policy_service or PolicyService()

    def _safe_get_user(self, user_id):
        try:
            return self.auth_service.get_user(user_id)
        except AuthError:
            return None

    def _get_booking_user_or_abort(self, user_id):
        user = self._safe_get_user(user_id)
        if user is None:
            print_error("사용자를 찾을 수 없습니다.")
            pause()
        return user

    def _run_policy_checks(self):
        try:
            self.policy_service.run_all_checks()
            return True
        except (PenaltyError, AdminRequiredError, AuthError) as e:
            print_error(str(e))
            pause()
            return False

    def _print_daily_booking_guide(self):
        print(
            f"  이용 시간은 매일 {FIXED_BOOKING_START_HOUR:02d}:{FIXED_BOOKING_START_MINUTE:02d} ~ {FIXED_BOOKING_END_HOUR:02d}:{FIXED_BOOKING_END_MINUTE:02d}로 고정됩니다."
        )
        print("  예약 시작일은 내일부터 최대 180일, 예약 기간은 최대 14일입니다.")

    def _print_review_rows(self, rows):
        print_subheader("입력 내용 확인")
        for label, value in rows:
            print(f"  {label}: {value}")

    def _refresh_admin(self):
        try:
            self.user = self.auth_service.get_user(self.user.id)
            if not self.auth_service.is_admin(self.user):
                raise AuthError("관리자 권한이 필요합니다.")
            return True
        except AuthError as e:
            print_error(str(e))
            pause()
            return False

    def _get_room_bookings_or_abort(self):
        try:
            return self.room_service.get_all_bookings(self.user)
        except (RoomAdminRequiredError, AuthError) as e:
            print_error(str(e))
            pause()
            return None

    def _get_room_overview_or_abort(self):
        try:
            return self.room_service.get_room_operational_overview(self.user)
        except (RoomBookingError, RoomAdminRequiredError, AuthError, PenaltyError) as e:
            print_error(str(e))
            pause()
            return None

    def _get_equipment_bookings_or_abort(self):
        try:
            return self.equipment_service.get_all_bookings(self.user)
        except (EquipmentAdminRequiredError, AuthError) as e:
            print_error(str(e))
            pause()
            return None

    def _get_all_users_or_abort(self):
        try:
            return self.auth_service.get_all_users(self.user)
        except AuthError as e:
            print_error(str(e))
            pause()
            return None

    def run(self):
        """
        관리자 메뉴 실행

        Returns:
            로그아웃 여부
        """
        while True:
            if not self._run_policy_checks():
                return True
            if not self._refresh_admin():
                return True

            print_header(f"관리자 메뉴 ({self.user.username})")

            print("\n[회의실 관리]")
            print("  1. 전체 회의실 예약 조회")
            print("  2. 회의실 목록 조회 및 상태 변경")
            print("  3. 회의실 체크인 처리")
            print("  4. 회의실 퇴실 승인 처리")
            print("  5. 회의실 예약 변경 (관리자)")
            print("  6. 회의실 예약 취소 (관리자)")
            print("  7. 회의실 수정 (관리자)")

            print("\n[장비 관리]")
            print("  8. 전체 장비 예약 조회")
            print("  9. 장비 목록 조회 및 상태 변경")
            print("  10. 장비 대여 시작 처리")
            print("  11. 장비 반납 승인 처리")
            print("  12. 장비 예약 변경 (관리자)")
            print("  13. 장비 예약 취소 (관리자)")

            print("\n[사용자 관리]")
            print("  14. 사용자 목록")
            print("  15. 사용자 상세 조회")
            print("  16. 파손/오염 패널티 부여")
            print("  17. 예약 직전 취소 패널티 부여")
            print("  18. 회의실 퇴실 지연 처리")
            print("  19. 장비 반납 지연 처리")
            print("  20. 운영 시계")
            print("  기존 독립 점검/미래 상태 메뉴 번호는 잘못된 선택입니다.")

            print("\n  0. 로그아웃")
            print("-" * 50)

            choice = input("선택: ").strip()

            if choice == "1":
                self._show_all_room_bookings()
            elif choice == "2":
                self._show_rooms_and_change_status()
            elif choice == "3":
                self._room_checkin()
            elif choice == "4":
                self._room_checkout()
            elif choice == "5":
                self._admin_modify_room_booking_time()
            elif choice == "6":
                self._admin_cancel_room_booking()
            elif choice == "7":
                self._manage_room_resources()
            elif choice == "8":
                self._show_all_equipment_bookings()
            elif choice == "9":
                self._show_equipment_and_change_status()
            elif choice == "10":
                self._equipment_checkout()
            elif choice == "11":
                self._equipment_return()
            elif choice == "12":
                self._admin_modify_equipment_booking_time()
            elif choice == "13":
                self._admin_cancel_equipment_booking()
            elif choice == "14":
                self._show_users()
            elif choice == "15":
                self._show_user_detail()
            elif choice == "16":
                self._apply_damage_penalty()
            elif choice == "17":
                self._force_late_cancel_penalty()
            elif choice == "18":
                self._force_room_late_checkout()
            elif choice == "19":
                self._force_equipment_late_return()
            elif choice == "20":
                ClockMenu(self.policy_service, actor_id=self.user.id).run()
            elif choice == "0":
                if confirm("로그아웃 하시겠습니까?"):
                    print_success("로그아웃 되었습니다.")
                    return True
            else:
                print_error("잘못된 선택입니다.")

    def _show_rooms(self):
        """회의실 목록"""
        print_header("회의실 목록")

        rooms = self.room_service.get_all_rooms()
        if not rooms:
            print_info("등록된 회의실이 없습니다.")
            pause()
            return

        headers = ["ID", "이름", "수용인원", "위치", "상태"]
        rows = []
        for room in rooms:
            rows.append(
                [
                    room.id[:8],
                    room.name,
                    f"{room.capacity}명",
                    room.location,
                    format_status_badge(room.status.value),
                ]
            )

        print(format_table(headers, rows))
        pause()

    def _show_rooms_and_change_status(self):
        """회의실 목록 조회 및 상태 변경"""
        self._change_room_status()

    def _manage_room_resources(self):
        print_header("회의실 수정 (관리자)")
        print("  1. 회의실 추가")
        print("  2. 회의실 삭제")
        print("  3. 회의실 수용인원/위치 수정")
        print("  0. 취소")
        choice = input("선택: ").strip()
        if choice == "1":
            self._add_room_resource()
        elif choice == "2":
            self._delete_room_resource()
        elif choice == "3":
            self._edit_room_resource()
        elif choice == "0":
            return
        else:
            print_error("잘못된 선택입니다.")
            pause()

    def _add_room_resource(self):
        while True:
            if not input_start_gate("회의실 추가 입력"):
                return
            name = input("회의실 이름: ").strip()
            capacity_text = input("수용 인원: ").strip()
            location = input("위치: ").strip()
            self._print_review_rows([("회의실 이름", name), ("수용 인원", capacity_text), ("위치", location)])
            decision = review_action("회의실 추가 검토", "저장")
            if decision == "confirm":
                break
            if decision == "cancel":
                print_info("회의실 추가를 취소했습니다.")
                pause()
                return
        try:
            room = self.room_service.add_room_resource(
                self.user, name, capacity_text, location
            )
            print_success(f"회의실이 추가되었습니다: {room.name}")
        except (RoomBookingError, RoomAdminRequiredError, AuthError, PenaltyError) as e:
            print_error(str(e))
        pause()

    def _select_room_resource(self, prompt):
        rooms = self.room_service.get_all_rooms()
        if not rooms:
            print_info("등록된 회의실이 없습니다.")
            pause()
            return None
        return select_from_list(
            [
                (room.id, f"{room.name} ({room.capacity}명, {room.location}) {format_status_badge(room.status.value)}")
                for room in rooms
            ],
            prompt,
        )

    def _delete_room_resource(self):
        while True:
            room_id = self._select_room_resource("삭제할 회의실 선택")
            if not room_id:
                return
            self._print_review_rows([("회의실 ID", room_id[:8])])
            decision = review_action("회의실 삭제 검토", "처리")
            if decision == "confirm":
                break
            if decision == "cancel":
                print_info("회의실 삭제를 취소했습니다.")
                pause()
                return
        try:
            room = self.room_service.delete_room_resource(self.user, room_id)
            print_success(f"회의실이 삭제되었습니다: {room.name}")
        except (RoomBookingError, RoomAdminRequiredError, AuthError, PenaltyError) as e:
            print_error(str(e))
        pause()

    def _edit_room_resource(self):
        while True:
            if not input_start_gate("회의실 수정 입력"):
                return
            room_id = self._select_room_resource("수정할 회의실 선택")
            if not room_id:
                return
            capacity_text = input("새 수용 인원: ").strip()
            location = input("새 위치: ").strip()
            self._print_review_rows([("회의실 ID", room_id[:8]), ("새 수용 인원", capacity_text), ("새 위치", location)])
            decision = review_action("회의실 수정 검토", "저장")
            if decision == "confirm":
                break
            if decision == "cancel":
                print_info("회의실 수정을 취소했습니다.")
                pause()
                return
        try:
            room = self.room_service.edit_room_resource(
                self.user, room_id, capacity_text, location
            )
            print_success(f"회의실이 수정되었습니다: {room.name}")
        except (RoomBookingError, RoomAdminRequiredError, AuthError, PenaltyError) as e:
            print_error(str(e))
        pause()

    def _change_room_status(self):
        """회의실 상태 변경"""
        print_header("회의실 목록 조회 및 상태 변경")

        rooms = self.room_service.get_all_rooms()
        if not rooms:
            print_info("등록된 회의실이 없습니다.")
            pause()
            return

        items = [
            (r.id, f"{r.name} {format_status_badge(r.status.value)}") for r in rooms
        ]
        room_id = select_from_list(items, "회의실 선택")
        if not room_id:
            return

        print("\n선택한 회의실 작업:")
        print("  1. 상태 변경")
        print("  2. 정기 점검")
        print("  0. 취소")
        action_choice = input("\n선택: ").strip()
        if action_choice == "2":
            active_schedules = [
                schedule
                for schedule in self.room_service.maintenance_repo.get_all()
                if schedule.room_id == room_id and schedule.status in {"scheduled", "active"}
            ]
            if active_schedules:
                self._cancel_room_maintenance(room_id)
            else:
                self._create_room_maintenance(room_id)
            return
        if action_choice == "0":
            return
        if action_choice != "1":
            print_error("잘못된 선택입니다.")
            pause()
            return

        print("\n변경할 상태:")
        print("  1. 사용가능 (available)")
        print("  2. 점검중 (maintenance)")
        print("  3. 사용불가 (disabled)")

        choice = input("\n선택: ").strip()
        status_map = {
            "1": ResourceStatus.AVAILABLE,
            "2": ResourceStatus.MAINTENANCE,
            "3": ResourceStatus.DISABLED,
        }

        if choice not in status_map:
            print_error("잘못된 선택입니다.")
            pause()
            return

        new_status = status_map[choice]

        if new_status in (ResourceStatus.MAINTENANCE, ResourceStatus.DISABLED):
            print_warning("점검중/사용불가로 변경 시 미래 예약이 자동 취소됩니다.")
        self._print_review_rows([("회의실 ID", room_id[:8]), ("새 상태", new_status.value)])
        decision = review_action("회의실 상태 변경 검토", "처리")
        if decision == "retry":
            return self._change_room_status()
        if decision == "cancel":
            print_info("회의실 상태 변경을 취소했습니다.")
            pause()
            return

        try:
            room, cancelled = self.room_service.update_room_status(
                admin=self.user, room_id=room_id, new_status=new_status
            )
            print_success(
                f"상태가 변경되었습니다: {format_status_badge(new_status.value)}"
            )
            if cancelled:
                print_info(f"자동 취소된 예약: {len(cancelled)}건")
        except (RoomBookingError, RoomAdminRequiredError, AuthError, PenaltyError) as e:
            print_error(str(e))

        pause()

    def _show_all_room_bookings(self):
        """전체 회의실 예약 조회"""
        print_header("회의실 목록")

        overview = self._get_room_overview_or_abort()
        if overview is None:
            return
        if not overview:
            print_info("등록된 회의실이 없습니다.")
            pause()
            return

        headers = ["이름", "수용인원", "위치", "현황", "예약일"]
        rows = []
        reservation_width = len("예약일")
        for item in overview:
            reservation_lines = item.reservation_summary.splitlines() or ["X"]
            reservation_width = max(
                reservation_width, *(len(line) for line in reservation_lines)
            )
            rows.append(
                [
                    item.room_name,
                    f"{item.capacity}명",
                    item.location,
                    item.operational_status,
                    reservation_lines[0],
                ]
            )
            for reservation_line in reservation_lines[1:]:
                rows.append(["", "", "", "", reservation_line])

        col_widths = [
            min(max(len("이름"), *(len(str(row[0])) for row in rows)) + 2, 40),
            min(max(len("수용인원"), *(len(str(row[1])) for row in rows)) + 2, 40),
            min(max(len("위치"), *(len(str(row[2])) for row in rows)) + 2, 40),
            min(max(len("현황"), *(len(str(row[3])) for row in rows)) + 2, 40),
            reservation_width + 2,
        ]
        print(format_table(headers, rows, col_widths=col_widths))

        pause()

    def _room_checkin(self):
        """회의실 체크인 처리"""
        print_header("회의실 체크인")

        all_bookings = self._get_room_bookings_or_abort()
        if all_bookings is None:
            return
        pending = [
            b for b in all_bookings if b.status == RoomBookingStatus.CHECKIN_REQUESTED
        ]

        if not pending:
            print_info("체크인 대기 중인 예약이 없습니다.")
            pause()
            return

        items = []
        for booking in pending:
            room = self.room_service.get_room(booking.room_id)
            user = self._get_booking_user_or_abort(booking.user_id)
            if user is None:
                return
            items.append(
                (
                    booking.id,
                    f"{room.name if room else '-'} / {user.username} / {format_booking_time_range(booking.start_time, booking.end_time)}",
                )
            )

        booking_id = select_from_list(items, "체크인할 예약 선택")
        if not booking_id:
            return
        self._print_review_rows([("예약 ID", booking_id[:8])])
        decision = review_action("회의실 체크인 처리 검토", "처리")
        if decision == "retry":
            return self._room_checkin()
        if decision == "cancel":
            print_info("체크인 처리를 취소했습니다.")
            pause()
            return

        try:
            booking = self.room_service.check_in(self.user, booking_id)
            print_success("체크인 처리되었습니다.")
        except (RoomBookingError, RoomAdminRequiredError, AuthError, PenaltyError) as e:
            print_error(str(e))

        pause()

    def _room_checkout(self):
        print_header("회의실 퇴실 승인")

        all_bookings = self._get_room_bookings_or_abort()
        if all_bookings is None:
            return
        requested = [
            b
            for b in all_bookings
            if b.status == RoomBookingStatus.CHECKOUT_REQUESTED
        ]

        if not requested:
            print_info("퇴실 승인 대기 중인 예약이 없습니다.")
            pause()
            return

        items = []
        for booking in requested:
            room = self.room_service.get_room(booking.room_id)
            user = self._get_booking_user_or_abort(booking.user_id)
            if user is None:
                return
            items.append(
                (
                    booking.id,
                    f"{room.name if room else '-'} / {user.username} / {format_booking_time_range(booking.start_time, booking.end_time)}",
                )
            )

        booking_id = select_from_list(items, "퇴실 승인할 예약 선택")
        if not booking_id:
            return
        self._print_review_rows([("예약 ID", booking_id[:8])])
        decision = review_action("회의실 퇴실 승인 검토", "처리")
        if decision == "retry":
            return self._room_checkout()
        if decision == "cancel":
            print_info("퇴실 승인을 취소했습니다.")
            pause()
            return

        try:
            self.room_service.approve_checkout_request(self.user, booking_id)
            print_success("퇴실 승인이 완료되었습니다.")
        except (RoomBookingError, RoomAdminRequiredError, AuthError, PenaltyError) as e:
            print_error(str(e))

        pause()

    def _force_room_late_checkout(self):
        print_header("회의실 퇴실 지연 처리")

        all_bookings = self._get_room_bookings_or_abort()
        if all_bookings is None:
            return
        current_time = self.policy_service.clock.now().isoformat()
        checked_in = [
            b
            for b in all_bookings
            if b.status == RoomBookingStatus.CHECKED_IN and b.end_time == current_time
        ]

        if not checked_in:
            print_info("퇴실 지연 처리 대상이 없습니다.")
            pause()
            return

        items = []
        for booking in checked_in:
            room = self.room_service.get_room(booking.room_id)
            user = self._get_booking_user_or_abort(booking.user_id)
            if user is None:
                return
            items.append(
                (
                    booking.id,
                    f"{room.name if room else '-'} / {user.username} / {format_booking_time_range(booking.start_time, booking.end_time)}",
                )
            )

        booking_id = select_from_list(items, "퇴실 지연 처리할 예약 선택")
        if not booking_id:
            return
        self._print_review_rows([("예약 ID", booking_id[:8])])
        decision = review_action("회의실 퇴실 지연 처리 검토", "처리")
        if decision == "retry":
            return self._force_room_late_checkout()
        if decision == "cancel":
            print_info("퇴실 지연 처리를 취소했습니다.")
            pause()
            return

        try:
            _, delay_minutes = self.room_service.force_complete_checkout(
                self.user, booking_id
            )
            print_success("퇴실 지연 처리가 완료되었습니다.")
            print_info(f"지연 처리 시간: {delay_minutes}분, 지연 패널티 2점 부과")
        except (RoomBookingError, RoomAdminRequiredError, AuthError, PenaltyError) as e:
            print_error(str(e))

        pause()

    def _force_late_cancel_penalty(self):
        print_header("예약 직전 취소 패널티 부여")

        users = [u for u in (self._get_all_users_or_abort() or []) if u.role == UserRole.USER]
        if not users:
            print_info("일반 사용자가 없습니다.")
            pause()
            return

        user_id = select_from_list([(u.id, u.username) for u in users], "사용자 선택")
        if not user_id:
            return
        user = self._safe_get_user(user_id)
        if user is None:
            print_error("사용자를 찾을 수 없습니다.")
            pause()
            return

        room_bookings = [
            b
            for b in (self.room_service.get_user_bookings(user.id) or [])
            if b.status == RoomBookingStatus.CANCELLED
        ]
        equip_bookings = [
            b
            for b in (self.equipment_service.get_user_bookings(user.id) or [])
            if b.status == EquipmentBookingStatus.CANCELLED
        ]

        items = [(b.id, f"회의실 / {format_booking_time_range(b.start_time, b.end_time)}") for b in room_bookings]
        items.extend(
            (b.id, f"장비 / {format_booking_time_range(b.start_time, b.end_time)}")
            for b in equip_bookings
        )
        if not items:
            print_info("직전 취소 패널티를 수동 부과할 취소 예약이 없습니다.")
            pause()
            return

        booking_id = select_from_list(items, "관련 예약 선택")
        if not booking_id:
            return

        booking_type = (
            "room_booking" if any(b.id == booking_id for b in room_bookings) else "equipment_booking"
        )
        self._print_review_rows([("사용자", user.username), ("예약 ID", booking_id[:8]), ("패널티", "2점")])
        decision = review_action("직전 취소 패널티 부여 검토", "처리")
        if decision == "retry":
            return self._force_late_cancel_penalty()
        if decision == "cancel":
            print_info("직전 취소 패널티 부여를 취소했습니다.")
            pause()
            return

        try:
            self.penalty_service.apply_late_cancel(
                user=user,
                booking_type=booking_type,
                booking_id=booking_id,
                actor_id=self.user.id,
            )
            print_success("직전 취소 패널티가 부여되었습니다. (+2점)")
        except (PenaltyError, AuthError) as e:
            print_error(str(e))

        pause()

    def _admin_modify_room_booking_time(self):
        """관리자 회의실 예약 시간 변경"""
        print_header("회의실 예약 변경 (관리자)")

        all_bookings = self._get_room_bookings_or_abort()
        if all_bookings is None:
            return
        modifiable = [b for b in all_bookings if b.status == RoomBookingStatus.RESERVED]

        if not modifiable:
            print_info("변경 가능한 예약이 없습니다.")
            pause()
            return

        items = []
        for booking in modifiable:
            room = self.room_service.get_room(booking.room_id)
            user = self._get_booking_user_or_abort(booking.user_id)
            if user is None:
                return
            items.append(
                (
                    booking.id,
                    f"{room.name if room else '-'} / {user.username} / {format_booking_time_range(booking.start_time, booking.end_time)}",
                )
            )

        while True:
            if not input_start_gate("관리자 회의실 예약 변경 입력"):
                return
            booking_id = select_from_list(items, "변경할 예약 선택")
            if not booking_id:
                return

            self._print_daily_booking_guide()
            start_date, end_date = get_daily_date_range_input("시작 날짜", "종료 날짜")
            if start_date is None or end_date is None:
                return
            self._print_review_rows([("예약 ID", booking_id[:8]), ("새 기간", f"{start_date} ~ {end_date}")])
            decision = review_action("관리자 회의실 예약 변경 검토", "저장")
            if decision == "confirm":
                break
            if decision == "cancel":
                print_info("예약 변경을 취소했습니다.")
                pause()
                return

        try:
            booking = self.room_service.admin_modify_daily_booking(
                admin=self.user,
                booking_id=booking_id,
                start_date=start_date,
                end_date=end_date,
            )
            print_success("예약이 변경되었습니다.")
        except (RoomBookingError, RoomAdminRequiredError, AuthError, PenaltyError) as e:
            print_error(str(e))

        pause()

    def _admin_cancel_room_booking(self):
        """관리자 회의실 예약 취소"""
        print_header("회의실 예약 취소 (관리자)")

        all_bookings = self._get_room_bookings_or_abort()
        if all_bookings is None:
            return
        cancellable = [
            b for b in all_bookings if b.status == RoomBookingStatus.RESERVED
        ]

        if not cancellable:
            print_info("취소 가능한 예약이 없습니다.")
            pause()
            return

        items = []
        for booking in cancellable:
            room = self.room_service.get_room(booking.room_id)
            user = self._get_booking_user_or_abort(booking.user_id)
            if user is None:
                return
            items.append(
                (
                    booking.id,
                    f"{room.name if room else '-'} / {user.username} / {format_status_badge(booking.status.value)}",
                )
            )

        booking_id = select_from_list(items, "취소할 예약 선택")
        if not booking_id:
            return

        while True:
            if not input_start_gate("관리자 회의실 예약 취소 입력"):
                return
            reason = input("취소 사유: ").strip()
            valid, error = validate_reason(reason)
            if not valid:
                print_error(error)
                pause()
                return
            self._print_review_rows([("예약 ID", booking_id[:8]), ("취소 사유", reason or "-")])
            decision = review_action("관리자 회의실 예약 취소 검토", "처리")
            if decision == "confirm":
                break
            if decision == "cancel":
                print_info("예약 취소를 취소했습니다.")
                pause()
                return

        try:
            self.room_service.admin_cancel_booking(self.user, booking_id, reason)
            print_success("예약이 취소되었습니다.")
        except (RoomBookingError, RoomAdminRequiredError, AuthError, PenaltyError) as e:
            print_error(str(e))

        pause()

    def _show_equipment(self):
        """장비 목록"""
        print_header("장비 목록")

        equipment_list = self.equipment_service.get_all_equipment()
        if not equipment_list:
            print_info("등록된 장비가 없습니다.")
            pause()
            return

        headers = ["ID", "이름", "종류", "시리얼번호", "상태"]
        rows = []
        for equip in equipment_list:
            rows.append(
                [
                    equip.id[:8],
                    equip.name,
                    equip.asset_type,
                    equip.serial_number,
                    format_status_badge(equip.status.value),
                ]
            )

        print(format_table(headers, rows))
        pause()

    def _show_equipment_and_change_status(self):
        """장비 목록 조회 및 상태 변경"""
        self._change_equipment_status()

    def _change_equipment_status(self):
        """장비 상태 변경"""
        print_header("장비 목록 조회 및 상태 변경")

        equipment_list = self.equipment_service.get_all_equipment()
        if not equipment_list:
            print_info("등록된 장비가 없습니다.")
            pause()
            return

        headers = ["ID", "이름", "종류", "시리얼번호", "상태"]
        rows = [
            [
                item.id[:8],
                item.name,
                item.asset_type,
                item.serial_number,
                format_status_badge(item.status.value),
            ]
            for item in equipment_list
        ]
        print(format_table(headers, rows))
        print("\n  1. 현재 시점 상태 변경")
        print("  2. 미래 날짜 상태 예약")
        print("  3. 미래 상태 예약 취소")
        print("\n  +. 편집")
        print("  0. 취소")
        first_choice = input("\n선택: ").strip()
        if first_choice == "+":
            self._manage_equipment_resources()
            return
        if first_choice == "2":
            self._schedule_equipment_future_status()
            return
        if first_choice == "3":
            self._cancel_equipment_future_status()
            return
        if first_choice == "0":
            return
        if first_choice != "1":
            print_error("잘못된 선택입니다.")
            pause()
            return

        items = [
            (e.id, f"{e.name} ({e.asset_type}) {format_status_badge(e.status.value)}")
            for e in equipment_list
        ]
        equipment_id = select_from_list(items, "장비 선택")
        if not equipment_id:
            return

        print("\n변경할 상태:")
        print("  1. 사용가능 (available)")
        print("  2. 점검중 (maintenance)")
        print("  3. 사용불가 (disabled)")

        choice = input("\n선택: ").strip()
        status_map = {
            "1": ResourceStatus.AVAILABLE,
            "2": ResourceStatus.MAINTENANCE,
            "3": ResourceStatus.DISABLED,
        }

        if choice not in status_map:
            print_error("잘못된 선택입니다.")
            pause()
            return

        new_status = status_map[choice]

        if new_status in (ResourceStatus.MAINTENANCE, ResourceStatus.DISABLED):
            print_warning("점검중/사용불가로 변경 시 미래 예약이 자동 취소됩니다.")
        self._print_review_rows([("장비 ID", equipment_id[:8]), ("새 상태", new_status.value)])
        decision = review_action("장비 상태 변경 검토", "처리")
        if decision == "retry":
            return self._change_equipment_status()
        if decision == "cancel":
            print_info("장비 상태 변경을 취소했습니다.")
            pause()
            return

        try:
            equip, cancelled = self.equipment_service.update_equipment_status(
                admin=self.user, equipment_id=equipment_id, new_status=new_status
            )
            print_success(
                f"상태가 변경되었습니다: {format_status_badge(new_status.value)}"
            )
            if cancelled:
                print_info(f"자동 취소된 예약: {len(cancelled)}건")
        except (
            EquipmentBookingError,
            EquipmentAdminRequiredError,
            AuthError,
            PenaltyError,
        ) as e:
            print_error(str(e))

        pause()

    def _manage_equipment_resources(self):
        print_header("장비 편집")
        print("  1. 장비 이름 수정")
        print("  2. 장비 삭제")
        print("  3. 장비 추가")
        print("  0. 취소")
        choice = input("선택: ").strip()
        if choice == "1":
            self._edit_equipment_resource()
        elif choice == "2":
            self._delete_equipment_resource()
        elif choice == "3":
            self._add_equipment_resource()
        elif choice == "0":
            return
        else:
            print_error("잘못된 선택입니다.")
            pause()

    def _select_equipment_resource(self, prompt):
        equipment_list = self.equipment_service.get_all_equipment()
        if not equipment_list:
            print_info("등록된 장비가 없습니다.")
            pause()
            return None
        return select_from_list(
            [
                (item.id, f"{item.name} ({item.asset_type}, S/N: {item.serial_number}) {format_status_badge(item.status.value)}")
                for item in equipment_list
            ],
            prompt,
        )

    def _edit_equipment_resource(self):
        while True:
            if not input_start_gate("장비 이름 수정 입력"):
                return
            equipment_id = self._select_equipment_resource("수정할 장비 선택")
            if not equipment_id:
                return
            name = input("새 장비 이름: ").strip()
            self._print_review_rows([("장비 ID", equipment_id[:8]), ("새 이름", name)])
            decision = review_action("장비 이름 수정 검토", "저장")
            if decision == "confirm":
                break
            if decision == "cancel":
                print_info("장비 이름 수정을 취소했습니다.")
                pause()
                return
        try:
            equipment = self.equipment_service.edit_equipment_resource_name(
                self.user, equipment_id, name
            )
            print_success(f"장비 이름이 수정되었습니다: {equipment.name}")
        except (EquipmentBookingError, EquipmentAdminRequiredError, AuthError, PenaltyError) as e:
            print_error(str(e))
        pause()

    def _delete_equipment_resource(self):
        while True:
            equipment_id = self._select_equipment_resource("삭제할 장비 선택")
            if not equipment_id:
                return
            self._print_review_rows([("장비 ID", equipment_id[:8])])
            decision = review_action("장비 삭제 검토", "처리")
            if decision == "confirm":
                break
            if decision == "cancel":
                print_info("장비 삭제를 취소했습니다.")
                pause()
                return
        try:
            equipment = self.equipment_service.delete_equipment_resource(
                self.user, equipment_id
            )
            print_success(f"장비가 삭제되었습니다: {equipment.name}")
        except (EquipmentBookingError, EquipmentAdminRequiredError, AuthError, PenaltyError) as e:
            print_error(str(e))
        pause()

    def _add_equipment_resource(self):
        while True:
            if not input_start_gate("장비 추가 입력"):
                return
            equipment_list = self.equipment_service.get_all_equipment()
            existing_types = sorted({item.asset_type for item in equipment_list})
            print("\n장비 종류:")
            for index, asset_type in enumerate(existing_types, 1):
                print(f"  {index}. {asset_type}")
            print("  +. 직접 입력")
            print("  0. 취소")
            type_choice = input("종류 선택: ").strip()
            if type_choice == "0":
                return
            if type_choice == "+":
                asset_type = input("새 장비 종류: ").strip().lower()
            else:
                try:
                    asset_type = existing_types[int(type_choice) - 1]
                except (ValueError, IndexError):
                    print_error("잘못된 선택입니다.")
                    pause()
                    return
            name = input("장비 이름: ").strip()
            description = input("설명 (선택): ").strip()
            self._print_review_rows([("장비 이름", name), ("종류", asset_type), ("설명", description or "-")])
            decision = review_action("장비 추가 검토", "저장")
            if decision == "confirm":
                break
            if decision == "cancel":
                print_info("장비 추가를 취소했습니다.")
                pause()
                return
        try:
            equipment = self.equipment_service.add_equipment_resource(
                self.user, name, asset_type, description
            )
            print_success(
                f"장비가 추가되었습니다: {equipment.name} / S/N: {equipment.serial_number}"
            )
        except (EquipmentBookingError, EquipmentAdminRequiredError, AuthError, PenaltyError) as e:
            print_error(str(e))
        pause()

    def _show_all_equipment_bookings(self):
        """전체 장비 예약 조회"""
        print_header("전체 장비 예약")

        bookings = self._get_equipment_bookings_or_abort()
        if bookings is None:
            return
        if not bookings:
            print_info("예약 내역이 없습니다.")
            pause()
            return

        bookings.sort(key=lambda b: b.start_time, reverse=True)

        headers = ["ID", "장비", "사용자", "대여 기간", "상태"]
        rows = []
        for booking in bookings[:30]:
            equip = self.equipment_service.get_equipment(booking.equipment_id)
            user = self._get_booking_user_or_abort(booking.user_id)
            if user is None:
                return
            rows.append(
                [
                    booking.id[:8],
                    equip.name if equip else "-",
                    user.username,
                    format_booking_time_range(booking.start_time, booking.end_time),
                    format_status_badge(booking.status.value),
                ]
            )

        print(format_table(headers, rows))

        if len(bookings) > 30:
            print(f"\n  ... 외 {len(bookings) - 30}건")

        pause()

    def _equipment_checkout(self):
        """장비 대여 시작 처리"""
        print_header("장비 대여 시작")

        all_bookings = self._get_equipment_bookings_or_abort()
        if all_bookings is None:
            return
        pending = [
            b for b in all_bookings if b.status == EquipmentBookingStatus.PICKUP_REQUESTED
        ]

        if not pending:
            print_info("대여 대기 중인 예약이 없습니다.")
            pause()
            return

        items = []
        for booking in pending:
            equip = self.equipment_service.get_equipment(booking.equipment_id)
            user = self._get_booking_user_or_abort(booking.user_id)
            if user is None:
                return
            items.append(
                (
                    booking.id,
                    f"{equip.name if equip else '-'} / {user.username} / {format_booking_time_range(booking.start_time, booking.end_time)}",
                )
            )

        booking_id = select_from_list(items, "대여 시작할 예약 선택")
        if not booking_id:
            return
        self._print_review_rows([("예약 ID", booking_id[:8])])
        decision = review_action("장비 대여 시작 검토", "처리")
        if decision == "retry":
            return self._equipment_checkout()
        if decision == "cancel":
            print_info("장비 대여 시작을 취소했습니다.")
            pause()
            return

        try:
            self.equipment_service.checkout(self.user, booking_id)
            print_success("대여가 시작되었습니다.")
        except (
            EquipmentBookingError,
            EquipmentAdminRequiredError,
            AuthError,
            PenaltyError,
        ) as e:
            print_error(str(e))

        pause()

    def _equipment_return(self):
        print_header("장비 반납 승인")

        all_bookings = self._get_equipment_bookings_or_abort()
        if all_bookings is None:
            return
        requested = [
            b
            for b in all_bookings
            if b.status == EquipmentBookingStatus.RETURN_REQUESTED
        ]

        if not requested:
            print_info("반납 승인 대기 중인 예약이 없습니다.")
            pause()
            return

        items = []
        for booking in requested:
            equip = self.equipment_service.get_equipment(booking.equipment_id)
            user = self._get_booking_user_or_abort(booking.user_id)
            if user is None:
                return
            items.append(
                (
                    booking.id,
                    f"{equip.name if equip else '-'} / {user.username} / {format_booking_time_range(booking.start_time, booking.end_time)}",
                )
            )

        booking_id = select_from_list(items, "반납 승인할 예약 선택")
        if not booking_id:
            return
        self._print_review_rows([("예약 ID", booking_id[:8])])
        decision = review_action("장비 반납 승인 검토", "처리")
        if decision == "retry":
            return self._equipment_return()
        if decision == "cancel":
            print_info("장비 반납 승인을 취소했습니다.")
            pause()
            return

        try:
            self.equipment_service.approve_return_request(
                self.user, booking_id
            )
            print_success("반납 승인이 완료되었습니다.")
        except (
            EquipmentBookingError,
            EquipmentAdminRequiredError,
            AuthError,
            PenaltyError,
        ) as e:
            print_error(str(e))

        pause()

    def _force_equipment_late_return(self):
        print_header("장비 반납 지연 처리")

        all_bookings = self._get_equipment_bookings_or_abort()
        if all_bookings is None:
            return
        current_time = self.policy_service.clock.now().isoformat()
        checked_out = [
            b
            for b in all_bookings
            if b.status == EquipmentBookingStatus.CHECKED_OUT
            and b.end_time == current_time
        ]

        if not checked_out:
            print_info("반납 지연 처리 대상이 없습니다.")
            pause()
            return

        items = []
        for booking in checked_out:
            equip = self.equipment_service.get_equipment(booking.equipment_id)
            user = self._get_booking_user_or_abort(booking.user_id)
            if user is None:
                return
            items.append(
                (
                    booking.id,
                    f"{equip.name if equip else '-'} / {user.username} / {format_booking_time_range(booking.start_time, booking.end_time)}",
                )
            )

        booking_id = select_from_list(items, "반납 지연 처리할 예약 선택")
        if not booking_id:
            return
        self._print_review_rows([("예약 ID", booking_id[:8])])
        decision = review_action("장비 반납 지연 처리 검토", "처리")
        if decision == "retry":
            return self._force_equipment_late_return()
        if decision == "cancel":
            print_info("장비 반납 지연 처리를 취소했습니다.")
            pause()
            return

        try:
            _, delay_minutes = self.equipment_service.force_complete_return(
                self.user, booking_id
            )
            print_success("반납 지연 처리가 완료되었습니다.")
            print_info(f"지연 처리 시간: {delay_minutes}분, 지연 패널티 2점 부과")
        except (
            EquipmentBookingError,
            EquipmentAdminRequiredError,
            AuthError,
            PenaltyError,
        ) as e:
            print_error(str(e))

        pause()

    def _admin_modify_equipment_booking_time(self):
        """관리자 장비 예약 시간 변경"""
        print_header("장비 예약 변경 (관리자)")

        all_bookings = self._get_equipment_bookings_or_abort()
        if all_bookings is None:
            return
        modifiable = [
            b for b in all_bookings if b.status == EquipmentBookingStatus.RESERVED
        ]

        if not modifiable:
            print_info("변경 가능한 예약이 없습니다.")
            pause()
            return

        items = []
        for booking in modifiable:
            equip = self.equipment_service.get_equipment(booking.equipment_id)
            user = self._get_booking_user_or_abort(booking.user_id)
            if user is None:
                return
            items.append(
                (
                    booking.id,
                    f"{equip.name if equip else '-'} / {user.username} / {format_booking_time_range(booking.start_time, booking.end_time)}",
                )
            )

        while True:
            if not input_start_gate("관리자 장비 예약 변경 입력"):
                return
            booking_id = select_from_list(items, "변경할 예약 선택")
            if not booking_id:
                return

            self._print_daily_booking_guide()
            start_date, end_date = get_daily_date_range_input("시작 날짜", "종료 날짜")
            if start_date is None or end_date is None:
                return
            self._print_review_rows([("예약 ID", booking_id[:8]), ("새 기간", f"{start_date} ~ {end_date}")])
            decision = review_action("관리자 장비 예약 변경 검토", "저장")
            if decision == "confirm":
                break
            if decision == "cancel":
                print_info("예약 변경을 취소했습니다.")
                pause()
                return

        try:
            booking = self.equipment_service.admin_modify_daily_booking(
                admin=self.user,
                booking_id=booking_id,
                start_date=start_date,
                end_date=end_date,
            )
            print_success("예약이 변경되었습니다.")
        except (
            EquipmentBookingError,
            EquipmentAdminRequiredError,
            AuthError,
            PenaltyError,
        ) as e:
            print_error(str(e))

        pause()

    def _admin_cancel_equipment_booking(self):
        """관리자 장비 예약 취소"""
        print_header("장비 예약 취소 (관리자)")

        all_bookings = self._get_equipment_bookings_or_abort()
        if all_bookings is None:
            return
        cancellable = [
            b for b in all_bookings if b.status == EquipmentBookingStatus.RESERVED
        ]

        if not cancellable:
            print_info("취소 가능한 예약이 없습니다.")
            pause()
            return

        items = []
        for booking in cancellable:
            equip = self.equipment_service.get_equipment(booking.equipment_id)
            user = self._get_booking_user_or_abort(booking.user_id)
            if user is None:
                return
            items.append(
                (
                    booking.id,
                    f"{equip.name if equip else '-'} / {user.username} / {format_status_badge(booking.status.value)}",
                )
            )

        booking_id = select_from_list(items, "취소할 예약 선택")
        if not booking_id:
            return

        while True:
            if not input_start_gate("관리자 장비 예약 취소 입력"):
                return
            reason = input("취소 사유: ").strip()
            valid, error = validate_reason(reason)
            if not valid:
                print_error(error)
                pause()
                return
            self._print_review_rows([("예약 ID", booking_id[:8]), ("취소 사유", reason or "-")])
            decision = review_action("관리자 장비 예약 취소 검토", "처리")
            if decision == "confirm":
                break
            if decision == "cancel":
                print_info("예약 취소를 취소했습니다.")
                pause()
                return

        try:
            self.equipment_service.admin_cancel_booking(self.user, booking_id, reason)
            print_success("예약이 취소되었습니다.")
        except (
            EquipmentBookingError,
            EquipmentAdminRequiredError,
            AuthError,
            PenaltyError,
        ) as e:
            print_error(str(e))

        pause()

    def _create_room_maintenance(self, selected_room_id=None):
        print_header("회의실 점검 일정 생성")
        rooms = self.room_service.get_all_rooms()
        if not rooms:
            print_info("등록된 회의실이 없습니다.")
            pause()
            return
        while True:
            if not input_start_gate("회의실 점검 일정 입력"):
                return
            room_id = selected_room_id
            if room_id is None:
                room_id = select_from_list(
                    [(room.id, f"{room.name} ({room.location})") for room in rooms],
                    "점검 회의실 선택",
                )
            if not room_id:
                return
            self._print_daily_booking_guide()
            start_date, end_date = get_daily_date_range_input("점검 시작 날짜", "점검 종료 날짜")
            if start_date is None or end_date is None:
                return
            reason = input("점검 사유 (선택, 20자 이하): ").strip()
            valid, error = validate_reason(reason)
            if not valid:
                print_error(error)
                pause()
                return
            self._print_review_rows([("회의실 ID", room_id[:8]), ("기간", f"{start_date} ~ {end_date}"), ("사유", reason or "-")])
            decision = review_action("회의실 점검 일정 생성 검토", "저장")
            if decision == "confirm":
                break
            if decision == "cancel":
                print_info("회의실 점검 일정 생성을 취소했습니다.")
                pause()
                return
        try:
            from src.domain.daily_booking_rules import build_maintenance_period

            start_time, end_time = build_maintenance_period(start_date, end_date)
            schedule = self.room_service.create_maintenance_schedule(
                self.user, room_id, start_time, end_time, reason
            )
            print_success("회의실 점검 일정이 생성되었습니다.")
            print(f"  일정 ID: {schedule.id[:8]}...")
            print(f"  기간: {format_booking_time_range(schedule.start_time, schedule.end_time)}")
        except (RoomBookingError, RoomAdminRequiredError, AuthError, PenaltyError) as e:
            print_error(str(e))
        pause()

    def _cancel_room_maintenance(self, selected_room_id=None):
        print_header("회의실 점검 일정 취소")
        schedules = [
            schedule
            for schedule in self.room_service.maintenance_repo.get_all()
            if schedule.status in {"scheduled", "active"}
            and (selected_room_id is None or schedule.room_id == selected_room_id)
        ]
        if not schedules:
            print_info("취소 가능한 점검 일정이 없습니다.")
            pause()
            return
        items = []
        for schedule in schedules:
            room = self.room_service.get_room(schedule.room_id)
            room_name = room.name if room else "알 수 없음"
            items.append((schedule.id, f"{room_name} - {format_booking_time_range(schedule.start_time, schedule.end_time)}"))
        schedule_id = select_from_list(items, "취소할 점검 일정 선택")
        if not schedule_id:
            return
        while True:
            if not input_start_gate("회의실 점검 일정 취소 입력"):
                return
            reason = input("취소 사유 (선택, 20자 이하): ").strip()
            valid, error = validate_reason(reason)
            if not valid:
                print_error(error)
                pause()
                return
            self._print_review_rows([("일정 ID", schedule_id[:8]), ("취소 사유", reason or "-")])
            decision = review_action("회의실 점검 일정 취소 검토", "처리")
            if decision == "confirm":
                break
            if decision == "cancel":
                print_info("점검 일정 취소를 중단했습니다.")
                pause()
                return
        try:
            cancelled = self.room_service.cancel_maintenance_schedule(self.user, schedule_id, reason)
            print_success("회의실 점검 일정이 취소되었습니다.")
            print(f"  일정 ID: {cancelled.id[:8]}...")
        except (RoomBookingError, RoomAdminRequiredError, AuthError, PenaltyError) as e:
            print_error(str(e))
        pause()

    def _schedule_equipment_future_status(self):
        print_header("장비 미래 상태 예약")
        equipment_list = self.equipment_service.get_all_equipment()
        if not equipment_list:
            print_info("등록된 장비가 없습니다.")
            pause()
            return
        status_map = {
            "1": ResourceStatus.AVAILABLE,
            "2": ResourceStatus.MAINTENANCE,
            "3": ResourceStatus.DISABLED,
        }
        while True:
            if not input_start_gate("장비 미래 상태 예약 입력"):
                return
            equipment_id = select_from_list(
                [(item.id, f"{item.name} ({item.asset_type}, S/N: {item.serial_number})") for item in equipment_list],
                "상태 예약 장비 선택",
            )
            if not equipment_id:
                return
            print("\n예약할 상태:")
            print("  1. 사용가능 (available)")
            print("  2. 점검중 (maintenance)")
            print("  3. 사용불가 (disabled)")
            choice = input("\n선택: ").strip()
            if choice not in status_map:
                print_error("목록에 존재하는 번호를 입력해주세요.")
                pause()
                return
            self._print_daily_booking_guide()
            start_date, end_date = get_daily_date_range_input("상태 시작 날짜", "상태 종료 날짜")
            if start_date is None or end_date is None:
                return
            self._print_review_rows([("장비 ID", equipment_id[:8]), ("상태", status_map[choice].value), ("기간", f"{start_date} ~ {end_date}")])
            decision = review_action("장비 미래 상태 예약 검토", "저장")
            if decision == "confirm":
                break
            if decision == "cancel":
                print_info("장비 미래 상태 예약을 취소했습니다.")
                pause()
                return
        try:
            from src.domain.daily_booking_rules import build_daily_booking_period

            start_time, end_time = build_daily_booking_period(start_date, end_date)
            item = self.equipment_service.schedule_future_status_change(
                self.user, equipment_id, start_time, end_time, status_map[choice]
            )
            print_success("장비 미래 상태 예약이 생성되었습니다.")
            print(f"  예약 ID: {item['id'][:8]}...")
            print(f"  상태: {item['status']}")
            print(f"  기간: {format_booking_time_range(item['start_time'], item['end_time'])}")
        except (EquipmentBookingError, EquipmentAdminRequiredError, AuthError, PenaltyError) as e:
            print_error(str(e))
        pause()

    def _cancel_equipment_future_status(self):
        print_header("장비 미래 상태 예약 취소")
        equipment_list = self.equipment_service.get_all_equipment()
        items = []
        for equipment in equipment_list:
            for item in decode_future_status_changes(equipment.future_status_changes):
                if item["state"] in {"pending", "started"}:
                    items.append((f"{equipment.id}|{item['id']}", f"{equipment.name} - {item['status']} {format_booking_time_range(item['start_time'], item['end_time'])}"))
        if not items:
            print_info("취소 가능한 장비 미래 상태 예약이 없습니다.")
            pause()
            return
        selected = select_from_list(items, "취소할 장비 미래 상태 예약 선택")
        if not selected:
            return
        equipment_id, schedule_id = selected.split("|", 1)
        self._print_review_rows([("예약 ID", schedule_id[:8])])
        decision = review_action("장비 미래 상태 예약 취소 검토", "처리")
        if decision == "retry":
            return self._cancel_equipment_future_status()
        if decision == "cancel":
            print_info("장비 미래 상태 예약 취소를 중단했습니다.")
            pause()
            return
        try:
            cancelled = self.equipment_service.cancel_future_status_change(
                self.user, equipment_id, schedule_id
            )
            print_success("장비 미래 상태 예약이 취소되었습니다.")
            print(f"  예약 ID: {cancelled['id'][:8]}...")
        except (EquipmentBookingError, EquipmentAdminRequiredError, AuthError, PenaltyError) as e:
            print_error(str(e))
        pause()

    def _show_users(self):
        """사용자 목록"""
        print_header("사용자 목록")

        users = self._get_all_users_or_abort()
        if users is None:
            return
        if not users:
            print_info("등록된 사용자가 없습니다.")
            pause()
            return

        headers = ["ID", "사용자명", "역할", "패널티", "상태"]
        rows = []
        try:
            for user in users:
                status = self.penalty_service.get_user_status(user)
                state = (
                    "이용금지"
                    if status.get("is_banned")
                    else "제한중" if status.get("is_restricted") else "정상"
                )
                rows.append(
                    [
                        user.id[:8],
                        user.username,
                        format_status_badge(user.role.value),
                        f"{status['points']}점",
                        state,
                    ]
                )
        except (PenaltyError, RoomBookingError, EquipmentBookingError) as e:
            print_error(str(e))
            pause()
            return

        print(format_table(headers, rows))
        pause()

    def _show_user_detail(self):
        """사용자 상세 조회"""
        print_header("사용자 상세 조회")

        users = self._get_all_users_or_abort()
        if users is None:
            return
        if not users:
            print_info("등록된 사용자가 없습니다.")
            pause()
            return

        items = [
            (u.id, f"{u.username} {format_status_badge(u.role.value)}") for u in users
        ]
        user_id = select_from_list(items, "사용자 선택")
        if not user_id:
            return

        user = self._safe_get_user(user_id)
        if not user:
            print_error("사용자를 찾을 수 없습니다.")
            pause()
            return

        try:
            status = cast(dict[str, Any], self.penalty_service.get_user_status(user))

            print(f"\n사용자명: {user.username}")
            print(f"역할: {format_status_badge(user.role.value)}")
            print(f"가입일: {format_datetime(user.created_at)}")

            points = int(status["points"])
            is_banned = bool(status["is_banned"])
            is_restricted = bool(status["is_restricted"])

            print_subheader("패널티 상태")
            print(
                f"  상태: {format_penalty_status(points, is_banned, is_restricted)}"
            )
            print(f"  누적 점수: {points}점")
            print(f"  정상 이용 연속: {status.get('normal_use_streak', 0)}회")

            restriction_until = status.get("restriction_until")
            if restriction_until:
                print(f"  제한 해제일: {str(restriction_until)[:10]}")

            print_subheader("활성 예약")
            room_active = self.room_service.get_user_active_bookings(user.id)
            equip_active = self.equipment_service.get_user_active_bookings(user.id)

            print(f"  회의실: {len(room_active)}건")
            for b in room_active:
                room = self.room_service.get_room(b.room_id)
                print(
                    f"    - {room.name if room else '-'}: {format_booking_time_range(b.start_time, b.end_time)}"
                )

            print(f"  장비: {len(equip_active)}건")
            for b in equip_active:
                equip = self.equipment_service.get_equipment(b.equipment_id)
                print(
                    f"    - {equip.name if equip else '-'}: {format_booking_time_range(b.start_time, b.end_time)}"
                )

            print_subheader("패널티 이력")
            penalties = self.penalty_service.get_user_penalties(user.id)
            if not penalties:
                print("  패널티 이력이 없습니다.")
            else:
                penalties.sort(key=lambda p: p.created_at, reverse=True)
                for p in penalties[:10]:
                    print(
                        f"  - {format_datetime(p.created_at)}: {p.reason.value} (+{p.points}점) {p.memo}"
                    )
                if len(penalties) > 10:
                    print(f"    ... 외 {len(penalties) - 10}건")
        except (PenaltyError, RoomBookingError, EquipmentBookingError) as e:
            print_error(str(e))

        pause()

    def _apply_damage_penalty(self):
        """파손/오염 패널티 부여"""
        print_header("파손/오염 패널티 부여")

        users = [
            u for u in (self._get_all_users_or_abort() or []) if u.role == UserRole.USER
        ]
        if not users:
            print_info("일반 사용자가 없습니다.")
            pause()
            return

        items = [(u.id, u.username) for u in users]
        user_id = select_from_list(items, "사용자 선택")
        if not user_id:
            return

        user = self._safe_get_user(user_id)
        if not user:
            print_error("사용자를 찾을 수 없습니다.")
            pause()
            return

        print("\n예약 유형:")
        print("  1. 회의실 예약")
        print("  2. 장비 예약")
        print("  0. 돌아가기")

        type_choice = input("\n선택: ").strip()

        try:
            if type_choice == "1":
                bookings = self.room_service.get_user_bookings(user.id)
                booking_type = "room_booking"
            elif type_choice == "2":
                bookings = self.equipment_service.get_user_bookings(user.id)
                booking_type = "equipment_booking"
            elif type_choice == "0":
                return
            else:
                print_error("잘못된 선택입니다.")
                pause()
                return
        except (PenaltyError, RoomBookingError, EquipmentBookingError) as e:
            print_error(str(e))
            pause()
            return

        if not bookings:
            print_info("예약 내역이 없습니다.")
            pause()
            return

        items = [
            (
                b.id,
                f"{b.id[:8]} - {format_booking_time_range(b.start_time, b.end_time)} {format_status_badge(b.status.value)}",
            )
            for b in bookings[:20]
        ]
        booking_id = select_from_list(items, "관련 예약 선택")
        if not booking_id:
            return

        while True:
            if not input_start_gate("파손/오염 패널티 입력"):
                return
            while True:
                points_str = input("패널티 점수 (1~5): ").strip()
                valid, points, error = validate_positive_int(points_str, 1, 5)
                if valid and points is not None:
                    break
                print_error(error)

            memo = input("사유: ").strip()
            valid, error = validate_reason(memo)
            if not valid:
                print_error(error)
                pause()
                return
            if not memo:
                memo = "파손/오염"
            self._print_review_rows([("사용자", user.username), ("예약 ID", booking_id[:8]), ("패널티", f"{points}점"), ("사유", memo)])
            decision = review_action("파손/오염 패널티 부여 검토", "처리")
            if decision == "confirm":
                break
            if decision == "cancel":
                print_info("파손/오염 패널티 부여를 취소했습니다.")
                pause()
                return

        try:
            penalty = self.penalty_service.apply_damage(
                admin=self.user,
                user=user,
                booking_type=booking_type,
                booking_id=booking_id,
                points=points,
                memo=memo,
            )
            print_success(f"패널티가 부여되었습니다. (+{penalty.points}점)")

            updated_status = self.penalty_service.get_user_status(user)
            print_info(f"사용자 현재 누적: {updated_status['points']}점")

            if updated_status.get("is_banned"):
                print_warning("사용자가 이용 금지 상태가 되었습니다.")
            elif updated_status.get("is_restricted"):
                print_warning("사용자가 예약 제한 상태가 되었습니다.")
        except (PenaltyError, AdminRequiredError, AuthError) as e:
            print_error(str(e))

        pause()
