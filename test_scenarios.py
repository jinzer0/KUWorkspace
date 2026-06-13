"""
회의실 메뉴 1~7 종합 시나리오 테스트
"""
import sys, io, contextlib
from pathlib import Path
from datetime import datetime, date, timedelta
from unittest.mock import patch
from dataclasses import replace

sys.path.insert(0, str(Path(__file__).parent))

from src.config import ensure_data_dir
from src.runtime_clock import SystemClock, set_active_clock
from src.domain.models import RoomBookingStatus, now_iso
from src.domain.auth_service import AuthService
from src.domain.room_service import RoomService, RoomBookingError
from src.domain.equipment_service import EquipmentService
from src.domain.penalty_service import PenaltyService
from src.domain.policy_service import PolicyService
from src.domain.daily_booking_rules import build_daily_booking_period, validate_daily_booking_dates
from src.cli.validators import validate_positive_int, validate_date_plan
from src.cli.user_menu import UserMenu
from src.storage.repositories import UserRepository, UnitOfWork
from src.storage.file_lock import global_lock

SEP = "=" * 60
passed = failed = 0


def ok(label, detail=""):
    global passed
    passed += 1
    suffix = f"  ({detail})" if detail else ""
    print(f"  ✓  {label}{suffix}")


def fail(label, detail=""):
    global failed
    failed += 1
    suffix = f"  → {detail}" if detail else ""
    print(f"  ✗  {label}{suffix}")


def sec(title):
    print(f"\n{SEP}\n  {title}\n{SEP}")


def run_fn(fn, inputs):
    buf = io.StringIO()
    it = iter(inputs)
    with contextlib.redirect_stdout(buf), \
         patch("builtins.input", side_effect=lambda _="": next(it, "")):
        fn()
    return buf.getvalue()


def set_penalty_points(user_id, points):
    """penalty_points와 restriction_until을 함께 설정 (실제 패널티 부과 로직 모사)."""
    from src.config import (
        PENALTY_BAN_THRESHOLD, PENALTY_RESTRICTION_THRESHOLD,
        BAN_DURATION_DAYS, RESTRICTION_DURATION_DAYS,
    )
    from src.runtime_clock import get_current_time
    now = get_current_time()
    if points >= PENALTY_BAN_THRESHOLD:
        restriction_until = (now + timedelta(days=BAN_DURATION_DAYS)).isoformat()
    elif points >= PENALTY_RESTRICTION_THRESHOLD:
        restriction_until = (now + timedelta(days=RESTRICTION_DURATION_DAYS)).isoformat()
    else:
        restriction_until = None
    repo = UserRepository()
    with global_lock(), UnitOfWork():
        u = repo.get_by_id(user_id)
        repo.update(replace(u, penalty_points=points,
                            restriction_until=restriction_until,
                            updated_at=now_iso()))
    return repo.get_by_id(user_id)


def make_booking(room_svc, user, start_d, end_d=None, attendees=3):
    if end_d is None:
        end_d = start_d
    s, e = build_daily_booking_period(start_d, end_d)
    avail = room_svc.get_available_rooms_for_attendees(attendees, s, e)
    if not avail:
        raise RuntimeError(f"{start_d} 예약 가능 회의실 없음")
    return room_svc.create_daily_booking(
        user=user, room_id=avail[0].id,
        start_date=start_d, end_date=end_d,
        attendee_count=attendees, max_active=1,
    )


def new_user(auth, name):
    try:
        return auth.signup(name, "pass1234")
    except Exception:
        return auth.login(name, "pass1234")


td = timedelta


