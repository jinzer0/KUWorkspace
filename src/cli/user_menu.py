"""
일반 사용자 메뉴 - 회의실/장비 예약, 조회, 취소

[병합본]
 - 팀원 코드 기준: 회의실 파트(1~7), 내 상태 조회(15), 대기 예약 신청(16), 운영 시계(17) 유지
 - 장비 파트 기준: 장비 메뉴(8~14) 및 6.5.2.x 헬퍼/우선권 처리 반영

[전제]
 models.py 등에 아래 확장이 적용되어 있어야 합니다.
 EquipmentBookingStatus.PENDING, EquipmentBooking.group_id/memo,
 PenaltyReason.FREQUENT_CANCEL, User.equipment_cancel_restricted_until
"""

import re
from dataclasses import replace
from datetime import datetime, timedelta, time
from typing import Any, cast

from src.domain.models import (
    RoomBookingStatus,
    EquipmentBookingStatus,
    ResourceStatus,
    EquipmentBooking,
    Penalty,
    PenaltyReason,
    WaitingListEntry,
    generate_id,
    now_iso,
)
from src.domain.auth_service import AuthService, AuthError
from src.domain.room_service import RoomService, RoomBookingError
from src.domain.equipment_service import EquipmentService, EquipmentBookingError
from src.domain.penalty_service import PenaltyService, PenaltyError
from src.domain.policy_service import PolicyService
from src.domain.daily_booking_rules import (
    build_daily_booking_period,
    validate_daily_booking_dates,
)
from src.storage.repositories import WaitingListRepository, UnitOfWork
from src.storage.file_lock import global_lock
from src.config import (
    FIXED_BOOKING_END_HOUR,
    FIXED_BOOKING_END_MINUTE,
    FIXED_BOOKING_START_HOUR,
    FIXED_BOOKING_START_MINUTE,
)
from src.runtime_clock import get_runtime_clock
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
    get_positive_int_input,
    validate_date_plan,
)


# ============================================================
# 장비 파트 공통 상수 / 헬퍼  (6.5.2.x)
# ============================================================
MAX_ACTIVE = 3                 # 활성 예약 제한 (정상 상태)
MAX_GROUP_SIZE = 3             # 묶음 내 최대 장비 개수
FREQUENT_CANCEL_THRESHOLD = 3
RESTRICTION_DAYS = 7
LATE_CANCEL_POINT_PER_ITEM = 1   # 묶음 직전취소 장비당 1점
_KO = "가나다라마바사아자차카타파하"

_ACTIVE_STATUSES = (
    EquipmentBookingStatus.RESERVED,
    EquipmentBookingStatus.PICKUP_REQUESTED,
    EquipmentBookingStatus.CHECKED_OUT,
    EquipmentBookingStatus.RETURN_REQUESTED,
)
# pending은 확정 전이므로 활성 예약 카운트·패널티·정책에서 제외 (6.5.2.9)
_CONFLICT_STATUSES = (
    EquipmentBookingStatus.RESERVED,
    EquipmentBookingStatus.PICKUP_REQUESTED,
    EquipmentBookingStatus.CHECKED_OUT,
    EquipmentBookingStatus.RETURN_REQUESTED,
)
# 물리적으로 장비가 사용 중인 상태 (pending→reject 판단 시 사용)
_HARD_CONFLICT_STATUSES = (
    EquipmentBookingStatus.PICKUP_REQUESTED,
    EquipmentBookingStatus.CHECKED_OUT,
    EquipmentBookingStatus.RETURN_REQUESTED,
)


def _eq_confirm(prompt):
    """y/yes/예/ㅇ -> True, n/no/아니오/ㄴ -> False, 그 외 재입력."""
    while True:
        raw = input(prompt).strip().lower()
        if raw in ("y", "yes", "예", "ㅇ"):
            return True
        if raw in ("n", "no", "아니오", "ㄴ"):
            return False
        print("y 또는 n을 입력해주세요.")


def _eq_back():
    """결과/조회 화면 하단의 '0. 돌아가기' 입력 대기 (Enter 복귀 폐지)."""
    pause()


def _input_start_or_back():
    """6.1절 CUI: 값 입력 전 '1. 입력 시작 / 0. 돌아가기' 선택."""
    return input_start_gate("장비 예약 입력")


def _overlap(s1, e1, s2, e2):
    return s1 < e2 and e1 > s2


def _name_of(equip):
    return equip.name if equip else "-"


def _period_str(b):
    s = datetime.fromisoformat(b.start_time).strftime("%Y-%m-%d %H:%M")
    e = datetime.fromisoformat(b.end_time).strftime("%Y-%m-%d %H:%M")
    return f"{s} ~ {e}"


def _group_by_group_id(bookings):
    """예약들을 group_id 기준으로 묶어 리스트의 리스트로 반환 (단일은 1개짜리)."""
    group_map = {}
    for b in bookings:
        group_id = getattr(b, "group_id", None)
        key = b.id if (not group_id or group_id == "-") else group_id
        group_map.setdefault(key, []).append(b)
    return list(group_map.values())



def _group_by_group_id_and_status(bookings):
    """조회 화면용: 같은 묶음이라도 상태가 다르면 별도 줄로 표시한다."""
    group_map = {}
    for b in bookings:
        group_key = b.id if (not b.group_id or b.group_id == "-") else b.group_id
        key = (group_key, b.status.value)
        group_map.setdefault(key, []).append(b)
    return list(group_map.values())


def _equipment_sort_key_by_name(equipment_service, booking):
    equip = equipment_service.get_equipment(booking.equipment_id)
    if equip is None:
        return ("", booking.equipment_id, booking.id)
    return (equip.name, equip.serial_number, booking.equipment_id, booking.id)


def _equipment_sort_key_by_serial(equipment_service, booking):
    equip = equipment_service.get_equipment(booking.equipment_id)
    if equip is None:
        return (booking.equipment_id, "", booking.id)
    return (equip.serial_number, equip.name, booking.equipment_id, booking.id)


def _equipment_label_with_serial(equipment_service, booking):
    equip = equipment_service.get_equipment(booking.equipment_id)
    if equip is None:
        return f"{booking.equipment_id} 알 수 없음"
    serial = equip.serial_number or booking.equipment_id
    return f"{serial} {_name_of(equip)}"


def _equipment_group_label(equipment_service, group, sort_by="name"):
    sort_key = (
        (lambda b: _equipment_sort_key_by_serial(equipment_service, b))
        if sort_by == "serial"
        else (lambda b: _equipment_sort_key_by_name(equipment_service, b))
    )
    labels = [_equipment_label_with_serial(equipment_service, b) for b in sorted(group, key=sort_key)]
    if len(labels) == 1:
        return labels[0]
    return "[묶음] " + ", ".join(labels)


