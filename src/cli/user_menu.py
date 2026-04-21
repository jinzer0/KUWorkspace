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

    def _is_requestable_now(self, booking, required_status, time_attr, current_time):
        if booking.status != required_status:
            return False
        return datetime.fromisoformat(getattr(booking, time_attr)) == current_time

    def _is_room_checkin_requestable_now(self, booking):
        return self._is_requestable_now(
            booking=booking,
            required_status=RoomBookingStatus.RESERVED,
            time_attr="start_time",
            current_time=self.room_service.clock.now(),
        )

    def _is_room_checkout_requestable_now(self, booking):
        return booking.status == RoomBookingStatus.CHECKED_IN

    def _is_equipment_pickup_requestable_now(self, booking):
        return self._is_requestable_now(
            booking=booking,
            required_status=EquipmentBookingStatus.RESERVED,
            time_attr="start_time",
            current_time=self.equipment_service.clock.now(),
        )

    def _is_equipment_return_requestable_now(self, booking):
        return booking.status == EquipmentBookingStatus.CHECKED_OUT

    def run(self):
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
                restriction_until = status.get("restriction_until")
                restriction_date = (
                    restriction_until[:10]
                    if isinstance(restriction_until, str) and restriction_until
                    else "-"
                )
                print_warning(
                    f"이용이 금지된 상태입니다. (해제일: {restriction_date})"
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
                ClockMenu(
                    self.policy_service,
                    actor_id=self.user.id,
                    actor_role="user",
                ).run()
            elif choice == "0":
                if confirm("로그아웃 하시겠습니까?"):
                    print_success("로그아웃 되었습니다.")
                    return True
            else:
                print_error("잘못된 선택입니다.")

    def _refresh_user(self):
        try:
            self.user = self.auth_service.get_user(self.user.id)
            return True
        except AuthError as e:
            print_error(str(e))
            pause()
            return False

    # ===========================================================================
    # 회의실 파트 (원본 유지)
    # ===========================================================================

    def _show_rooms(self):
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
                status_text += " 예약 불가 (문의: 관리자에게 연락하세요)"
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
        print_header("회의실 예약하기")
        if not self._run_policy_checks():
            return
        if not self._refresh_user():
            return
        try:
            can_book, max_active, message = self.policy_service.check_user_can_book(self.user)
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
        rooms = self.room_service.get_available_rooms_for_attendees(attendee_count, start_time, end_time)
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
            room_limit = limits.get("room_limit")
            if not isinstance(room_limit, int) or room_limit <= 0:
                raise RoomBookingError("이미 활성 회의실 예약이 있습니다.")
            booking = self.room_service.create_daily_booking(
                user=self.user,
                room_id=room_id,
                start_date=start_date,
                end_date=end_date,
                attendee_count=attendee_count,
                max_active=room_limit,
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
            rows.append([
                booking.id[:8],
                room_name,
                format_booking_time_range(booking.start_time, booking.end_time),
                format_status_badge(booking.status.value),
            ])
        print(format_table(headers, rows))
        if len(bookings) > 20:
            print(f"\n  ... 외 {len(bookings) - 20}건")
        pause()

    def _modify_room_booking(self):
        print_header("회의실 예약 변경")
        if not self._run_policy_checks():
            return
        if not self._refresh_user():
            return
        try:
            active_bookings = [
                b for b in self.room_service.get_user_bookings(self.user.id)
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
            items.append((booking.id, f"{room_name} - {format_booking_time_range(booking.start_time, booking.end_time)}"))
        booking_id = select_from_list(items, "변경할 예약 선택")
        if not booking_id:
            return

        selected = next((b for b in active_bookings if b.id == booking_id), None)
        if selected is None:
            print_error("선택한 예약을 찾을 수 없습니다.")
            pause()
            return

        if datetime.fromisoformat(selected.start_time) <= self.room_service.clock.now():
            print_error("이미 시작된 예약은 변경할 수 없습니다.")
            pause()
            return

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
                user=self.user, booking_id=booking_id, start_date=start_date, end_date=end_date,
            )
            print_success("예약이 변경되었습니다.")
            print(f"  새 시간: {format_booking_time_range(booking.start_time, booking.end_time)}")
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
                if self._is_room_checkin_requestable_now(b)
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
            items.append((booking.id, f"{room.name if room else '-'} - {format_booking_time_range(booking.start_time, booking.end_time)}"))
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
                if self._is_room_checkout_requestable_now(b)
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
            items.append((booking.id, f"{room.name if room else '-'} - {format_booking_time_range(booking.start_time, booking.end_time)}"))
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
        print_header("회의실 예약 취소")
        if not self._run_policy_checks():
            return
        if not self._refresh_user():
            return
        try:
            active_bookings = [
                b for b in self.room_service.get_user_bookings(self.user.id)
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
            items.append((booking.id, f"{room_name} - {format_booking_time_range(booking.start_time, booking.end_time)}"))
        booking_id = select_from_list(items, "취소할 예약 선택")
        if not booking_id:
            return

        try:
            is_late_cancel = self.room_service.will_apply_late_cancel_penalty(
                self.user, booking_id
            )
        except (RoomBookingError, PenaltyError) as e:
            print_error(str(e))
            pause()
            return

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

    def _get_equipment_date_range_input(self):
        """validators.py get_current_time 미정의 우회 - clock.now() 사용"""
        from src.domain.daily_booking_rules import validate_daily_booking_dates
        from src.cli.validators import validate_date_plan
        while True:
            start_str = input("  시작 날짜 (YYYY-MM-DD / YYYY.MM.DD / YYYY MM DD): ").strip()
            if start_str.lower() in ("q", "quit", "취소"):
                return None, None
            end_str = input("  종료 날짜 (YYYY-MM-DD / YYYY.MM.DD / YYYY MM DD): ").strip()
            if end_str.lower() in ("q", "quit", "취소"):
                return None, None
            start_valid, start_date, start_error = validate_date_plan(start_str)
            if not start_valid or start_date is None:
                print("  날짜 형식이 올바르지 않습니다. (예: 2099-01-01)")
                continue
            end_valid, end_date, end_error = validate_date_plan(end_str)
            if not end_valid or end_date is None:
                print("  날짜 형식이 올바르지 않습니다. (예: 2099-01-01)")
                continue
            valid, error, _ = validate_daily_booking_dates(
                start_date, end_date, self.equipment_service.clock.now()
            )
            if valid:
                return start_date, end_date
            print(f"  {error}")

    def _get_real_active_equipment_bookings(self):
        """
        [유령 예약 문제 해결]
        end_time이 현재 운영 시점보다 이후인 예약만 실제 활성으로 간주
        """
        now_dt = self.equipment_service.clock.now()
        raw = self.equipment_service.get_user_active_bookings(self.user.id)
        return [
            b for b in raw
            if datetime.fromisoformat(b.end_time) > now_dt
        ]

    # ===========================================================================
    # 6.5.2.1  장비 목록 조회
    # ===========================================================================

    def _show_equipment(self):
        print_header("장비 목록 조회")
        try:
            all_equips = self.equipment_service.get_all_equipment()
        except EquipmentBookingError as e:
            print_error(str(e))
            pause()
            return

        # [기획서 4.3.1 + 6.5.2.1 출력 예시 참고]
        # 기획서 4.3.1: "장비의 종류는 노트북, 프로젝터, 웹캠, 케이블로 구성"
        # 기획서 6.5.2.1 출력 예시: 프로젝터→노트북→케이블→웹캠 순으로 표기
        # → 출력 예시를 우선 적용하여 projector→laptop→cable→webcam 순 정렬
        # 기존 코드도 동일 순서였으나 주석이 없어 근거 불명확했음
        _TYPE_ORDER = ["projector", "laptop", "cable", "webcam"]

        def _sort_key(e):
            try:
                ti = _TYPE_ORDER.index(e.asset_type.lower())
            except ValueError:
                ti = len(_TYPE_ORDER)
            # [기획서 5.4.1] serial_number: 장비를 구분하는 고유 인식코드 → 2차 정렬 기준
            return (ti, e.serial_number)

        sorted_equips = sorted(all_equips, key=_sort_key)

        # [기획서 6.5.2.1] 출력 컬럼: 이름, 종류, 시리얼번호, 상태
        headers = ["이름", "종류", "시리얼번호", "상태"]
        rows = []
        has_unavailable = False

        for e in sorted_equips:
            sv = e.status.value.lower()
            # [기획서 6.5.2.1] 상태 표시 기준:
            # available → "[사용가능]"
            # maintenance → "[점검 중]"
            # 그 외(disabled 등) → "[사용 불가]"
            if sv == "available":
                status_text = "[사용가능]"
            elif sv == "maintenance":
                status_text = "[점검 중]"
                has_unavailable = True
            else:
                status_text = "[사용 불가]"
                has_unavailable = True
            rows.append([e.name, e.asset_type, e.serial_number, status_text])

        print(format_table(headers, rows))

        # [기획서 6.5.2.1] maintenance 또는 disabled 장비가 있을 경우
        # "예약 불가 (문의: 관리자에게 연락하세요)" 안내 출력
        # 기존 코드에서 이 안내 문구가 완전히 누락되어 있었음 → 추가
        if has_unavailable:
            print_info("예약 불가 (문의: 관리자에게 연락하세요)")

        input("\n계속하려면 Enter를 누르세요...")

    # ===========================================================================
    # 6.5.2.2  장비 예약하기
    # ===========================================================================

    def _create_equipment_booking(self):
        print_header("장비 예약하기")
        if not self._refresh_user():
            return

        # [기획서 6.5.2.2] banned 상태 차단
        # "이용이 금지된 상태입니다. 해제일: YYYY-MM-DD" 출력 후 예약 차단
        try:
            status = self.penalty_service.get_user_status(self.user)
        except PenaltyError as e:
            print_error(str(e))
            pause()
            return
        if status.get("is_banned"):
            restriction_until = status.get("restriction_until")
            until = (
                restriction_until[:10]
                if isinstance(restriction_until, str) and restriction_until
                else ""
            )
            print_error(f"이용이 금지된 상태입니다. 해제일: {until}")
            pause()
            return

        real_active = self._get_real_active_equipment_bookings()

        

        # [기획서 6.6.3.3.1] 정상 상태도 장비 활성 예약은 1건까지만 허용
        # "이미 활성 장비 예약이 있습니다." 출력 후 차단
        if len(real_active) >= 1:
            print_error("이미 활성 장비 예약이 있습니다.")
            pause()
            return

        # [기획서 4.3.1] 장비 종류: 노트북, 프로젝터, 웹캠, 케이블 4종
        # [기획서 6.5.2.2] available 상태 종류만 목록에 표시
        # [기획서 6.5.2.1·6.5.2.2 출력 예시] 종류 정렬: projector→laptop→cable→webcam
        try:
            all_equips = self.equipment_service.get_all_equipment()
        except EquipmentBookingError as e:
            print_error(str(e))
            pause()
            return

        _TYPE_ORDER = ["projector", "laptop", "cable", "webcam"]
        available_types = sorted(
            {e.asset_type for e in all_equips if e.status.value.lower() == "available"},
            key=lambda t: (_TYPE_ORDER.index(t.lower()) if t.lower() in _TYPE_ORDER else 99),
        )
        if not available_types:
            print_info("현재 예약 가능한 장비가 없습니다.")
            pause()
            return

        print()
        for i, t in enumerate(available_types, 1):
            print(f"  {i}. {t}")
        print("  0. 취소")
        print("-" * 50)
        while True:
            raw = input("장비 종류 선택 (번호): ").strip()
            if raw == "0":
                return
            if not raw.isdigit():
                print_error("숫자를 입력해주세요.")
                continue
            idx = int(raw) - 1
            if idx < 0 or idx >= len(available_types):
                print_error(f"1~{len(available_types)} 사이의 번호를 입력해주세요.")
                continue
            selected_type = available_types[idx]
            break

        # [기획서 6.5.2.2] 날짜 입력 안내 문구 (기획서 출력 예시 그대로 사용)
        print()
        print(f"  이용 시간: 매일 {FIXED_BOOKING_START_HOUR:02d}:{FIXED_BOOKING_START_MINUTE:02d} ~ {FIXED_BOOKING_END_HOUR:02d}:{FIXED_BOOKING_END_MINUTE:02d} 고정")
        print("  예약 시작일: 내일부터 최대 6개월까지 가능")
        print("  예약 기간: 1일 이상 14일 이하")
        print()
        start_date, end_date = self._get_equipment_date_range_input()
        if start_date is None or end_date is None:
            return

        # [기획서 6.5.2.2] 개별 장비 선택
        # 시리얼번호 오름차순 정렬, 해당 기간 활성 예약 충돌 없는 장비만 표시
        # [기획서 4.3.2] 시리얼번호: [장비 영문 대문자약어]-[고유번호] 형식 (예: PJ-001)
        from src.domain.daily_booking_rules import build_daily_booking_period
        start_time, end_time = build_daily_booking_period(start_date, end_date)
        try:
            candidates = self.equipment_service.get_available_equipment_by_type(
                selected_type, start_time, end_time
            )
        except EquipmentBookingError as e:
            print_error(str(e))
            pause()
            return

        # [기획서 6.5.2.2] 시리얼번호 오름차순 정렬
        candidates.sort(key=lambda e: e.serial_number)
        if not candidates:
            print_info("해당 기간에 예약 가능한 장비가 없습니다.")
            pause()
            return

        print()
        for i, e in enumerate(candidates, 1):
            print(f"  {i}. {e.name} ({e.asset_type}, S/N: {e.serial_number})")
        print("  0. 취소")
        print("-" * 50)
        while True:
            raw = input("장비 선택 (번호): ").strip()
            if raw == "0":
                return
            if not raw.isdigit():
                print_error("숫자를 입력해주세요.")
                continue
            idx = int(raw) - 1
            if idx < 0 or idx >= len(candidates):
                print_error(f"1~{len(candidates)} 사이의 번호를 입력해주세요.")
                continue
            chosen = candidates[idx]
            break

        # [기획서 6.5.2.2] 예약 성공 메시지: "장비 선택이 완료되었습니다."
        # [기획서 5.4.3] 예약 생성 시 status=reserved, 나머지 시각 필드는 "\-"로 저장
        # [기획서 6.6.3.3.1] 정상/제한 모두 장비 활성 예약 1건까지 허용
        # → max_active=1 고정 (기존 코드의 real_active_count+1 동적 계산 방식 제거)
        try:
            self.equipment_service.create_daily_booking(
                user=self.user,
                equipment_id=chosen.id,
                start_date=start_date,
                end_date=end_date,
                max_active=1,
            )
            print_success("장비 선택이 완료되었습니다.")
        except EquipmentBookingError as e:
            print_error(str(e))

        input("\n계속하려면 Enter를 누르세요...")

    # ===========================================================================
    # 6.5.2.3  내 장비 예약 조회
    # ===========================================================================

    def _show_my_equipment_bookings(self):
        # [기획서 6.5.2.3] 화면 헤더: "장비 예약 조회"
        # 기존 코드: print_header("내 장비 예약") → 기획서 6.5.2.3 헤더와 불일치하여 수정
        print_header("장비 예약 조회")
        try:
            bookings = self.equipment_service.get_user_bookings(self.user.id)
        except EquipmentBookingError as e:
            print_error(str(e))
            pause()
            return

        # [기획서 6.5.2.3] 예약 없을 경우 출력 문구: "예약중인 장비가 없습니다."
        if not bookings:
            print_info("예약중인 장비가 없습니다.")
            input("\n계속하려면 Enter를 누르세요...")
            return

        # [기획서 6.5.2.3] 정렬: 대여 시작일(start_time) 기준 내림차순
        bookings.sort(key=lambda b: b.start_time, reverse=True)
        display = bookings[:20]

        # [기획서 6.5.2.3] 컬럼: ID / 장비 / 대여 기간 / 상태
        # 기존 코드: headers = ["ID", "장비 종류", "대여 기간", "상태"]
        # 기획서 6.5.2.3 출력 예시에서 "장비"로 명시 → "장비 종류"에서 "장비"로 수정
        #
        # [기획서 5.4.3] 장비 예약 status 정의값:
        # reserved, pickup_requested, checked_out, return_requested,
        # returned, cancelled, admin_cancelled
        _STATUS_KO = {
            "reserved":         "[예약됨]",
            "pickup_requested": "[픽업 요청중]",
            "checked_out":      "[사용중]",
            "return_requested": "[반납 요청중]",
            "returned":         "[반납 완료]",
            "cancelled":        "[취소됨]",
            "admin_cancelled":  "[관리자 취소]",
        }
        headers = ["ID", "장비", "대여 기간", "상태"]
        rows = []
        for b in display:
            equip = self.equipment_service.get_equipment(b.equipment_id)
            rows.append([
                b.id[:8],
                equip.asset_type if equip else "-",
                format_booking_time_range(b.start_time, b.end_time),
                _STATUS_KO.get(b.status.value.lower(), f"[{b.status.value}]"),
            ])
        print(format_table(headers, rows))
        if len(bookings) > 20:
            print(f"\n  ... 외 {len(bookings) - 20}건")
        input("\n계속하려면 Enter를 누르세요...")

    # ===========================================================================
    # 6.5.2.4  장비 예약 변경
    # ===========================================================================

    def _modify_equipment_booking(self):
        print_header("장비 예약 변경")
        try:
            all_bookings = self.equipment_service.get_user_bookings(self.user.id)
        except EquipmentBookingError as e:
            print_error(str(e))
            pause()
            return

        # [기획서 6.5.2.4] 변경 가능 조건: 본인 소유이며 reserved 상태인 예약만
        active = [b for b in all_bookings if b.status == EquipmentBookingStatus.RESERVED]

        # [기획서 6.5.2.4] 예약 없을 경우 출력 문구: "장비가 예약되어 있지 않습니다"
        if not active:
            print_info("장비가 예약되어 있지 않습니다.")
            pause()
            return

        print()
        for i, b in enumerate(active, 1):
            equip = self.equipment_service.get_equipment(b.equipment_id)
            name = equip.name if equip else "-"
            print(f"  {i}. {name} - {format_booking_time_range(b.start_time, b.end_time)}")
        print("  0. 취소")
        print("-" * 50)
        while True:
            raw = input("변경할 예약 선택 (번호): ").strip()
            if raw == "0":
                return
            if not raw.isdigit():
                # [기획서 6.5.2.4] 잘못된 입력 시 출력 문구:
                # "잘못입력되었습니다. 다시 입력해주세요"
                print_error("잘못입력되었습니다. 다시 입력해주세요.")
                continue
            idx = int(raw) - 1
            if idx < 0 or idx >= len(active):
                print_error("잘못입력되었습니다. 다시 입력해주세요.")
                continue
            chosen_booking = active[idx]
            break

        # [기획서 6.5.2.4] 날짜 안내 문구 (기획서 출력 예시 그대로)
        print()
        print("  이용 시간은 매일 09:00 ~ 18:00로 고정됩니다.")
        print("  예약 시작일은 내일부터 선택할 수 있고, 시작일 기준 최대 6개월까지 가능합니다.")
        print("  예약 기간은 1일 이상 14일 이하입니다.")
        print()
        start_date, end_date = self._get_equipment_date_range_input()
        if start_date is None or end_date is None:
            return

        # [기획서 6.5.2.4] 변경 확인 문구: "장비를 예약하시겠습니까?"
        # y/yes/예/ㅇ → 변경 진행
        # n/no/아니오/ㄴ → 변경 철회 후 사용자 메뉴로 이동
        # 그 외 → "y 또는 n을 입력해주세요." 재입력
        while True:
            yn = input("장비를 예약하시겠습니까? (y/n): ").strip().lower()
            if yn in ("y", "yes", "예", "ㅇ"):
                break
            elif yn in ("n", "no", "아니오", "ㄴ"):
                return
            else:
                print_error("y 또는 n을 입력해주세요.")

        try:
            updated = self.equipment_service.modify_daily_booking(
                user=self.user, booking_id=chosen_booking.id,
                start_date=start_date, end_date=end_date,
            )
            print_success("예약이 변경되었습니다.")
            print(f"  새 기간: {format_booking_time_range(updated.start_time, updated.end_time)}")
        except EquipmentBookingError as e:
            print_error(str(e))
        input("\n계속하려면 Enter를 누르세요...")

    # ===========================================================================
    # 6.5.2.5  장비 예약 취소
    # ===========================================================================

    def _cancel_equipment_booking(self):
        print_header("장비 예약 취소")
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
            items.append((booking.id, f"{equip_name} / {format_booking_time_range(booking.start_time, booking.end_time)}"))

        booking_id = select_from_list(items, "취소할 장비 선택")
        if not booking_id:
            return

        try:
            is_late_cancel = self.equipment_service.will_apply_late_cancel_penalty(
                self.user, booking_id
            )
        except (EquipmentBookingError, PenaltyError) as e:
            print_error(str(e))
            pause()
            return

        if is_late_cancel:
            print_warning("직전 취소로 인해 패널티 2점이 부과됩니다.")
            if not confirm("그래도 취소하시겠습니까?"):
                return
        else:
            if not confirm("정말 취소하시겠습니까?"):
                return

        try:
            _, is_late = self.equipment_service.cancel_booking(self.user, booking_id)
            print_success("장비 예약 취소가 완료되었습니다.")
            if is_late:
                print_warning("직전 취소 패널티 2점이 부과되었습니다.")
        except EquipmentBookingError as e:
            print_error(str(e))
        pause()

    # ===========================================================================
    # 6.5.2.6  장비 픽업 신청
    # ===========================================================================

    def _request_equipment_pickup(self):
        print_header("장비 픽업 신청")
        try:
            requestable = [
                b
                for b in self.equipment_service.get_user_bookings(self.user.id)
                if self._is_equipment_pickup_requestable_now(b)
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
            equip_name = equip.name if equip else "알 수 없음"
            items.append((booking.id, f"{equip_name} / {format_booking_time_range(booking.start_time, booking.end_time)}"))

        booking_id = select_from_list(items, "픽업할 장비 선택")
        if not booking_id:
            return

        if not confirm("정말로 픽업 요청하시겠습니까?"):
            return

        try:
            self.equipment_service.request_pickup(self.user, booking_id)
            print_success("픽업 요청이 접수되었습니다. 관리자 승인 대기 상태입니다.")
        except EquipmentBookingError as e:
            print_error(str(e))
        pause()

    # ===========================================================================
    # 6.5.2.7  장비 반납 신청
    # ===========================================================================

    def _request_equipment_return(self):
        print_header("장비 반납 신청")
        if not self._refresh_user():
            return
        try:
            requestable = [
                b
                for b in self.equipment_service.get_user_bookings(self.user.id)
                if self._is_equipment_return_requestable_now(b)
            ]
        except EquipmentBookingError as e:
            print_error(str(e))
            pause()
            return

        if not requestable:
            print_info("반납 신청 가능한 장비 예약이 없습니다.")
            pause()
            return

        items = []
        for booking in requestable:
            equip = self.equipment_service.get_equipment(booking.equipment_id)
            equip_name = equip.name if equip else "알 수 없음"
            items.append((booking.id, f"{equip_name} / {format_booking_time_range(booking.start_time, booking.end_time)}"))

        booking_id = select_from_list(items, "반납할 장비 선택")
        if not booking_id:
            return

        if not confirm("정말 반납 신청하시겠습니까?"):
            return

        try:
            self.equipment_service.request_return(self.user, booking_id)
            print_success("장비 반납 신청이 완료되었습니다.")
        except EquipmentBookingError as e:
            print_error(str(e))
        pause()

    # ===========================================================================
    # 내 상태 조회
    # ===========================================================================

    def _show_my_status(self):
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
        print(f"  상태: {format_penalty_status(status['points'], status['is_banned'], status['is_restricted'])}")
        print(f"  누적 점수: {status['points']}점")
        print(f"  정상 이용 연속: {status.get('normal_use_streak', 0)}회")
        restriction_until = status.get("restriction_until")
        if isinstance(restriction_until, str) and restriction_until:
            print(f"  제한 해제일: {restriction_until[:10]}")
        print_subheader("활성 예약")
        print(f"  회의실: {len(room_active)}건")
        for b in room_active:
            room = self.room_service.get_room(b.room_id)
            room_name = room.name if room else "알 수 없음"
            print(f"    - {room_name}: {format_booking_time_range(b.start_time, b.end_time)}")
        print(f"  장비: {len(equip_active)}건")
        for b in equip_active:
            equip = self.equipment_service.get_equipment(b.equipment_id)
            equip_name = equip.name if equip else "알 수 없음"
            print(f"    - {equip_name}: {format_booking_time_range(b.start_time, b.end_time)}")
        print_subheader("예약 이력 요약")
       
        completed_room_statuses = (RoomBookingStatus.COMPLETED, RoomBookingStatus.CANCELLED, RoomBookingStatus.ADMIN_CANCELLED)
        completed_equip_statuses = (EquipmentBookingStatus.RETURNED, EquipmentBookingStatus.CANCELLED, EquipmentBookingStatus.ADMIN_CANCELLED)
        completed_rooms = [b for b in all_room_bookings if b.status in completed_room_statuses]
        completed_equip = [b for b in all_equip_bookings if b.status in completed_equip_statuses]
        print(f"  회의실: 총 {len(all_room_bookings)}건 (완료/취소 {len(completed_rooms)}건, 활성 {len(room_active)}건)")
        print(f"  장비: 총 {len(all_equip_bookings)}건 (완료/취소 {len(completed_equip)}건, 활성 {len(equip_active)}건)")
        if completed_rooms:
            recent_rooms = sorted(completed_rooms, key=lambda b: b.updated_at, reverse=True)[:3]
            print("  최근 회의실 이력:")
            for b in recent_rooms:
                room = self.room_service.get_room(b.room_id)
                room_name = room.name if room else "알 수 없음"
                print(f"    - {room_name}: {b.start_time[:10]} ({format_status_badge(b.status.value)})")
        if completed_equip:
            recent_equip = sorted(completed_equip, key=lambda b: b.updated_at, reverse=True)[:3]
           
            print("  최근 장비 이력:")
            for b in recent_equip:
                equip = self.equipment_service.get_equipment(b.equipment_id)
                equip_name = equip.name if equip else "알 수 없음"
                print(f"    - {equip_name}: {b.start_time[:10]} ({format_status_badge(b.status.value)})")
        print_subheader("패널티 이력")
      
        if not penalties:
            print("  패널티 이력이 없습니다.")
        else:
            penalties.sort(key=lambda p: p.created_at, reverse=True)
            for p in penalties[:5]:
                print(f"  - {format_datetime(p.created_at)}: {p.reason.value} (+{p.points}점) {p.memo}")
            if len(penalties) > 5:
                print(f"    ... 외 {len(penalties) - 5}건")
        pause()
