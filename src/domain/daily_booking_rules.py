from calendar import monthrange
from datetime import datetime, timedelta, time

from src.config import (
    BOOKING_WINDOW_MONTHS,
    FIXED_BOOKING_START_HOUR,
    FIXED_BOOKING_START_MINUTE,
    FIXED_BOOKING_END_HOUR,
    FIXED_BOOKING_END_MINUTE,
    MAX_BOOKING_DAYS,
)


def add_months(base_date, months):
    month_index = base_date.month - 1 + months
    year = base_date.year + month_index // 12
    month = month_index % 12 + 1
    day = min(base_date.day, monthrange(year, month)[1])
    return base_date.replace(year=year, month=month, day=day)


def get_daily_booking_window(now):
    today = now.date()
    return today + timedelta(days=1), add_months(today, BOOKING_WINDOW_MONTHS)


def validate_daily_booking_dates(start_date, end_date, now):
    min_date, max_date = get_daily_booking_window(now)

    if start_date < min_date:
        return False, "당일 예약은 불가하며 내일부터 예약할 수 있습니다.", 0

    if start_date > max_date:
        return (
            False,
            f"예약 시작일은 내일부터 최대 {BOOKING_WINDOW_MONTHS}개월까지만 선택할 수 있습니다.",
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


def calculate_request_delay_minutes(end_time, requested_at):
    if requested_at <= end_time:
        return 0
    return int((requested_at - end_time).total_seconds() / 60)