# ============================================================
# 6.5.2.2 단일 예약 + 공통 헬퍼  (EquipmentBookingManager)
# ============================================================
class EquipmentBookingManager:
    """단일 예약(6.5.2.2 단일) 및 묶음 흐름 공통 헬퍼."""

    def __init__(self, user, equipment_service, penalty_service):
        self.user = user
        self.penalty_service = penalty_service
        self.equipment_service = equipment_service
        self.clock = equipment_service.clock
        self.booking_repo = equipment_service.booking_repo
        self.audit_repo = equipment_service.audit_repo

    def _check_blocked_conditions(self):
        try:
            status = self.penalty_service.get_user_status(self.user)
        except PenaltyError as e:
            return str(e)
        if status.get("is_banned"):
            until = status.get("restriction_until")
            until = until[:10] if isinstance(until, str) and until else "-"
            return f"이용이 금지된 상태입니다. 해제일: {until}"
        ru = getattr(self.user, "equipment_cancel_restricted_until", None)
        if isinstance(ru, str) and ru:
            try:
                if datetime.fromisoformat(ru) > self.clock.now():
                    return ("최근 30일 악의적인 장비 반복 취소로 인한 이용이 "
                            f"금지된 상태입니다. 해제일: {ru[:10]}")
            except ValueError:
                pass
        active = [b for b in self.booking_repo.get_active_by_user(self.user.id)
                  if b.status in _ACTIVE_STATUSES]
        # 묶음 예약은 1건으로 카운트
        active_groups = _group_by_group_id(active)
        if status.get("is_restricted"):
            if len(active_groups) >= 1:
                return "패널티로 인해 추가 예약이 불가합니다."
        else:
            if len(active_groups) >= MAX_ACTIVE:
                return "이미 활성 장비 예약이 3건 존재합니다. 추가 예약이 불가합니다."
        return ""

    def _input_dates(self):
        return get_daily_date_range_input(self.clock.now())

    def _input_memo(self):
        while True:
            raw = input("  메모 입력 (선택, 최대 50자 / 없으면 엔터): ")
            memo = raw.strip()
            if memo == "" or memo == "0":
                return "-"
            if len(memo) > 50:
                print("  메모는 최대 50자까지 입력 가능합니다.")
                continue
            return memo

    def is_period_conflicted(self, equipment_id, start_iso, end_iso, exclude_id=None):
        for b in self.booking_repo.get_by_equipment(equipment_id):
            if exclude_id and b.id == exclude_id:
                continue
            if b.status in _CONFLICT_STATUSES and _overlap(
                start_iso, end_iso, b.start_time, b.end_time
            ):
                return True
        return False

    def _decide_status(self, equipment_id, start_iso, end_iso):
        """6.5.2.9 우선권 규칙에 따라 예약 상태를 결정한다.

        - 모든 예약은 PENDING으로 저장 (시점 이동 시 resolve_all에서 확정)
        - 단독 신청이어도 PENDING → 시점 이동 시 바로 RESERVED 확정
        - 예외: 18:00 + 다음날 09:00 → 우선권 없이 선착순 즉시 RESERVED
        - 물리적 사용중(pickup/checked_out/return) 또는 확정된 RESERVED 충돌 → None
        """
        current = self.clock.now()
        try:
            start_dt = datetime.fromisoformat(start_iso)
        except ValueError:
            start_dt = current

        existing = self.booking_repo.get_by_equipment(equipment_id)

        # ── 18:00 + 다음날 → 우선권 없이 선착순 즉시 RESERVED ──
        is_1800 = current.hour == 18 and current.minute == 0
        starts_next_day = start_dt.date() == (current.date() + timedelta(days=1))
        if is_1800 and starts_next_day:
            for b in existing:
                if b.status in _CONFLICT_STATUSES and _overlap(
                        start_iso, end_iso, b.start_time, b.end_time):
                    return None
            return EquipmentBookingStatus.RESERVED

        # ── 물리적 사용중 충돌 → 예약 불가 ──
        for b in existing:
            if b.status in _HARD_CONFLICT_STATUSES and _overlap(
                    start_iso, end_iso, b.start_time, b.end_time):
                return None

        # ── 확정된 RESERVED 충돌 (이전 시점에서 확정된 것) → 예약 불가 ──
        for b in existing:
            if b.status == EquipmentBookingStatus.RESERVED and _overlap(
                    start_iso, end_iso, b.start_time, b.end_time):
                return None

        # ── 그 외 모든 경우 (단독이든 경쟁이든) → PENDING ──
        # 시점 이동 시 resolve_all()에서:
        #   단독 → 바로 RESERVED 확정
        #   경쟁 → penalty_points 낮은 쪽 우선, 동점이면 created_at 빠른 쪽
        return EquipmentBookingStatus.PENDING

    def _save_booking(self, equipment_id, start_iso, end_iso, memo, group_id, status):
        if status is None:
            return None
        booking = EquipmentBooking(
            id=generate_id(), user_id=self.user.id, equipment_id=equipment_id,
            start_time=start_iso, end_time=end_iso, status=status,
            group_id=group_id if group_id else "-", memo=memo if memo else "-",
            created_at=now_iso(), updated_at=now_iso(),
        )
        self.booking_repo.add(booking)
        return booking


# ============================================================
# 6.5.2.1 장비 목록 조회  (EquipmentListViewer)
#
# [기획서]
#  - 프로젝터 → 노트북 → 케이블 → 웹캠 순서, 각 종류 내 시리얼 오름차순
#  - 컬럼: 이름 / 종류 / 시리얼번호 / 상태
#  - 상태: available=[사용가능], maintenance=[점검중], disabled/기타=[사용불가]
#  - 장비 편집(삭제 등)에 따라 자동 반영
#  - "0. 돌아가기"로 복귀
# ============================================================
class EquipmentListViewer:
    _TYPE_ORDER = ["projector", "laptop", "cable", "webcam"]

    def __init__(self, equipment_service):
        self.equipment_service = equipment_service

    def _sort_key(self, e):
        try:
            ti = self._TYPE_ORDER.index(e.asset_type.lower())
        except ValueError:
            ti = len(self._TYPE_ORDER)
        return (ti, e.serial_number)

    def show(self):
        print_header("장비 목록 조회")
        try:
            equips = self.equipment_service.get_all_equipment()
        except EquipmentBookingError as e:
            print_error(str(e))
            _eq_back()
            return

        if not equips:
            print_info("등록된 장비가 없습니다.")
            _eq_back()
            return

        # 컬럼 헤더
        headers = ["이름", "종류", "시리얼번호", "상태"]
        rows = []
        for e in sorted(equips, key=self._sort_key):
            sv = e.status.value.lower()
            if sv == "available":
                badge = "[사용가능]"
            elif sv == "maintenance":
                badge = "[점검중]"
            else:
                badge = "[사용불가]"
            rows.append([e.name, e.asset_type, e.serial_number, badge])

        print(format_table(headers, rows))
        _eq_back()


