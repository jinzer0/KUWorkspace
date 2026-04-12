"""
일반 사용자 메뉴 - 회의실/장비 예약, 조회, 취소
"""

from datetime import datetime
from src.domain.models import (
    RoomBookingStatus,
    EquipmentBookingStatus,
    ResourceStatus,
)
from src.domain.auth_service import AuthService, AuthError
from src.domain.room_service import RoomService, RoomBookingError
from src.domain.equipment_service import EquipmentService, EquipmentBookingError
from src.domain.penalty_service import PenaltyService, PenaltyError
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
from src.runtime_clock import get_current_time
from src.cli.validators import get_daily_date_range_input, get_positive_int_input


class UserMenu:
    """일반 사용자 메뉴"""

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

    def _run_policy_checks(self):
        try:
            self.policy_service.run_all_checks()
            return True
        except PenaltyError as e:
            print_error(str(e))
            pause()
            return False

    def _handle_user_query_error(self, error):
        print_error(str(error))
        pause()

    def _print_daily_booking_guide(self):
        print(
            f"  이용 시간은 매일 {FIXED_BOOKING_START_HOUR:02d}:{FIXED_BOOKING_START_MINUTE:02d} ~ {FIXED_BOOKING_END_HOUR:02d}:{FIXED_BOOKING_END_MINUTE:02d}로 고정됩니다."
        )
        print("  예약 시작일은 내일부터 선택할 수 있고, 오늘로부터 최대 180일까지 가능합니다.")
        print("  예약 기간은 1일 이상 14일 이하입니다.")

    def run(self):
        """
        사용자 메뉴 실행

        Returns:
            로그아웃 여부 (True면 로그아웃)
        """
        while True:
            if not self._run_policy_checks():
                return True
            if not self._refresh_user():
                return True

            print_header(f"사용자 메뉴 ({self.user.username})")

            try:
                status = self.penalty_service.get_user_status(self.user)
            except PenaltyError as e:
                self._handle_user_query_error(e)
                return True
            if status.get("is_banned"):
                print_warning(
                    f"이용이 금지된 상태입니다. (해제일: {status.get('restriction_until', '-')[:10]})"
                )
            elif status.get("is_restricted"):
                print_warning(f"패널티로 인해 활성 예약 1건만 허용됩니다.")

            print("\n[회의실]")
            print("  1. 회의실 목록 조회")
            print("  2. 회의실 예약하기")
            print("  3. 내 회의실 예약 조회")
            print("  4. 회의실 예약 변경")
            print("  5. 회의실 예약 취소")
            print("  6. 회의실 체크인 요청")
            print("  7. 회의실 퇴실 신청")

            print("\n[장비]")
            print("  8. 장비 목록 조회")
            print("  9. 장비 예약하기")
            print("  10. 내 장비 예약 조회")
            print("  11. 장비 예약 변경")
            print("  12. 장비 예약 취소")
            print("  13. 장비 픽업 요청")
            print("  14. 장비 반납 신청")

            print("\n[내 정보]")
            print("  15. 내 상태 조회")
            print("  16. 운영 시계")

            print("\n  0. 로그아웃")
            print("-" * 50)

            choice = input("선택: ").strip()

            if choice == "1":
                self._show_rooms()
            elif choice == "2":
                self._create_room_booking()
            elif choice == "3":
                self._show_my_room_bookings()
            elif choice == "4":
                self._modify_room_booking()
            elif choice == "5":
                self._cancel_room_booking()
            elif choice == "6":
                self._request_room_checkin()
            elif choice == "7":
                self._request_room_checkout()
            elif choice == "8":
                self._show_equipment()
            elif choice == "9":
                self._create_equipment_booking()
            elif choice == "10":
                self._show_my_equipment_bookings()
            elif choice == "11":
                self._modify_equipment_booking()
            elif choice == "12":
                self._cancel_equipment_booking()
            elif choice == "13":
                self._request_equipment_pickup()
            elif choice == "14":
                self._request_equipment_return()
            elif choice == "15":
                self._show_my_status()
            elif choice == "16":
                ClockMenu(self.policy_service, actor_id=self.user.id).run()
            elif choice == "0":
                if confirm("로그아웃 하시겠습니까?"):
                    print_success("로그아웃 되었습니다.")
                    return True
            else:
                print_error("잘못된 선택입니다.")

    def _refresh_user(self):
        """최신 사용자 정보로 갱신"""
        try:
            self.user = self.auth_service.get_user(self.user.id)
            return True
        except AuthError as e:
            print_error(str(e))
            pause()
            return False

    def _show_rooms(self):
        """회의실 목록 조회"""
        print_header("회의실 목록")

        rooms = self.room_service.get_all_rooms()
        if not rooms:
            print_info("등록된 회의실이 없습니다.")
            pause()
            return

        headers = ["이름", "수용인원", "위치", "상태"]
        rows = []
        for room in rooms:
            status_text = format_status_badge(room.status.value)
            if room.status != ResourceStatus.AVAILABLE:
                status_text += " 예약 불가"
            rows.append(
                [
                    room.name,
                    f"{room.capacity}명",
                    room.location,
                    status_text,
                ]
            )

        print(format_table(headers, rows))
        pause()

    def _create_room_booking(self):
        """회의실 예약 생성"""
        print_header("회의실 예약하기")

        # 예약 작업 전 정책 점검 (no-show, 제한 상태 확인)
        if not self._run_policy_checks():
            return
        if not self._refresh_user():
            return

        try:
            can_book, max_active, message = self.policy_service.check_user_can_book(
                self.user
            )
        except (PenaltyError, RoomBookingError, EquipmentBookingError) as e:
            self._handle_user_query_error(e)
            return
        if not can_book:
            print_error(message)
            pause()
            return

        if message:
            print_warning(message)

        self._print_daily_booking_guide()
        attendee_count = get_positive_int_input("이용 인원", 1, 8, min_error_msg="1 이상의 인원을 입력해주세요.", max_error_msg="수용 가능한 최대 인원은 8명입니다.")
        if attendee_count is None:
            return

        start_date, end_date = get_daily_date_range_input("시작 날짜", "종료 날짜")
        if start_date is None or end_date is None:
            return

        from src.domain.daily_booking_rules import build_daily_booking_period

        start_time, end_time = build_daily_booking_period(start_date, end_date)
        rooms = self.room_service.get_available_rooms_for_attendees(
            attendee_count, start_time, end_time
        )
        if not rooms:
            print_info("해당 인원과 기간에 예약 가능한 회의실이 없습니다.")
            pause()
            return

        items = [(r.id, f"{r.name} ({r.capacity}명, {r.location})") for r in rooms]
        while True:
            room_id = select_from_list(items, "회의실 선택")
            if not room_id:
                return

            selected_room = next((r for r in rooms if r.id == room_id), None)
            if selected_room and any(r.capacity < selected_room.capacity for r in rooms):
                print_warning("더 작은 회의실이 예약 가능합니다. 해당 회의실을 먼저 이용해주세요.")
                continue
            break

        try:
            limits = self.policy_service.get_user_flow_limits(self.user)
            if limits["room_limit"] <= 0:
                raise RoomBookingError("이미 활성 회의실 예약이 있습니다.")
            booking = self.room_service.create_daily_booking(
                user=self.user,
                room_id=room_id,
                start_date=start_date,
                end_date=end_date,
                attendee_count=attendee_count,
                max_active=limits["room_limit"],
            )
            print_success("예약이 완료되었습니다.")
            print(f"  예약 ID: {booking.id[:8]}...")
            print(
                f"  시간: {format_booking_time_range(booking.start_time, booking.end_time)}"
            )
        except RoomBookingError:
            print_error("선택한 회의실을 예약할 수 없습니다. 다시 시도해주세요.")
        except PenaltyError as e:
            print_error(str(e))

        pause()

    def _show_my_room_bookings(self):
        """내 회의실 예약 조회"""
        print_header("내 회의실 예약")

        if not self._refresh_user():
            return

        try:
            bookings = self.room_service.get_user_bookings(self.user.id)
        except (PenaltyError, RoomBookingError, EquipmentBookingError) as e:
            self._handle_user_query_error(e)
            return
        if not bookings:
            print_info("예약 내역이 없습니다.")
            pause()
            return

        bookings.sort(key=lambda b: b.start_time, reverse=True)

        headers = ["ID", "회의실", "시간", "상태"]
        rows = []
        for booking in bookings[:20]:
            room = self.room_service.get_room(booking.room_id)
            room_name = room.name if room else "알 수 없음"
            rows.append(
                [
                    booking.id[:8],
                    room_name,
                    format_booking_time_range(booking.start_time, booking.end_time),
                    format_status_badge(booking.status.value),
                ]
            )

        print(format_table(headers, rows))

        if len(bookings) > 20:
            print(f"\n  ... 외 {len(bookings) - 20}건")

        pause()

    def _modify_room_booking(self):
        """회의실 예약 변경"""
        print_header("회의실 예약 변경")

        # 예약 작업 전 정책 점검 (no-show, 제한 상태 확인)
        if not self._run_policy_checks():
            return
        if not self._refresh_user():
            return

        try:
            active_bookings = [
                b
                for b in self.room_service.get_user_bookings(self.user.id)
                if b.status == RoomBookingStatus.RESERVED
            ]
        except (PenaltyError, RoomBookingError, EquipmentBookingError) as e:
            self._handle_user_query_error(e)
            return

        if not active_bookings:
            print_info("변경 가능한 예약이 없습니다. (예약 대기 상태만 변경 가능)")
            pause()
            return

        items = []
        for booking in active_bookings:
            room = self.room_service.get_room(booking.room_id)
            room_name = room.name if room else "알 수 없음"
            items.append(
                (
                    booking.id,
                    f"{room_name} - {format_booking_time_range(booking.start_time, booking.end_time)}",
                )
            )

        booking_id = select_from_list(items, "변경할 예약 선택")
        if not booking_id:
            return

        selected = next((b for b in active_bookings if b.id == booking_id), None)

        self._print_daily_booking_guide()
        while True:
            start_date, end_date = get_daily_date_range_input("시작 날짜", "종료 날짜")
            if start_date is None or end_date is None:
                return

            from src.domain.daily_booking_rules import build_daily_booking_period
            new_start, new_end = build_daily_booking_period(start_date, end_date)

            if selected:
                existing_start = datetime.fromisoformat(selected.start_time)
                existing_end = datetime.fromisoformat(selected.end_time)
                if new_start == existing_start and new_end == existing_end:
                    print_error("변경된 내용이 없습니다. 다른 날짜를 입력해주세요.")
                    continue

            if not confirm("정말 변경하시겠습니까?"):
                return
            break

        try:
            booking = self.room_service.modify_daily_booking(
                user=self.user,
                booking_id=booking_id,
                start_date=start_date,
                end_date=end_date,
            )
            print_success("예약이 변경되었습니다.")
            print(
                f"  새 시간: {format_booking_time_range(booking.start_time, booking.end_time)}"
            )
        except (RoomBookingError, PenaltyError) as e:
            print_error(str(e))

        pause()

    def _request_room_checkin(self):
        print_header("회의실 체크인 요청")

        if not self._refresh_user():
            return

        try:
            requestable = [
                b
                for b in self.room_service.get_user_bookings(self.user.id)
                if b.status == RoomBookingStatus.RESERVED
            ]
        except (PenaltyError, RoomBookingError, EquipmentBookingError) as e:
            self._handle_user_query_error(e)
            return

        if not requestable:
            print_info("체크인 요청 가능한 회의실 예약이 없습니다.")
            pause()
            return

        items = []
        for booking in requestable:
            room = self.room_service.get_room(booking.room_id)
            items.append(
                (
                    booking.id,
                    f"{room.name if room else '-'} - {format_booking_time_range(booking.start_time, booking.end_time)}",
                )
            )

        booking_id = select_from_list(items, "체크인 요청할 예약 선택")
        if not booking_id:
            return

        if not confirm("체크인 요청하시겠습니까?"):
            return

        try:
            self.room_service.request_check_in(self.user, booking_id)
            print_success("체크인 요청이 접수되었습니다. 관리자 승인 대기 상태입니다.")
        except (PenaltyError, RoomBookingError) as e:
            print_error(str(e))

        pause()

    def _request_room_checkout(self):
        print_header("회의실 퇴실 신청")

        if not self._refresh_user():
            return

        try:
            requestable = [
                b
                for b in self.room_service.get_user_bookings(self.user.id)
                if b.status == RoomBookingStatus.CHECKED_IN
            ]
        except (PenaltyError, RoomBookingError, EquipmentBookingError) as e:
            self._handle_user_query_error(e)
            return

        if not requestable:
            print_info("퇴실 신청 가능한 회의실 예약이 없습니다.")
            pause()
            return

        items = []
        for booking in requestable:
            room = self.room_service.get_room(booking.room_id)
            items.append(
                (
                    booking.id,
                    f"{room.name if room else '-'} - {format_booking_time_range(booking.start_time, booking.end_time)}",
                )
            )

        booking_id = select_from_list(items, "퇴실 신청할 예약 선택")
        if not booking_id:
            return

        if not confirm("퇴실 신청하시겠습니까?"):
            return

        try:
            self.room_service.request_checkout(self.user, booking_id)
            print_success("퇴실 신청이 접수되었습니다. 관리자 승인 대기 상태입니다.")
        except (PenaltyError, RoomBookingError) as e:
            print_error(str(e))

        pause()

    def _cancel_room_booking(self):
        """회의실 예약 취소"""
        print_header("회의실 예약 취소")

        # 예약 작업 전 정책 점검 (no-show, 제한 상태 확인)
        if not self._run_policy_checks():
            return
        if not self._refresh_user():
            return

        try:
            active_bookings = [
                b
                for b in self.room_service.get_user_bookings(self.user.id)
                if b.status == RoomBookingStatus.RESERVED
            ]
        except (PenaltyError, RoomBookingError, EquipmentBookingError) as e:
            self._handle_user_query_error(e)
            return

        if not active_bookings:
            print_info("취소 가능한 예약이 없습니다.")
            pause()
            return

        items = []
        for booking in active_bookings:
            room = self.room_service.get_room(booking.room_id)
            room_name = room.name if room else "알 수 없음"
            items.append(
                (
                    booking.id,
                    f"{room_name} - {format_booking_time_range(booking.start_time, booking.end_time)}",
                )
            )

        booking_id = select_from_list(items, "취소할 예약 선택")
        if not booking_id:
            return

        selected = next((b for b in active_bookings if b.id == booking_id), None)
        is_late_cancel = selected and datetime.fromisoformat(selected.start_time) <= get_current_time()

        if is_late_cancel:
            print_warning("직전 취소로 인해 패널티 2점이 부과됩니다.")
            if not confirm("그래도 취소하시겠습니까?"):
                return
        else:
            if not confirm("정말 취소하시겠습니까?"):
                return

        try:
            booking, _ = self.room_service.cancel_booking(self.user, booking_id)
            print_success("예약이 취소되었습니다.")
        except (RoomBookingError, PenaltyError) as e:
            print_error(str(e))

        pause()

    def _show_equipment(self):
        """장비 목록 조회"""
        print_header("장비 목록")

        equipment_list = self.equipment_service.get_all_equipment()
        if not equipment_list:
            print_info("등록된 장비가 없습니다.")
            pause()
            return

        headers = ["이름", "종류", "시리얼번호", "상태"]
        rows = []
        for equip in equipment_list:
            rows.append(
                [
                    equip.name,
                    equip.asset_type,
                    equip.serial_number,
                    format_status_badge(equip.status.value),
                ]
            )

        print(format_table(headers, rows))
        pause()

    def _create_equipment_booking(self):
        """장비 예약 생성"""
        print_header("장비 예약하기")

        # 예약 작업 전 정책 점검 (no-show, 제한 상태 확인)
        if not self._run_policy_checks():
            return
        if not self._refresh_user():
            return

        try:
            can_book, max_active, message = self.policy_service.check_user_can_book(
                self.user
            )
        except (PenaltyError, RoomBookingError, EquipmentBookingError) as e:
            self._handle_user_query_error(e)
            return
        if not can_book:
            print_error(message)
            pause()
            return

        if message:
            print_warning(message)

        equipment_list = self.equipment_service.get_available_equipment()
        if not equipment_list:
            print_info("예약 가능한 장비가 없습니다.")
            pause()
            return

        asset_types = sorted({item.asset_type for item in equipment_list})
        type_items = [(asset_type, asset_type) for asset_type in asset_types]
        asset_type = select_from_list(type_items, "장비 종류 선택")
        if not asset_type:
            return

        self._print_daily_booking_guide()
        start_date, end_date = get_daily_date_range_input("시작 날짜", "종료 날짜")
        if start_date is None or end_date is None:
            return

        from src.domain.daily_booking_rules import build_daily_booking_period

        start_time, end_time = build_daily_booking_period(start_date, end_date)
        filtered_equipment = self.equipment_service.get_available_equipment_by_type(
            asset_type, start_time, end_time
        )
        if not filtered_equipment:
            print_info("해당 종류의 장비가 선택한 기간에 모두 예약 중입니다.")
            pause()
            return

        items = [
            (e.id, f"{e.name} ({e.asset_type}, S/N: {e.serial_number})")
            for e in filtered_equipment
        ]
        equipment_id = select_from_list(items, "장비 선택")
        if not equipment_id:
            return

        try:
            limits = self.policy_service.get_user_flow_limits(self.user)
            if limits["equipment_limit"] <= 0:
                raise EquipmentBookingError("이미 활성 장비 예약이 있습니다.")
            booking = self.equipment_service.create_daily_booking(
                user=self.user,
                equipment_id=equipment_id,
                start_date=start_date,
                end_date=end_date,
                max_active=limits["equipment_limit"],
            )
            print_success("예약이 완료되었습니다.")
            print(f"  예약 ID: {booking.id[:8]}...")
            print(
                f"  대여 기간: {format_booking_time_range(booking.start_time, booking.end_time)}"
            )
        except (EquipmentBookingError, PenaltyError) as e:
            print_error(str(e))

        pause()

    def _show_my_equipment_bookings(self):
        """내 장비 예약 조회"""
        print_header("내 장비 예약")

        if not self._refresh_user():
            return

        try:
            bookings = self.equipment_service.get_user_bookings(self.user.id)
        except (PenaltyError, RoomBookingError, EquipmentBookingError) as e:
            self._handle_user_query_error(e)
            return
        if not bookings:
            print_info("예약 내역이 없습니다.")
            pause()
            return

        bookings.sort(key=lambda b: b.start_time, reverse=True)

        headers = ["ID", "장비", "대여 기간", "상태"]
        rows = []
        for booking in bookings[:20]:
            equip = self.equipment_service.get_equipment(booking.equipment_id)
            equip_name = equip.name if equip else "알 수 없음"
            rows.append(
                [
                    booking.id[:8],
                    equip_name,
                    format_booking_time_range(booking.start_time, booking.end_time),
                    format_status_badge(booking.status.value),
                ]
            )

        print(format_table(headers, rows))

        if len(bookings) > 20:
            print(f"\n  ... 외 {len(bookings) - 20}건")

        pause()

    def _modify_equipment_booking(self):
        """장비 예약 변경"""
        print_header("장비 예약 변경")

        # 예약 작업 전 정책 점검 (no-show, 제한 상태 확인)
        if not self._run_policy_checks():
            return
        if not self._refresh_user():
            return

        try:
            active_bookings = [
                b
                for b in self.equipment_service.get_user_bookings(self.user.id)
                if b.status == EquipmentBookingStatus.RESERVED
            ]
        except (PenaltyError, RoomBookingError, EquipmentBookingError) as e:
            self._handle_user_query_error(e)
            return

        if not active_bookings:
            print_info("변경 가능한 예약이 없습니다. (예약 대기 상태만 변경 가능)")
            pause()
            return

        items = []
        for booking in active_bookings:
            equip = self.equipment_service.get_equipment(booking.equipment_id)
            equip_name = equip.name if equip else "알 수 없음"
            items.append(
                (
                    booking.id,
                    f"{equip_name} - {format_booking_time_range(booking.start_time, booking.end_time)}",
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
            booking = self.equipment_service.modify_daily_booking(
                user=self.user,
                booking_id=booking_id,
                start_date=start_date,
                end_date=end_date,
            )
            print_success("예약이 변경되었습니다.")
            print(
                f"  새 기간: {format_booking_time_range(booking.start_time, booking.end_time)}"
            )
        except (EquipmentBookingError, PenaltyError) as e:
            print_error(str(e))

        pause()

    def _request_equipment_pickup(self):
        print_header("장비 픽업 요청")

        if not self._refresh_user():
            return

        try:
            requestable = [
                b
                for b in self.equipment_service.get_user_bookings(self.user.id)
                if b.status == EquipmentBookingStatus.RESERVED
            ]
        except (PenaltyError, RoomBookingError, EquipmentBookingError) as e:
            self._handle_user_query_error(e)
            return

        if not requestable:
            print_info("픽업 요청 가능한 장비 예약이 없습니다.")
            pause()
            return

        items = []
        for booking in requestable:
            equip = self.equipment_service.get_equipment(booking.equipment_id)
            items.append(
                (
                    booking.id,
                    f"{equip.name if equip else '-'} - {format_booking_time_range(booking.start_time, booking.end_time)}",
                )
            )

        booking_id = select_from_list(items, "픽업 요청할 예약 선택")
        if not booking_id:
            return

        try:
            self.equipment_service.request_pickup(self.user, booking_id)
            print_success("픽업 요청이 접수되었습니다. 관리자 승인 대기 상태입니다.")
        except (PenaltyError, EquipmentBookingError) as e:
            print_error(str(e))

        pause()

    def _request_equipment_return(self):
        print_header("장비 반납 신청")

        if not self._refresh_user():
            return

        try:
            requestable = [
                b
                for b in self.equipment_service.get_user_bookings(self.user.id)
                if b.status == EquipmentBookingStatus.CHECKED_OUT
            ]
        except (PenaltyError, RoomBookingError, EquipmentBookingError) as e:
            self._handle_user_query_error(e)
            return

        if not requestable:
            print_info("반납 신청 가능한 장비 예약이 없습니다.")
            pause()
            return

        items = []
        for booking in requestable:
            equip = self.equipment_service.get_equipment(booking.equipment_id)
            items.append(
                (
                    booking.id,
                    f"{equip.name if equip else '-'} - {format_booking_time_range(booking.start_time, booking.end_time)}",
                )
            )

        booking_id = select_from_list(items, "반납 신청할 예약 선택")
        if not booking_id:
            return

        try:
            self.equipment_service.request_return(self.user, booking_id)
            print_success("반납 신청이 접수되었습니다. 관리자 승인 대기 상태입니다.")
        except (PenaltyError, EquipmentBookingError) as e:
            print_error(str(e))

        pause()

    def _cancel_equipment_booking(self):
        """장비 예약 취소"""
        print_header("장비 예약 취소")

        # 예약 작업 전 정책 점검 (no-show, 제한 상태 확인)
        if not self._run_policy_checks():
            return
        if not self._refresh_user():
            return

        try:
            active_bookings = [
                b
                for b in self.equipment_service.get_user_bookings(self.user.id)
                if b.status == EquipmentBookingStatus.RESERVED
            ]
        except (PenaltyError, RoomBookingError, EquipmentBookingError) as e:
            self._handle_user_query_error(e)
            return

        if not active_bookings:
            print_info("취소 가능한 예약이 없습니다.")
            pause()
            return

        items = []
        for booking in active_bookings:
            equip = self.equipment_service.get_equipment(booking.equipment_id)
            equip_name = equip.name if equip else "알 수 없음"
            items.append(
                (
                    booking.id,
                    f"{equip_name} - {format_booking_time_range(booking.start_time, booking.end_time)}",
                )
            )

        booking_id = select_from_list(items, "취소할 예약 선택")
        if not booking_id:
            return

        if not confirm("정말 취소하시겠습니까?"):
            return

        try:
            booking, is_late = self.equipment_service.cancel_booking(
                self.user, booking_id
            )
            print_success("예약이 취소되었습니다.")

            if is_late:
                print_warning("직전 취소로 패널티 2점이 부과됩니다.")
        except (EquipmentBookingError, PenaltyError) as e:
            print_error(str(e))

        pause()

    def _show_my_status(self):
        """내 상태 조회"""
        print_header("내 상태")

        if not self._refresh_user():
            return
        try:
            status = self.penalty_service.get_user_status(self.user)
            room_active = self.room_service.get_user_active_bookings(self.user.id)
            equip_active = self.equipment_service.get_user_active_bookings(self.user.id)
            all_room_bookings = self.room_service.get_user_bookings(self.user.id)
            all_equip_bookings = self.equipment_service.get_user_bookings(self.user.id)
            penalties = self.penalty_service.get_user_penalties(self.user.id)
        except (PenaltyError, RoomBookingError, EquipmentBookingError) as e:
            self._handle_user_query_error(e)
            return

        print(f"\n사용자명: {self.user.username}")
        print(f"역할: {format_status_badge(self.user.role.value)}")

        print_subheader("패널티 상태")
        print(
            f"  상태: {format_penalty_status(status['points'], status['is_banned'], status['is_restricted'])}"
        )
        print(f"  누적 점수: {status['points']}점")
        print(f"  정상 이용 연속: {status.get('normal_use_streak', 0)}회")

        if status.get("restriction_until"):
            print(f"  제한 해제일: {status['restriction_until'][:10]}")

        print_subheader("활성 예약")
        print(f"  회의실: {len(room_active)}건")
        for b in room_active:
            room = self.room_service.get_room(b.room_id)
            room_name = room.name if room else "알 수 없음"
            print(
                f"    - {room_name}: {format_booking_time_range(b.start_time, b.end_time)}"
            )

        print(f"  장비: {len(equip_active)}건")
        for b in equip_active:
            equip = self.equipment_service.get_equipment(b.equipment_id)
            equip_name = equip.name if equip else "알 수 없음"
            print(
                f"    - {equip_name}: {format_booking_time_range(b.start_time, b.end_time)}"
            )

        print_subheader("예약 이력 요약")
        completed_room_statuses = (
            RoomBookingStatus.COMPLETED,
            RoomBookingStatus.CANCELLED,
            RoomBookingStatus.ADMIN_CANCELLED,
        )
        completed_equip_statuses = (
            EquipmentBookingStatus.RETURNED,
            EquipmentBookingStatus.CANCELLED,
            EquipmentBookingStatus.ADMIN_CANCELLED,
        )

        completed_rooms = [
            b for b in all_room_bookings if b.status in completed_room_statuses
        ]
        completed_equip = [
            b for b in all_equip_bookings if b.status in completed_equip_statuses
        ]

        print(
            f"  회의실: 총 {len(all_room_bookings)}건 (완료/취소 {len(completed_rooms)}건, 활성 {len(room_active)}건)"
        )
        print(
            f"  장비: 총 {len(all_equip_bookings)}건 (완료/취소 {len(completed_equip)}건, 활성 {len(equip_active)}건)"
        )

        if completed_rooms:
            recent_rooms = sorted(
                completed_rooms, key=lambda b: b.updated_at, reverse=True
            )[:3]
            print("  최근 회의실 이력:")
            for b in recent_rooms:
                room = self.room_service.get_room(b.room_id)
                room_name = room.name if room else "알 수 없음"
                print(
                    f"    - {room_name}: {b.start_time[:10]} ({format_status_badge(b.status.value)})"
                )

        if completed_equip:
            recent_equip = sorted(
                completed_equip, key=lambda b: b.updated_at, reverse=True
            )[:3]
            print("  최근 장비 이력:")
            for b in recent_equip:
                equip = self.equipment_service.get_equipment(b.equipment_id)
                equip_name = equip.name if equip else "알 수 없음"
                print(
                    f"    - {equip_name}: {b.start_time[:10]} ({format_status_badge(b.status.value)})"
                )

        print_subheader("패널티 이력")
        if not penalties:
            print("  패널티 이력이 없습니다.")
        else:
            penalties.sort(key=lambda p: p.created_at, reverse=True)
            for p in penalties[:5]:
                print(
                    f"  - {format_datetime(p.created_at)}: {p.reason.value} (+{p.points}점) {p.memo}"
                )
            if len(penalties) > 5:
                print(f"    ... 외 {len(penalties) - 5}건")

        pause()
