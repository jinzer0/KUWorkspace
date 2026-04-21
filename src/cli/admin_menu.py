"""
관리자 메뉴 - 회의실/장비 관리, 예약 관리, 사용자 관리
"""
from datetime import datetime
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
    LATE_CANCEL_THRESHOLD_MINUTES,
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
        except (RoomBookingError, RoomAdminRequiredError, AuthError) as e:
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

            print("\n[장비 관리]")
            print("  7. 전체 장비 예약 조회")
            print("  8. 장비 목록 조회 및 상태 변경")
            print("  9. 장비 대여 시작 처리")
            print("  10. 장비 반납 승인 처리")
            print("  11. 장비 예약 변경 (관리자)")
            print("  12. 장비 예약 취소 (관리자)")

            print("\n[사용자 관리]")
            print("  13. 사용자 목록")
            print("  14. 사용자 상세 조회")
            print("  15. 파손/오염 패널티 부여")
            print("  16. 회의실 퇴실 지연 처리")
            print("  17. 장비 반납 지연 처리")
            print("  18. 예약 직전 취소 패널티 부여")
            print("  19. 운영 시계")

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
                # 타겟 함수 변경함
                self._admin_modify_room_booking_time()
            elif choice == "6":
                self._admin_cancel_room_booking()
            elif choice == "7":
                self._show_all_equipment_bookings()
            elif choice == "8":
                self._show_equipment_and_change_status()
            elif choice == "9":
                self._equipment_checkout()
            elif choice == "10":
                self._equipment_return()
            elif choice == "11":
                self._admin_modify_equipment_booking_time()
            elif choice == "12":
                self._admin_cancel_equipment_booking()
            elif choice == "13":
                self._show_users()
            elif choice == "14":
                self._show_user_detail()
            elif choice == "15":
                self._apply_damage_penalty()
            elif choice == "16":
                self._apply_fixed_penalty("late_checkout")
            elif choice == "17":
                self._apply_fixed_penalty("late_return")
            elif choice == "18":
                self._apply_fixed_penalty("late_cancel")
            elif choice == "19":
                ClockMenu(
                    self.policy_service,
                    actor_id=self.user.id,
                    actor_role="admin",
                ).run()
            elif choice == "0":
                if confirm("로그아웃 하시겠습니까?"):
                    print_success("로그아웃 되었습니다.")
                    return True
            else:
                print_error("잘못된 선택입니다.")

    def _show_room_overview(self):
        """관리자 회의실 1번 : 전체 회의실 예약 조회"""
        print_header("회의실 목록")
        rooms =self.room_service.get_all_rooms()
        if not rooms: 
            print_info("등록된 회의실이 없습니다.")
            pause()
            return 
        bookings = self._get_room_bookings_or_abort()
        if bookings is None:
            return 

        current_time = self.policy_service.clock.now()
        rooms = sorted(rooms, key=lambda room:(room.capacity, room.name))
        header = (
            f"{'이름':<14}"
            f"{'수용인원':<10}"
            f"{'위치':<8}"
            f"{'현황':<10}"
            f"예약일"
        )
        print(header)
        print("-" * 70)

        for room in rooms:
            room_bookings = self._get_visible_room_bookings(room.id, bookings,
        current_time)
            room_status = self._get_room_overview_status(room_bookings,
        current_time)

            if not room_bookings:
                print(
                    f"{room.name:<14}"
                    f"{f'{room.capacity}명':<10}"
                    f"{room.location:<8}"
                    f"{room_status:<10}"
                    f"X"
                )
                continue

            booking_ranges = [
                self._format_booking_date_range(booking.start_time, booking.end_time)
                for booking in room_bookings
            ]

            print(
                f"{room.name:<14}"
                f"{f'{room.capacity}명':<10}"
                f"{room.location:<8}"
                f"{room_status:<10}"
                f"{booking_ranges[0]}"
            )

            for date_range in booking_ranges[1:]:
                print(f"{'':<42}{date_range}")

        pause()

    def _get_visible_room_bookings(self, room_id, bookings, current_time):
        """현재 시점 기준으로 의미 있는 유효 예약만 추리는 함수"""
        active_statuses = {
            RoomBookingStatus.RESERVED,
            RoomBookingStatus.CHECKIN_REQUESTED,
            RoomBookingStatus.CHECKED_IN,
            RoomBookingStatus.CHECKOUT_REQUESTED,
        }

        room_bookings = [
            booking
            for booking in bookings
            if booking.room_id == room_id
            and booking.status in active_statuses
            and datetime.fromisoformat(booking.end_time) >= current_time
        ]

        room_bookings.sort(key=lambda booking: booking.start_time)
        return room_bookings
    def _get_room_overview_status(self, room_bookings, current_time):
        """사용중 / 예약있음 / 예약없음 판정"""
        if not room_bookings:
            return "예약없음"

        for booking in room_bookings:
            start_time = datetime.fromisoformat(booking.start_time)
            end_time = datetime.fromisoformat(booking.end_time)

            if (
                booking.status in {
                  RoomBookingStatus.CHECKED_IN,
                  RoomBookingStatus.CHECKOUT_REQUESTED,
                }
                and start_time <= current_time <= end_time
            ):
                return "사용중"

        return "예약있음"

    def _format_booking_date_range(self, start_time, end_time):
        start_dt = datetime.fromisoformat(start_time)
        end_dt = datetime.fromisoformat(end_time)
        return f"{start_dt.strftime('%Y.%m.%d')} ~ {end_dt.strftime('%Y.%m.%d')}"

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

        print("\n변경할 상태:")
        print("  1. 사용가능 (available)")
        print("  2. 점검중 (maintenance)")

        choice = input("\n선택: ").strip()
        status_map = {
            "1": ResourceStatus.AVAILABLE,
            "2": ResourceStatus.MAINTENANCE,
        }

        if choice not in status_map:
            print_error("잘못된 선택입니다.")
            pause()
            return

        new_status = status_map[choice]
        current_time = self.policy_service.clock.now()
        if (new_status == ResourceStatus.MAINTENANCE and 
            (current_time.hour, current_time.minute) != (18, 0)):
            print_error(f"관리자가 회의실을 [점검중] 으로 변경할 수 있는 시점은 18:00 입니다.")
            pause()
            return

        if new_status == ResourceStatus.MAINTENANCE:
            print_warning("점검중으로 변경 시 미래 예약이 자동 취소됩니다.")
        if not confirm("정말로 수정하시겠습니까?"):
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
        self._show_room_overview()

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

        if not confirm("승인 처리하시겠습니까?"):
            return

        try:
            booking = self.room_service.check_in(self.user, booking_id)
            print_success("체크인 처리됐습니다.")
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

        if not confirm("퇴실 승인 처리하시겠습니까?"):
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
            if b.status == RoomBookingStatus.CANCELLED and self._is_late_cancelled_booking(b)
        ]
        equip_bookings = [
            b
            for b in (self.equipment_service.get_user_bookings(user.id) or [])
            if b.status == EquipmentBookingStatus.CANCELLED and self._is_late_cancelled_booking(b)
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

    def _is_late_cancelled_booking(self, booking):
        if not booking.cancelled_at:
            return False
        cancelled_at = datetime.fromisoformat(booking.cancelled_at)
        start_time = datetime.fromisoformat(booking.start_time)
        if cancelled_at >= start_time:
            return True
        return (start_time - cancelled_at).total_seconds() / 60 <= LATE_CANCEL_THRESHOLD_MINUTES


    def _admin_modify_or_swap_room_booking(self):
        # 이제 사용하지 않는 함수
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

        print_info("활성 회의실 예약 교체는 현재 서비스 계층에서 지원되지 않습니다.")

        pause()

    def _admin_modify_room_booking_time(self):
        """관리자 회의실 예약 시간 변경"""
        print_header("회의실 예약 변경 (관리자)")

        all_bookings = self._get_room_bookings_or_abort()
        if all_bookings is None:
            return
        now = self.policy_service.clock.now()
        modifiable = [
            b
            for b in all_bookings
            if b.status == RoomBookingStatus.RESERVED
            and datetime.fromisoformat(b.start_time) > now
        ]

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
                    f"{room.name if room else '-'} / {user.username} / {format_booking_time_range(booking.start_time, booking.end_time)}",
                )
            )

        booking_id = select_from_list(items, "취소할 예약 선택")
        if not booking_id:
            return

        selected_booking = next((b for b in cancellable if b.id == booking_id), None)
        if selected_booking is None:
            print_error("선택한 예약을 찾을 수 없습니다.")
            pause()
            return

        if datetime.fromisoformat(selected_booking.start_time).date() == self.policy_service.clock.now().date():
            print_error("당일 예약은 취소할 수 없습니다.")
            pause()
            return

        reason = input("취소 사유: ").strip()
        valid, error = validate_reason(reason)
        if not valid:
            print_error(error)
            pause()
            return

        if not confirm("정말 취소하시겠습니까?"):
            return

        try:
            self.room_service.admin_cancel_booking(self.user, booking_id, reason)
            print_success("예약이 취소되었습니다.")
        except (RoomBookingError, RoomAdminRequiredError, AuthError, PenaltyError) as e:
            print_error(str(e))

        pause()

    def _show_equipment(self):
        """장비 목록 조회"""
        print_header("장비 목록")

        equipment_list = self.equipment_service.get_all_equipment()
        if not equipment_list:
            print_info("등록된 장비가 없습니다.")
            pause()
            return None

        equipment_list.sort(key=lambda e: e.serial_number)

        status_label = {
            "available": "[사용가능]",
            "maintenance": "[점검중]",
            "disabled": "[사용불가]",
        }

        headers = ["번호", "이름", "종류", "시리얼번호", "상태"]
        rows = []
        for i, equip in enumerate(equipment_list, 1):
            label = status_label.get(equip.status.value, f"[{equip.status.value}]")
            rows.append([str(i), equip.name, equip.asset_type, equip.serial_number, label])

        print(format_table(headers, rows))
        return equipment_list

    def _change_equipment_status(self):
        """장비 상태 변경"""
        while True:
            equipment_list = self._show_equipment()
            if not equipment_list:
                return

            print("\n  0. 메뉴로 돌아가기")

            # 가. 장비 선택
            while True:
                raw = input("\n장비 선택 (번호): ").strip()
                if not raw.lstrip("-").isdigit():
                    print("  숫자를 입력해주세요.")
                    continue
                choice_int = int(raw)
                if choice_int == 0:
                    return
                if 1 <= choice_int <= len(equipment_list):
                    selected = equipment_list[choice_int - 1]
                    break
                print("  목록에 존재하는 번호를 입력해주세요.")

            # 나. 변경할 상태
            print("\n변경할 상태:")
            print("  1. 사용가능 (available)")
            print("  2. 점검중 (maintenance)")
            print("  0. 취소")

            status_map = {
                "1": ResourceStatus.AVAILABLE,
                "2": ResourceStatus.MAINTENANCE,
            }

            while True:
                raw2 = input("\n선택: ").strip()
                if not raw2.lstrip("-").isdigit():
                    print("  숫자를 입력해주세요.")
                    continue
                if raw2 == "0":
                    break
                if raw2 in status_map:
                    new_status = status_map[raw2]
                    status_name = "사용가능" if raw2 == "1" else "점검중"

                    current_time = self.policy_service.clock.now()
                    if (
                        new_status == ResourceStatus.MAINTENANCE
                        and (current_time.hour, current_time.minute) != (18, 0)
                    ):
                        print_error("관리자가 장비를 [점검중] 으로 변경할 수 있는 시점은 18:00 입니다.")
                        pause()
                        return

                    # 다. 확인
                    print(f"\n  선택: {raw2}")
                    while True:
                        yn = input("정말로 수정하시겠습니까? [y/n]: ").strip().lower()
                        if yn in ("y", "yes", "예", "ㅇ"):
                            try:
                                self.equipment_service.update_equipment_status(
                                    admin=self.user,
                                    equipment_id=selected.serial_number,
                                    new_status=new_status,
                                )
                                # 라. 완료
                                print(f"\n✓ 상태가 변경되었습니다: [{status_name}]")
                            except (EquipmentBookingError, EquipmentAdminRequiredError, AuthError, PenaltyError) as e:
                                print_error(str(e))
                            pause()
                            break
                        elif yn in ("n", "no", "아니오", "ㄴ"):
                            return
                        else:
                            print("  y 또는 n을 입력해주세요.")
                    break
                print("  목록에 존재하는 번호를 입력해주세요.")

    def _show_equipment_and_change_status(self):
        """장비 목록 조회 및 상태 변경"""
        self._change_equipment_status()

    def _show_all_equipment_bookings(self):
        """전체 장비 예약 조회"""
        print_header("최근 장비 예약")

        bookings = self._get_equipment_bookings_or_abort()
        if bookings is None:
            return

        now = self.policy_service.clock.now().isoformat()

        # 현재 사용중이거나 미래 예약만 필터링 (종료일이 현재 이후)
        active_bookings = [
            b for b in bookings
            if b.status in (
                EquipmentBookingStatus.RESERVED,
                EquipmentBookingStatus.PICKUP_REQUESTED,
                EquipmentBookingStatus.CHECKED_OUT,
                EquipmentBookingStatus.RETURN_REQUESTED,
            )
        ]

        if not active_bookings:
            print_info("예약 내역이 없습니다.")
            pause()
            return

        # 종료일 기준 내림차순 정렬
        active_bookings.sort(key=lambda b: b.end_time, reverse=True)

        # 상태 한글 매핑
        status_label = {
            EquipmentBookingStatus.CHECKED_OUT: "[사용중]",
            EquipmentBookingStatus.RETURN_REQUESTED: "[사용중]",
            EquipmentBookingStatus.PICKUP_REQUESTED: "[예약있음]",
            EquipmentBookingStatus.RESERVED: "[예약있음]",
        }

        headers = ["시리얼번호", "장비", "유저ID", "대여 기간", "상태"]
        rows = []
        for booking in active_bookings:
            equip = self.equipment_service.get_equipment(booking.equipment_id)
            user = self._get_booking_user_or_abort(booking.user_id)
            if user is None:
                return
            serial = equip.serial_number if equip else "-"
            name = equip.name if equip else "-"
            period = format_booking_time_range(booking.start_time, booking.end_time)
            status = status_label.get(booking.status, f"[{booking.status.value}]")
            rows.append([serial, name, user.username, period, status])

        print(format_table(headers, rows))
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
            print_info("대여 대기 중인 요청이 없습니다.")
            pause()
            return

        # 시리얼번호 오름차순 정렬
        pending.sort(
            key=lambda b: (
                equip.serial_number if (equip := self.equipment_service.get_equipment(b.equipment_id)) else ""
            )
        )

        print()
        items = []
        for i, booking in enumerate(pending, 1):
            equip = self.equipment_service.get_equipment(booking.equipment_id)
            user = self._get_booking_user_or_abort(booking.user_id)
            if user is None:
                return
            label = f"{equip.name if equip else '-'}({equip.serial_number if equip else '-'}) / {user.username} / {format_booking_time_range(booking.start_time, booking.end_time)}"
            print(f"  {i}. {label}")
            items.append((booking.id, label))
        print("  0. 취소")

        # 가. 대여 시작할 예약 선택
        while True:
            raw = input("\n대여 시작할 예약 선택 (번호): ").strip()
            if not raw.lstrip("-").isdigit():
                print("  숫자를 입력해주세요.")
                continue
            choice_int = int(raw)
            if choice_int == 0:
                return
            if 1 <= choice_int <= len(items):
                booking_id = items[choice_int - 1][0]
                break
            print("  목록에 존재하는 번호를 입력해주세요.")

        # 나. 최종 확인
        while True:
            yn = input("정말로 승인하시겠습니까? [y/n]: ").strip().lower()
            if yn in ("y", "yes", "예", "ㅇ"):
                try:
                    self.equipment_service.checkout(self.user, booking_id)
                    print_success("요청을 승인했습니다.")
                except (EquipmentBookingError, EquipmentAdminRequiredError, AuthError, PenaltyError) as e:
                    print_error(str(e))
                pause()
                return
            elif yn in ("n", "no", "아니오", "ㄴ"):
                return
            else:
                print("  y 또는 n을 입력해주세요.")

    def _equipment_return(self):
        """장비 반납 승인 처리"""
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
            print_info("반납 승인 대기 중인 요청이 없습니다.")
            pause()
            return

        # 시리얼번호 오름차순 정렬
        requested.sort(
            key=lambda b: (
                equip.serial_number if (equip := self.equipment_service.get_equipment(b.equipment_id)) else ""
            )
        )

        print()
        items = []
        for i, booking in enumerate(requested, 1):
            equip = self.equipment_service.get_equipment(booking.equipment_id)
            user = self._get_booking_user_or_abort(booking.user_id)
            if user is None:
                return
            label = f"{equip.name if equip else '-'}({equip.serial_number if equip else '-'}) / {user.username} / {format_booking_time_range(booking.start_time, booking.end_time)}"
            print(f"  {i}. {label}")
            items.append((booking.id, label))
        print("  0. 취소")

        # 가. 반납 승인할 요청 선택
        while True:
            raw = input("\n반납 승인할 요청 선택 (번호): ").strip()
            if not raw.lstrip("-").isdigit():
                print("  숫자를 입력해주세요.")
                continue
            choice_int = int(raw)
            if choice_int == 0:
                return
            if 1 <= choice_int <= len(items):
                booking_id = items[choice_int - 1][0]
                break
            print("  목록에 존재하는 번호를 입력해주세요.")

        # 나. 최종 확인
        while True:
            yn = input("정말로 승인하시겠습니까? [y/n]: ").strip().lower()
            if yn in ("y", "yes", "예", "ㅇ"):
                try:
                    self.equipment_service.approve_return_request(self.user, booking_id)
                    print_success("요청을 승인했습니다.")
                except (EquipmentBookingError, EquipmentAdminRequiredError, AuthError, PenaltyError) as e:
                    print_error(str(e))
                pause()
                return
            elif yn in ("n", "no", "아니오", "ㄴ"):
                return
            else:
                print("  y 또는 n을 입력해주세요.")

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
            if equip.serial_number == selected_booking.equipment_id:
                continue
            
            if equip.status != ResourceStatus.AVAILABLE:
                continue
            
            conflicts = self.equipment_service.booking_repo.get_conflicting(
                equip.serial_number,
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
                e.serial_number,
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

        new_equipment = next((e for e in eligible_equipment if e.serial_number == new_equipment_id), None)
        if new_equipment is None:
            print_error("선택한 장비를 찾을 수 없습니다.")
            pause()
            return

        print_warning(
            f"장비를 '{current_equipment.name if current_equipment else '-'}'에서 '{new_equipment.name}'으로 교체합니다."
        )
        if not confirm("교체하시겠습니까?"):
            return

        print_info("활성 장비 예약 교체는 현재 서비스 계층에서 지원되지 않습니다.")

        pause()

    def _admin_modify_equipment_booking_time(self):
        """관리자 장비 예약 변경"""
        print_header("장비 예약 변경 (관리자용)")

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

        # 대여 종료일 기준 내림차순 정렬
        modifiable.sort(key=lambda b: b.end_time, reverse=True)

        print()
        items = []
        for i, booking in enumerate(modifiable, 1):
            equip = self.equipment_service.get_equipment(booking.equipment_id)
            user = self._get_booking_user_or_abort(booking.user_id)
            if user is None:
                return
            label = f"{equip.name if equip else '-'}({equip.serial_number if equip else '-'}) / {user.username} / {format_booking_time_range(booking.start_time, booking.end_time)}"
            print(f"  {i}. {label}")
            items.append((booking.id, label))
        print("  0. 취소")

        # 가. 변경할 예약 선택
        while True:
            raw = input("\n변경할 예약 선택 (번호): ").strip()
            if not raw.lstrip("-").isdigit():
                print("  숫자를 입력해주세요.")
                continue
            choice_int = int(raw)
            if choice_int == 0:
                return
            if 1 <= choice_int <= len(items):
                booking_id = items[choice_int - 1][0]
                break
            print("  목록에 존재하는 번호를 입력해주세요.")

        # 나-1, 나-2. 날짜 입력
        from datetime import datetime, date as date_type
        while True:
            print(f"\n  이용 시간은 대여 시작일 {FIXED_BOOKING_START_HOUR:02d}:{FIXED_BOOKING_START_MINUTE:02d}부터 반납일 {FIXED_BOOKING_END_HOUR:02d}:{FIXED_BOOKING_END_MINUTE:02d}로 고정됩니다.")
            print("  예약 시작일은 기존 예약 시작일(시작일 포함) 기준으로부터 최대 180일 사이에서 선택할 수 있고, 예약 기간은 최대 14일 입니다.")

            start_str = input("  시작 날짜 (YYYY-MM-DD): ").strip()
            end_str = input("  종료 날짜 (YYYY-MM-DD): ").strip()

            # 날짜 형식 검증
            try:
                start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
            except ValueError:
                print(f"  ✗ {start_str} 날짜 형식이 올바르지 않습니다.")
                continue

            try:
                end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
            except ValueError:
                print(f"  ✗ {end_str} 날짜 형식이 올바르지 않습니다.")
                continue

            today = self.policy_service.clock.now().date()

            # 당일 혹은 과거 시작일 검증
            if start_date <= today:
                print(f"  ✗ {start_str} 예약 시작 날짜가 조건에 맞지 않습니다.")
                continue

            # 기간 14일 초과 검증
            if (end_date - start_date).days >= 14:
                print("  ✗ 예약 기간은 최대 14일까지 가능합니다.")
                continue

            # 나. 최종 확인
            print(f"\n  ✓ 예약이 {start_str} {FIXED_BOOKING_START_HOUR:02d}:{FIXED_BOOKING_START_MINUTE:02d} ~ {end_str} {FIXED_BOOKING_END_HOUR:02d}:{FIXED_BOOKING_END_MINUTE:02d} 로 변경됩니다.")

            while True:
                yn = input("정말로 변경하시겠습니까? [y/n]: ").strip().lower()
                if yn in ("y", "yes", "예", "ㅇ"):
                    try:
                        self.equipment_service.admin_modify_daily_booking(
                            admin=self.user,
                            booking_id=booking_id,
                            start_date=start_date,
                            end_date=end_date,
                        )
                        print_success("예약을 변경했습니다.")
                    except (EquipmentBookingError, EquipmentAdminRequiredError, AuthError, PenaltyError) as e:
                        print_error(str(e))
                    pause()
                    return
                elif yn in ("n", "no", "아니오", "ㄴ"):
                    return
                else:
                    print("  y 또는 n을 입력해주세요.")

    def _admin_cancel_equipment_booking(self):
        """관리자 장비 예약 취소"""
        print_header("장비 예약 취소 (관리자용)")

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

        # 대여 종료일 기준 내림차순 정렬
        cancellable.sort(key=lambda b: b.end_time, reverse=True)

        print()
        items = []
        for i, booking in enumerate(cancellable, 1):
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
        valid, error = validate_reason(reason)
        if not valid:
            print_error(error)
            pause()
            return

        # 가. 취소할 예약 선택
        while True:
            raw = input("\n취소할 예약 선택 (번호): ").strip()
            if not raw.lstrip("-").isdigit():
                print("  숫자를 입력해주세요.")
                continue
            choice_int = int(raw)
            if choice_int == 0:
                return
            if 1 <= choice_int <= len(items):
                booking_id = items[choice_int - 1][0]
                break
            print("  목록에 존재하는 번호를 입력해주세요.")

        # 나. 취소 사유 (최대 30자)
        while True:
            reason = input("\n취소 사유 (최대 30자): ").strip()
            if len(reason) > 30:
                print("  30자가 초과되었습니다. 30자 내로 입력해주세요.")
                continue
            break

        # 다. 최종 확인
        while True:
            yn = input("정말로 취소하시겠습니까? [y/n]: ").strip().lower()
            if yn in ("y", "yes", "예", "ㅇ"):
                try:
                    self.equipment_service.admin_cancel_booking(self.user, booking_id, reason)
                    print_success("예약을 취소했습니다.")
                except (EquipmentBookingError, EquipmentAdminRequiredError, AuthError, PenaltyError) as e:
                    print_error(str(e))
                pause()
                return
            elif yn in ("n", "no", "아니오", "ㄴ"):
                return
            else:
                print("  y 또는 n을 입력해주세요.")

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

        headers = ["사용자명", "역할", "패널티", "상태"]
        rows = []
        try:
            for user in users:
                status = self.penalty_service.get_user_status(user)
                state = (
                    "금지"
                    if status.get("is_banned")
                    else "제한" if status.get("is_restricted") else "정상"
                )
                rows.append(
                    [
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

            restriction_until = status.get("restriction_until")
            if isinstance(restriction_until, str) and restriction_until:
                print(f"  제한 해제일: {restriction_until[:10]}")

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
        valid, error = validate_reason(memo)
        if not valid:
            print_error(error)
            pause()
            return
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
        users = [u for u in users if u.role == UserRole.USER]
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

        try:
            if penalty_type == "late_checkout":
                bookings = self.room_service.get_user_bookings(user.id)
                booking_type = "room_booking"
                bookings = [
                    b
                    for b in bookings
                    if b.status
                    in {
                        RoomBookingStatus.CHECKED_IN,
                    }
                    and b.end_time == self.policy_service.clock.now().isoformat()
                ]
            elif penalty_type == "late_return":
                bookings = self.equipment_service.get_user_bookings(user.id)
                booking_type = "equipment_booking"
                bookings = [
                    b
                    for b in bookings
                    if b.status
                    in {
                        EquipmentBookingStatus.CHECKED_OUT,
                    }
                    and b.end_time == self.policy_service.clock.now().isoformat()
                ]
            else:
                print("\n예약 유형:")
                print("  1. 회의실 예약")
                print("  2. 장비 예약")
                type_choice = input("\n선택: ").strip()
                if type_choice == "1":
                    bookings = self.room_service.get_user_bookings(user.id)
                    booking_type = "room_booking"
                    bookings = [
                        b
                        for b in bookings
                        if b.status
                        in {
                            RoomBookingStatus.CANCELLED,
                        }
                        and self._is_late_cancelled_booking(b)
                    ]
                elif type_choice == "2":
                    bookings = self.equipment_service.get_user_bookings(user.id)
                    booking_type = "equipment_booking"
                    bookings = [
                        b
                        for b in bookings
                        if b.status
                        in {
                            EquipmentBookingStatus.CANCELLED,
                        }
                        and self._is_late_cancelled_booking(b)
                    ]
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

        booking_items = [
            (
                b.id,
                f"{b.id[:8]} - {format_booking_time_range(b.start_time, b.end_time)} {format_status_badge(b.status.value)}",
            )
            for b in bookings[:20]
        ]
        booking_id = select_from_list(booking_items, "관련 예약 선택")
        if not booking_id:
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
                memo=reason,
                booking_type=booking_type,
                booking_id=booking_id,
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
