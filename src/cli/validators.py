"""
CLI 입력 검증 유틸리티
"""

from datetime import datetime
import re

from src.domain.daily_booking_rules import validate_daily_booking_dates
from src.domain.auth_rules import (
    validate_username as validate_auth_username,
    validate_password as validate_auth_password,
)
from src.domain.field_rules import validate_reason_text
from src.runtime_clock import get_current_time


def validate_positive_int(value_str, min_val=1, max_val=100):
    """
    양의 정수 입력 검증

    Returns:
        (valid, int_value, error_message)
    """
    value_str = value_str.strip()

    try:
        value = int(value_str)
    except ValueError:
        return False, None, "숫자를 입력해주세요."

    if value < min_val:
        return False, None, f"{min_val} 이상의 값을 입력해주세요."

    if value > max_val:
        return False, None, f"{max_val} 이하의 값을 입력해주세요."

    return True, value, ""


def validate_username(username):
    """
    사용자명 검증

    Returns:
        (valid, error_message)
    """
    return validate_auth_username(username)


def validate_password(password):
    """
    비밀번호 검증 (final_plan.md 4.1.2)
    
    문법 규칙:
    - 길이: 4 이상 50 이하
    - 공백 미포함 (plan 4.1.2 명시)
    
    Returns:
        (valid, error_message)
    """
    return validate_auth_password(password)


def validate_date_plan(date_str):
    """
    날짜 검증 (final_plan.md 4.2.1)
    
    문법 규칙:
    - 형식: YYYY-MM-DD, YYYY.MM.DD, YYYY MM DD
    - 연도: 2026~2100 사이 정수
    - 월: 1~12 사이 정수
    - 일: 1~31 사이 정수
    - 구분자 혼합 불가 (e.g., "2026-04.03" 거절)
    - 월, 일은 0 패딩 필수 (e.g., "2026.4.3" → "2026.04.03")
    - 문자열 선후 공백 미포함
    
    의미 규칙:
    - 실제 해당 월에 존재하는 날짜 (e.g., 2월 31일 거절)
    
    Returns:
        (valid, datetime_obj, error_message)
    """
    if not isinstance(date_str, str):
        return False, None, "날짜는 텍스트여야 합니다."

    if not date_str or not date_str.strip():
        return False, None, "날짜를 입력해주세요."

    if date_str != date_str.strip():
        return False, None, "날짜 앞뒤에 공백을 포함할 수 없습니다."

    # 구분자 선택 및 일관성 확인
    separator = None
    if '-' in date_str:
        separator = '-'
    elif '.' in date_str:
        separator = '.'
    elif ' ' in date_str:
        separator = ' '
    else:
        return False, None, "날짜 형식이 올바르지 않습니다. (예: 2026-04-03, 2026.04.03, 2026 04 03)"
    
    # 구분자 혼합 확인
    other_seps = [s for s in ['-', '.', ' '] if s != separator]
    for sep in other_seps:
        if sep in date_str:
            return False, None, "날짜에 여러 구분자를 혼합할 수 없습니다."
    
    # 분할
    parts = date_str.split(separator)
    if len(parts) != 3:
        return False, None, "날짜 형식이 올바르지 않습니다. (예: 2026-04-03)"
    
    try:
        year_str, month_str, day_str = parts

        if len(year_str) != 4:
            return False, None, "연도는 4자리여야 합니다."

        # 0 패딩 확인 (월, 일은 2자리 필수)
        if len(month_str) != 2 or len(day_str) != 2:
            return False, None, "월과 일은 0을 포함한 2자리여야 합니다. (예: 2026-04-03)"
        
        year = int(year_str)
        month = int(month_str)
        day = int(day_str)
        
        # 범위 확인
        if year < 2026 or year > 2100:
            return False, None, "연도는 2026~2100 사이여야 합니다."
        
        if month < 1 or month > 12:
            return False, None, "월은 1~12 사이여야 합니다."
        
        if day < 1 or day > 31:
            return False, None, "일은 1~31 사이여야 합니다."
        
        # 실제 유효한 날짜 확인 (leap year 포함)
        date_obj = datetime(year, month, day).date()
        return True, date_obj, ""
    
    except ValueError as e:
        if "month must be in" in str(e):
            return False, None, "유효한 월을 입력해주세요. (1~12)"
        elif "day is out of range" in str(e):
            return False, None, "유효한 날짜를 입력해주세요."
        else:
            return False, None, "유효하지 않은 날짜입니다."
    except (TypeError, IndexError):
        return False, None, "날짜 형식이 올바르지 않습니다."


