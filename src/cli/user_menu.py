"""
일반 사용자 메뉴 - 회의실/장비 예약, 조회, 취소
"""

import re
from datetime import datetime, timedelta
from typing import Any, cast

from src.domain.models import (
    RoomBookingStatus,
    EquipmentBookingStatus,
    WaitingListEntry,
    generate_id,
    now_iso,
)
from src.domain.auth_service import AuthService, AuthError
from src.domain.room_service import RoomService, RoomBookingError
from src.domain.equipment_service import EquipmentService, EquipmentBookingError
from src.domain.penalty_service import PenaltyService, PenaltyError
from src.domain.policy_service import PolicyService
from src.storage.repositories import WaitingListRepository
from src.storage.repositories import UnitOfWork
from src.storage.file_lock import global_lock
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
        waiting_list_repo=None,
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
        self.waiting_list_repo = waiting_list_repo or WaitingListRepository()

    def _run_policy_checks(self):
        try:
            self.policy_service.run_all_checks(resolve_pending=False)
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

    def _print_cancel_impact_preview(self, impact):
        print_subheader("취소 영향 미리보기")
        if impact.is_late_cancel:
            print_warning("직전 취소 패널티 2점이 부과됩니다.")
        if impact.applies_cancel_restriction:
            until = impact.cancel_restriction_until or "-"
            print_warning(f"빈번 취소로 예약 제한이 적용됩니다. (해제일: {until[:10]})")
        if impact.applies_frequent_cancel_penalty:
            print_warning("빈번 취소 패널티 1점이 부과됩니다.")
        if impact.total_penalty_points:
            print_info(f"예상 패널티 점수: {impact.total_penalty_points}점")
        if not impact.penalty_reasons and not impact.applies_cancel_restriction:
            print_info("추가 패널티나 예약 제한 없이 취소됩니다.")

    def _get_memo_input(self):
        return input("예약 메모 (선택, 최대 50자): ").strip()

    def _parse_equipment_selection_numbers(self, raw_value, item_count):
        value = raw_value.strip()
        if not value:
            raise EquipmentBookingError("번호를 입력해주세요.")
        if not re.fullmatch(r"\d+(?: \d+)*|\d+(?:,\d+)*|\d+(?:, \d+)*", value):
            raise EquipmentBookingError("올바른 번호를 입력해주세요. (예: 1 2 3 또는 1,2,3 또는 1, 2, 3)")
        numbers = [int(part) for part in re.split(r", ?| ", value)]
        if len(numbers) != len(set(numbers)):
            raise EquipmentBookingError("중복된 번호가 있습니다. (예: 1, 1, 2) 다시 입력해주세요.")
        if len(numbers) > 3:
            raise EquipmentBookingError("묶음 예약은 최대 3건까지만 가능합니다.")
        if any(number < 1 or number > item_count for number in numbers):
            raise EquipmentBookingError("없는 번호입니다. 다시 입력해주세요.")
        return numbers

    def _print_review_rows(self, rows):
        print_subheader("입력 내용 확인")
        for label, value in rows:
            print(f"  {label}: {value}")

    def _print_booking_result(self, booking, time_label="시간"):
        status = getattr(booking, "status", None)
        print_success("예약 요청이 접수되었습니다." if status and status.value == "pending" else "예약이 완료되었습니다.")
        print(f"  예약 ID: {booking.id[:8]}...")
        print(f"  {time_label}: {format_booking_time_range(booking.start_time, booking.end_time)}")
        if status and status.value == "pending":
            print_warning("동일 시간대 경쟁 예약이 있어 대기 상태로 접수되었습니다. 운영 시계 이동 시 정책에 따라 확정 여부가 결정됩니다.")

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
                status = cast(dict[str, Any], self.penalty_service.get_user_status(self.user))
            except PenaltyError as e:
                self._handle_user_query_error(e)
                return True
            if status.get("is_banned"):
                restriction_until = str(status.get("restriction_until") or "-")
                print_warning(
                    f"이용이 금지된 상태입니다. (해제일: {restriction_until[:10]})"
                )
            elif status.get("is_restricted"):
                print_warning("패널티로 인해 회의실 1건, 장비 1건까지만 유지할 수 있습니다.")

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
            print("  16. 대기 예약 신청")
            print("  17. 운영 시계")

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
                self._create_waiting_list_request()
            elif choice == "17":
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
            rows.append(
                [
                    room.name,
                    f"{room.capacity}명",
                    room.location,
                    format_status_badge(room.status.value),
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

        from src.domain.daily_booking_rules import build_daily_booking_period

        while True:
            if not input_start_gate("회의실 예약 입력"):
                return
            self._print_daily_booking_guide()
            attendee_count = get_positive_int_input("이용 인원", 1, 100)
            if attendee_count is None:
                return

            start_date, end_date = get_daily_date_range_input("시작 날짜", "종료 날짜")
            if start_date is None or end_date is None:
                return

            start_time, end_time = build_daily_booking_period(start_date, end_date)
            rooms = self.room_service.get_available_rooms_for_attendees(
                attendee_count, start_time, end_time
            )
            if not rooms:
                print_info("해당 인원과 기간에 예약 가능한 회의실이 없습니다.")
                pause()
                return

            items = [(r.id, f"{r.name} ({r.capacity}명, {r.location})") for r in rooms]
            room_id = select_from_list(items, "회의실 선택")
            if not room_id:
                return

            room = self.room_service.get_room(room_id)
            memo = self._get_memo_input()
            self._print_review_rows(
                [
                    ("회의실", room.name if room else room_id),
                    ("이용 인원", f"{attendee_count}명"),
                    ("기간", format_booking_time_range(start_time.isoformat(), end_time.isoformat())),
                    ("메모", memo or "-"),
                ]
            )
            decision = review_action("회의실 예약 검토", "저장")
            if decision == "confirm":
                break
            if decision == "cancel":
                print_info("회의실 예약을 취소했습니다.")
                pause()
                return

        try:
            limits = cast(dict[str, Any], self.policy_service.get_user_flow_limits(self.user))
            room_limit = int(limits["room_limit"])
            if room_limit <= 0:
                raise RoomBookingError("활성 회의실 예약 한도에 도달했습니다.")
            booking = self.room_service.create_daily_booking(
                user=self.user,
                room_id=room_id,
                start_date=start_date,
                end_date=end_date,
                attendee_count=attendee_count,
                max_active=room_limit,
                memo=memo,
            )
            self._print_booking_result(booking)
        except (RoomBookingError, PenaltyError) as e:
            print_error(str(e))

        pause()

    def _waitlist_cutoff_date(self):
        return self.policy_service.clock.now().date() + timedelta(days=1)

    def _is_waitlist_target_start_allowed(self, booking):
        return datetime.fromisoformat(booking.start_time).date() > self._waitlist_cutoff_date()

    def _get_waitlist_target_booking(self, related_type, related_id):
        if related_type == "room_booking":
            booking = self.room_service.booking_repo.get_by_id(related_id)
            eligible_statuses = {
                RoomBookingStatus.RESERVED,
                RoomBookingStatus.CHECKIN_REQUESTED,
                RoomBookingStatus.CHECKED_IN,
                RoomBookingStatus.CHECKOUT_REQUESTED,
            }
            error_type = RoomBookingError
        elif related_type == "equipment_booking":
            booking = self.equipment_service.booking_repo.get_by_id(related_id)
            eligible_statuses = {
                EquipmentBookingStatus.RESERVED,
                EquipmentBookingStatus.PICKUP_REQUESTED,
                EquipmentBookingStatus.CHECKED_OUT,
                EquipmentBookingStatus.RETURN_REQUESTED,
            }
            error_type = EquipmentBookingError
        else:
            raise ValueError("대기 예약 대상 유형이 올바르지 않습니다.")
        if booking is None:
            raise error_type("존재하지 않는 예약 건입니다.")
        if booking.status not in eligible_statuses:
            raise error_type("대기 신청 가능한 예약 건이 아닙니다.")
        if not self._is_waitlist_target_start_allowed(booking):
            raise error_type("내일 또는 그 이전에 시작하는 예약은 대기 신청할 수 없습니다.")
        return booking

    def _eligible_room_waitlist_targets(self):
        statuses = {
            RoomBookingStatus.RESERVED,
            RoomBookingStatus.CHECKIN_REQUESTED,
            RoomBookingStatus.CHECKED_IN,
            RoomBookingStatus.CHECKOUT_REQUESTED,
        }
        targets = []
        for booking in self.room_service.booking_repo.get_all():
            if booking.user_id == self.user.id or booking.status not in statuses:
                continue
            if not self._is_waitlist_target_start_allowed(booking):
                continue
            room = self.room_service.get_room(booking.room_id)
            label = room.name if room else booking.room_id
            targets.append((booking.id, f"{label} / {format_booking_time_range(booking.start_time, booking.end_time)}"))
        return sorted(targets, key=lambda item: item[1])

    def _eligible_equipment_waitlist_targets(self):
        statuses = {
            EquipmentBookingStatus.RESERVED,
            EquipmentBookingStatus.PICKUP_REQUESTED,
            EquipmentBookingStatus.CHECKED_OUT,
            EquipmentBookingStatus.RETURN_REQUESTED,
        }
        targets = []
        for booking in self.equipment_service.booking_repo.get_all():
            if booking.user_id == self.user.id or booking.status not in statuses:
                continue
            if not self._is_waitlist_target_start_allowed(booking):
                continue
            equipment = self.equipment_service.get_equipment(booking.equipment_id)
            label = equipment.name if equipment else booking.equipment_id
            targets.append((booking.id, f"{label} / {format_booking_time_range(booking.start_time, booking.end_time)}"))
        return sorted(targets, key=lambda item: item[1])

    def create_waiting_list_request(self, related_type, related_id, user_count):
        with global_lock(), UnitOfWork():
            self._get_waitlist_target_booking(related_type, related_id)
            error_type = EquipmentBookingError if related_type == "equipment_booking" else RoomBookingError
            if self.waiting_list_repo.has_duplicate(self.user.username, related_type, related_id):
                raise error_type("이미 같은 예약 건에 대한 대기 신청이 있습니다. 중복 신청할 수 없습니다.")
            if self.waiting_list_repo.count_by_username_and_related_type(self.user.username, related_type) >= 3:
                raise error_type("대기 신청은 유형별 최대 3건까지 가능합니다.")
            entry = WaitingListEntry(
                id=generate_id(),
                username=self.user.username,
                related_type=related_type,
                related_id=related_id,
                user_count=user_count,
                created_at=now_iso(),
                updated_at=now_iso(),
            )
            return self.waiting_list_repo.add(entry)

    def _create_waiting_list_request(self):
        print_header("대기 예약 신청")
        if not self._refresh_user():
            return
        while True:
            if not input_start_gate("대기 예약 신청 입력"):
                return
            print("  1. 회의실")
            print("  2. 장비")
            print("  0. 취소")
            choice = input("대상 유형 선택: ").strip()
            if choice == "0":
                return
            if choice == "1":
                related_type = "room_booking"
                targets = self._eligible_room_waitlist_targets()
                prompt = "대기 신청 회의실 예약 선택"
            elif choice == "2":
                related_type = "equipment_booking"
                targets = self._eligible_equipment_waitlist_targets()
                prompt = "대기 신청 장비 예약 선택"
            else:
                print_error("잘못된 선택입니다.")
                pause()
                return
            if not targets:
                print_info("대기 신청 가능한 예약 건이 없습니다. 일반 예약 메뉴를 이용해 주세요.")
                pause()
                return
            related_id = select_from_list(targets, prompt)
            if not related_id:
                return
            max_user_count = 100
            if related_type == "room_booking":
                target_booking = self.room_service.booking_repo.get_by_id(related_id)
                target_room = self.room_service.get_room(target_booking.room_id) if target_booking else None
                if target_room:
                    max_user_count = target_room.capacity
            user_count = get_positive_int_input("이용 인원", 1, max_user_count)
            if user_count is None:
                return
            self._print_review_rows(
                [("대상 유형", related_type), ("대상 예약", related_id), ("이용 인원", f"{user_count}명")]
            )
            decision = review_action("대기 예약 신청 검토", "저장")
            if decision == "confirm":
                break
            if decision == "cancel":
                print_info("대기 예약 신청을 취소했습니다.")
                pause()
                return
        try:
            entry = self.create_waiting_list_request(related_type, related_id, user_count)
            print_success("대기 예약 신청이 저장되었습니다.")
            print(f"  대기 ID: {entry.id[:8]}...")
            print(f"  대상: {entry.related_type} / {entry.related_id}")
            sequence = len(self.waiting_list_repo.get_ordered_by_related(entry.related_type, entry.related_id))
            print(f"  현재 대기 순번: {sequence}번")
        except (RoomBookingError, EquipmentBookingError, ValueError) as e:
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

        visible_bookings = bookings[:20]
        headers = ["ID", "회의실", "시간", "상태"]
        rows = []
        for booking in visible_bookings:
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

        for booking in visible_bookings:
            memo = booking.memo.strip()
            if memo and memo != "-":
                print(f"  {booking.id[:8]} 메모: {memo}")

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

        while True:
            if not input_start_gate("회의실 예약 변경 입력"):
                return
            booking_id = select_from_list(items, "변경할 예약 선택")
            if not booking_id:
                return

            self._print_daily_booking_guide()
            start_date, end_date = get_daily_date_range_input("시작 날짜", "종료 날짜")
            if start_date is None or end_date is None:
                return
            self._print_review_rows(
                [("예약 ID", booking_id[:8]), ("새 기간", f"{start_date} ~ {end_date}")]
            )
            decision = review_action("회의실 예약 변경 검토", "저장")
            if decision == "confirm":
                break
            if decision == "cancel":
                print_info("예약 변경을 취소했습니다.")
                pause()
                return

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
            items.append(
                (
                    booking.id,
                    f"{room.name if room else '-'} - {format_booking_time_range(booking.start_time, booking.end_time)}",
                )
            )

        booking_id = select_from_list(items, "체크인 요청할 예약 선택")
        if not booking_id:
            return
        self._print_review_rows([("예약 ID", booking_id[:8])])
        decision = review_action("체크인 요청 검토", "처리")
        if decision == "retry":
            return self._request_room_checkin()
        if decision == "cancel":
            print_info("체크인 요청을 취소했습니다.")
            pause()
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
            items.append(
                (
                    booking.id,
                    f"{room.name if room else '-'} - {format_booking_time_range(booking.start_time, booking.end_time)}",
                )
            )

        booking_id = select_from_list(items, "퇴실 신청할 예약 선택")
        if not booking_id:
            return
        self._print_review_rows([("예약 ID", booking_id[:8])])
        decision = review_action("퇴실 신청 검토", "처리")
        if decision == "retry":
            return self._request_room_checkout()
        if decision == "cancel":
            print_info("퇴실 신청을 취소했습니다.")
            pause()
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

        while True:
            booking_id = select_from_list(items, "취소할 예약 선택")
            if not booking_id:
                return

            try:
                impact = self.room_service.preview_cancel_booking_impact(self.user, booking_id)
                self._print_cancel_impact_preview(impact)
            except (RoomBookingError, PenaltyError) as e:
                print_error(str(e))
                pause()
                return

            self._print_review_rows([("예약 ID", booking_id[:8])])
            decision = review_action("회의실 예약 취소 검토", "처리")
            if decision == "confirm":
                break
            if decision == "cancel":
                print_info("예약 취소를 취소했습니다.")
                pause()
                return

        try:
            booking, is_late = self.room_service.cancel_booking(self.user, booking_id)
            print_success("예약이 취소되었습니다.")

            if is_late:
                print_warning("직전 취소로 패널티 2점이 부과됩니다.")
        except (RoomBookingError, PenaltyError) as e:
            print_error(str(e))

        pause()

    def _show_equipment(self):
        """장비 목록 조회"""
        print_header("장비 목록")

        type_order = {"projector": 0, "laptop": 1, "cable": 2, "webcam": 3}
        equipment_list = sorted(
            self.equipment_service.get_all_equipment(),
            key=lambda equip: (
                type_order.get(equip.asset_type, len(type_order)),
                equip.asset_type,
                equip.serial_number,
                equip.name,
            ),
        )
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

        from src.domain.daily_booking_rules import build_daily_booking_period

        while True:
            if not input_start_gate("장비 예약 입력"):
                return
            self._print_daily_booking_guide()
            start_date, end_date = get_daily_date_range_input("시작 날짜", "종료 날짜")
            if start_date is None or end_date is None:
                return

            start_time, end_time = build_daily_booking_period(start_date, end_date)
            filtered_equipment = sorted(
                self.equipment_service.get_available_equipment_for_period(start_time, end_time),
                key=lambda e: (e.asset_type, e.serial_number, e.name),
            )
            if not filtered_equipment:
                print_info("해당 기간에 예약 가능한 장비가 없습니다.")
                pause()
                return

            print("\n장비 선택")
            print("-" * 50)
            for index, item in enumerate(filtered_equipment, 1):
                print(f"  {index}. {item.name} ({item.asset_type}, S/N: {item.serial_number})")
            print("  0. 취소")
            while True:
                raw_selection = input("\n장비 선택 (번호): ").strip()
                if raw_selection == "0":
                    return
                try:
                    selected_numbers = self._parse_equipment_selection_numbers(raw_selection, len(filtered_equipment))
                    selected_equipment = [filtered_equipment[number - 1] for number in selected_numbers]
                    selected_types = [item.asset_type for item in selected_equipment]
                    if len(selected_types) != len(set(selected_types)):
                        raise EquipmentBookingError("같은 종류의 장비는 예약하실 수 없습니다.")
                    selected_ids = [item.id for item in selected_equipment]
                    break
                except EquipmentBookingError as e:
                    print_error(str(e))

            memo = self._get_memo_input()
            self._print_review_rows(
                [
                    ("장비", ", ".join(item.name for item in selected_equipment)),
                    ("장비 수", f"{len(selected_ids)}건"),
                    ("기간", format_booking_time_range(start_time.isoformat(), end_time.isoformat())),
                    ("메모", memo or "-"),
                ]
            )
            decision = review_action("장비 예약 검토", "저장")
            if decision == "confirm":
                break
            if decision == "cancel":
                print_info("장비 예약을 취소했습니다.")
                pause()
                return

        try:
            limits = cast(dict[str, Any], self.policy_service.get_user_flow_limits(self.user))
            equipment_limit = int(limits["equipment_limit"])
            if equipment_limit <= 0:
                raise EquipmentBookingError("활성 장비 예약 한도에 도달했습니다.")
            if len(selected_ids) == 1:
                booking = self.equipment_service.create_daily_booking(
                    user=self.user,
                    equipment_id=selected_ids[0],
                    start_date=start_date,
                    end_date=end_date,
                    max_active=equipment_limit,
                    memo=memo,
                )
                self._print_booking_result(booking, "대여 기간")
            else:
                bookings = self.equipment_service.create_group_booking(
                    user=self.user,
                    equipment_ids=selected_ids,
                    start_time=start_time,
                    end_time=end_time,
                    max_active=equipment_limit,
                    memo=memo,
                )
                print_success("장비 그룹 예약 요청이 접수되었습니다.")
                print(f"  그룹 예약 수: {len(bookings)}건")
                print(f"  대여 기간: {format_booking_time_range(bookings[0].start_time, bookings[0].end_time)}")
                reserved_bookings = [
                    booking
                    for booking in bookings
                    if booking.status == EquipmentBookingStatus.RESERVED
                ]
                pending_bookings = [
                    booking
                    for booking in bookings
                    if booking.status == EquipmentBookingStatus.PENDING
                ]
                if reserved_bookings:
                    print(f"  확정 예약: {len(reserved_bookings)}건")
                    for booking in reserved_bookings:
                        equipment = self.equipment_service.get_equipment(booking.equipment_id)
                        equipment_name = equipment.name if equipment else booking.equipment_id
                        print(f"    - {equipment_name}: 예약 확정")
                if pending_bookings:
                    print_warning("경쟁 예약이 있는 장비는 대기 상태로 접수되었습니다.")
                    print(f"  대기 예약: {len(pending_bookings)}건")
                    for booking in pending_bookings:
                        equipment = self.equipment_service.get_equipment(booking.equipment_id)
                        equipment_name = equipment.name if equipment else booking.equipment_id
                        print(f"    - {equipment_name}: 대기")
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
        collapsed_bookings = []
        seen_group_ids = set()
        for booking in bookings:
            if booking.group_id:
                if booking.group_id in seen_group_ids:
                    continue
                seen_group_ids.add(booking.group_id)
            collapsed_bookings.append(booking)

        headers = ["ID", "장비", "대여 기간", "상태"]
        rows = []
        visible_bookings = collapsed_bookings[:20]
        memo_rows = []
        for booking in visible_bookings:
            members = [booking]
            row_id = booking.id[:8]
            if booking.group_id:
                members = self.equipment_service.booking_repo.get_by_group_id(booking.group_id)
                members.sort(key=lambda member: self._equipment_history_member_sort_key(member))
                row_id = booking.group_id[:8]
                equip_name = "[묶음] " + ", ".join(
                    self._equipment_history_name(member) for member in members
                )
            else:
                equip_name = self._equipment_history_name(booking)
            memo = self._first_booking_memo(members)
            if memo:
                memo_rows.append((row_id, memo))
            rows.append(
                [
                    row_id,
                    equip_name,
                    format_booking_time_range(booking.start_time, booking.end_time),
                    format_status_badge(booking.status.value),
                ]
            )

        print(format_table(headers, rows))

        for row_id, memo in memo_rows:
            print(f"  {row_id} 메모: {memo}")

        if len(collapsed_bookings) > 20:
            print(f"\n  ... 외 {len(collapsed_bookings) - 20}건")

        pause()

    def _equipment_history_name(self, booking):
        equipment = self.equipment_service.get_equipment(booking.equipment_id)
        return equipment.name if equipment else "알 수 없음"

    def _equipment_history_member_sort_key(self, booking):
        equipment = self.equipment_service.get_equipment(booking.equipment_id)
        if equipment is None:
            return ("", booking.equipment_id, booking.id)
        return (equipment.serial_number, equipment.name, booking.id)

    def _equipment_request_label(self, booking):
        if not booking.group_id:
            equipment = self.equipment_service.get_equipment(booking.equipment_id)
            equipment_name = equipment.name if equipment else "-"
            return f"{equipment_name} - {format_booking_time_range(booking.start_time, booking.end_time)}"

        members = self.equipment_service.booking_repo.get_by_group_id(booking.group_id)
        members.sort(key=lambda member: self._equipment_history_member_sort_key(member))
        member_labels = []
        for member in members:
            equipment = self.equipment_service.get_equipment(member.equipment_id)
            if equipment is None:
                member_labels.append("알 수 없음")
            else:
                member_labels.append(f"{equipment.name} ({equipment.serial_number})")
        return f"[묶음] {', '.join(member_labels)} - {format_booking_time_range(booking.start_time, booking.end_time)}"

    def _first_booking_memo(self, bookings):
        for booking in bookings:
            memo = booking.memo.strip()
            if memo and memo != "-":
                return memo
        return ""

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

        while True:
            if not input_start_gate("장비 예약 변경 입력"):
                return
            booking_id = select_from_list(items, "변경할 예약 선택")
            if not booking_id:
                return

            self._print_daily_booking_guide()
            start_date, end_date = get_daily_date_range_input("시작 날짜", "종료 날짜")
            if start_date is None or end_date is None:
                return
            self._print_review_rows(
                [("예약 ID", booking_id[:8]), ("새 기간", f"{start_date} ~ {end_date}")]
            )
            decision = review_action("장비 예약 변경 검토", "저장")
            if decision == "confirm":
                break
            if decision == "cancel":
                print_info("예약 변경을 취소했습니다.")
                pause()
                return

        try:
            booking_result = self.equipment_service.modify_daily_booking(
                user=self.user,
                booking_id=booking_id,
                start_date=start_date,
                end_date=end_date,
            )
            booking = booking_result[0] if isinstance(booking_result, list) else booking_result
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
            items.append(
                (
                    booking.id,
                    self._equipment_request_label(booking),
                )
            )

        booking_id = select_from_list(items, "픽업 요청할 예약 선택")
        if not booking_id:
            return
        self._print_review_rows([("예약 ID", booking_id[:8])])
        decision = review_action("픽업 요청 검토", "처리")
        if decision == "retry":
            return self._request_equipment_pickup()
        if decision == "cancel":
            print_info("픽업 요청을 취소했습니다.")
            pause()
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
                if self._is_equipment_return_requestable_now(b)
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
            items.append(
                (
                    booking.id,
                    self._equipment_request_label(booking),
                )
            )

        booking_id = select_from_list(items, "반납 신청할 예약 선택")
        if not booking_id:
            return
        self._print_review_rows([("예약 ID", booking_id[:8])])
        decision = review_action("반납 신청 검토", "처리")
        if decision == "retry":
            return self._request_equipment_return()
        if decision == "cancel":
            print_info("반납 신청을 취소했습니다.")
            pause()
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

        while True:
            booking_id = select_from_list(items, "취소할 예약 선택")
            if not booking_id:
                return

            try:
                impact = self.equipment_service.preview_cancel_booking_impact(
                    self.user, booking_id
                )
                self._print_cancel_impact_preview(impact)
            except (EquipmentBookingError, PenaltyError) as e:
                print_error(str(e))
                pause()
                return

            self._print_review_rows([("예약 ID", booking_id[:8])])
            decision = review_action("장비 예약 취소 검토", "처리")
            if decision == "confirm":
                break
            if decision == "cancel":
                print_info("예약 취소를 취소했습니다.")
                pause()
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
            status = cast(dict[str, Any], self.penalty_service.get_user_status(self.user))
            room_active = self.room_service.get_user_active_bookings(self.user.id)
            equip_active = self.equipment_service.get_user_active_bookings(self.user.id)
            all_room_bookings = self.room_service.get_user_bookings(self.user.id)
            all_equip_bookings = self.equipment_service.get_user_bookings(self.user.id)
            cancel_summary = self.penalty_service.get_cancel_restriction_summary(
                self.user, all_room_bookings, all_equip_bookings
            )
            penalties = self.penalty_service.get_user_penalties(self.user.id)
        except (PenaltyError, RoomBookingError, EquipmentBookingError) as e:
            self._handle_user_query_error(e)
            return

        print(f"\n사용자명: {self.user.username}")
        print(f"역할: {format_status_badge(self.user.role.value)}")

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

        print_subheader("취소 제한 현황")
        print(
            f"  회의실 직접 취소: {cancel_summary.room_cancel_count_30d}/{cancel_summary.max_cancel_count}건 (최근 30일)"
        )
        print(
            f"  장비 직접 취소: {cancel_summary.equipment_cancel_count_30d}/{cancel_summary.max_cancel_count}건 (최근 30일)"
        )
        if cancel_summary.room_cancel_restricted_until:
            print(f"  회의실 신규 예약 제한 해제일: {cancel_summary.room_cancel_restricted_until[:10]}")
        if cancel_summary.equipment_cancel_restricted_until:
            print(f"  장비 신규 예약 제한 해제일: {cancel_summary.equipment_cancel_restricted_until[:10]}")

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
