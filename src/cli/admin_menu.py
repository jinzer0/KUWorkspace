"""
관리자 메뉴 - 회의실/장비 관리, 예약 관리, 사용자 관리
"""

import calendar
import curses
import os
import re
from datetime import date, timedelta
from dataclasses import replace
from typing import Any, cast

from src.domain.models import (
    RoomBookingStatus,
    EquipmentBookingStatus,
    ResourceStatus,
    UserRole,
    decode_future_status_changes,
    encode_future_status_changes,
    generate_id,
    now_iso,
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



class CalendarOverlay:
    """curses 기반 오버레이 캘린더 - 장비 상태 변경용 날짜 선택"""

    MAX_DAYS_AHEAD = 195

    def __init__(self, equipment, reservations, clock):
        self.equipment = equipment
        self.reservations = reservations
        self.clock = clock
        today = clock.now().date()
        self.today = today
        self.current_year = today.year
        self.current_month = today.month
        self.mode = "date"  # 'date' or 'month'
        # 커서 초기 위치: 오늘 날짜 셀
        self.cursor_row, self.cursor_col = self._find_today_pos()

    def _find_today_pos(self):
        grid = calendar.monthcalendar(self.current_year, self.current_month)
        for r, week in enumerate(grid):
            for c, day in enumerate(week):
                if day == self.today.day:
                    return r, c
        return 0, 0

    def _max_date(self):
        return self.today + timedelta(days=self.MAX_DAYS_AHEAD)

    def _date_of(self, row, col):
        grid = calendar.monthcalendar(self.current_year, self.current_month)
        if row < 0 or row >= len(grid):
            return None
        day = grid[row][col]
        if day == 0:
            return None
        try:
            return date(self.current_year, self.current_month, day)
        except ValueError:
            return None

    def _build_grid(self):
        """7열 N행 셀 배열 생성. 각 셀: {day, user_id, is_start, is_end, is_renting, in_range}"""
        month_grid = calendar.monthcalendar(self.current_year, self.current_month)
        result = []
        for week in month_grid:
            row_cells = []
            for day in week:
                if day == 0:
                    row_cells.append({
                        "day": None, "user_id": None,
                        "is_start": False, "is_end": False,
                        "is_renting": False, "in_range": False,
                    })
                    continue
                cell_date = date(self.current_year, self.current_month, day)
                in_range = self.today <= cell_date <= self._max_date()
                user_id = None
                is_start = False
                is_end = False
                is_renting = False
                for bk in self.reservations:
                    bk_start = date.fromisoformat(bk.start_time[:10])
                    bk_end = date.fromisoformat(bk.end_time[:10])
                    if bk_start <= cell_date <= bk_end:
                        user_id = bk.user_id
                        is_renting = bk.status in {
                            EquipmentBookingStatus.CHECKED_OUT,
                            EquipmentBookingStatus.RETURN_REQUESTED,
                        }
                        if bk_start == bk_end:
                            is_start = False
                            is_end = False
                        else:
                            is_start = (cell_date == bk_start)
                            is_end = (cell_date == bk_end)
                        break
                row_cells.append({
                    "day": day, "user_id": user_id,
                    "is_start": is_start, "is_end": is_end,
                    "is_renting": is_renting, "in_range": in_range,
                })
            result.append(row_cells)
        return result

    def _cell_width(self):
        return 10

    def _render(self, stdscr, grid, error_msg=""):
        stdscr.clear()
        cw = self._cell_width()
        days_header = ["일", "월", "화", "수", "목", "금", "토"]

        # 월 헤더
        month_str = f"← {self.current_year}년 {self.current_month}월 →"
        if self.mode == "month":
            month_str = f"[{self.current_year}년 {self.current_month}월]"
        if self.cursor_row == -1:
            month_str = f"[{self.current_year}년 {self.current_month}월]"

        header_line = "=" * (cw * 7)
        stdscr.addstr(0, 0, header_line)
        month_x = max(0, (cw * 7 - len(month_str)) // 2)
        stdscr.addstr(1, month_x, month_str)
        stdscr.addstr(2, 0, header_line)

        # 요일 헤더
        day_header_line = ""
        for d in days_header:
            day_header_line += d.center(cw)
        stdscr.addstr(3, 0, day_header_line)
        stdscr.addstr(4, 0, "-" * (cw * 7))

        # 날짜 셀 (셀별 개별 출력 - 색상반전 적용을 위해)
        for r, week in enumerate(grid):
            row_y = 5 + r * 3
            x = 0
            for c, cell in enumerate(week):
                if cell["day"] is None:
                    try:
                        stdscr.addstr(row_y, x, " " * cw)
                        stdscr.addstr(row_y + 1, x, " " * cw)
                    except curses.error:
                        pass
                    x += cw
                    continue

                is_cursor = (r == self.cursor_row and c == self.cursor_col and self.mode == "date")
                day_str = f"[{cell['day']}]" if is_cursor else str(cell['day'])
                top = day_str.center(cw)

                if cell["is_renting"]:
                    bot = "대여중".center(cw)
                elif cell["user_id"]:
                    uid = cell["user_id"][:6]
                    if cell["is_start"] and cell["is_end"]:
                        bot = f"▶{uid}◀"[:cw].center(cw)
                    elif cell["is_start"]:
                        bot = f"▶{uid}"[:cw].ljust(cw)
                    elif cell["is_end"]:
                        bot = f"{uid}◀"[:cw].rjust(cw)
                    else:
                        bot = uid.center(cw)
                else:
                    bot = " " * cw

                try:
                    if cell["is_renting"]:
                        # 대여중: 날짜, 텍스트 모두 색상반전
                        stdscr.addstr(row_y, x, top, curses.A_REVERSE)
                        stdscr.addstr(row_y + 1, x, bot, curses.A_REVERSE)
                    else:
                        stdscr.addstr(row_y, x, top)
                        stdscr.addstr(row_y + 1, x, bot)
                except curses.error:
                    pass
                x += cw

            try:
                stdscr.addstr(row_y + 2, 0, "-" * (cw * 7))
            except curses.error:
                pass

        # 하단 가이드
        bottom_y = 5 + len(grid) * 3 + 1
        stdscr.addstr(bottom_y, 0, "=" * (cw * 7))
        guide = "[방향키: 날짜 이동 / 엔터: 날짜 선택 / 0: 닫기]"
        stdscr.addstr(bottom_y + 1, max(0, (cw * 7 - len(guide)) // 2), guide)
        stdscr.addstr(bottom_y + 2, 0, "=" * (cw * 7))

        if error_msg:
            try:
                stdscr.addstr(bottom_y + 4, 0, f"✗ {error_msg}")
            except curses.error:
                pass

        stdscr.refresh()

    def _validate_date(self, sel_date):
        """예약/대여 존재 여부 검사. 문제 있으면 오류 메시지, 없으면 None"""
        for bk in self.reservations:
            bk_start = date.fromisoformat(bk.start_time[:10])
            bk_end = date.fromisoformat(bk.end_time[:10])
            if bk_start <= sel_date <= bk_end:
                if bk.status in {EquipmentBookingStatus.CHECKED_OUT,
                                  EquipmentBookingStatus.RETURN_REQUESTED}:
                    return "해당 날짜에는 이미 장비의 대여가 존재합니다."
                else:
                    return "해당 날짜에는 이미 장비의 예약이 존재합니다."
        return None

    def _handle_key(self, key):
        """방향키, 엔터, 0 입력을 처리하는 메서드.
        반환값: 선택된 날짜 문자열(YYYY-MM-DD) / None(닫기) / 오류 메시지 문자열 / 'continue'(재렌더링)
        """
        # 0 키: 닫기
        if key == ord("0"):
            return None

        # 엔터: 날짜 선택 또는 월 이동 모드 전환
        if key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if self.cursor_row == -1 or self.mode == "month":
                self.mode = "date"
                self.cursor_row, self.cursor_col = self._find_today_in_month()
                return "continue"
            else:
                sel_date = self._date_of(self.cursor_row, self.cursor_col)
                if sel_date is None:
                    return "날짜를 선택해주세요."
                if sel_date < self.today:
                    return "현재보다 과거의 날짜는 선택할 수 없습니다."
                if sel_date > self._max_date():
                    return "현재 시점으로부터 최대 195일 뒤까지 선택 가능합니다."
                err = self._validate_date(sel_date)
                if err:
                    return err
                return sel_date.isoformat()

        # 월 이동 모드 방향키
        if self.mode == "month":
            if key == curses.KEY_LEFT:
                self._prev_month()
            elif key == curses.KEY_RIGHT:
                self._next_month()
            elif key == curses.KEY_UP:
                self.mode = "date"
                self.cursor_row = -1
            return "continue"

        # 날짜 이동 모드 방향키
        if key == curses.KEY_UP:
            if self.cursor_row == 0:
                self.mode = "month"
                self.cursor_row = -1
            else:
                new_row = self.cursor_row - 1
                new_date = self._date_of(new_row, self.cursor_col)
                if new_date:
                    self.cursor_row = new_row
                else:
                    self.mode = "month"
                    self.cursor_row = -1

        elif key == curses.KEY_DOWN:
            grid_len = len(calendar.monthcalendar(self.current_year, self.current_month))
            if self.cursor_row < grid_len - 1:
                new_row = self.cursor_row + 1
                new_date = self._date_of(new_row, self.cursor_col)
                if new_date and new_date <= self._max_date():
                    self.cursor_row = new_row

        elif key == curses.KEY_LEFT:
            cur_date = self._date_of(self.cursor_row, self.cursor_col)
            if cur_date and cur_date - timedelta(days=1) >= self.today:
                prev_date = cur_date - timedelta(days=1)
                if prev_date.month != self.current_month:
                    self._prev_month()
                    self._set_cursor_to_date(prev_date)
                else:
                    self.cursor_col -= 1
                    if self.cursor_col < 0:
                        self.cursor_col = 6
                        self.cursor_row -= 1

        elif key == curses.KEY_RIGHT:
            cur_date = self._date_of(self.cursor_row, self.cursor_col)
            if cur_date and cur_date + timedelta(days=1) <= self._max_date():
                next_date = cur_date + timedelta(days=1)
                if next_date.month != self.current_month:
                    self._next_month()
                    self._set_cursor_to_date(next_date)
                else:
                    self.cursor_col += 1
                    if self.cursor_col > 6:
                        self.cursor_col = 0
                        self.cursor_row += 1

        return "continue"

    def show(self):
        """캘린더를 표시하고 선택된 날짜 문자열(YYYY-MM-DD) 또는 None 반환"""
        result = {"date": None}

        def _run(stdscr):
            curses.curs_set(0)
            error_msg = ""
            while True:
                grid = self._build_grid()
                self._render(stdscr, grid, error_msg)
                error_msg = ""
                key = stdscr.getch()

                outcome = self._handle_key(key)

                if outcome is None:
                    # 닫기
                    result["date"] = None
                    return
                elif outcome == "continue":
                    # 재렌더링
                    continue
                elif len(outcome) == 10 and outcome[4] == "-":
                    # YYYY-MM-DD 형식 → 날짜 선택 완료
                    result["date"] = outcome
                    return
                else:
                    # 오류 메시지
                    error_msg = outcome

        try:
            curses.wrapper(_run)
        except Exception:
            pass
        return result["date"]

    def _find_today_in_month(self):
        """현재 표시 월에서 오늘 또는 첫 유효 날짜의 위치 반환"""
        grid = calendar.monthcalendar(self.current_year, self.current_month)
        for r, week in enumerate(grid):
            for c, day in enumerate(week):
                if day != 0:
                    d = date(self.current_year, self.current_month, day)
                    if d >= self.today:
                        return r, c
        return 0, 0

    def _set_cursor_to_date(self, target_date):
        grid = calendar.monthcalendar(self.current_year, self.current_month)
        for r, week in enumerate(grid):
            for c, day in enumerate(week):
                if day == target_date.day:
                    self.cursor_row = r
                    self.cursor_col = c
                    return
        self.cursor_row, self.cursor_col = self._find_today_in_month()

    def _prev_month(self):
        if self.current_month == 1:
            self.current_month = 12
            self.current_year -= 1
        else:
            self.current_month -= 1

    def _next_month(self):
        if self.current_month == 12:
            self.current_month = 1
            self.current_year += 1
        else:
            self.current_month += 1


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

            choice = input("선택: ")

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
                self._run_room_edit_menu()
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

    def _run_room_edit_menu(self):
        """회의실 수정 (관리자) - 메뉴 7 하위 메뉴 (기획서 6.6.1.7)"""
        print_header("회의실 수정 메뉴 (관리자)")
        print()
        print("  1. 회의실 추가")
        print("  2. 회의실 삭제")
        print("  3. 회의실 수정")
        print("  0. 취소")
        while True:
            choice = input("선택 : ")
            if choice in ("0", "1", "2", "3"):
                break
            print_error("0, 1, 2, 3 중에서 입력해주세요.")
            print("다시 입력해 주세요.")
        if choice == "0":
            return
        if choice == "1":
            self._add_room()
        elif choice == "2":
            self._delete_room()
        elif choice == "3":
            self._modify_room()
        # 작업 완료/철회(confirm n) 후 하위 메뉴를 반복하지 않고 관리자 메뉴로 복귀

    def _add_room(self):
        """회의실 추가 (기획서 6.6.1.7.1)"""
        print_header("회의실 수정 메뉴 (추가)")
        while True:
            print()
            name_input = input("회의실 이름 : ")
            capacity_input = input("수용 인원 : ")
            floor_input = input("위치 : ")

            # 회의실 이름 -> 수용 인원 -> 위치 순서로 가장 먼저 발견된 오류 1개만 안내
            error = None
            if name_input == "":
                error = "회의실 이름을 입력해주세요."
            elif not re.fullmatch(r"[0-9][A-Z]", name_input):
                error = "회의실 이름 형식이 올바르지 않습니다. 예) 8C"
            elif capacity_input == "":
                error = "수용 인원을 입력해주세요."
            elif not re.fullmatch(r"[0-9]+", capacity_input):
                error = "수용 인원은 숫자만 입력해주세요"
            elif not (4 <= int(capacity_input) <= 8):
                error = "수용 인원은 4명 이상 8명 이하로 입력해주세요."
            elif floor_input == "":
                error = "위치를 입력해주세요."
            elif not re.fullmatch(r"[0-9]", floor_input):
                error = "위치는 층 번호 숫자 1자리만 입력해주세요."
            elif not (1 <= int(floor_input) <= 9):
                error = "위치는 1층 이상 9층 이하로 입력해주세요."
            if error:
                print()
                print_error(error)
                print("다시 입력해 주세요.")
                continue

            capacity = int(capacity_input)
            floor = int(floor_input)

            print()
            if not confirm("정말 추가하시겠습니까?"):
                return

            try:
                self.room_service.create_room(
                    admin=self.user,
                    room_name_input=name_input,
                    capacity=capacity,
                    floor=floor,
                )
            except (RoomBookingError, RoomAdminRequiredError, AuthError, PenaltyError) as e:
                print()
                print_error(str(e))
                print("다시 입력해 주세요.")
                continue

            print_success("회의실이 추가됐습니다.")
            pause()
            return

    def _get_room_edit_listing(self):
        """삭제/수정 메뉴용 회의실 목록과 상태/현황/예약일 정보를 결합해 반환한다.

        반환: (rooms 정렬목록, overview_by_name) / 오류 시 (None, None)
        """
        try:
            overview = self.room_service.get_room_operational_overview(self.user)
        except (RoomBookingError, RoomAdminRequiredError, AuthError, PenaltyError) as e:
            print_error(str(e))
            pause()
            return None, None
        rooms = sorted(self.room_service.get_all_rooms(), key=lambda room: room.name)
        overview_by_name = {item.room_name: item for item in overview}
        return rooms, overview_by_name

    def _read_room_number(self, room_count):
        """회의실 선택 번호 입력 검증 (기획서 6.6.1.7.2 / 6.6.1.7.3)

        반환: ("return", None) 복귀 / ("retry", None) 오류 후 재입력 / ("ok", index0) 선택
        """
        raw = input("선택(번호) : ")
        if raw == "":
            print_error("회의실 번호를 입력해주세요")
            return "retry", None
        if not re.fullmatch(r"[0-9]+", raw):
            print_error("회의실 번호는 숫자만 입력해주세요")
            return "retry", None
        number = int(raw)
        if number == 0:
            return "return", None
        if not (1 <= number <= room_count):
            print_error("존재하지 않는 회의실 번호입니다.")
            return "retry", None
        return "ok", number - 1

    def _delete_room(self):
        """회의실 삭제 (기획서 6.6.1.7.2)"""
        print_header("회의실 수정 메뉴 (삭제)")
        rooms, overview_by_name = self._get_room_edit_listing()
        if rooms is None:
            return
        if not rooms:
            print_info("등록된 회의실이 없습니다.")
            pause()
            return

        print(f"\n{'번호':<6}{'이름':<14}{'상태':<10}{'현황':<10}예약일")
        print("-" * 60)
        for index, room in enumerate(rooms, 1):
            overview = overview_by_name.get(room.name)
            operational = overview.operational_status if overview else "예약없음"
            status_kr = self._status_display_for_change_menu(room, operational)
            reservation = (overview.reservation_summary if overview else "X").splitlines() or ["X"]
            print(f"{index:<6}{room.name:<14}{status_kr:<10}{operational:<10}{reservation[0]}")
            for line in reservation[1:]:
                print(f"{'':<40}{line}")
        print("\n0. 돌아가기")

        while True:
            outcome, index = self._read_room_number(len(rooms))
            if outcome == "return":
                return
            if outcome == "retry":
                print("다시 입력해 주세요.")
                continue

            selected_room = rooms[index]
            overview = overview_by_name.get(selected_room.name)
            operational = overview.operational_status if overview else "예약없음"

            # 설계 6.6.1.7.2 예외 문구 순서: 점검중 -> 정기점검 -> 사용불가 -> 사용중 -> 예약있음
            error_message = None
            if selected_room.status == ResourceStatus.MAINTENANCE:
                error_message = "점검중인 회의실은 삭제할 수 없습니다."
            elif self.room_service.get_active_or_scheduled_room_maintenance(selected_room.id):
                error_message = "정기 점검 예약이 있어 삭제할 수 없습니다."
            elif selected_room.status == ResourceStatus.DISABLED:
                error_message = "사용불가 상태인 회의실은 삭제할 수 없습니다."
            elif operational == "사용중":
                error_message = "사용중인 회의실은 삭제할 수 없습니다."
            elif operational == "예약있음":
                error_message = "예약이 있는 회의실은 삭제할 수 없습니다"
            if error_message:
                print_error(error_message)
                print("다시 선택해 주세요.")
                continue

            print()
            if not confirm("정말 삭제하시겠습니까?"):
                return

            try:
                self.room_service.delete_room(admin=self.user, room_id=selected_room.id)
            except (RoomBookingError, RoomAdminRequiredError, AuthError, PenaltyError) as e:
                print()
                print_error(str(e))
                print("다시 선택해 주세요.")
                continue

            print_success("회의실이 삭제됐습니다.")
            pause()
            return

    def _modify_room(self):
        """회의실 수정 (기획서 6.6.1.7.3) - 수용 인원/위치 변경"""
        print_header("회의실 수정 메뉴 (수정)")
        rooms, overview_by_name = self._get_room_edit_listing()
        if rooms is None:
            return
        if not rooms:
            print_info("등록된 회의실이 없습니다.")
            pause()
            return

        print(f"\n{'번호':<6}{'이름':<14}{'수용인원':<8}{'위치':<8}{'상태':<10}{'현황':<10}예약일")
        print("-" * 72)
        for index, room in enumerate(rooms, 1):
            overview = overview_by_name.get(room.name)
            operational = overview.operational_status if overview else "예약없음"
            status_kr = self._status_display_for_change_menu(room, operational)
            reservation = (overview.reservation_summary if overview else "X").splitlines() or ["X"]
            print(
                f"{index:<6}{room.name:<14}{str(room.capacity) + '명':<8}{room.location:<8}"
                f"{status_kr:<10}{operational:<10}{reservation[0]}"
            )
            for line in reservation[1:]:
                print(f"{'':<56}{line}")
        print("\n0. 돌아가기")

        while True:
            outcome, index = self._read_room_number(len(rooms))
            if outcome == "return":
                return
            if outcome == "retry":
                print("다시 입력해 주세요.")
                continue

            selected_room = rooms[index]
            overview = overview_by_name.get(selected_room.name)
            operational = overview.operational_status if overview else "예약없음"

            if selected_room.status != ResourceStatus.AVAILABLE:
                print_error("해당 회의실은 수정할 수 없습니다. (회의실 상태 조건 미충족)")
                print("다시 선택해 주세요.")
                continue
            if operational != "예약없음":
                print_error("해당 회의실은 수정할 수 없습니다. (회의실 예약 있음)")
                print("다시 선택해 주세요.")
                continue

            new_capacity = None
            new_floor = None
            while True:
                print()
                capacity_input = input("새 수용 인원 : ")
                floor_input = input("새 위치 : ")
                # 수용 인원/위치 규칙은 회의실 추가(_add_room)와 동일
                error = None
                if capacity_input == "":
                    error = "수용 인원을 입력해주세요."
                elif not re.fullmatch(r"[0-9]+", capacity_input):
                    error = "수용 인원은 숫자만 입력해주세요"
                elif not (4 <= int(capacity_input) <= 8):
                    error = "수용 인원은 4명 이상 8명 이하로 입력해주세요."
                elif floor_input == "":
                    error = "위치를 입력해주세요."
                elif not re.fullmatch(r"[0-9]", floor_input):
                    error = "위치는 층 번호 숫자 1자리만 입력해주세요."
                elif not (1 <= int(floor_input) <= 9):
                    error = "위치는 1층 이상 9층 이하로 입력해주세요."
                if error:
                    print()
                    print_error(error)
                    print("다시 입력해 주세요.")
                    continue
                new_capacity = int(capacity_input)
                new_floor = int(floor_input)
                break

            print()
            if not confirm("정말 수정하시겠습니까?"):
                return

            try:
                self.room_service.update_room_info(
                    admin=self.user,
                    room_id=selected_room.id,
                    capacity=new_capacity,
                    floor=new_floor,
                )
            except (RoomBookingError, RoomAdminRequiredError, AuthError, PenaltyError) as e:
                print()
                print_error(str(e))
                print("다시 선택해 주세요.")
                continue

            print_success("회의실이 수정됐습니다.")
            pause()
            return
            return

    def _status_display_for_change_menu(self, room, operational):
        """상태변경 목록(6.6.1.2)용 상태 표시값.

        점검중(maintenance) / 사용불가(disabled 또는 당일 점유=사용중) / 사용가능(그 외)
        """
        if room.status == ResourceStatus.MAINTENANCE:
            return "점검중"
        if room.status == ResourceStatus.DISABLED or operational == "사용중":
            return "사용불가"
        return "사용가능"

    def _change_room_status(self):
        """회의실 목록 조회 및 상태 변경 (기획서 6.6.1.2)"""
        print_header("회의실 목록 조회 및 상태 변경")
        rooms, overview_by_name = self._get_room_edit_listing()
        if rooms is None:
            return
        if not rooms:
            print_info("등록된 회의실이 없습니다.")
            pause()
            return

        print(f"\n{'번호':<6}{'이름':<14}{'수용인원':<8}{'위치':<8}{'상태':<10}정기점검")
        print("-" * 64)
        for index, room in enumerate(rooms, 1):
            overview = overview_by_name.get(room.name)
            operational = overview.operational_status if overview else "예약없음"
            status_kr = self._status_display_for_change_menu(room, operational)
            # 정기점검 컬럼: 'X' 또는 'YYYY-MM-DD - YYYY-MM-DD'
            schedules = self.room_service.get_active_or_scheduled_room_maintenance(room.id)
            if schedules:
                nearest = sorted(schedules, key=lambda s: (s.start_time, s.id))[0]
                maintenance = f"{nearest.start_time[:10]} - {nearest.end_time[:10]}"
            else:
                maintenance = "X"
            print(
                f"{index:<6}{room.name:<14}{str(room.capacity) + '명':<8}{room.location:<8}"
                f"{status_kr:<10}{maintenance}"
            )
        print("\n0 : 취소")

        while True:
            outcome, idx = self._read_room_number(len(rooms))
            if outcome == "return":
                return
            if outcome == "retry":
                print("다시 입력해 주세요.")
                continue
            break
        selected_room = rooms[idx]

        # 상태 변경 / 정기 점검 선택 (정기점검에서 기존 점검 취소를 거절하면 재선택)
        while True:
            print("\n1. 상태 변경")
            print("2. 정기 점검")
            print("0. 취소")
            while True:
                action = input("선택 : ").strip()
                if action in ("0", "1", "2"):
                    break
                print_error("0, 1, 2 중에서 입력해주세요.")
                print("다시 입력해 주세요.")
            if action == "0":
                return
            if action == "2":
                if self._schedule_room_maintenance(selected_room) == "back":
                    continue
                return

            # action == "1": 상태 변경 (기획서 6.6.1.2.1)
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

            print()
            if not confirm("계속하시겠습니까?"):
                return

            try:
                room, cancelled = self.room_service.update_room_status(
                    admin=self.user, room_id=selected_room.id, new_status=new_status
                )
                print_success(
                    f"상태가 변경되었습니다: {format_status_badge(new_status.value)}"
                )
                if cancelled:
                    print_info(f"자동 취소된 예약: {len(cancelled)}건")
            except (RoomBookingError, RoomAdminRequiredError, AuthError, PenaltyError) as e:
                print_error(str(e))
            pause()
            return

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
        """장비 상태 변경 - 기획서 6.6.2.2"""

        def _print_equipment_table(equipment_list):
            """장비 목록을 clear 후 최상단에 출력 (고정 효과)"""
            os.system("clear")
            print()
            print("=" * 50)
            print("  장비 목록")
            print("=" * 50)
            headers = ["번호", "이름", "종류", "시리얼번호", "상태"]
            rows = [
                [
                    str(i + 1),
                    item.name,
                    item.asset_type,
                    item.serial_number,
                    format_status_badge(item.status.value),
                ]
                for i, item in enumerate(equipment_list)
            ]
            print(format_table(headers, rows))
            print("-" * 50)
            print("  +. 편집")
            print("  0. 돌아가기")

        def _has_returned_today(equipment_id):
            """오늘 해당 장비의 반납이 승인된 예약이 있는지 확인 (규칙 4)"""
            today_str = self.policy_service.clock.now().date().isoformat()
            for bk in self.equipment_service.get_equipment_bookings(equipment_id):
                if bk.status in {
                    EquipmentBookingStatus.RETURNED,
                    EquipmentBookingStatus.RETURN_REQUESTED,
                }:
                    if bk.end_time[:10] == today_str:
                        return True
            return False

        equipment_list = self.equipment_service.get_all_equipment()
        if not equipment_list:
            print_info("등록된 장비가 없습니다.")
            pause()
            return

        # ── 가. 장비 선택 루프 ──────────────────────────────
        log_lines = []
        while True:
            _print_equipment_table(equipment_list)
            for line in log_lines:
                print(line)
            print()
            raw = input("선택: ").strip()

            if raw == "0":
                return

            if raw == "+":
                self._manage_equipment_resources()
                # 편집 후 목록 갱신
                equipment_list = self.equipment_service.get_all_equipment()
                log_lines = []
                continue

            if not raw.isdigit():
                log_lines = ["✗ 숫자를 입력해주세요."]
                continue

            idx = int(raw) - 1
            if idx < 0 or idx >= len(equipment_list):
                log_lines = ["✗ 목록에 존재하는 번호를 입력해주세요."]
                continue

            selected_equipment = equipment_list[idx]

            # 규칙 4: 현재 점검중이고 오늘 반납 없으면 변경 불가
            if selected_equipment.status == ResourceStatus.MAINTENANCE:
                if not _has_returned_today(selected_equipment.id):
                    log_lines = ["✗ 해당 장비는 변경할 수 없습니다."]
                    continue

            # ── 나. 날짜 선택 (캘린더) ──────────────────────
            reservations = self.equipment_service.get_equipment_bookings(selected_equipment.id)
            calendar_overlay = CalendarOverlay(
                selected_equipment, reservations, self.policy_service.clock
            )
            selected_date_str = calendar_overlay.show()

            if selected_date_str is None:
                # 0 입력 → 가 단계로 복귀
                equipment_list = self.equipment_service.get_all_equipment()
                log_lines = []
                continue

            selected_date = date.fromisoformat(selected_date_str)
            today = self.policy_service.clock.now().date()
            is_future = selected_date > today

            # ── 다. 변경할 상태 선택 ────────────────────────
            status_map = {
                "1": ResourceStatus.AVAILABLE,
                "2": ResourceStatus.MAINTENANCE,
                "3": ResourceStatus.DISABLED,
            }
            status_log = []
            while True:
                os.system("clear")
                print()
                print("=" * 50)
                print("  변경할 상태를 선택해주세요.")
                print("=" * 50)
                print(f"  장비: {selected_equipment.name}({selected_equipment.serial_number})")
                print(f"  선택 날짜: {selected_date_str}")
                print()
                print("  1. 사용가능 (available)")
                print("  2. 점검중 (maintenance)")
                print("  3. 사용불가 (disabled)")
                print("-" * 50)
                print("  0. 취소")
                for line in status_log:
                    print(line)
                status_log = []
                print()
                choice = input("선택: ").strip()

                if choice == "0":
                    # 나 단계(캘린더)로 돌아가기
                    break

                if not choice or choice.isspace():
                    status_log = ["✗ 번호를 입력해주세요."]
                    continue

                if not choice.isdigit():
                    status_log = ["✗ 숫자를 입력해주세요."]
                    continue

                if choice not in status_map:
                    status_log = ["✗ 목록에 존재하는 번호를 입력해주세요."]
                    continue

                new_status = status_map[choice]

                # 현재 날짜 예외처리: 규칙 4 위배 체크
                if not is_future:
                    if new_status == ResourceStatus.MAINTENANCE:
                        if not _has_returned_today(selected_equipment.id):
                            status_log = ["✗ 해당 장비는 변경할 수 없습니다."]
                            continue

                # 미래 날짜 예외처리: 해당 날짜에 예약 존재 체크
                if is_future:
                    has_booking = False
                    for bk in reservations:
                        bk_start = date.fromisoformat(bk.start_time[:10])
                        bk_end = date.fromisoformat(bk.end_time[:10])
                        if bk_start <= selected_date <= bk_end:
                            has_booking = True
                            break
                    if has_booking:
                        status_log = ["✗ 해당 날짜에 예약이 존재하여 상태를 변경할 수 없습니다."]
                        continue

                # ── 라. 최종 확인 ────────────────────────────
                os.system("clear")
                print()
                print("=" * 50)
                print("  정말로 변경하시겠습니까?")
                print("=" * 50)
                print(f"  장비: {selected_equipment.name}({selected_equipment.serial_number})")
                print(f"  선택 날짜: {selected_date_str}")
                print(f"  변경 상태: {format_status_badge(new_status.value)}")
                print()
                confirm_input = input("정말로 수정하시겠습니까?[y/n]: ").strip().lower()

                if confirm_input in ("y", "yes", "예", "ㅇ"):
                    try:
                        if not is_future:
                            # 현재 시점 상태 변경
                            equip, cancelled = self.equipment_service.update_equipment_status(
                                admin=self.user,
                                equipment_id=selected_equipment.id,
                                new_status=new_status,
                            )
                            print_success(f"✓ 상태가 변경되었습니다: {format_status_badge(new_status.value)}")
                            if cancelled:
                                print_info(f"자동 취소된 예약: {len(cancelled)}건")
                        else:
                            # 미래 시점 상태 변경 → future_status_changes에 직접 추가
                            from src.storage.repositories import EquipmentAssetRepository, UnitOfWork
                            from src.storage.file_lock import global_lock
                            equipment_repo = self.equipment_service.equipment_repo
                            current_equip = equipment_repo.get_by_id(selected_equipment.id)
                            if current_equip is None:
                                print_error("장비를 찾을 수 없습니다.")
                            else:
                                existing_items = decode_future_status_changes(
                                    current_equip.future_status_changes
                                )
                                new_item = {
                                    "id": generate_id(),
                                    "start_time": f"{selected_date_str}T09:00",
                                    "end_time": f"{selected_date_str}T18:00",
                                    "status": new_status.value,
                                    "restore_status": ResourceStatus.AVAILABLE.value,
                                    "state": "pending",
                                }
                                # 같은 날짜 기존 항목 덮어쓰기
                                existing_items = [
                                    it for it in existing_items
                                    if it["start_time"][:10] != selected_date_str
                                ]
                                existing_items.append(new_item)
                                updated_equip = replace(
                                    current_equip,
                                    future_status_changes=encode_future_status_changes(existing_items),
                                    updated_at=now_iso(),
                                )
                                with global_lock(), UnitOfWork():
                                    equipment_repo.update(updated_equip)
                                print_success(f"✓ 상태가 변경되었습니다: {format_status_badge(new_status.value)}")

                    except (EquipmentBookingError, EquipmentAdminRequiredError, AuthError, PenaltyError) as e:
                        print_error(str(e))

                    print("\n0. 메뉴 화면으로 돌아가기")
                    while True:
                        k = input("선택: ").strip()
                        if k == "0":
                            return

                elif confirm_input in ("n", "no", "아니오", "ㄴ"):
                    print_info("상태 변경을 취소했습니다.")
                    return
                else:
                    status_log = ["✗ y 또는 n을 입력해주세요."]
                    continue

                return  # 라 단계 완료 후 메뉴 복귀

            # choice == "0" → 나 단계(캘린더)로 돌아가기 위해 while True 재진입
            continue



    def _manage_equipment_resources(self):
        """장비 편집 메뉴 진입 - EquipmentEdit 클래스로 위임"""
        equipment_list = self.equipment_service.get_all_equipment()
        booking_list = self.equipment_service.get_all_bookings(self.user)
        editor = EquipmentEdit(
            equipment_list=equipment_list,
            booking_list=booking_list,
            equipment_service=self.equipment_service,
            user=self.user,
        )
        editor.run()

    def _edit_equipment_resource(self):
        """장비 이름 편집 - EquipmentEdit._edit_equipment()로 위임"""
        equipment_list = self.equipment_service.get_all_equipment()
        booking_list = self.equipment_service.get_all_bookings(self.user)
        editor = EquipmentEdit(
            equipment_list=equipment_list,
            booking_list=booking_list,
            equipment_service=self.equipment_service,
            user=self.user,
        )
        editor._edit_equipment()

    def _delete_equipment_resource(self):
        """장비 삭제 - EquipmentEdit._delete_equipment()로 위임"""
        equipment_list = self.equipment_service.get_all_equipment()
        booking_list = self.equipment_service.get_all_bookings(self.user)
        editor = EquipmentEdit(
            equipment_list=equipment_list,
            booking_list=booking_list,
            equipment_service=self.equipment_service,
            user=self.user,
        )
        editor._delete_equipment()

    def _add_equipment_resource(self):
        """장비 추가 - EquipmentEdit._add_equipment()로 위임"""
        equipment_list = self.equipment_service.get_all_equipment()
        booking_list = self.equipment_service.get_all_bookings(self.user)
        editor = EquipmentEdit(
            equipment_list=equipment_list,
            booking_list=booking_list,
            equipment_service=self.equipment_service,
            user=self.user,
        )
        editor._add_equipment()





    def _show_all_equipment_bookings(self):
        """전체 장비 예약 조회 - 기획서 6.6.2.1"""
        print_header("최근 장비 예약")

        bookings = self._get_equipment_bookings_or_abort()
        if bookings is None:
            return

        # 현재/미래 예약만 필터링 (사용중, 예약있음)
        active_statuses = {
            EquipmentBookingStatus.RESERVED,
            EquipmentBookingStatus.PICKUP_REQUESTED,
            EquipmentBookingStatus.CHECKED_OUT,
            EquipmentBookingStatus.RETURN_REQUESTED,
        }
        bookings = [b for b in bookings if b.status in active_statuses]

        if not bookings:
            print_info("예약 내역이 없습니다.")
            pause()
            return

        # 종료일(end_time) 기준 내림차순 정렬
        bookings.sort(key=lambda b: b.end_time, reverse=True)

        headers = ["시리얼번호", "장비", "유저ID", "대여 기간", "상태"]
        rows = []
        for booking in bookings:
            equip = self.equipment_service.get_equipment(booking.equipment_id)
            user = self._get_booking_user_or_abort(booking.user_id)
            if user is None:
                return

            if booking.status in {EquipmentBookingStatus.CHECKED_OUT, EquipmentBookingStatus.RETURN_REQUESTED}:
                status_label = "[사 용 중]"
            else:
                status_label = "[예약 있음]"

            rows.append([
                equip.serial_number if equip else "-",
                equip.name if equip else "-",
                user.username,
                format_booking_time_range(booking.start_time, booking.end_time),
                status_label,
            ])

        print(format_table(headers, rows))
        print("-" * 50)
        pause()

    def _equipment_checkout(self):
        """장비 대여 승인 처리 - 기획서 6.6.2.3"""
        print_header("장비 대여 시작")

        all_bookings = self._get_equipment_bookings_or_abort()
        if all_bookings is None:
            return
        pending = [
            b for b in all_bookings if b.status == EquipmentBookingStatus.PICKUP_REQUESTED
        ]

        if not pending:
            print_info("i 대여 대기 중인 요청이 없습니다.")
            pause()
            return

        # 묶음 예약: group_id 기준으로 대표 예약 1개만 목록에 표시
        seen_groups = set()
        items = []
        # 시리얼번호 오름차순 정렬
        pending_sorted = sorted(pending, key=lambda b: (
            self.equipment_service.get_equipment(b.equipment_id).serial_number
            if self.equipment_service.get_equipment(b.equipment_id) else ""
        ))
        for booking in pending_sorted:
            key = booking.group_id if booking.group_id else booking.id
            if key in seen_groups:
                continue
            seen_groups.add(key)
            equip = self.equipment_service.get_equipment(booking.equipment_id)
            user = self._get_booking_user_or_abort(booking.user_id)
            if user is None:
                return
            if booking.group_id:
                # 묶음 예약이면 같은 그룹 장비들 함께 표시
                group_members = [
                    b for b in pending_sorted if b.group_id == booking.group_id
                ]
                equip_names = ", ".join(
                    f"{self.equipment_service.get_equipment(b.equipment_id).name}({self.equipment_service.get_equipment(b.equipment_id).serial_number})"
                    if self.equipment_service.get_equipment(b.equipment_id) else "-"
                    for b in group_members
                )
                label = f"{equip_names} / {user.username} / {format_booking_time_range(booking.start_time, booking.end_time)}"
            else:
                label = f"{equip.name if equip else '-'}({equip.serial_number if equip else '-'}) / {user.username} / {format_booking_time_range(booking.start_time, booking.end_time)}"
            items.append((booking.id, label))

        booking_id = select_from_list(items, "대여 시작할 예약 선택 (번호)")
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
            print_success("요청을 승인했습니다.")
        except (EquipmentBookingError, EquipmentAdminRequiredError, AuthError, PenaltyError) as e:
            print_error(str(e))

        pause()

    def _equipment_return(self):
        """장비 반납 승인 처리 - 기획서 6.6.2.4"""
        print_header("장비 반납 승인")

        all_bookings = self._get_equipment_bookings_or_abort()
        if all_bookings is None:
            return
        requested = [
            b for b in all_bookings if b.status == EquipmentBookingStatus.RETURN_REQUESTED
        ]

        if not requested:
            print_info("i 반납 승인 대기 중인 요청이 없습니다.")
            pause()
            return

        # 반납일(end_time) 기준 오름차순 정렬, 묶음 내부는 시리얼번호 오름차순
        requested_sorted = sorted(requested, key=lambda b: (
            b.end_time,
            self.equipment_service.get_equipment(b.equipment_id).serial_number
            if self.equipment_service.get_equipment(b.equipment_id) else ""
        ))

        seen_groups = set()
        items = []
        for booking in requested_sorted:
            key = booking.group_id if booking.group_id else booking.id
            if key in seen_groups:
                continue
            seen_groups.add(key)
            equip = self.equipment_service.get_equipment(booking.equipment_id)
            user = self._get_booking_user_or_abort(booking.user_id)
            if user is None:
                return
            if booking.group_id:
                group_members = sorted(
                    [b for b in requested_sorted if b.group_id == booking.group_id],
                    key=lambda b: (
                        self.equipment_service.get_equipment(b.equipment_id).serial_number
                        if self.equipment_service.get_equipment(b.equipment_id) else ""
                    )
                )
                equip_names = ", ".join(
                    f"{self.equipment_service.get_equipment(b.equipment_id).name}({self.equipment_service.get_equipment(b.equipment_id).serial_number})"
                    if self.equipment_service.get_equipment(b.equipment_id) else "-"
                    for b in group_members
                )
                label = f"{equip_names} / {user.username} / {format_booking_time_range(booking.start_time, booking.end_time)}"
            else:
                label = f"{equip.name if equip else '-'}({equip.serial_number if equip else '-'}) / {user.username} / {format_booking_time_range(booking.start_time, booking.end_time)}"
            items.append((booking.id, label))

        booking_id = select_from_list(items, "반납 승인할 요청 선택 (번호)")
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
            self.equipment_service.approve_return_request(self.user, booking_id)
            print_success("요청을 승인했습니다.")
        except (EquipmentBookingError, EquipmentAdminRequiredError, AuthError, PenaltyError) as e:
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
        """관리자 장비 예약 변경 - 기획서 6.6.2.5"""
        print_header("장비 예약 변경 (관리자용)")

        all_bookings = self._get_equipment_bookings_or_abort()
        if all_bookings is None:
            return
        modifiable = [
            b for b in all_bookings if b.status == EquipmentBookingStatus.RESERVED
        ]

        if not modifiable:
            print_info("i 변경 가능한 예약이 없습니다.")
            pause()
            return

        # 종료일 내림차순, 묶음 내부 시리얼번호 오름차순
        modifiable_sorted = sorted(modifiable, key=lambda b: (
            b.end_time,
            self.equipment_service.get_equipment(b.equipment_id).serial_number
            if self.equipment_service.get_equipment(b.equipment_id) else ""
        ), reverse=True)

        seen_groups = set()
        items = []
        for booking in modifiable_sorted:
            key = booking.group_id if booking.group_id else booking.id
            if key in seen_groups:
                continue
            seen_groups.add(key)
            equip = self.equipment_service.get_equipment(booking.equipment_id)
            user = self._get_booking_user_or_abort(booking.user_id)
            if user is None:
                return
            if booking.group_id:
                group_members = sorted(
                    [b for b in modifiable_sorted if b.group_id == booking.group_id],
                    key=lambda b: (
                        self.equipment_service.get_equipment(b.equipment_id).serial_number
                        if self.equipment_service.get_equipment(b.equipment_id) else ""
                    )
                )
                equip_names = ", ".join(
                    f"{self.equipment_service.get_equipment(b.equipment_id).name}({self.equipment_service.get_equipment(b.equipment_id).serial_number})"
                    if self.equipment_service.get_equipment(b.equipment_id) else "-"
                    for b in group_members
                )
                label = f"{equip_names} / {user.username} / {format_booking_time_range(booking.start_time, booking.end_time)}"
            else:
                label = f"{equip.name if equip else '-'}({equip.serial_number if equip else '-'}) / {user.username} / {format_booking_time_range(booking.start_time, booking.end_time)}"
            items.append((booking.id, label))

        # 가. 변경할 예약 선택
        booking_id = select_from_list(items, "변경할 예약 선택 (번호)")
        if not booking_id:
            return

        # 나. 날짜 입력
        while True:
            print()
            print("  이용 시간은 대여 시작일 09:00 부터 반납일 18:00까지 입니다.")
            print("  예약 시작일은 기존 예약 시작일(시작일 포함) 기준으로부터 최대 180일 사이에서")
            print("  선택할 수 있고, 예약기간은 최대 14일 입니다.")
            start_date, end_date = get_daily_date_range_input("시작 날짜", "종료 날짜")
            if start_date is None or end_date is None:
                # 0 입력 → 이전단계 복귀
                return

            # 묶음 예약 충돌 체크
            selected_booking = next((b for b in modifiable if b.id == booking_id), None)
            if selected_booking and selected_booking.group_id:
                group_members = [b for b in modifiable if b.group_id == selected_booking.group_id]
                conflict_names = []
                for member in group_members:
                    try:
                        self.equipment_service.admin_modify_daily_booking(
                            admin=self.user,
                            booking_id=member.id,
                            start_date=start_date,
                            end_date=end_date,
                        )
                    except (EquipmentBookingError, EquipmentAdminRequiredError, AuthError, PenaltyError) as e:
                        equip = self.equipment_service.get_equipment(member.equipment_id)
                        if equip:
                            conflict_names.append(equip.name)
                if conflict_names:
                    print_error(f"{'，'.join(conflict_names)}의 예약이 이미 존재합니다.")
                    continue

            self._print_review_rows([("예약 ID", booking_id[:8]), ("새 기간", f"{start_date} ~ {end_date}")])
            decision = review_action("관리자 장비 예약 변경 검토", "저장")
            if decision == "confirm":
                break
            if decision == "cancel":
                print_info("예약 변경을 취소했습니다.")
                return

        # 다. 최종 확인 및 변경
        try:
            self.equipment_service.admin_modify_daily_booking(
                admin=self.user,
                booking_id=booking_id,
                start_date=start_date,
                end_date=end_date,
            )
            print_success(f"✓ 예약이 {start_date} 09:00 ~ {end_date} 18:00 로 변경되었습니다.")
            print_success("예약을 변경했습니다.")
        except (EquipmentBookingError, EquipmentAdminRequiredError, AuthError, PenaltyError) as e:
            print_error(str(e))

        print("\n0. 상위 메뉴로 복귀")
        while True:
            k = input("선택: ").strip()
            if k == "0":
                return

    def _admin_cancel_equipment_booking(self):
        """관리자 장비 예약 취소 - 기획서 6.6.2.6"""
        print_header("장비 예약 취소 (관리자용)")

        all_bookings = self._get_equipment_bookings_or_abort()
        if all_bookings is None:
            return
        cancellable = [
            b for b in all_bookings if b.status == EquipmentBookingStatus.RESERVED
        ]

        if not cancellable:
            print_info("i 취소 가능한 예약이 없습니다.")
            pause()
            return

        # 종료일 내림차순
        cancellable_sorted = sorted(cancellable, key=lambda b: b.end_time, reverse=True)
        items = []
        for booking in cancellable_sorted:
            equip = self.equipment_service.get_equipment(booking.equipment_id)
            user = self._get_booking_user_or_abort(booking.user_id)
            if user is None:
                return
            label = f"{equip.name if equip else '-'}({equip.serial_number if equip else '-'}) / {user.username} / {format_booking_time_range(booking.start_time, booking.end_time)}"
            items.append((booking.id, label))

        # 가. 취소할 예약 선택
        booking_id = select_from_list(items, "취소할 예약 선택 (번호)")
        if not booking_id:
            return

        # 나. 취소 사유 입력
        while True:
            reason = input("\n취소 사유(최대 20자): ").strip()
            # 0 단독 입력 시 이전단계 복귀
            if reason == "0":
                return
            valid, error = validate_reason(reason)
            if not valid:
                print_error(error)
                continue
            break

        # 다. 최종 확인
        while True:
            self._print_review_rows([("예약 ID", booking_id[:8]), ("취소 사유", reason or "-")])
            confirm_input = input("정말로 취소하시겠습니까?[y/n]: ").strip().lower()
            if confirm_input in ("y", "yes", "예", "ㅇ"):
                try:
                    self.equipment_service.admin_cancel_booking(self.user, booking_id, reason)
                    print_success("예약을 취소했습니다.")
                except (EquipmentBookingError, EquipmentAdminRequiredError, AuthError, PenaltyError) as e:
                    print_error(str(e))
                print("\n0. 상위 메뉴로 복귀")
                while True:
                    k = input("선택: ").strip()
                    if k == "0":
                        return
            elif confirm_input in ("n", "no", "아니오", "ㄴ"):
                print_info("취소를 취소했습니다.")
                return
            else:
                print_error("y 또는 n을 입력해주세요.")

    def _schedule_room_maintenance(self, selected_room):
        """정기 점검 (관리자, 기획서 6.6.1.2.2 / 설계 1.7.1)

        반환: "back" -> 기존 점검 취소를 거절(상태변경/정기점검 재선택), 그 외 None.
        """
        existing = self.room_service.get_active_or_scheduled_room_maintenance(selected_room.id)
        if existing:
            has_active = any(schedule.status == "active" for schedule in existing)
            if has_active:
                prompt = "진행중인 정기 점검 예약이 있습니다. 취소하시겠습니까?"
            else:
                prompt = "기존 정기 점검 예약이 있습니다. 취소하시겠습니까?"
            if not confirm(prompt):
                return "back"
            try:
                cancelled = self.room_service.cancel_room_maintenance(
                    admin=self.user, room_id=selected_room.id
                )
            except (RoomBookingError, RoomAdminRequiredError, AuthError, PenaltyError) as e:
                print_error(str(e))
                pause()
                return
            print_success(
                f"기존 정기 점검 예약이 취소됐습니다 "
                f"({cancelled.start_time[:10]} ~ {cancelled.end_time[:10]})"
            )
            pause()
            return

        # 기존 점검 없음 -> 신규 등록
        print_header(f"정기 점검 (회의실 : {selected_room.name})")
        print("\n정기 점검 시작일은 입력한 날짜의 18:00, 종료일은 입력한 날짜의 09:00으로 해석됩니다.")

        def parse_date(value):
            # YYYY-MM-DD 문자열 -> date, 형식 오류 시 None
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                return None
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None

        while True:
            print()
            start_str = input("정기 점검 시작일 (YYYY-MM-DD): ")
            if start_str == "0":
                return
            end_str = input("정기 점검 종료일 (YYYY-MM-DD): ")
            if end_str == "0":
                return

            start_date = parse_date(start_str)
            end_date = parse_date(end_str)
            if start_date is None or end_date is None:
                print()
                print_error("형식에 맞게 다시 입력해주세요.")
                print("다시 입력해 주세요.")
                continue

            valid, error = self.room_service.validate_maintenance_request(
                selected_room.id, start_date, end_date
            )
            if not valid:
                print()
                print_error(error)
                print("다시 입력해 주세요.")
                continue

            print()
            if not confirm("정기 점검 예약하시겠습니까?"):
                return
            try:
                scheduled = self.room_service.schedule_room_maintenance(
                    admin=self.user,
                    room_id=selected_room.id,
                    start_date=start_date,
                    end_date=end_date,
                )
            except (RoomBookingError, RoomAdminRequiredError, AuthError, PenaltyError) as e:
                print()
                print_error(str(e))
                print("다시 입력해 주세요.")
                continue

            print_success("정기 점검이 등록되었습니다.")
            print(f"회의실 : {selected_room.name}")
            print(
                f"점검 기간: {scheduled.start_time[:16].replace('T', ' ')} ~ "
                f"{scheduled.end_time[:16].replace('T', ' ')}"
            )
            pause()
            return

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


def assign_serial(asset_type, abbr, equipment_list):
    """설계서 1.5.3 assign_serial() - 해당 종류의 사용 중이지 않은 가장 빠른 번호로 시리얼 번호 자동 부여"""
    if abbr:
        prefix = abbr.upper()
    else:
        prefix = "".join(
            c.upper() for c in asset_type if c.isascii() and c.isalpha()
        )[:2] or "EQ"

    used_numbers = []
    for item in equipment_list:
        if item.serial_number.startswith(f"{prefix}-"):
            suffix = item.serial_number.split("-", 1)[1]
            if suffix.isdigit():
                used_numbers.append(int(suffix))

    # 비어있는 가장 작은 번호 탐색
    n = 1
    while n in used_numbers:
        n += 1
    return f"{prefix}-{n:03d}"


class EquipmentEdit:
    """설계서 1.5.3 EquipmentEdit - 관리자의 장비 편집(추가/삭제/수정) 메뉴 인터페이스"""

    def __init__(self, equipment_list, booking_list, equipment_service, user):
        self.equipment_list = equipment_list
        self.booking_list = booking_list
        self.equipment_service = equipment_service
        self.user = user

    def run(self):
        """장비 편집 메뉴(1.편집 / 2.삭제 / 3.추가 / 0.취소)를 출력하고 각 메서드로 분기"""
        while True:
            self.equipment_list = self.equipment_service.get_all_equipment()
            self.booking_list = self.equipment_service.get_all_bookings(self.user)
            print_header("장비 편집")
            headers = ["번호", "이름", "종류", "시리얼번호", "상태"]
            rows = [
                [str(i + 1), e.name, e.asset_type, e.serial_number, format_status_badge(e.status.value)]
                for i, e in enumerate(self.equipment_list)
            ]
            print(format_table(headers, rows))
            print("-" * 50)
            print("  1. 편집")
            print("  2. 삭제")
            print("  3. 추가")
            print("  0. 취소")
            choice = input("선택: ").strip()
            if choice == "1":
                self._edit_equipment()
            elif choice == "2":
                self._delete_equipment()
            elif choice == "3":
                self._add_equipment()
            elif choice == "0":
                return
            else:
                print_error("잘못된 선택입니다.")

    def _edit_equipment(self):
        """장비 이름 수정 절차 - 가-나-다-라 순으로 진행"""
        self.equipment_list = self.equipment_service.get_all_equipment()
        self.booking_list = self.equipment_service.get_all_bookings(self.user)

        def _print_table():
            os.system("clear")
            print()
            print("=" * 50)
            print("  장비 편집 - 이름 수정")
            print("=" * 50)
            headers = ["번호", "이름", "종류", "시리얼번호", "상태"]
            rows = [
                [str(i + 1), e.name, e.asset_type, e.serial_number, format_status_badge(e.status.value)]
                for i, e in enumerate(self.equipment_list)
            ]
            print(format_table(headers, rows))
            print("-" * 50)

        # 가. 편집할 장비 선택
        log = []
        target = None
        while True:
            _print_table()
            for line in log:
                print(line)
            log = []
            print("  0. 이전 메뉴로")
            raw = input("\n편집할 장비 번호: ").strip()
            if raw == "0":
                return
            if not raw.isdigit():
                log = ["✗ 숫자를 입력해주세요."]
                continue
            idx = int(raw) - 1
            if idx < 0 or idx >= len(self.equipment_list):
                log = ["✗ 목록에 존재하는 번호를 입력해주세요."]
                continue
            equip = self.equipment_list[idx]
            is_renting = any(
                bk.status in {EquipmentBookingStatus.CHECKED_OUT, EquipmentBookingStatus.RETURN_REQUESTED}
                for bk in self.equipment_service.get_equipment_bookings(equip.id)
            )
            if is_renting:
                log = ["✗ 대여중인 장비는 편집할 수 없습니다."]
                continue
            target = equip
            break

        # 나. 새로운 이름 입력
        log = []
        new_name = None
        all_names = [e.name for e in self.equipment_list if e.id != target.id]
        while True:
            _print_table()
            print(f"  선택한 장비: {target.name} ({target.serial_number})")
            for line in log:
                print(line)
            log = []
            name_input = input("\n새로운 이름을 입력해주세요 (0: 이전): ").strip()
            if name_input == "0":
                return
            if not name_input:
                log = ["✗ 이름을 입력해주세요."]
                continue
            if not re.search(r"[가-힣]", name_input):
                log = ["✗ 한글을 반드시 포함해야 합니다."]
                continue
            if len(name_input) > 10:
                log = ["✗ 10글자 이하로 입력해주세요."]
                continue
            if name_input in all_names:
                log = ["✗ 이미 존재하는 이름입니다."]
                continue
            new_name = name_input
            break

        # 다. 정말로 수정하시겠습니까?[y/n]
        while True:
            os.system("clear")
            print(f"\n  장비: {target.name} → {new_name}")
            confirm_input = input("정말로 수정하시겠습니까?[y/n]: ").strip().lower()
            if confirm_input in ("y", "yes", "예", "ㅇ"):
                try:
                    self.equipment_service.edit_equipment_resource_name(
                        self.user, target.id, new_name
                    )
                    print_success(f"✓ 이름이 변경되었습니다: {new_name}")
                except (EquipmentBookingError, EquipmentAdminRequiredError, AuthError, PenaltyError) as e:
                    print_error(str(e))
                # 라. 완료
                print("\n0. 관리자 메뉴로 복귀")
                while True:
                    k = input("선택: ").strip()
                    if k == "0":
                        return
            elif confirm_input in ("n", "no", "아니오", "ㄴ"):
                print_info("편집을 취소했습니다.")
                return
            else:
                print_error("y 또는 n을 입력해주세요.")

    def _delete_equipment(self):
        """장비 삭제 절차 - 가-나-다 순으로 진행"""
        self.equipment_list = self.equipment_service.get_all_equipment()

        def _print_table():
            os.system("clear")
            print()
            print("=" * 50)
            print("  장비 편집 - 삭제")
            print("=" * 50)
            headers = ["번호", "이름", "종류", "시리얼번호", "상태"]
            rows = [
                [str(i + 1), e.name, e.asset_type, e.serial_number, format_status_badge(e.status.value)]
                for i, e in enumerate(self.equipment_list)
            ]
            print(format_table(headers, rows))
            print("-" * 50)

        # 가. 삭제할 장비 선택
        log = []
        target = None
        while True:
            _print_table()
            for line in log:
                print(line)
            log = []
            print("  0. 이전 메뉴로")
            raw = input("\n삭제할 장비 번호: ").strip()
            if raw == "0":
                return
            if not raw.isdigit():
                log = ["✗ 숫자를 입력해주세요."]
                continue
            idx = int(raw) - 1
            if idx < 0 or idx >= len(self.equipment_list):
                log = ["✗ 목록에 존재하는 번호를 입력해주세요."]
                continue
            if len(self.equipment_list) <= 12:
                log = ["✗ 장비는 최소 12개 이상 유지되어야 합니다."]
                continue
            equip = self.equipment_list[idx]
            has_booking = any(
                bk.status in {
                    EquipmentBookingStatus.RESERVED,
                    EquipmentBookingStatus.PICKUP_REQUESTED,
                    EquipmentBookingStatus.CHECKED_OUT,
                    EquipmentBookingStatus.RETURN_REQUESTED,
                }
                for bk in self.equipment_service.get_equipment_bookings(equip.id)
            )
            if has_booking:
                log = ["✗ 해당 장비는 삭제할 수 없습니다."]
                continue
            target = equip
            break

        # 나. 정말로 삭제하시겠습니까?[y/n]
        while True:
            os.system("clear")
            print(f"\n  삭제할 장비: {target.name} ({target.serial_number})")
            confirm_input = input("정말로 삭제하시겠습니까?[y/n]: ").strip().lower()
            if confirm_input in ("y", "yes", "예", "ㅇ"):
                try:
                    self.equipment_service.delete_equipment_resource(self.user, target.id)
                    print_success(f"✓ 장비를 삭제했습니다: {target.name}({target.serial_number})")
                except (EquipmentBookingError, EquipmentAdminRequiredError, AuthError, PenaltyError) as e:
                    print_error(str(e))
                # 다. 완료
                print("\n0. 상위 메뉴로 복귀")
                while True:
                    k = input("선택: ").strip()
                    if k == "0":
                        return
            elif confirm_input in ("n", "no", "아니오", "ㄴ"):
                print_info("삭제를 취소했습니다.")
                return
            else:
                print_error("y 또는 n을 입력해주세요.")

    def _add_equipment(self):
        """장비 추가 절차 - 가-나-다-라 순으로 진행"""
        self.equipment_list = self.equipment_service.get_all_equipment()

        def _print_table():
            os.system("clear")
            print()
            print("=" * 50)
            print("  장비 편집 - 추가")
            print("=" * 50)
            headers = ["번호", "이름", "종류", "시리얼번호", "상태"]
            rows = [
                [str(i + 1), e.name, e.asset_type, e.serial_number, format_status_badge(e.status.value)]
                for i, e in enumerate(self.equipment_list)
            ]
            print(format_table(headers, rows))
            print("-" * 50)

        if len(self.equipment_list) >= 20:
            print_error("장비는 최대 20개까지 추가할 수 있습니다.")
            pause()
            return

        # 가. 장비 종류 선택
        existing_types = sorted({e.asset_type for e in self.equipment_list})
        log = []
        asset_type = None
        is_new_type = False

        while True:
            _print_table()
            for line in log:
                print(line)
            log = []
            print()
            print("=" * 50)
            print("  장비 종류 선택")
            print("=" * 50)
            for i, t in enumerate(existing_types, 1):
                print(f"  {i}. {t}")
            print(f"  {len(existing_types) + 1}. 직접입력")
            print("-" * 50)
            print("  0. 취소")
            raw = input("선택: ").strip()
            if raw == "0":
                return
            if not raw.isdigit():
                log = ["✗ 숫자를 입력해주세요."]
                continue
            idx = int(raw) - 1
            if idx < 0 or idx > len(existing_types):
                log = ["✗ 목록에 존재하는 번호를 입력해주세요."]
                continue
            if idx == len(existing_types):
                # 가-1. 직접 입력
                type_log = []
                while True:
                    _print_table()
                    for line in type_log:
                        print(line)
                    type_log = []
                    type_input = input("\n추가할 장비의 종류를 입력해주세요. (0: 취소): ").strip()
                    if type_input == "0":
                        break
                    if not type_input or not re.fullmatch(r"[a-zA-Z]+", type_input):
                        type_log = ["✗ 영어만 입력해주세요."]
                        continue
                    if len(type_input) > 15:
                        type_log = ["✗ 15글자 이하로 입력해주세요."]
                        continue
                    asset_type = type_input.lower()
                    is_new_type = True
                    break
                if asset_type is None:
                    continue
            else:
                asset_type = existing_types[idx]
                is_new_type = False
            break

        if asset_type is None:
            return

        # 나. 장비 이름 입력
        all_names = [e.name for e in self.equipment_list]
        log = []
        new_name = None
        while True:
            _print_table()
            for line in log:
                print(line)
            log = []
            name_input = input("\n추가할 장비의 이름을 입력해주세요. (0: 취소): ").strip()
            if name_input == "0":
                return
            if not name_input:
                log = ["✗ 이름을 입력해주세요."]
                continue
            if not re.search(r"[가-힣]", name_input):
                log = ["✗ 한글을 반드시 포함해야 합니다."]
                continue
            if len(name_input) > 10:
                log = ["✗ 10글자 이하로 입력해주세요."]
                continue
            if name_input in all_names:
                log = ["✗ 이미 존재하는 이름입니다."]
                continue
            new_name = name_input
            break

        # 다. 시리얼 번호 영문 약자 입력 (직접입력 시에만)
        abbr = None
        if is_new_type:
            existing_abbrs = {
                e.serial_number.split("-")[0]
                for e in self.equipment_list
                if "-" in e.serial_number
            }
            log = []
            while True:
                _print_table()
                for line in log:
                    print(line)
                log = []
                abbr_input = input("\n시리얼 번호에 사용할 영문 약자 2글자를 입력해주세요. (0: 취소): ").strip()
                if abbr_input == "0":
                    return
                if not re.fullmatch(r"[a-zA-Z]+", abbr_input):
                    log = ["✗ 영어만 입력해주세요."]
                    continue
                if len(abbr_input) != 2:
                    log = ["✗ 영어 약자는 두 글자여야 합니다."]
                    continue
                if abbr_input.upper() in existing_abbrs:
                    log = ["✗ 이미 존재하는 약자입니다."]
                    continue
                abbr = abbr_input.upper()
                break

        # assign_serial()로 시리얼 번호 자동 부여
        new_serial = assign_serial(asset_type, abbr, self.equipment_list)

        # 라. 정말로 추가하시겠습니까?[y/n]
        while True:
            os.system("clear")
            print()
            print("=" * 50)
            print("  추가할 장비 정보 확인")
            print("=" * 50)
            print(f"  종류: {asset_type}")
            print(f"  이름: {new_name}")
            print(f"  시리얼 번호: {new_serial}")
            print()
            confirm_input = input("정말로 추가하시겠습니까?[y/n]: ").strip().lower()
            if confirm_input in ("y", "yes", "예", "ㅇ"):
                try:
                    equipment = self.equipment_service.add_equipment_resource(
                        self.user, new_name, asset_type, abbr=abbr
                    )
                    print_success(f"✓ 장비가 추가되었습니다: {asset_type} / {equipment.name}({equipment.serial_number})")
                except (EquipmentBookingError, EquipmentAdminRequiredError, AuthError, PenaltyError) as e:
                    print_error(str(e))
                print("\n0. 상위 메뉴로 복귀")
                while True:
                    k = input("선택: ").strip()
                    if k == "0":
                        return
            elif confirm_input in ("n", "no", "아니오", "ㄴ"):
                print_info("추가를 취소했습니다.")
                return
            else:
                print_error("y 또는 n을 입력해주세요.")