def main():
    ensure_data_dir()

    clock = SystemClock(datetime(2026, 4, 11, 9, 0))
    set_active_clock(clock)

    auth      = AuthService()
    penalty   = PenaltyService()
    room_svc  = RoomService(penalty_service=penalty)
    equip_svc = EquipmentService(penalty_service=penalty)
    policy    = PolicyService()
    admin     = auth.get_user("admin")

    def menu(user):
        return UserMenu(user=user, auth_service=auth, room_service=room_svc,
                        equipment_service=equip_svc, penalty_service=penalty,
                        policy_service=policy)

    # ════════════════════════════════════════════════════════════
    # 1. 정상 흐름
    # ════════════════════════════════════════════════════════════
    sec("1. 정상 흐름: 예약 → 체크인요청 → 승인 → 퇴실신청 → 승인")
    clock.set_time(datetime(2026, 4, 11, 9, 0))

    u1 = new_user(auth, "sc_flow")
    b = make_booking(room_svc, u1, date(2026, 4, 13))
    ok(f"예약 생성", f"{b.start_time[:10]} [{b.status.value}]")

    clock.set_time(datetime(2026, 4, 13, 9, 0))
    b = room_svc.request_check_in(u1, b.id)
    ok("체크인 요청", f"[{b.status.value}]")

    b = room_svc.check_in(admin, b.id)
    ok("관리자 체크인 승인", f"[{b.status.value}]")

    clock.set_time(datetime(2026, 4, 13, 18, 0))
    b = room_svc.request_checkout(u1, b.id)
    ok("퇴실 신청", f"[{b.status.value}]")

    b, delay = room_svc.approve_checkout_request(admin, b.id)
    ok("관리자 퇴실 승인", f"[{b.status.value}]  지연={delay}분")

    # ════════════════════════════════════════════════════════════
    # 2. 이용 인원 경계값
    # ════════════════════════════════════════════════════════════
    sec("2. 이용 인원 경계값  (min=1, max=8)")

    cases = [
        ("-1",  False, "1 이상의 값"),
        ("0",   False, "1 이상의 값"),
        ("1",   True,  None),
        ("8",   True,  None),
        ("9",   False, "8 이하의 값"),
        ("abc", False, "숫자를 입력"),
    ]
    for inp, expect_valid, expect_substr in cases:
        v, val, msg = validate_positive_int(inp, 1, 8)
        label = f"입력 {inp!r:6s}"
        if v != expect_valid:
            fail(label, f"expect valid={expect_valid}, got={v}, msg={msg!r}")
        elif not v and expect_substr and expect_substr not in msg:
            fail(label, f"메시지에 {expect_substr!r} 없음 (got={msg!r})")
        else:
            ok(label, f"{'유효' if v else '오류: '+msg}")

    # ════════════════════════════════════════════════════════════
    # 3. 날짜 경계값
    # ════════════════════════════════════════════════════════════
    sec("3. 날짜 경계값  (기준 시계: 2026-04-11 09:00)")
    clock.set_time(datetime(2026, 4, 11, 9, 0))
    now = clock.now()
    today = now.date()

    date_cases = [
        (today,          today,          False, "오늘 (당일 예약 불가)"),
        (today+td(1),    today+td(1),    True,  "내일 (최소 시작일)"),
        (today+td(180),  today+td(180),  True,  "오늘+180일 (최대 시작일)"),
        (today+td(181),  today+td(181),  False, "오늘+181일 (초과)"),
        (today+td(1),    today+td(14),   True,  "14일 기간 (최대)"),
        (today+td(1),    today+td(15),   False, "15일 기간 (초과)"),
    ]
    for s_d, e_d, expect_ok, label in date_cases:
        v, msg, days = validate_daily_booking_dates(s_d, e_d, now)
        if v == expect_ok:
            ok(label, f"{'유효 '+str(days)+'일' if v else '오류: '+msg}")
        else:
            fail(label, f"expect={expect_ok}, got={v}, msg={msg!r}")

    # 존재하지 않는 날짜
    v, _, msg = validate_date_plan("2026-02-30")
    if not v:
        ok("2026-02-30 (존재 안 하는 날짜)", f"오류: {msg}")
    else:
        fail("2026-02-30 존재하지 않는 날짜 → 유효 처리됨")

    # ════════════════════════════════════════════════════════════
    # 4. 날짜 형식 오류
    # ════════════════════════════════════════════════════════════
    sec("4. 날짜 형식 오류")

    fmt_cases = [
        ("2026/04/13", "슬래시 구분자"),
        ("26-04-13",   "연도 2자리"),
        ("2026-04.13", "혼합 구분자 (- 와 .)"),
        ("2026-4-13",  "월 0 패딩 없음"),
        ("",           "빈 입력"),
    ]
    for inp, label in fmt_cases:
        v, _, msg = validate_date_plan(inp)
        if not v:
            ok(f"{label}  {inp!r}", f"오류: {msg}")
        else:
            fail(f"{label}  {inp!r}", "유효 처리됨 (오류여야 함)")

    # ════════════════════════════════════════════════════════════
    # 5. 패널티 제한 상태 (3점)
    # ════════════════════════════════════════════════════════════
    sec("5. 패널티 제한 상태 (3점: 활성 예약 1건 한도)")
    clock.set_time(datetime(2026, 4, 11, 9, 0))

    u_res = new_user(auth, "sc_restricted")
    set_penalty_points(u_res.id, 3)
    u_res = auth.get_user(u_res.id)

    # 활성 0건 → 예약 가능
    try:
        b_res = make_booking(room_svc, u_res, date(2026, 4, 20))
        ok("3점, 활성 0건 → 예약 성공", f"[{b_res.status.value}]")
    except RoomBookingError as e:
        fail("3점, 활성 0건 → 예약 성공이어야 함", str(e))

    # 활성 1건 → 추가 예약 불가
    try:
        make_booking(room_svc, u_res, date(2026, 4, 21))
        fail("3점, 활성 1건 → 거부여야 함")
    except RoomBookingError as e:
        ok("3점, 활성 1건 → 예약 거부", str(e))

    # ════════════════════════════════════════════════════════════
    # 6. 이용 금지 상태 (6점)
    # ════════════════════════════════════════════════════════════
    sec("6. 이용 금지 상태 (6점)")
    clock.set_time(datetime(2026, 4, 11, 9, 0))

    u_ban = new_user(auth, "sc_banned")
    set_penalty_points(u_ban.id, 6)
    u_ban = auth.get_user(u_ban.id)

    # 예약 시도 → 거부
    try:
        make_booking(room_svc, u_ban, date(2026, 4, 22))
        fail("금지 상태 예약 → 거부여야 함")
    except RoomBookingError as e:
        ok("금지 상태 예약 시도 → 거부", str(e))

    # 금지 전 예약 생성 후 → 정책 점검 시 자동 취소 확인
    u_ban2 = new_user(auth, "sc_banned2")
    b_ban2 = make_booking(room_svc, u_ban2, date(2026, 4, 23))
    ok("금지 전 예약 생성", f"[{b_ban2.status.value}]")

    set_penalty_points(u_ban2.id, 6)
    policy.run_all_checks()

    b_ban2_upd = room_svc.get_user_bookings(u_ban2.id)[0]
    if b_ban2_upd.status == RoomBookingStatus.ADMIN_CANCELLED:
        ok("금지 상태 후 정책 점검 → 예약 자동 취소", f"[{b_ban2_upd.status.value}]")
    else:
        fail("자동 취소 기대", f"status={b_ban2_upd.status.value}")

    # 변경 시도 → 이미 취소된 예약
    try:
        room_svc.modify_daily_booking(u_ban2, b_ban2.id, date(2026, 4, 24), date(2026, 4, 24))
        fail("취소된 예약 변경 → 거부여야 함")
    except RoomBookingError as e:
        ok("취소된 예약 변경 시도 → 거부", str(e))

    # ════════════════════════════════════════════════════════════
    # 7. 직전 취소 (시계 = 예약 당일 09:00)
    # ════════════════════════════════════════════════════════════
    sec("7. 직전 취소 — 패널티 경고 문구 출력 및 패널티 2점 부과")
    clock.set_time(datetime(2026, 4, 11, 9, 0))

    u_lc = new_user(auth, "sc_latecancel")
    make_booking(room_svc, u_lc, date(2026, 4, 12))
    ok("예약 생성", "2026-04-12")

    clock.set_time(datetime(2026, 4, 12, 9, 0))
    print(f"  [시계 이동] 2026-04-12 09:00")

    out = run_fn(menu(u_lc)._cancel_room_booking, ["1", "y", ""])

    if "직전 취소로 인해 패널티 2점이 부과됩니다" in out:
        ok("직전 취소 경고 문구 출력")
    else:
        fail("직전 취소 경고 문구 없음", repr(out[:150]))

    if "예약이 취소되었습니다" in out:
        ok("취소 완료")
    else:
        fail("취소 미완료")

    status = penalty.get_user_status(auth.get_user(u_lc.id))
    pts = status.get("points", 0)
    if pts >= 2:
        ok(f"패널티 2점 부과 확인", f"현재 {pts}점")
    else:
        fail("패널티 미부과", f"현재 {pts}점")

    # ════════════════════════════════════════════════════════════
    # 8. 작은 회의실 우선 선택 강제
    # ════════════════════════════════════════════════════════════
    sec("8. 작은 회의실 우선 선택 강제")
    clock.set_time(datetime(2026, 4, 11, 9, 0))

    u_sm = new_user(auth, "sc_smallroom")

    # 3명 이용: [4A(4명)=1번, 4B=2번, 4C=3번, 6A(6명)=4번, ...]
    # → 4번(6A) 선택 → 경고 → 1번(4A) 선택 → 예약
    out = run_fn(
        menu(u_sm)._create_room_booking,
        [
            "3",           # 이용 인원
            "2026-04-25",  # 시작 날짜
            "2026-04-25",  # 종료 날짜
            "4",           # 6A (6명) 선택 → 경고
            "1",           # 4A (4명) 선택 → 통과
            "",            # pause
        ],
    )

    if "더 작은 회의실이 예약 가능합니다" in out:
        ok("큰 회의실 선택 시 경고 출력")
    else:
        fail("경고 없음", repr(out[:150]))

    if "예약이 완료되었습니다" in out:
        ok("재선택 후 예약 완료")
    else:
        fail("예약 미완료", repr(out[:150]))

    # ════════════════════════════════════════════════════════════
    # 9. 이미 활성 예약 있을 때 추가 예약 시도
    # ════════════════════════════════════════════════════════════
    sec("9. 이미 활성 예약 있을 때 추가 예약 시도")
    clock.set_time(datetime(2026, 4, 11, 9, 0))

    u_dup = new_user(auth, "sc_dup")
    make_booking(room_svc, u_dup, date(2026, 4, 16))
    ok("첫 번째 예약 생성", "2026-04-16")

    try:
        make_booking(room_svc, u_dup, date(2026, 4, 17))
        fail("두 번째 예약 → 거부여야 함")
    except RoomBookingError as e:
        ok("두 번째 예약 거부", str(e))

    # ════════════════════════════════════════════════════════════
    # 최종 결과
    # ════════════════════════════════════════════════════════════
    total = passed + failed
    print(f"\n{SEP}")
    print(f"  결과: {passed}/{total} 통과   실패: {failed}")
    print(SEP)


if __name__ == "__main__":
    main()