# ============================================================
# 6.5.2.2 묶음 예약  (EquipmentGroupBookingManager) + 6.5.2.8 메모
#
# [흐름 — 1차 코드 _create_equipment_booking 그대로]
#  1. 차단 조건 확인 (banned / 활성 3건 / restricted 1건 / 반복취소 제한)
#  2. 장비 종류 목록 출력 → 종류 선택 (단일: "1" / 묶음: "1,2,3")
#  3. 날짜 입력 (시작/종료)
#  4. 선택한 종류별로 해당 기간 예약 가능 장비 후보 출력 → 하나씩 선택
#  5. 메모 입력 (6.5.2.8)
#  6. 최종 확인 → 저장
# ============================================================
class EquipmentGroupBookingManager:
    def __init__(self, user, equipment_service, penalty_service):
        self.user = user
        self.mgr = EquipmentBookingManager(user, equipment_service, penalty_service)
        self.equipment_service = equipment_service
        self.clock = equipment_service.clock
        self.audit_repo = equipment_service.audit_repo

    def create_group(self):
        print_header("장비 예약하기")

        # ── 1. 차단 조건 ──
        block = self.mgr._check_blocked_conditions()
        if block:
            print_error(block)
            _eq_back()
            return

        try:
            all_equips = self.equipment_service.get_all_equipment()
        except EquipmentBookingError as e:
            print_error(str(e))
            _eq_back()
            return
        if not any(e.status == ResourceStatus.AVAILABLE for e in all_equips):
            print_info("현재 예약 가능한 장비가 없습니다.")
            _eq_back()
            return

        while True:
            if not _input_start_or_back():
                return

            print()
            print(f"  이용 시간: 매일 {FIXED_BOOKING_START_HOUR:02d}:{FIXED_BOOKING_START_MINUTE:02d}"
                  f" ~ {FIXED_BOOKING_END_HOUR:02d}:{FIXED_BOOKING_END_MINUTE:02d} 고정")
            print("  예약 시작일: 내일부터 최대 180일까지 가능")
            print("  예약 기간: 1일 이상 14일 이하")
            print()
            start_date, end_date = self.mgr._input_dates()
            if start_date is None or end_date is None:
                return
            start_dt, end_dt = build_daily_booking_period(start_date, end_date)

            candidates = []
            for asset_type in sorted({e.asset_type for e in all_equips}):
                try:
                    candidates.extend(
                        self.equipment_service.get_available_equipment_by_type(
                            asset_type,
                            start_dt,
                            end_dt,
                        )
                    )
                except EquipmentBookingError as e:
                    print_error(str(e))
                    _eq_back()
                    return
            candidates = sorted(
                {equipment.id: equipment for equipment in candidates}.values(),
                key=lambda e: (e.asset_type, e.serial_number),
            )
            if not candidates:
                print_info("해당 기간에 예약 가능한 장비가 없습니다.")
                _eq_back()
                return

            print()
            for i, e in enumerate(candidates, 1):
                print(f"  {i}. {e.name} ({e.asset_type}, S/N: {e.serial_number})")
            print("  0. 취소")
            print("-" * 50)

            if len(candidates) == 1:
                chosen_equips = [candidates[0]]
            else:
                raw = input("장비 선택 (번호): ").strip()
                result_type, indices, msg = self._parse_selection_input(raw, candidates)
                if result_type == "cancel":
                    return
                if result_type == "error":
                    print_error(msg)
                    continue
                chosen_equips = [candidates[i] for i in indices]

            memo = self.mgr._input_memo()
            if len(chosen_equips) == 1:
                print(f"\n선택한 장비:\n - {chosen_equips[0].name}"
                      f" ({chosen_equips[0].serial_number})")
            else:
                self._show_group_confirm_list(chosen_equips)

            decision = review_action("장비 예약 검토", "예약")
            if decision == "retry":
                continue
            if decision == "cancel":
                print_info("장비 예약을 취소했습니다.")
                _eq_back()
                return

            if len(chosen_equips) == 1:
                self.equipment_service.create_daily_booking(
                    self.user,
                    chosen_equips[0].id,
                    start_date,
                    end_date,
                    memo=memo,
                )
            else:
                self.equipment_service.create_group_booking(
                    self.user,
                    [equipment.id for equipment in chosen_equips],
                    start_dt,
                    end_dt,
                    memo=memo,
                )
            print_success("예약 요청이 접수되었습니다.")
            _eq_back()
            return

    # ── 종류 선택 파싱 (단일: "1" / 묶음: "1,2,3" "1 2 3") ──
    def _parse_selection_input(self, raw, available_types):
        """반환: (result_type, indices, message)
        result_type ∈ {single, group, error, cancel}"""
        if raw == "0":
            return ("cancel", [], "")
        if raw == "":
            return ("error", [], "번호를 입력해주세요.")
        # 단일 정수
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(available_types):
                return ("single", [idx], "")
            return ("error", [], "잘못 입력했습니다. 다시 입력해주세요.")
        # 숫자+콤마 or 숫자+공백 조합 → 묶음 시도
        has_digit = any(c.isdigit() for c in raw)
        has_sep = ',' in raw or ' ' in raw
        if has_digit and has_sep:
            if not self._is_allowed_group_format(raw):
                return ("error", [],
                        "올바른 번호를 입력해주세요. (예: 1 2 3 또는 1,2,3 또는 1, 2, 3)")
            tokens = raw.replace(",", " ").split()
            if not all(t.isdigit() for t in tokens):
                return ("error", [],
                        "올바른 번호를 입력해주세요. (예: 1 2 3 또는 1,2,3 또는 1, 2, 3)")
            numbers = [int(t) for t in tokens]
            if len(numbers) > MAX_GROUP_SIZE:
                return ("error", [], "묶음 예약은 최대 3건까지만 가능합니다.")
            if len(numbers) != len(set(numbers)):
                return ("error", [],
                        "중복된 번호가 있습니다. (예: 1, 1, 2) 다시 입력해주세요.")
            indices = []
            for n in numbers:
                if not (1 <= n <= len(available_types)):
                    return ("error", [], "잘못 입력했습니다. 다시 입력해주세요.")
                indices.append(n - 1)
            return ("group", indices, "")
        # 그 외 (순수 문자 등)
        return ("error", [], "숫자를 입력해주세요.")

    # ── 개별 장비 하나 선택 ──
    def _pick_one_equipment(self, candidates):
        """후보 목록에서 하나를 고른다. 0이면 None(취소)."""
        while True:
            raw = input("장비 선택 (번호): ").strip()
            if raw == "0":
                return None
            if raw == "":
                print_error("번호를 입력해주세요.")
                continue
            if not raw.isdigit():
                print_error("숫자를 입력해주세요.")
                continue
            idx = int(raw) - 1
            if idx < 0 or idx >= len(candidates):
                print_error("잘못 입력했습니다. 다시 입력해주세요.")
                continue
            return candidates[idx]

    @staticmethod
    def _is_allowed_group_format(raw):
        return (bool(re.fullmatch(r"\d+(\s+\d+)+", raw))
                or bool(re.fullmatch(r"\d+(\s*,\s*\d+)+", raw)))

    def _show_group_confirm_list(self, equipments):
        names = sorted(e.name for e in equipments)
        print(f"\n[묶음] {', '.join(names)}")

    def _save_group_bookings(self, equipments, start_iso, end_iso, memo):
        group_id = generate_id()
        new_bookings = []
        for e in equipments:
            status = self.mgr._decide_status(e.id, start_iso, end_iso)
            saved = self.mgr._save_booking(
                e.id, start_iso, end_iso, memo, group_id, status)
            if saved is not None:
                new_bookings.append(saved)
        if new_bookings:
            self.audit_repo.log_action(
                actor_id=self.user.id, action="create_equipment_group_booking",
                target_type="equipment_booking", target_id=group_id,
                details=f"묶음 {len(new_bookings)}건",
            )
        return new_bookings


