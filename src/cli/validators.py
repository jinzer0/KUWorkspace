"""
CLI 입력 검증 유틸리티
"""

from datetime import datetime, timedelta
import re

from src.config import MAX_BOOKING_DAYS, TIME_SLOT_MINUTES
from src.domain.daily_booking_rules import validate_daily_booking_dates
from src.domain.auth_rules import (
    validate_username as validate_auth_username,
    validate_password as validate_auth_password,
)
from src.runtime_clock import get_current_time


def validate_date_input(date_str):
    """
    날짜 입력 검증 (YYYY-MM-DD 형식)

    Returns:
        (valid, datetime_obj, error_message)
    """
    date_str = date_str.strip()

    # 형식 검증
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return False, None, "날짜 형식이 올바르지 않습니다. (예: 2024-01-15)"

    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return False, None, "유효하지 않은 날짜입니다."

    # 날짜 범위 검증
    today = get_current_time().replace(hour=0, minute=0, second=0, microsecond=0)
    max_date = today + timedelta(days=MAX_BOOKING_DAYS)

    if date < today:
        return False, None, "과거 날짜는 선택할 수 없습니다."

    if date > max_date:
        return False, None, f"{MAX_BOOKING_DAYS}일 이내의 날짜만 선택 가능합니다."

    return True, date, ""


def validate_time_input(time_str):
    """
    시간 입력 검증 (HH:MM 형식, 30분 단위)

    Returns:
        (valid, time_obj, error_message)
    """
    time_str = time_str.strip()

    # 형식 검증
    if not re.match(r"^\d{2}:\d{2}$", time_str):
        return False, None, "시간 형식이 올바르지 않습니다. (예: 09:00, 14:30)"

    try:
        time = datetime.strptime(time_str, "%H:%M")
    except ValueError:
        return False, None, "유효하지 않은 시간입니다."

    # 30분 단위 검증
    if time.minute % TIME_SLOT_MINUTES != 0:
        return (
            False,
            None,
            f"시간은 {TIME_SLOT_MINUTES}분 단위로만 입력 가능합니다. (예: 09:00, 09:30)",
        )

    return True, time, ""


def validate_datetime_input(date_str, time_str):
    """
    날짜+시간 입력 검증

    Returns:
        (valid, datetime_obj, error_message)
    """
    # 날짜 검증
    date_valid, date_obj, date_error = validate_date_input(date_str)
    if not date_valid:
        return False, None, date_error

    # 시간 검증
    time_valid, time_obj, time_error = validate_time_input(time_str)
    if not time_valid:
        return False, None, time_error

    assert date_obj is not None
    assert time_obj is not None
    combined = date_obj.replace(
        hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0
    )

    # 과거 시간 검증
    if combined < get_current_time():
        return False, None, "과거 시간은 선택할 수 없습니다."

    return True, combined, ""


def validate_positive_int(value_str, min_val=1, max_val=100):
    """
    양의 정수 입력 검증

    Returns:
        (valid, int_value, error_message)
    """
    value_str = value_str.strip()

    if not value_str.isdigit():
        return False, None, "숫자를 입력해주세요."

    value = int(value_str)

    if value < min_val:
        return False, None, f"{min_val} 이상의 값을 입력해주세요."

    if value > max_val:
        return False, None, f"{max_val} 이하의 값을 입력해주세요."

    return True, value, ""


def validate_menu_choice(choice, max_option, allow_zero=True):
    """
    메뉴 선택 검증

    Returns:
        (valid, choice_int, error_message)
    """
    choice = choice.strip()

    if not choice.isdigit():
        return False, None, "숫자를 입력해주세요."

    choice_int = int(choice)
    min_val = 0 if allow_zero else 1

    if choice_int < min_val or choice_int > max_option:
        return False, None, f"{min_val}~{max_option} 사이의 숫자를 입력해주세요."

    return True, choice_int, ""


def validate_username(username):
    """
    사용자명 검증

    Returns:
        (valid, error_message)
    """
    return validate_auth_username(username)


def validate_password(password):
    """
    비밀번호 검증

    Returns:
        (valid, error_message)
    """
    return validate_auth_password(password)


def get_date_input(prompt="날짜 (YYYY-MM-DD)"):
    """날짜 입력 받기 (취소 시 None)"""
    while True:
        date_str = input(f"{prompt}: ").strip()
        if date_str.lower() in ("q", "quit", "취소"):
            return None

        valid, date_obj, error = validate_date_input(date_str)
        if valid:
            return date_obj
        print(f"  ✗ {error}")


def get_time_input(prompt="시간 (HH:MM)"):
    """시간 입력 받기 (취소 시 None)"""
    while True:
        time_str = input(f"{prompt}: ").strip()
        if time_str.lower() in ("q", "quit", "취소"):
            return None

        valid, time_obj, error = validate_time_input(time_str)
        if valid:
            return time_obj
        print(f"  ✗ {error}")


def get_datetime_input(date_prompt="날짜", time_prompt="시간"):
    """날짜+시간 입력 받기"""
    print("  (취소하려면 'q' 입력)")

    while True:
        date_str = input(f"  {date_prompt} (YYYY-MM-DD): ").strip()
        if date_str.lower() in ("q", "quit", "취소"):
            return None

        time_str = input(f"  {time_prompt} (HH:MM): ").strip()
        if time_str.lower() in ("q", "quit", "취소"):
            return None

        valid, dt_obj, error = validate_datetime_input(date_str, time_str)
        if valid:
            return dt_obj
        print(f"  ✗ {error}")


def get_daily_date_range_input(start_prompt="시작 날짜", end_prompt="종료 날짜"):
    while True:
        start_str = input(f"  {start_prompt} (YYYY-MM-DD): ").strip()
        if start_str.lower() in ("q", "quit", "취소"):
            return None, None

        end_str = input(f"  {end_prompt} (YYYY-MM-DD): ").strip()
        if end_str.lower() in ("q", "quit", "취소"):
            return None, None

        if not re.match(r"^\d{4}-\d{2}-\d{2}$", start_str):
            print("  ✗ 날짜 형식이 올바르지 않습니다. (예: 2024-01-15)")
            continue
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", end_str):
            print("  ✗ 날짜 형식이 올바르지 않습니다. (예: 2024-01-15)")
            continue

        try:
            start_date = datetime.strptime(start_str, "%Y-%m-%d")
            end_date = datetime.strptime(end_str, "%Y-%m-%d")
        except ValueError:
            print("  ✗ 유효하지 않은 날짜입니다.")
            continue

        valid, error, _ = validate_daily_booking_dates(
            start_date.date(), end_date.date(), get_current_time()
        )
        if valid:
            return start_date.date(), end_date.date()
        print(f"  ✗ {error}")


def get_positive_int_input(prompt, min_val=1, max_val=100):
    while True:
        value_str = input(f"{prompt}: ").strip()
        if value_str.lower() in ("q", "quit", "취소"):
            return None

        valid, value, error = validate_positive_int(value_str, min_val, max_val)
        if valid:
            return value
        print(f"  ✗ {error}")
