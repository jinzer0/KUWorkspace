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