# ============================================================
# 6.5.2.3 장비 예약 조회  (EquipmentBookingViewer)
# ============================================================
class EquipmentBookingViewer:
    STATUS_MAP = {
        "pending": "[예약 대기중]",
        "reserved": "[예약됨]",
        "pickup_requested": "[픽업요청]",
        "checked_out": "[대여중]",
        "return_requested": "[반납승인대기]",
        "returned": "[반납완료]",
        "cancelled": "[취소]",
        "admin_cancelled": "[관리자취소]",
    }

    def __init__(self, user, equipment_service):
        self.user = user
        self.equipment_service = equipment_service
        self.booking_repo = equipment_service.booking_repo

    def show(self):
        print_header("내 장비 예약")
        try:
            # get_user_bookings()는 묶음을 대표 1건으로 접어서 반환하므로,
            # 조회 화면에서는 원본 예약들을 직접 묶어 표시해야 한다.
            bookings = self.booking_repo.get_by_user(self.user.id)
        except EquipmentBookingError as e:
            print_error(str(e))
            _eq_back()
            return
        if not bookings:
            print_info("예약 내역이 없습니다.")
            _eq_back()
            return
        print(f"{'ID':<10}{'장비':<36}{'대여 기간':<40}{'상태'}")
        print("-" * 80)
        for group in self._group_sorted(bookings):
            print(self._format_row(group))
            memo_line = self._format_memo(self._first_memo(group))
            if memo_line:
                print(memo_line)
        _eq_back()

    def _group_sorted(self, bookings):
        groups = _group_by_group_id_and_status(bookings)
        groups.sort(key=lambda g: min(g, key=lambda b: b.start_time).start_time, reverse=True)
        return groups

    def _format_row(self, group):
        rep = min(group, key=lambda b: b.id)
        period = _period_str(rep)
        status = self.STATUS_MAP.get(rep.status.value.lower(), f"[{rep.status.value}]")
        label = _equipment_group_label(self.equipment_service, group, sort_by="serial")
        return f"{rep.id[:8]:<10}{label:<36}{period:<40}{status}"

    @staticmethod
    def _first_memo(group):
        for booking in group:
            memo = getattr(booking, "memo", "") or ""
            if memo.strip() and memo.strip() != "-":
                return memo.strip()
        return ""

    @staticmethod
    def _format_memo(memo):
        if not memo or memo == "-":
            return ""
        return " " * 10 + "메모: " + memo


# ============================================================
# 6.5.2.4 장비 예약 변경  (EquipmentBookingModifier)
#
# [기획서 흐름]
#  1. banned 체크 (활성 예약 차단은 기획서에서 삭제됨)
#  2. reserved 목록 출력 (단일: "장비명 - 기간" / 묶음: "[묶음] 이름,이름 - 기간")
#  3. 예약 선택 → 이미 시작된 예약이면 차단
#  4. "1. 입력 시작 / 0. 돌아가기"
#  5. 날짜 입력 → 동일날짜·충돌 검사
#  6. "정말 변경하시겠습니까? (y/n)"
#  7. 장비 상태 재확인 → 변경 실행
#  8. "예약이 변경되었습니다." + "새 기간: …"
#  9. "0. 돌아가기"
# ============================================================
class EquipmentBookingModifier:
    def __init__(self, user, equipment_service, penalty_service):
        self.user = user
        self.mgr = EquipmentBookingManager(user, equipment_service, penalty_service)
        self.equipment_service = equipment_service
        self.penalty_service = penalty_service
        self.clock = equipment_service.clock
        self.booking_repo = equipment_service.booking_repo
        self.audit_repo = equipment_service.audit_repo

    def modify(self):
        print_header("장비 예약 변경")

        # ── banned 체크 ──
        try:
            status = self.penalty_service.get_user_status(self.user)
        except PenaltyError as e:
            print_error(str(e))
            _eq_back()
            return
        if status.get("is_banned"):
            until = status.get("restriction_until")
            until = until[:10] if isinstance(until, str) and until else "-"
            print_error(f"이용이 금지된 상태입니다. 해제일: {until}")
            _eq_back()
            return

        modifiable = self._build_modifiable()
        if not modifiable:
            print_info("변경 가능한 예약이 없습니다.")
            _eq_back()
            return

        selected = self._select_booking(modifiable)
        if selected is None:
            return

        rep = min(selected, key=lambda b: b.id)

        if datetime.fromisoformat(rep.start_time) <= self.clock.now():
            print_error("이미 시작된 예약은 변경할 수 없습니다.")
            _eq_back()
            return

        if not _input_start_or_back():
            return

        while True:
            start_date, end_date = self._input_dates_modify()
            if start_date is None or end_date is None:
                return
            new_start, new_end = build_daily_booking_period(start_date, end_date)
            ns, ne = new_start.isoformat(), new_end.isoformat()
            if any(self.mgr.is_period_conflicted(b.equipment_id, ns, ne, exclude_id=b.id)
                   for b in selected):
                print_error("잘못입력했습니다. 다시 입력해주세요.")
                continue
            break

        if not _eq_confirm("정말 변경하시겠습니까? (y/n): "):
            return

        if len(selected) == 1:
            self.equipment_service.modify_daily_booking(
                user=self.user, booking_id=rep.id,
                start_date=start_date, end_date=end_date,
            )
        else:
            self._modify_group_booking(rep.group_id, ns, ne)

        print_success("예약이 변경되었습니다.")
        print(f"  새 기간: {new_start.strftime('%Y-%m-%d %H:%M')} ~ "
              f"{new_end.strftime('%Y-%m-%d %H:%M')}")
        _eq_back()

    def _build_modifiable(self):
        # 묶음 예약을 온전하게 표시하기 위해 repository 원본을 사용한다.
        bookings = [b for b in self.booking_repo.get_by_user(self.user.id)
                    if b.status == EquipmentBookingStatus.RESERVED]
        groups = _group_by_group_id(bookings)
        groups.sort(key=lambda g: min(g, key=lambda b: b.start_time).start_time, reverse=True)
        return groups

    def _select_booking(self, modifiable):
        print()
        for i, group in enumerate(modifiable, 1):
            rep = min(group, key=lambda b: b.id)
            label = _equipment_group_label(self.equipment_service, group, sort_by="name")
            print(f"  {i}. {label} - {_period_str(rep)}")
        print("  0. 취소")
        print("-" * 60)
        while True:
            raw = input("변경할 예약 선택 (번호): ").strip()
            if raw == "0":
                return None
            if raw == "":
                print_error("번호를 입력해주세요.")
                continue
            if not raw.isdigit():
                print_error("숫자를 입력해주세요.")
                continue
            idx = int(raw) - 1
            if idx < 0 or idx >= len(modifiable):
                print_error("잘못 입력했습니다. 다시 입력해주세요.")
                continue
            return modifiable[idx]

    def _input_dates_modify(self):
        """6.5.2.4 전용: 모든 날짜 오류 → '잘못입력했습니다. 다시 입력해주세요.'"""
        while True:
            start_str = input("  시작 날짜 (YYYY-MM-DD): ").strip()
            if start_str.lower() in ("q", "quit", "취소"):
                return None, None
            end_str = input("  종료 날짜 (YYYY-MM-DD): ").strip()
            if end_str.lower() in ("q", "quit", "취소"):
                return None, None
            sv, start_date, _ = validate_date_plan(start_str)
            if not sv or start_date is None:
                print_error("잘못입력했습니다. 다시 입력해주세요.")
                continue
            ev, end_date, _ = validate_date_plan(end_str)
            if not ev or end_date is None:
                print_error("잘못입력했습니다. 다시 입력해주세요.")
                continue
            valid, error, _ = validate_daily_booking_dates(
                start_date, end_date, self.clock.now()
            )
            if valid:
                return start_date, end_date
            print_error("잘못입력했습니다. 다시 입력해주세요.")

    def _modify_group_booking(self, group_id, ns, ne):
        group = [b for b in self.booking_repo.get_by_user(self.user.id)
                 if b.group_id == group_id and b.status == EquipmentBookingStatus.RESERVED]
        with global_lock():
            with UnitOfWork() as uow:
                for b in group:
                    updated = replace(b, start_time=ns, end_time=ne, updated_at=now_iso())
                    self.booking_repo.update(updated)
                self.audit_repo.log_action(
                    actor_id=self.user.id, action="modify_equipment_group_booking",
                    target_type="equipment_booking", target_id=group_id,
                    details=f"묶음 {len(group)}건 기간 변경",
                )
        return group


