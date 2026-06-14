from datetime import datetime, timedelta, time

from src.config import (
    BOOKING_WINDOW_DAYS,
    FIXED_BOOKING_START_HOUR,
    FIXED_BOOKING_START_MINUTE,
    FIXED_BOOKING_END_HOUR,
    FIXED_BOOKING_END_MINUTE,
    MAX_BOOKING_DAYS,
)


def get_daily_booking_window(now):
    today = now.date()
    return today + timedelta(days=1), today + timedelta(days=BOOKING_WINDOW_DAYS)


def validate_daily_booking_dates(start_date, end_date, now):
    min_date, max_date = get_daily_booking_window(now)
    today = now.date()

    if start_date < today:
        return False, "과거 날짜는 예약할 수 없습니다.", 0

    if start_date < min_date:
        return False, "당일 예약은 불가합니다. 내일부터 예약 가능합니다.", 0

    if start_date > max_date:
        return (
            False,
            f"예약 시작일은 오늘로부터 {BOOKING_WINDOW_DAYS}일 이내여야 합니다.",
            0,
        )

    if end_date < start_date:
        return False, "종료 날짜는 시작 날짜보다 빠를 수 없습니다.", 0

    duration_days = (end_date - start_date).days + 1
    if duration_days > MAX_BOOKING_DAYS:
        return False, f"예약 기간은 최대 {MAX_BOOKING_DAYS}일까지 가능합니다.", 0

    return True, "", duration_days


def build_daily_booking_period(start_date, end_date):
    start_time = datetime.combine(
        start_date,
        time(hour=FIXED_BOOKING_START_HOUR, minute=FIXED_BOOKING_START_MINUTE),
    )
    end_time = datetime.combine(
        end_date,
        time(hour=FIXED_BOOKING_END_HOUR, minute=FIXED_BOOKING_END_MINUTE),
    )
    return start_time, end_time


def validate_maintenance_dates(start_date, end_date, now):
    """정기 점검 시작일/종료일 의미 규칙 검증 (기획서 6.6.1.2.2)

    반환: (valid, error_message, duration_days)
    예약(회의실 예약) 충돌 검증은 RoomService에서 별도로 수행한다.
    """
    today = now.date()

    # 시작일 == 종료일 (시작 18:00, 종료 09:00 이므로 같은 날짜 불가)
    if start_date == end_date:
        return (
            False,
            "정기 점검은 시작일 기준 18 시부터 시작되고 종료일 기준 09시까지 진행되므로, 날짜가 같을 수 없습니다.",
            0,
        )
    # 종료일이 시작일보다 앞섬
    if end_date < start_date:
        return False, "정기 점검 종료일은 정기 점검 시작일보다 앞설 수 없습니다.", 0
    # 시작일 == 현재 운영 시점 (당일 시작 불가)
    if start_date == today:
        return False, "정기 점검 시작일은 현 운영 시점과 동일할 수 없습니다.", 0
    # 시작일이 과거
    if start_date < today:
        return False, "정기 점검 시작일은 과거일 수 없습니다.", 0
    # 시작일은 현재 운영 시점 기준 180일 이내
    if start_date > today + timedelta(days=BOOKING_WINDOW_DAYS):
        return (
            False,
            f"정기 점검 시작일은 현재 운영 시점 기준 {BOOKING_WINDOW_DAYS}일 이내여야 합니다.",
            0,
        )
    # 점검 기간 최대 14일
    duration_days = (end_date - start_date).days + 1
    if duration_days > MAX_BOOKING_DAYS:
        return False, f"정기 점검 기간은 최대 {MAX_BOOKING_DAYS}일까지 가능합니다.", 0

    return True, "", duration_days


def build_maintenance_period(start_date, end_date):
    # 정기 점검 기간: 시작일 18:00 ~ 종료일 09:00
    start_time = datetime.combine(
        start_date,
        time(hour=FIXED_BOOKING_END_HOUR, minute=FIXED_BOOKING_END_MINUTE),
    )
    end_time = datetime.combine(
        end_date,
        time(hour=FIXED_BOOKING_START_HOUR, minute=FIXED_BOOKING_START_MINUTE),
    )
    return start_time, end_time
