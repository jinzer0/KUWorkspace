"""
관리자 메뉴 - 회의실/장비 관리, 예약 관리, 사용자 관리
"""

from src.domain.models import (
    RoomBookingStatus,
    EquipmentBookingStatus,
    ResourceStatus,
    UserRole,
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
from src.cli.menu import confirm, pause, select_from_list
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
            print("  1. 회의실 목록")
            print("  2. 회의실 상태 변경")
            print("  3. 전체 회의실 예약 조회")
            print("  4. 회의실 체크인 처리")
            print("  5. 회의실 퇴실 승인 처리")
            print("  6. 회의실 예약 변경/교체 (관리자)")
            print("  7. 회의실 예약 취소 (관리자)")

            print("\n[장비 관리]")
            print("  8. 장비 목록")
            print("  9. 장비 상태 변경")
            print("  10. 전체 장비 예약 조회")
            print("  11. 장비 대여 시작 처리")
            print("  12. 장비 반납 승인 처리")
            print("  13. 장비 예약 변경/교체 (관리자)")
            print("  14. 장비 예약 취소 (관리자)")

            print("\n[사용자 관리]")
            print("  15. 사용자 목록")
            print("  16. 사용자 상세 조회")
            print("  17. 파손/오염 패널티 부여")
            print("  18. 예약 직전 취소 패널티 부여")
            print("  19. 회의실 퇴실 지연 처리")
            print("  20. 장비 반납 지연 처리")
            print("  21. 운영 시계")

            print("\n  0. 로그아웃")
            print("-" * 50)

            choice = input("선택: ").strip()

            if choice == "1":
                self._show_rooms()
            elif choice == "2":
                self._change_room_status()
            elif choice == "3":
                self._show_all_room_bookings()
            elif choice == "4":
                self._room_checkin()
            elif choice == "5":
                self._room_checkout()
            elif choice == "6":
                self._admin_modify_or_swap_room_booking()
            elif choice == "7":
                self._admin_cancel_room_booking()
            elif choice == "8":
                self._show_equipment()
            elif choice == "9":
                self._change_equipment_status()
            elif choice == "10":
                self._show_all_equipment_bookings()
            elif choice == "11":
                self._equipment_checkout()
            elif choice == "12":
                self._equipment_return()
            elif choice == "13":
                self._admin_modify_or_swap_equipment_booking()
            elif choice == "14":
                self._admin_cancel_equipment_booking()
            elif choice == "15":
                self._show_users()
            elif choice == "16":
                self._show_user_detail()
            elif choice == "17":
                self._apply_damage_penalty()
            elif choice == "18":
                self._apply_fixed_penalty("late_checkout")
            elif choice == "19":
                self._apply_fixed_penalty("late_return")
            elif choice == "20":
                self._apply_fixed_penalty("late_cancel")
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

    def _change_room_status(self):
        """회의실 상태 변경"""
        print_header("회의실 상태 변경")

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
            if not confirm("계속하시겠습니까?"):
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
        print_header("전체 회의실 예약")

        bookings = self._get_room_bookings_or_abort()
        if bookings is None:
            return
        if not bookings:
            print_info("예약 내역이 없습니다.")
            pause()
            return

        bookings.sort(key=lambda b: b.start_time, reverse=True)

        headers = ["ID", "회의실", "사용자", "시간", "상태"]
        rows = []
        for booking in bookings[:30]:
            room = self.room_service.get_room(booking.room_id)
            user = self._get_booking_user_or_abort(booking.user_id)
            if user is None:
                return
            rows.append(
                [
                    booking.id[:8],
                    room.name if room else "-",
                    user.username,
                    format_booking_time_range(booking.start_time, booking.end_time),
                    format_status_badge(booking.status.value),
                ]
            )

        print(format_table(headers, rows))

        if len(bookings) > 30:
            print(f"\n  ... 외 {len(bookings) - 30}건")

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
        if not confirm(f"{user.username}에게 직전 취소 패널티 2점을 부여하시겠습니까?"):
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

    def _admin_modify_or_swap_room_booking(self):
        """관리자 회의실 예약 변경/교체 - 서브메뉴"""
        print_header("회의실 예약 변경/교체 (관리자)")
        
        print("\n선택 사항:")
        print("  1. 예약 시간 변경")
        print("  2. 진행중 예약 회의실 교체")
        print("  0. 취소")
        print("-" * 50)
        
        choice = input("선택: ").strip()
        
        if choice == "1":
            self._admin_modify_room_booking_time()
        elif choice == "2":
            self._admin_reassign_active_room_booking()
        elif choice == "0":
            return
        else:
            print_error("잘못된 선택입니다.")
            pause()

    def _admin_reassign_active_room_booking(self):
        """관리자 진행중 회의실 예약 교체"""
        print_header("진행중 회의실 예약 교체 (관리자)")

        all_bookings = self._get_room_bookings_or_abort()
        if all_bookings is None:
            return
        
        checked_in_bookings = [
            b for b in all_bookings if b.status == RoomBookingStatus.CHECKED_IN
        ]

        if not checked_in_bookings:
            print_info("진행중인 회의실 예약이 없습니다.")
            pause()
            return

        items = []
        for booking in checked_in_bookings:
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

        booking_id = select_from_list(items, "교체할 예약 선택")
        if not booking_id:
            return

        selected_booking = next(
            (b for b in checked_in_bookings if b.id == booking_id), None
        )
        if selected_booking is None:
            print_error("선택한 예약을 찾을 수 없습니다.")
            pause()
            return

        current_room = self.room_service.get_room(selected_booking.room_id)
        booking_user = self._get_booking_user_or_abort(selected_booking.user_id)
        if booking_user is None:
            return

        print_subheader("예약 정보")
        print(f"  현재 회의실: {current_room.name if current_room else '-'}")
        print(f"  사용자: {booking_user.username}")
        print(
            f"  기간: {format_booking_time_range(selected_booking.start_time, selected_booking.end_time)}"
        )

        all_rooms = self.room_service.get_all_rooms()
        eligible_rooms = []
        
        for room in all_rooms:
            if room.id == selected_booking.room_id:
                continue
            
            if room.status != ResourceStatus.AVAILABLE:
                continue
            
            conflicts = self.room_service.booking_repo.get_conflicting(
                room.id,
                selected_booking.start_time,
                selected_booking.end_time,
                exclude_id=booking_id,
            )
            if not conflicts:
                eligible_rooms.append(room)

        if not eligible_rooms:
            print_info("교체 가능한 회의실이 없습니다.")
            pause()
            return

        room_items = [
            (
                r.id,
                f"{r.name} (수용인원: {r.capacity}명, 위치: {r.location})",
            )
            for r in eligible_rooms
        ]
        new_room_id = select_from_list(room_items, "새 회의실 선택")
        if not new_room_id:
            return

        reason = input("교체 사유: ").strip()
        if not reason:
            print_error("사유를 입력해야 합니다.")
            pause()
            return

        new_room = next((r for r in eligible_rooms if r.id == new_room_id), None)
        if new_room is None:
            print_error("선택한 회의실을 찾을 수 없습니다.")
            pause()
            return

        print_warning(
            f"회의실을 '{current_room.name if current_room else '-'}'에서 '{new_room.name}'으로 교체합니다."
        )
        if not confirm("교체하시겠습니까?"):
            return

        try:
            updated_booking = self.room_service.admin_reassign_active_booking(
                admin=self.user,
                booking_id=booking_id,
                new_room_id=new_room_id,
                reason=reason,
            )
            print_success(
                f"회의실이 교체되었습니다: {current_room.name if current_room else '-'} → {new_room.name}"
            )
        except (RoomBookingError, RoomAdminRequiredError, AuthError, PenaltyError) as e:
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

        booking_id = select_from_list(items, "변경할 예약 선택")
        if not booking_id:
            return

        self._print_daily_booking_guide()
        start_date, end_date = get_daily_date_range_input("시작 날짜", "종료 날짜")
        if start_date is None or end_date is None:
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

        reason = input("취소 사유: ").strip()

        if not confirm("정말 취소하시겠습니까?"):
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

    def _change_equipment_status(self):
        """장비 상태 변경"""
        print_header("장비 상태 변경")

        equipment_list = self.equipment_service.get_all_equipment()
        if not equipment_list:
            print_info("등록된 장비가 없습니다.")
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
            if not confirm("계속하시겠습니까?"):
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

    def _admin_modify_or_swap_equipment_booking(self):
        """관리자 장비 예약 변경/교체 - 서브메뉴"""
        print_header("장비 예약 변경/교체 (관리자)")
        
        print("\n선택 사항:")
        print("  1. 예약 시간 변경")
        print("  2. 진행중 예약 장비 교체")
        print("  0. 취소")
        print("-" * 50)
        
        choice = input("선택: ").strip()
        
        if choice == "1":
            self._admin_modify_equipment_booking_time()
        elif choice == "2":
            self._admin_reassign_active_equipment_booking()
        elif choice == "0":
            return
        else:
            print_error("잘못된 선택입니다.")
            pause()

    def _admin_reassign_active_equipment_booking(self):
        """관리자 진행중 장비 예약 교체"""
        print_header("진행중 장비 예약 교체 (관리자)")

        all_bookings = self._get_equipment_bookings_or_abort()
        if all_bookings is None:
            return
        
        checked_out_bookings = [
            b for b in all_bookings if b.status == EquipmentBookingStatus.CHECKED_OUT
        ]

        if not checked_out_bookings:
            print_info("진행중인 장비 예약이 없습니다.")
            pause()
            return

        items = []
        for booking in checked_out_bookings:
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

        booking_id = select_from_list(items, "교체할 예약 선택")
        if not booking_id:
            return

        selected_booking = next(
            (b for b in checked_out_bookings if b.id == booking_id), None
        )
        if selected_booking is None:
            print_error("선택한 예약을 찾을 수 없습니다.")
            pause()
            return

        current_equipment = self.equipment_service.get_equipment(selected_booking.equipment_id)
        booking_user = self._get_booking_user_or_abort(selected_booking.user_id)
        if booking_user is None:
            return

        print_subheader("예약 정보")
        print(f"  현재 장비: {current_equipment.name if current_equipment else '-'}")
        print(f"  사용자: {booking_user.username}")
        print(
            f"  기간: {format_booking_time_range(selected_booking.start_time, selected_booking.end_time)}"
        )

        all_equipment = self.equipment_service.get_all_equipment()
        eligible_equipment = []
        
        for equip in all_equipment:
            if equip.id == selected_booking.equipment_id:
                continue
            
            if equip.status != ResourceStatus.AVAILABLE:
                continue
            
            conflicts = self.equipment_service.booking_repo.get_conflicting(
                equip.id,
                selected_booking.start_time,
                selected_booking.end_time,
                exclude_id=booking_id,
            )
            if not conflicts:
                eligible_equipment.append(equip)

        if not eligible_equipment:
            print_info("교체 가능한 장비가 없습니다.")
            pause()
            return

        equipment_items = [
            (
                e.id,
                f"{e.name} (종류: {e.asset_type}, 시리얼: {e.serial_number})",
            )
            for e in eligible_equipment
        ]
        new_equipment_id = select_from_list(equipment_items, "새 장비 선택")
        if not new_equipment_id:
            return

        reason = input("교체 사유: ").strip()
        if not reason:
            print_error("사유를 입력해야 합니다.")
            pause()
            return

        new_equipment = next((e for e in eligible_equipment if e.id == new_equipment_id), None)
        if new_equipment is None:
            print_error("선택한 장비를 찾을 수 없습니다.")
            pause()
            return

        print_warning(
            f"장비를 '{current_equipment.name if current_equipment else '-'}'에서 '{new_equipment.name}'으로 교체합니다."
        )
        if not confirm("교체하시겠습니까?"):
            return

        try:
            updated_booking = self.equipment_service.admin_reassign_active_booking(
                admin=self.user,
                booking_id=booking_id,
                new_equipment_id=new_equipment_id,
                reason=reason,
            )
            print_success(
                f"장비가 교체되었습니다: {current_equipment.name if current_equipment else '-'} → {new_equipment.name}"
            )
        except (EquipmentBookingError, EquipmentAdminRequiredError, AuthError, PenaltyError) as e:
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

        booking_id = select_from_list(items, "변경할 예약 선택")
        if not booking_id:
            return

        self._print_daily_booking_guide()
        start_date, end_date = get_daily_date_range_input("시작 날짜", "종료 날짜")
        if start_date is None or end_date is None:
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

        reason = input("취소 사유: ").strip()

        if not confirm("정말 취소하시겠습니까?"):
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
            status = self.penalty_service.get_user_status(user)

            print(f"\n사용자명: {user.username}")
            print(f"역할: {format_status_badge(user.role.value)}")
            print(f"가입일: {format_datetime(user.created_at)}")

            print_subheader("패널티 상태")
            print(
                f"  상태: {format_penalty_status(status['points'], status['is_banned'], status['is_restricted'])}"
            )
            print(f"  누적 점수: {status['points']}점")
            print(f"  정상 이용 연속: {status.get('normal_use_streak', 0)}회")

            if status.get("restriction_until"):
                print(f"  제한 해제일: {status['restriction_until'][:10]}")

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

        type_choice = input("\n선택: ").strip()

        try:
            if type_choice == "1":
                bookings = self.room_service.get_user_bookings(user.id)
                booking_type = "room_booking"
            elif type_choice == "2":
                bookings = self.equipment_service.get_user_bookings(user.id)
                booking_type = "equipment_booking"
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
            points_str = input("패널티 점수 (1~5): ").strip()
            valid, points, error = validate_positive_int(points_str, 1, 5)
            if valid and points is not None:
                break
            print_error(error)

        memo = input("사유: ").strip()
        if not memo:
            memo = "파손/오염"

        if not confirm(f"{user.username}에게 {points}점 패널티를 부여하시겠습니까?"):
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

    def _apply_fixed_penalty(self, penalty_type):
        type_info = {
            "late_checkout": "회의실 퇴실 지연",
            "late_return": "장비 반납 지연",
            "late_cancel": "직전 취소"
        }
        title = type_info.get(penalty_type, "패널티")
        print_header(f"{title} 패널티 부여")
        users = self.auth_service.get_all_users(self.user)
        users = [u for u in users if u.username != "admin"]
        if not users:
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

        penalty_points = 2
        print_info(f"\n{title} 규정에 따라 고정 패널티 {penalty_points}점이 배정됩니다.")
        
        reason = input("사유 입력: ").strip()
        if not reason:
            reason = f"관리자 수동 부과 ({title})"

        if not confirm(f"{user.username}에게 {penalty_points}점 패널티를 부여하시겠습니까?"):
            print_info("패널티 부여를 철회합니다.")
            return

        try:
            penalty = self.penalty_service.apply_fixed_penalty(
                admin=self.user,
                user=user,
                penalty_type=penalty_type,
                points=penalty_points,
                memo=reason
            )
            print_success(f"✓ 패널티가 부여되었습니다. (+{penalty.points}점)")

            status = self.penalty_service.get_user_status(user)
            print_info(f"i 사용자 현재 누적 : {status['points']}점")

            if status.get("is_banned"):
                print_warning("⚠️ 사용자가 이용 금지 상태가 되었습니다.")
            elif status.get("is_restricted"):
                print_warning("⚠️ 사용자가 예약 제한 상태가 되었습니다.")
                
        except (PenaltyError, AdminRequiredError, AuthError) as e:
            print_error(str(e))

        pause()