# ============================================================
# 6.5.2.5 장비 예약 취소  (EquipmentBookingCanceller)
#
# [기획서 흐름]
#  1. banned 체크
#  2. pending+reserved 목록 출력 (pending: 가나다 + [대기], reserved: 1,2,3)
#  3. 예약 선택
#  4. 이미 시작 → 차단
#  5. pending → "정말 취소하시겠습니까?" → 취소 (패널티 없음)
#  6. reserved 일반 → "정말로 취소하시겠습니까? 취소하시는 경우…(y/n)" → 취소
#  7. reserved 직전(start==current) → "직전 취소 패널티 N점…(y/n)" → 취소+패널티
#  8. 30일 반복 취소 로직 (3회째/4회이상)
#  9. "0. 돌아가기"
# ============================================================
class EquipmentBookingCanceller:
    def __init__(self, user, equipment_service, penalty_service):
        self.user = user
        self.penalty_service = penalty_service
        self.equipment_service = equipment_service
        self.clock = get_runtime_clock()
        self.booking_repo = equipment_service.booking_repo
        self.user_repo = equipment_service.user_repo
        self.audit_repo = equipment_service.audit_repo
        self.penalty_repo = penalty_service.penalty_repo

    def cancel(self):
        print_header("장비 예약 취소")

        # ── 1. banned 체크 ──
        try:
            status = self.penalty_service.get_user_status(self.user)
            if status.get("is_banned"):
                until = status.get("restriction_until")
                until = until[:10] if isinstance(until, str) and until else "-"
                print_error(f"이용이 금지된 상태입니다. 해제일: {until}")
                _eq_back()
                return
        except PenaltyError:
            pass

        # ── 2. 취소 가능 목록 ──
        items = self._build_cancellable_list()
        if not items:
            print_info("취소 가능한 예약이 없습니다.")
            _eq_back()
            return

        # ── 3. 예약 선택 ──
        selected, is_pending_item = self._select_booking(items)
        if selected is None:
            return

        # ── 5~7. 취소 분기 ──
        if is_pending_item:
            self._cancel_pending(selected)
        else:
            self._cancel_reserved(selected)
        _eq_back()

    # ── 목록 구성: pending 먼저 → reserved ──
    def _build_cancellable_list(self):
        # get_user_bookings()는 묶음 예약을 대표 1건으로 접어서 반환하므로,
        # pending 취소 화면에서는 repository 원본을 사용해야 묶음/일부 pending을 모두 표시·취소할 수 있다.
        all_b = self.booking_repo.get_by_user(self.user.id)
        service_bookings = self.equipment_service.get_user_bookings(self.user.id)
        known_ids = {booking.id for booking in all_b}
        all_b.extend(booking for booking in service_bookings if booking.id not in known_ids)
        pendings = [b for b in all_b if b.status == EquipmentBookingStatus.PENDING]
        reserveds = [b for b in all_b if b.status == EquipmentBookingStatus.RESERVED]
        items = []
        for group in self._sort_groups_for_cancel(_group_by_group_id(pendings)):
            items.append((group, True))
        for group in self._sort_groups_for_cancel(_group_by_group_id(reserveds)):
            items.append((group, False))
        return items

    def _sort_groups_for_cancel(self, groups):
        return sorted(groups, key=self._group_cancel_sort_key)

    def _group_cancel_sort_key(self, group):
        sorted_group = sorted(group, key=self._equipment_sort_key_for_cancel)
        first = sorted_group[0]
        first_key = self._equipment_sort_key_for_cancel(first)
        return (first_key, first.start_time, first.end_time, first.id)

    def _equipment_sort_key_for_cancel(self, booking):
        equip = self.equipment_service.get_equipment(booking.equipment_id)
        if equip is None:
            return ("", booking.equipment_id, booking.id)
        return (equip.name, getattr(equip, "serial_number", ""), booking.equipment_id)

    def _equipment_label_for_cancel(self, booking):
        equip = self.equipment_service.get_equipment(booking.equipment_id)
        if equip is None:
            return f"{booking.equipment_id} 알 수 없음"
        serial = getattr(equip, "serial_number", "") or booking.equipment_id
        return f"{serial} {_name_of(equip)}"

    # ── 목록 출력 + 선택 입력 ──
    def _select_booking(self, items):
        options = []
        groups_by_id = {}
        pending_by_id = {}
        for group, is_pending in items:
            rep = min(group, key=lambda b: b.id)
            options.append((rep.id, self._fmt(group, is_pending)))
            groups_by_id[rep.id] = group
            pending_by_id[rep.id] = is_pending
        selected_id = select_from_list(options, "취소할 예약 선택 (번호)")
        if not selected_id:
            return None, False
        return groups_by_id[selected_id], pending_by_id[selected_id]

    # ── 항목 포맷 ──
    def _fmt(self, group, pending):
        rep = min(group, key=lambda b: b.id)
        period = _period_str(rep)
        tag = "[대기] " if pending else ""
        if len(group) == 1:
            equip = self.equipment_service.get_equipment(rep.equipment_id)
            return f"{tag}{_name_of(equip)} / {period}"
        # 묶음: ㄱㄴㄷ순, 같은 이름이면 시리얼 오름차순. 시리얼 번호를 장비 왼쪽에 표시한다.
        parts = [
            self._equipment_label_for_cancel(b)
            for b in sorted(group, key=self._equipment_sort_key_for_cancel)
        ]
        joined = ", ".join(parts)
        if pending:
            return f"{tag}[묶음] {joined} / {period}"
        return f"[묶음] {joined} / {period}"

    # ══════════════════════════════════════════════════════════
    # pending 취소 (패널티·카운트 없음)
    # ══════════════════════════════════════════════════════════
    def _cancel_pending(self, group):
        if not _eq_confirm("정말 취소하시겠습니까? (y/n): "):
            return
        with global_lock():
            with UnitOfWork() as uow:
                for b in group:
                    updated = replace(b, status=EquipmentBookingStatus.CANCELLED,
                                      cancelled_at=now_iso(), updated_at=now_iso())
                    self.booking_repo.update(updated)
        print_success("예약 대기가 취소되었습니다.")

    # ══════════════════════════════════════════════════════════
    # reserved 취소
    # ══════════════════════════════════════════════════════════
    def _cancel_reserved(self, group):
        booking_id = min(group, key=lambda b: b.id).id
        impact = self.equipment_service.preview_cancel_booking_impact(
            self.user,
            booking_id,
        )
        if getattr(impact, "is_late_cancel", False):
            print_warning(f"직전 취소 패널티 {impact.total_penalty_points}점이 부과됩니다.")
        if review_action("장비 예약 취소 검토", "취소") != "confirm":
            return

        late_count = sum(1 for b in group if self._is_late_cancel(b))
        is_late = late_count > 0

        # ── 실제 취소 ──
        with global_lock():
            with UnitOfWork() as uow:
                if len(group) == 1:
                    self.equipment_service.cancel_booking(self.user, booking_id)
                else:
                    self._cancel_group_booking(group)
                self.user = self.user_repo.get_by_id(self.user.id)
                for line in self._apply_frequent_cancel_if_needed(booking_id, is_late):
                    print(line)

    # ── 묶음 취소 (직전 패널티 장비당 1점) ──
    def _cancel_group_booking(self, group):
        for b in group:
            updated = replace(b, status=EquipmentBookingStatus.CANCELLED,
                              cancelled_at=now_iso(), updated_at=now_iso())
            self.booking_repo.update(updated)
        for b in [x for x in group if self._is_late_cancel(x)]:
            self._append_penalty(PenaltyReason.LATE_CANCEL, LATE_CANCEL_POINT_PER_ITEM,
                                 b.id, "apply_late_cancel", "묶음 직전취소")
        self.audit_repo.log_action(
            actor_id=self.user.id, action="cancel_equipment_group_booking",
            target_type="equipment_booking",
            target_id=min(group, key=lambda b: b.id).group_id,
            details=f"묶음 {len(group)}건 취소",
        )

    # ── 직전 취소 판정: start_time == current_time ──
    def _is_late_cancel(self, booking):
        current = self.clock.now()
        start = datetime.fromisoformat(booking.start_time)
        return start == current

    # ══════════════════════════════════════════════════════════
    # 30일 반복 취소 로직
    # ══════════════════════════════════════════════════════════
    def _apply_frequent_cancel_if_needed(self, booking_id, is_late_cancel):
        cnt = self._count_cancellations_30()
        if is_late_cancel:
            # 직전 취소: 직전 패널티만, frequent 중복 부과 안 함
            if cnt == FREQUENT_CANCEL_THRESHOLD:
                self._update_restriction_until()
            # 4회 이상 직전: 제한 갱신 안 함
        else:
            # 일반 취소
            if cnt == FREQUENT_CANCEL_THRESHOLD:
                self._append_frequent_cancel_penalty(booking_id)
                self._update_restriction_until()
            elif cnt >= FREQUENT_CANCEL_THRESHOLD + 1:
                self._append_frequent_cancel_penalty(booking_id)
        return self._build_penalty_message(cnt, is_late_cancel)

    def _count_cancellations_30(self):
        """30일 내 취소 횟수 (시작 14일전 취소·관리자 취소 제외)"""
        all_b = self.equipment_service.get_user_bookings(self.user.id)
        current_date = self.clock.now().date()
        start_date = current_date - timedelta(days=29)
        cnt = 0
        for b in all_b:
            if b.status != EquipmentBookingStatus.CANCELLED:
                continue
            if not b.cancelled_at or b.cancelled_at == "-":
                continue
            cancel_date = datetime.fromisoformat(b.cancelled_at).date()
            if not (start_date <= cancel_date <= current_date):
                continue
            # 예약 시작 14일 이전 취소 → 미산정
            booking_start_date = datetime.fromisoformat(b.start_time).date()
            if cancel_date <= booking_start_date - timedelta(days=14):
                continue
            cnt += 1
        return cnt

    def _append_frequent_cancel_penalty(self, booking_id):
        self._append_penalty(PenaltyReason.FREQUENT_CANCEL, 1, booking_id,
                             "apply_frequent_cancel", "장비 30일 반복 취소")

    def _append_penalty(self, reason, points, related_id, action, detail):
        penalty = Penalty(
            id=generate_id(), user_id=self.user.id, reason=reason, points=points,
            related_type="equipment_booking", related_id=related_id, memo="",
            created_at=now_iso(), updated_at=now_iso(),
        )
        self.penalty_repo.add(penalty)
        self.user = replace(self.user,
                            penalty_points=self.user.penalty_points + points,
                            updated_at=now_iso())
        self.user_repo.update(self.user)
        self.audit_repo.log_action(
            actor_id=self.user.id, action=action, target_type="penalty",
            target_id=penalty.id, details=detail,
        )

    def _update_restriction_until(self):
        """취소 당일 포함 7일째 날의 다음날 09:00"""
        release_date = self.clock.now().date() + timedelta(days=RESTRICTION_DAYS)
        restriction_until = datetime.combine(release_date, time(9, 0)).isoformat()
        self.user = replace(self.user,
                            equipment_cancel_restricted_until=restriction_until,
                            updated_at=now_iso())
        self.user_repo.update(self.user)
        self.audit_repo.log_action(
            actor_id="system", action="update_restriction_until",
            target_type="user", target_id=self.user.id,
            details="장비 신규 예약 7일 제한",
        )

    def _build_penalty_message(self, cnt, is_late_cancel):
        release = (self.clock.now().date()
                   + timedelta(days=RESTRICTION_DAYS)).strftime("%Y-%m-%d")
        # 3회 미만: 정상 취소
        if cnt < FREQUENT_CANCEL_THRESHOLD:
            return ["✓ 장비 예약 취소가 완료되었습니다."]
        # 3회째 + 직전: 제한만, frequent 패널티 없음
        if is_late_cancel and cnt == FREQUENT_CANCEL_THRESHOLD:
            return ["✓ 장비 예약 취소가 완료되었습니다.",
                    "최근 30일 내 장비 예약 취소가 3회를 초과하였습니다.",
                    f"{release}까지 신규 예약이 제한됩니다."]
        # 4회이상 + 직전: 별도 메시지 없이 완료만
        if is_late_cancel and cnt >= FREQUENT_CANCEL_THRESHOLD + 1:
            return ["✓ 장비 예약 취소가 완료되었습니다."]
        # 3회째 + 일반: 패널티 1점 + 제한
        if not is_late_cancel and cnt == FREQUENT_CANCEL_THRESHOLD:
            return ["✓ 장비 예약 취소가 완료되었습니다.",
                    "최근 30일 내 장비 예약 취소가 3회를 초과하였습니다.",
                    f"패널티 1점이 부과되며, {release}까지 신규 예약이 제한됩니다."]
        # 4회이상 + 일반: 추가 패널티 1점
        return ["✓ 장비 예약 취소가 완료되었습니다.",
                "추가 취소로 인해 패널티 1점이 부과되었습니다."]