def validate_time_plan(time_str):
    """
    시간 검증 (final_plan.md 4.2.2)
    
    문법 규칙:
    - 형식: HH:MM, HHMM
    - 시: 09 또는 18
    - 분: 00
    - 구분자 혼합 불가 (e.g., "09:00MM" 거절)
    - 공백 미포함
    
    의미 규칙:
    - 실존하는 시각 (09:00 또는 18:00만 예약 처리에 영향)
    
    Returns:
        (valid, time_obj, error_message)
    """
    if not isinstance(time_str, str):
        return False, None, "시간은 텍스트여야 합니다."

    if not time_str or not time_str.strip():
        return False, None, "시간을 입력해주세요."

    if time_str != time_str.strip():
        return False, None, "시간 앞뒤에 공백을 포함할 수 없습니다."

    # 공백 확인
    if ' ' in time_str or '\t' in time_str or '\n' in time_str:
        return False, None, "시간에 공백을 포함할 수 없습니다."
    
    # 형식 선택: HH:MM 또는 HHMM
    if ':' in time_str:
        # HH:MM 형식
        parts = time_str.split(':')
        if len(parts) != 2:
            return False, None, "시간 형식이 올바르지 않습니다. (예: 09:00 또는 1800)"
        hour_str, minute_str = parts
        if (
            len(hour_str) != 2
            or len(minute_str) != 2
            or not hour_str.isdigit()
            or not minute_str.isdigit()
        ):
            return False, None, "시간 형식이 올바르지 않습니다. (예: 09:00 또는 1800)"
    else:
        # HHMM 형식
        if len(time_str) != 4 or not time_str.isdigit():
            return False, None, "시간 형식이 올바르지 않습니다. (예: 09:00 또는 1800)"
        hour_str = time_str[:2]
        minute_str = time_str[2:]
    
    try:
        hour = int(hour_str)
        minute = int(minute_str)
        
        # 유효한 시각 확인
        if hour not in (9, 18):
            return False, None, "시간은 09 또는 18만 가능합니다."
        
        if minute != 0:
            return False, None, "분은 00만 가능합니다."
        
        time_obj = datetime(2000, 1, 1, hour, minute, 0).time()
        return True, time_obj, ""
    
    except ValueError:
        return False, None, "유효한 시간을 입력해주세요. (09:00 또는 18:00)"


def validate_equipment_serial(serial_str):
    """
    장비 시리얼 번호 검증 (final_plan.md 4.3.2)
    
    문법 규칙:
    - 형식: [장비 영문 대문자 약어]-[고유번호]
    - 유효한 약어: NB (노트북), PJ (프로젝터), WC (웹캠), CB (케이블)
    - 고유번호: 001, 002, 003 (형식: 3자리 0 패딩)
    - 예: PJ-001, NB-002, CB-003, WC-001
    
    Returns:
        (valid, error_message)
    """
    if not isinstance(serial_str, str):
        return False, "시리얼 번호는 텍스트여야 합니다."
    
    serial_str = serial_str.strip()
    
    if not serial_str:
        return False, "시리얼 번호를 입력해주세요."
    
    # 형식 확인: [TYPE]-[NUMBER]
    if '-' not in serial_str:
        return False, "시리얼 번호 형식이 올바르지 않습니다. (예: PJ-001)"
    
    parts = serial_str.split('-')
    if len(parts) != 2:
        return False, "시리얼 번호 형식이 올바르지 않습니다. (예: PJ-001)"
    
    type_part, number_part = parts
    
    # 장비 유형 확인
    valid_types = {'NB', 'PJ', 'WC', 'CB'}
    if type_part not in valid_types:
        return False, f"유효한 장비 종류는 {', '.join(sorted(valid_types))}입니다."
    
    # 고유번호 확인
    if not number_part.isdigit() or len(number_part) != 3:
        return False, "고유번호는 3자리 숫자여야 합니다. (예: 001)"
    
    number = int(number_part)
    if number < 1 or number > 3:
        return False, f"각 장비는 3개씩만 존재합니다. (001~003 범위)"
    
    return True, ""


def validate_reason(reason_str):
    """
    사유(메모) 검증 (final_plan.md 4.4)
    
    문법 규칙:
    - 빈 문자열 "" 가능
    - 줄바꿈 문자 미포함
    - 길이: 0~20자
    
    Returns:
        (valid, error_message)
    """
    if not isinstance(reason_str, str):
        return False, "사유는 텍스트여야 합니다."
    
    # 앞뒤 공백 제거 (입력 후 strip 일반적 관례)
    reason_str = reason_str.strip()
    
    try:
        validate_reason_text(reason_str)
        return True, ""
    except ValueError as error:
        return False, str(error)


def get_daily_date_range_input(start_prompt="시작 날짜", end_prompt="종료 날짜"):
    while True:
        start_str = input(f"  {start_prompt} (YYYY-MM-DD): ")
        if start_str.strip().lower() in ("q", "quit", "취소"):
            return None, None

        end_str = input(f"  {end_prompt} (YYYY-MM-DD): ")
        if end_str.strip().lower() in ("q", "quit", "취소"):
            return None, None

        start_valid, start_date, start_error = validate_date_plan(start_str)
        if not start_valid or start_date is None:
            print(f"  ✗ {start_error}")
            continue
        end_valid, end_date, end_error = validate_date_plan(end_str)
        if not end_valid or end_date is None:
            print(f"  ✗ {end_error}")
            continue

        valid, error, _ = validate_daily_booking_dates(
            start_date, end_date, get_current_time()
        )
        if valid:
            return start_date, end_date
        print(f"  ✗ {error}")


def get_positive_int_input(prompt, min_val=1, max_val=100, min_error_msg=None, max_error_msg=None):
    while True:
        value_str = input(f"{prompt}: ").strip()
        if value_str.lower() in ("q", "quit", "취소"):
            return None

        valid, value, error = validate_positive_int(value_str, min_val, max_val)
        if valid:
            return value

        try:
            parsed = int(value_str)
            if min_error_msg and parsed < min_val:
                print(f"  ✗ {min_error_msg}")
            elif max_error_msg and parsed > max_val:
                print(f"  ✗ {max_error_msg}")
            else:
                print(f"  ✗ {error}")
        except ValueError:
            print(f"  ✗ {error}")