# ============================================================
# 6.5.2.6 장비 픽업 신청  (EquipmentPickupManager)
# ============================================================
# ============================================================
# 6.5.2.6 장비 픽업 신청  (EquipmentPickupManager)
#
# [기획서 흐름]
#  1. banned 체크
#  2. reserved 목록 (단일: "장비명 - 기간" / 묶음: "[묶음] SN 장비, SN 장비 - 기간")
#  3. 선택 → 시점 확인 (current == start)
#  4. 묶음이면 "선택한 묶음:" 상세 출력
#  5. "정말로 픽업 요청하시겠습니까? (y/n)"
#  6. 픽업 처리 → "픽업 요청이 접수되었습니다. 관리자 승인 대기 상태입니다."
#  7. "0. 돌아가기"
# ============================================================
class EquipmentPickupManager:
    def __init__(self, user, equipment_service, penalty_service):
        self.user = user
        self.penalty_service = penalty_service
        self.equipment_service = equipment_service
        self.clock = get_runtime_clock()
        self.booking_repo = equipment_service.booking_repo
        self.audit_repo = equipment_service.audit_repo

    def request_pickup(self):
        print_header("장비 픽업 신청")

        if self._banned():
            return

        items = self._build_pickup_list()
        if not items:
            print_info("픽업 요청 가능한 장비 예약이 없습니다.")
            _eq_back()
            return

        selected = self._select_booking(items)
        if selected is None:
            return

        current = self.clock.now()
        rep = min(selected, key=lambda b: b.id)
        if datetime.fromisoformat(rep.start_time) != current:
            print_error("현재 시점이 예약 시간보다 앞섭니다.")
            _eq_back()
            return

        if len(selected) > 1:
            print("\n선택한 묶음:")
            for b in sorted(selected, key=lambda x: _equipment_sort_key_by_serial(self.equipment_service, x)):
                equip = self.equipment_service.get_equipment(b.equipment_id)
                serial = equip.serial_number if equip else b.equipment_id
                print(f" - {_name_of(equip)} ({serial})")

        if not _eq_confirm("정말로 픽업 요청하시겠습니까? (y/n): "):
            return

        if len(selected) == 1:
            self.equipment_service.request_pickup(self.user, selected[0].id)
        else:
            self._request_group_pickup(selected[0].group_id)

        print_success("픽업 요청이 접수되었습니다. 관리자 승인 대기 상태입니다.")
        _eq_back()

    def _banned(self):
        try:
            status = self.penalty_service.get_user_status(self.user)
            if status.get("is_banned"):
                until = status.get("restriction_until")
                until = until[:10] if isinstance(until, str) and until else "-"
                print_error(f"이용이 금지된 상태입니다. 해제일: {until}")
                _eq_back()
                return True
        except PenaltyError:
            pass
        return False

    def _build_pickup_list(self):
        current_time = self.clock.now()
        bookings = [b for b in self.booking_repo.get_by_user(self.user.id)
                    if b.status == EquipmentBookingStatus.RESERVED
                    and datetime.fromisoformat(b.start_time) == current_time]
        groups = _group_by_group_id(bookings)
        groups.sort(key=lambda g: min(g, key=lambda b: b.start_time).start_time)
        return groups

    def _select_booking(self, items):
        options = []
        groups_by_id = {}
        for group in items:
            rep = min(group, key=lambda b: b.id)
            label = f"{_equipment_group_label(self.equipment_service, group, sort_by='serial')} - {_period_str(rep)}"
            options.append((rep.id, label))
            groups_by_id[rep.id] = group
        selected_id = select_from_list(options, "픽업할 장비 선택 (번호)")
        if not selected_id:
            return None
        return groups_by_id[selected_id]

    def _request_group_pickup(self, group_id):
        group = [b for b in self.booking_repo.get_by_user(self.user.id)
                 if b.group_id == group_id and b.status == EquipmentBookingStatus.RESERVED]
        with global_lock():
            with UnitOfWork() as uow:
                for b in group:
                    updated = replace(b, status=EquipmentBookingStatus.PICKUP_REQUESTED,
                                      requested_pickup_at=now_iso(), updated_at=now_iso())
                    self.booking_repo.update(updated)
                self.audit_repo.log_action(
                    actor_id=self.user.id, action="request_equipment_pickup_group",
                    target_type="equipment_booking", target_id=group_id,
                    details=f"묶음 {len(group)}건",
                )


# ============================================================
# 6.5.2.7 장비 반납 신청  (EquipmentReturnManager)
#
# [기획서 흐름]
#  1. banned 체크
#  2. checked_out 목록 (단일: "장비명 / SN / [사용중]"
#                      묶음: "[묶음] 장비1,장비2 / SN1,SN2 / [사용중]")
#  3. 선택
#  4. "정말로 반납하시겠습니까? (y/n)"
#  5. 반납 처리 → "장비 반납 신청이 완료되었습니다. 관리자 승인 대기 상태입니다."
#  6. "0. 돌아가기"
# ============================================================
class EquipmentReturnManager:
    def __init__(self, user, equipment_service, penalty_service):
        self.user = user
        self.penalty_service = penalty_service
        self.equipment_service = equipment_service
        self.booking_repo = equipment_service.booking_repo
        self.audit_repo = equipment_service.audit_repo

    def request_return(self):
        print_header("장비 반납 신청")

        if self._banned():
            return

        items = self._build_return_list()
        if not items:
            print_info("반납 신청 가능한 장비 예약이 없습니다.")
            _eq_back()
            return

        selected = self._select_booking(items)
        if selected is None:
            return

        if review_action("장비 반납 신청 검토", "반납") != "confirm":
            return

        if len(selected) == 1:
            self.equipment_service.request_return(self.user, selected[0].id)
        else:
            self._request_group_return(selected[0].group_id)

        print_success("장비 반납 신청이 완료되었습니다. 관리자 승인 대기 상태입니다.")
        _eq_back()

    def _banned(self):
        try:
            status = self.penalty_service.get_user_status(self.user)
            if status.get("is_banned"):
                until = status.get("restriction_until")
                until = until[:10] if isinstance(until, str) and until else "-"
                print_error(f"이용이 금지된 상태입니다. 해제일: {until}")
                _eq_back()
                return True
        except PenaltyError:
            pass
        return False

    def _build_return_list(self):
        bookings = [b for b in self.booking_repo.get_by_user(self.user.id)
                    if b.status == EquipmentBookingStatus.CHECKED_OUT]
        groups = _group_by_group_id(bookings)
        groups.sort(key=lambda g: min(g, key=lambda b: b.start_time).start_time)
        return groups

    def _select_booking(self, items):
        options = []
        groups_by_id = {}
        for group in items:
            rep = min(group, key=lambda b: b.id)
            label = f"{_equipment_group_label(self.equipment_service, group, sort_by='serial')} / [사용중]"
            options.append((rep.id, label))
            groups_by_id[rep.id] = group
        selected_id = select_from_list(options, "반납할 장비 선택 (번호)")
        if not selected_id:
            return None
        return groups_by_id[selected_id]

    def _request_group_return(self, group_id):
        group = [b for b in self.booking_repo.get_by_user(self.user.id)
                 if b.group_id == group_id and b.status == EquipmentBookingStatus.CHECKED_OUT]
        with global_lock():
            with UnitOfWork() as uow:
                for b in group:
                    updated = replace(b, status=EquipmentBookingStatus.RETURN_REQUESTED,
                                      requested_return_at=now_iso(), updated_at=now_iso())
                    self.booking_repo.update(updated)
                self.audit_repo.log_action(
                    actor_id=self.user.id, action="request_equipment_return_group",
                    target_type="equipment_booking", target_id=group_id,
                    details=f"묶음 {len(group)}건",
                )


# ============================================================
# 6.5.2.9 장비 예약 우선권  (EquipmentPriorityResolver)
#  - 시점 이동 시 PolicyService 등에서 resolve_all() 호출
# ============================================================
class EquipmentPriorityResolver:
    def __init__(self, equipment_service):
        self.equipment_service = equipment_service
        self.clock = equipment_service.clock
        self.booking_repo = equipment_service.booking_repo
        self.user_repo = equipment_service.user_repo
        self.audit_repo = equipment_service.audit_repo

    def resolve_all(self, current_time=None):
        if current_time is None:
            current_time = self.clock.now()
        pendings = [b for b in self.booking_repo.get_all()
                    if b.status == EquipmentBookingStatus.PENDING]
        if not pendings:
            return [], []
        confirmed_ids, cancelled_ids = [], []
        with global_lock():
            with UnitOfWork() as uow:
                for key, group in self._group_pendings(pendings).items():
                    sorted_group = self._sort_by_priority(group)
                    winner = sorted_group[0]
                    # 확정 전 기존 RESERVED와 겹침 확인
                    existing_reserved = [
                        b for b in self.booking_repo.get_by_equipment(key[0])
                        if b.status == EquipmentBookingStatus.RESERVED
                        and b.id != winner.id
                        and _overlap(key[1], key[2], b.start_time, b.end_time)
                    ]
                    if existing_reserved:
                        # 이미 확정된 예약과 겹침 → 전원 탈락
                        for b in sorted_group:
                            self.booking_repo.update(replace(
                                b, status=EquipmentBookingStatus.CANCELLED,
                                cancelled_at=current_time.isoformat(),
                                updated_at=current_time.isoformat()))
                            cancelled_ids.append(b.id)
                        continue

                    self.booking_repo.update(replace(
                        winner, status=EquipmentBookingStatus.RESERVED,
                        updated_at=current_time.isoformat()))
                    confirmed_ids.append(winner.id)
                    for loser in sorted_group[1:]:
                        self.booking_repo.update(replace(
                            loser, status=EquipmentBookingStatus.CANCELLED,
                            cancelled_at=current_time.isoformat(),
                            updated_at=current_time.isoformat()))
                        cancelled_ids.append(loser.id)
                    if len(sorted_group) > 1:
                        self.audit_repo.log_action(
                            actor_id="system", action="resolve_equipment_priority",
                            target_type="equipment_booking", target_id=key[0],
                            details=f"확정 1건, 탈락 {len(sorted_group) - 1}건")
        return confirmed_ids, cancelled_ids

    def _group_pendings(self, pendings):
        groups = {}
        for b in pendings:
            groups.setdefault((b.equipment_id, b.start_time, b.end_time), []).append(b)
        return groups

    def _sort_by_priority(self, group):
        def key(b):
            user = self.user_repo.get_by_id(b.user_id)
            return (user.penalty_points if user else 0, b.created_at)
        return sorted(group, key=key)

    def build_user_notifications(self, user_id, confirmed_ids, cancelled_ids):
        all_b = {b.id: b for b in self.booking_repo.get_all()}
        uc = [all_b[i] for i in confirmed_ids
              if i in all_b and all_b[i].user_id == user_id]
        ux = [all_b[i] for i in cancelled_ids
              if i in all_b and all_b[i].user_id == user_id]
        return self._format_lines(uc, True), self._format_lines(ux, False)

    def _format_lines(self, bookings, success):
        if not bookings:
            return []
        if success:
            header = "[알림] 동시 예약 시도로 인해 예약이 확정되었습니다."
        else:
            header = "[알림] 동시 예약 시도로 인해 예약에 실패하였습니다. 다시 시도해주세요."
        if len(bookings) == 1:
            return [header]
        # 복수건: ㄱㄴㄷ순 첫 번째 장비 기준
        def sort_key(b):
            equip = self.equipment_service.get_equipment(b.equipment_id)
            return (_name_of(equip), b.equipment_id)
        sorted_b = sorted(bookings, key=sort_key)
        first = sorted_b[0]
        equip = self.equipment_service.get_equipment(first.equipment_id)
        verb = "성공" if success else "실패"
        return [header, f"{_name_of(equip)} 예약 외 {len(sorted_b) - 1}건 {verb}"]

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
        # 장비 6.5.2.9: 운영 시계 이동 후 pending 예약 우선권 자동 처리 연결
        self._patch_policy_for_equipment_priority()

    def _run_policy_checks(self):
        try:
            self.policy_service.run_all_checks(resolve_pending=False)
            return True
        except PenaltyError as e:
            print_error(str(e))
            pause()
            return False

    def _patch_policy_for_equipment_priority(self):
        """운영 시계 이동 후 장비 pending 예약 우선권을 자동 확정/탈락 처리한다."""
        if not hasattr(self.policy_service, "advance_time"):
            return

        original_advance = self.policy_service.advance_time
        es = self.equipment_service
        user_ref = self

        def patched_advance(actor_id="system", force=False):
            result = original_advance(actor_id=actor_id, force=force)
            if result.get("can_advance"):
                resolver = EquipmentPriorityResolver(es)
                confirmed, cancelled = resolver.resolve_all()
                if confirmed or cancelled:
                    success_lines, fail_lines = resolver.build_user_notifications(
                        user_ref.user.id, confirmed, cancelled
                    )
                    events = result.get("events") or []
                    events.extend(success_lines)
                    events.extend(fail_lines)
                    result["events"] = events
            return result

        self.policy_service.advance_time = patched_advance

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

    # ----------------------------------------------------------------
    # 장비 파트 (8~14): 2차 장비 코드로 교체 — 헬퍼 클래스에 위임
    # ----------------------------------------------------------------
    def _resolve_equipment_priority(self):
        """시점 이동 후 pending 예약 우선권 자동 처리 + 사용자 알림."""
        resolver = EquipmentPriorityResolver(self.equipment_service)
        confirmed, cancelled = resolver.resolve_all()
        if confirmed or cancelled:
            success_lines, fail_lines = resolver.build_user_notifications(
                self.user.id, confirmed, cancelled
            )
            if success_lines or fail_lines:
                print()
                for line in success_lines:
                    print_success(line)
                for line in fail_lines:
                    print_warning(line)
                pause()

    def _show_equipment(self):                       # 6.5.2.1
        EquipmentListViewer(self.equipment_service).show()

    def _create_equipment_booking(self):             # 6.5.2.2 + 6.5.2.8
        if not self._refresh_user():
            return
        EquipmentGroupBookingManager(
            self.user, self.equipment_service, self.penalty_service
        ).create_group()

    def _show_my_equipment_bookings(self):           # 6.5.2.3
        EquipmentBookingViewer(self.user, self.equipment_service).show()

    def _modify_equipment_booking(self):             # 6.5.2.4
        if not self._refresh_user():
            return
        EquipmentBookingModifier(
            self.user, self.equipment_service, self.penalty_service
        ).modify()

    def _cancel_equipment_booking(self):             # 6.5.2.5
        if not self._run_policy_checks():
            return
        if not self._refresh_user():
            return
        EquipmentBookingCanceller(
            self.user, self.equipment_service, self.penalty_service
        ).cancel()

    def _request_equipment_pickup(self):             # 6.5.2.6
        if not self._refresh_user():
            return
        EquipmentPickupManager(
            self.user, self.equipment_service, self.penalty_service
        ).request_pickup()

    def _request_equipment_return(self):             # 6.5.2.7
        if not self._refresh_user():
            return
        EquipmentReturnManager(
            self.user, self.equipment_service, self.penalty_service
        ).request_return()

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
