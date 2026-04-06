"""
Comprehensive tests for src/cli/validators.py
Tests cover all validators from final_plan.md sections 4.1-4.4
"""

import pytest
from datetime import datetime, date

from src.cli.validators import (
    validate_password,
    validate_date_plan,
    validate_time_plan,
    validate_equipment_serial,
    validate_reason,
)


class TestValidatePassword:
    """final_plan.md 4.1.2: 비밀번호 검증"""
    
    def test_valid_password_minimum_length(self):
        valid, msg = validate_password("pass")
        assert valid is True
        assert msg == ""
    
    def test_valid_password_maximum_length(self):
        valid, msg = validate_password("a" * 50)
        assert valid is True
        assert msg == ""
    
    def test_valid_password_mixed_characters(self):
        valid, msg = validate_password("Pass123!@#")
        assert valid is True
        assert msg == ""
    
    def test_valid_password_korean_characters(self):
        valid, msg = validate_password("암호1234")
        assert valid is True
        assert msg == ""
    
    def test_invalid_password_empty(self):
        valid, msg = validate_password("")
        assert valid is False
        assert "입력" in msg
    
    def test_invalid_password_only_whitespace(self):
        valid, msg = validate_password("   ")
        assert valid is False
    
    def test_invalid_password_too_short(self):
        valid, msg = validate_password("abc")
        assert valid is False
        assert "4자 이상" in msg
    
    def test_invalid_password_too_long(self):
        valid, msg = validate_password("a" * 51)
        assert valid is False
        assert "50자 이하" in msg
    
    def test_invalid_password_contains_space(self):
        valid, msg = validate_password("pass word")
        assert valid is False
        assert "공백" in msg
    
    def test_invalid_password_contains_tab(self):
        valid, msg = validate_password("pass\tword")
        assert valid is False
        assert "공백" in msg
    
    def test_invalid_password_contains_newline(self):
        valid, msg = validate_password("pass\nword")
        assert valid is False
        assert "공백" in msg
    
    def test_invalid_password_leading_whitespace_stripped(self):
        # Input: "  pass" contains space characters (leading whitespace),
        # so it's invalid per plan 4.1.2 (공백 미포함)
        valid, msg = validate_password("  pass")
        assert valid is False
        assert "공백" in msg
    
    def test_valid_password_case_sensitive(self):
        # Both should be valid individually, but different
        valid1, _ = validate_password("Password")
        valid2, _ = validate_password("password")
        assert valid1 is True
        assert valid2 is True


class TestValidateDatePlan:
    """final_plan.md 4.2.1: 날짜 검증"""
    
    # Valid dates
    def test_valid_date_hyphen_separator(self):
        valid, date_obj, msg = validate_date_plan("2026-04-15")
        assert valid is True
        assert date_obj == date(2026, 4, 15)
        assert msg == ""
    
    def test_valid_date_dot_separator(self):
        valid, date_obj, msg = validate_date_plan("2026.04.15")
        assert valid is True
        assert date_obj == date(2026, 4, 15)
    
    def test_valid_date_space_separator(self):
        valid, date_obj, msg = validate_date_plan("2026 04 15")
        assert valid is True
        assert date_obj == date(2026, 4, 15)
    
    def test_valid_date_year_boundary_min(self):
        valid, date_obj, msg = validate_date_plan("2026-01-01")
        assert valid is True
        assert date_obj == date(2026, 1, 1)
    
    def test_valid_date_year_boundary_max(self):
        valid, date_obj, msg = validate_date_plan("2100-12-31")
        assert valid is True
        assert date_obj == date(2100, 12, 31)
    
    def test_valid_date_leap_year_feb_29(self):
        # 2024, 2028, 2032 are leap years
        valid, date_obj, msg = validate_date_plan("2028-02-29")
        assert valid is True
        assert date_obj == date(2028, 2, 29)
    
    def test_valid_date_month_end_31_days(self):
        valid, date_obj, msg = validate_date_plan("2026-05-31")
        assert valid is True
    
    def test_valid_date_with_leading_spaces_stripped(self):
        valid, date_obj, msg = validate_date_plan("  2026-04-15  ")
        assert valid is True
        assert date_obj == date(2026, 4, 15)
    
    # Invalid dates - format
    def test_invalid_date_empty(self):
        valid, date_obj, msg = validate_date_plan("")
        assert valid is False
        assert date_obj is None
    
    def test_invalid_date_missing_separator(self):
        valid, date_obj, msg = validate_date_plan("20260415")
        assert valid is False
        assert "형식" in msg or "구분자" in msg
    
    def test_invalid_date_mixed_separators(self):
        # One of the key requirements: no mixing separators
        valid, date_obj, msg = validate_date_plan("2026-04.15")
        assert valid is False
        assert "혼합" in msg or "여러 구분자" in msg
    
    def test_invalid_date_mixed_separators_dash_and_space(self):
        valid, date_obj, msg = validate_date_plan("2026-04 15")
        assert valid is False
    
    def test_invalid_date_missing_month(self):
        valid, date_obj, msg = validate_date_plan("2026-15")
        assert valid is False
    
    def test_invalid_date_month_not_padded(self):
        # Plan 4.2.1: 월, 일은 0 패딩 필수
        valid, date_obj, msg = validate_date_plan("2026-4-03")
        assert valid is False
        assert "0" in msg or "2자리" in msg
    
    def test_invalid_date_day_not_padded(self):
        valid, date_obj, msg = validate_date_plan("2026-04-3")
        assert valid is False
        assert "0" in msg or "2자리" in msg
    
    # Invalid dates - range
    def test_invalid_date_year_too_early(self):
        valid, date_obj, msg = validate_date_plan("2025-12-31")
        assert valid is False
        assert "2026" in msg or "연도" in msg
    
    def test_invalid_date_year_too_late(self):
        valid, date_obj, msg = validate_date_plan("2101-01-01")
        assert valid is False
        assert "2100" in msg or "연도" in msg
    
    def test_invalid_date_month_zero(self):
        valid, date_obj, msg = validate_date_plan("2026-00-15")
        assert valid is False
        assert "월" in msg
    
    def test_invalid_date_month_too_high(self):
        valid, date_obj, msg = validate_date_plan("2026-13-01")
        assert valid is False
        assert "월" in msg or "12" in msg
    
    def test_invalid_date_day_zero(self):
        valid, date_obj, msg = validate_date_plan("2026-04-00")
        assert valid is False
        assert "일" in msg
    
    def test_invalid_date_day_too_high(self):
        valid, date_obj, msg = validate_date_plan("2026-04-32")
        assert valid is False
        assert "일" in msg or "31" in msg
    
    def test_invalid_date_non_leap_year_feb_29(self):
        # 2027 is not a leap year
        valid, date_obj, msg = validate_date_plan("2027-02-29")
        assert valid is False
        assert "날짜" in msg or "유효" in msg
    
    def test_invalid_date_feb_31(self):
        valid, date_obj, msg = validate_date_plan("2026-02-31")
        assert valid is False
    
    def test_invalid_date_april_31(self):
        # April has 30 days
        valid, date_obj, msg = validate_date_plan("2026-04-31")
        assert valid is False


class TestValidateTimePlan:
    """final_plan.md 4.2.2: 시간 검증"""
    
    # Valid times
    def test_valid_time_0900_colon_format(self):
        valid, time_obj, msg = validate_time_plan("09:00")
        assert valid is True
        assert msg == ""
        assert time_obj.hour == 9
        assert time_obj.minute == 0
    
    def test_valid_time_1800_colon_format(self):
        valid, time_obj, msg = validate_time_plan("18:00")
        assert valid is True
        assert time_obj.hour == 18
        assert time_obj.minute == 0
    
    def test_valid_time_0900_no_separator(self):
        valid, time_obj, msg = validate_time_plan("0900")
        assert valid is True
        assert time_obj.hour == 9
        assert time_obj.minute == 0
    
    def test_valid_time_1800_no_separator(self):
        valid, time_obj, msg = validate_time_plan("1800")
        assert valid is True
        assert time_obj.hour == 18
        assert time_obj.minute == 0
    
    def test_valid_time_with_leading_spaces(self):
        valid, time_obj, msg = validate_time_plan("  09:00  ")
        assert valid is True
    
    # Invalid times - format
    def test_invalid_time_empty(self):
        valid, time_obj, msg = validate_time_plan("")
        assert valid is False
        assert time_obj is None
    
    def test_invalid_time_wrong_hour_09_but_wrong_minute(self):
        valid, time_obj, msg = validate_time_plan("09:30")
        assert valid is False
        assert "00" in msg or "분" in msg
    
    def test_invalid_time_wrong_hour_18_but_wrong_minute(self):
        valid, time_obj, msg = validate_time_plan("18:30")
        assert valid is False
    
    def test_invalid_time_hour_10(self):
        # Only 09 or 18 allowed
        valid, time_obj, msg = validate_time_plan("10:00")
        assert valid is False
        assert "09" in msg or "18" in msg or "시간" in msg
    
    def test_invalid_time_hour_17(self):
        valid, time_obj, msg = validate_time_plan("17:00")
        assert valid is False
    
    def test_invalid_time_hour_00(self):
        valid, time_obj, msg = validate_time_plan("00:00")
        assert valid is False
    
    def test_invalid_time_hour_12(self):
        valid, time_obj, msg = validate_time_plan("12:00")
        assert valid is False
    
    def test_invalid_time_no_separator_wrong_format(self):
        # "0930" is parsed as hour=09, minute=30, which fails on minute check
        # (분은 00만 가능) not format check
        valid, time_obj, msg = validate_time_plan("0930")
        assert valid is False
        assert "00" in msg or "분" in msg
    
    def test_invalid_time_too_short_no_separator(self):
        valid, time_obj, msg = validate_time_plan("900")
        assert valid is False
    
    def test_invalid_time_too_long_no_separator(self):
        valid, time_obj, msg = validate_time_plan("09000")
        assert valid is False
    
    def test_invalid_time_contains_space_in_middle(self):
        # Spaces in the middle are invalid (only leading/trailing allowed after strip)
        valid, time_obj, msg = validate_time_plan("09 00")
        assert valid is False
        assert "공백" in msg
    
    def test_invalid_time_non_numeric_colon_format(self):
        valid, time_obj, msg = validate_time_plan("ab:cd")
        assert valid is False
    
    def test_invalid_time_mixed_separators(self):
        # Plan: 구분자 혼합 불가
        # "09:00MM" is invalid, but this tests "09.00"
        valid, time_obj, msg = validate_time_plan("09.00")
        assert valid is False or time_obj is None


class TestValidateEquipmentSerial:
    """final_plan.md 4.3.2: 장비 시리얼 번호 검증"""
    
    # Valid serials
    def test_valid_serial_pj_001(self):
        valid, msg = validate_equipment_serial("PJ-001")
        assert valid is True
        assert msg == ""
    
    def test_valid_serial_nb_002(self):
        valid, msg = validate_equipment_serial("NB-002")
        assert valid is True
    
    def test_valid_serial_cb_003(self):
        valid, msg = validate_equipment_serial("CB-003")
        assert valid is True
    
    def test_valid_serial_wc_001(self):
        valid, msg = validate_equipment_serial("WC-001")
        assert valid is True
    
    # Invalid - missing separator
    def test_invalid_serial_no_separator(self):
        valid, msg = validate_equipment_serial("PJ001")
        assert valid is False
        assert "형식" in msg or "구분자" in msg
    
    # Invalid - wrong type
    def test_invalid_serial_wrong_type_xx(self):
        valid, msg = validate_equipment_serial("XX-001")
        assert valid is False
        assert "장비" in msg or "종류" in msg or "NB" in msg
    
    def test_invalid_serial_wrong_type_lowercase(self):
        valid, msg = validate_equipment_serial("pj-001")
        assert valid is False
    
    def test_invalid_serial_wrong_type_single_char(self):
        valid, msg = validate_equipment_serial("P-001")
        assert valid is False
    
    # Invalid - wrong number
    def test_invalid_serial_number_too_high(self):
        valid, msg = validate_equipment_serial("PJ-004")
        assert valid is False
        assert "3개" in msg or "001~003" in msg
    
    def test_invalid_serial_number_000(self):
        valid, msg = validate_equipment_serial("PJ-000")
        assert valid is False
    
    def test_invalid_serial_number_not_padded(self):
        valid, msg = validate_equipment_serial("PJ-1")
        assert valid is False
        assert "3자리" in msg
    
    def test_invalid_serial_number_not_numeric(self):
        valid, msg = validate_equipment_serial("PJ-ABC")
        assert valid is False
        assert "숫자" in msg
    
    # Invalid - format issues
    def test_invalid_serial_empty(self):
        valid, msg = validate_equipment_serial("")
        assert valid is False
    
    def test_invalid_serial_multiple_separators(self):
        valid, msg = validate_equipment_serial("PJ--001")
        assert valid is False
    
    def test_invalid_serial_extra_content(self):
        valid, msg = validate_equipment_serial("PJ-001-extra")
        assert valid is False


class TestValidateReason:
    """final_plan.md 4.4: 사유(메모) 검증"""
    
    # Valid reasons
    def test_valid_reason_empty_string(self):
        valid, msg = validate_reason("")
        assert valid is True
        assert msg == ""
    
    def test_valid_reason_single_char(self):
        valid, msg = validate_reason("가")
        assert valid is True
    
    def test_valid_reason_max_length(self):
        valid, msg = validate_reason("a" * 20)
        assert valid is True
    
    def test_valid_reason_korean_text(self):
        valid, msg = validate_reason("회의실 사용할 예정")
        assert valid is True
    
    def test_valid_reason_mixed_korean_english_numbers(self):
        valid, msg = validate_reason("Meeting2024 준비중")
        assert valid is True
    
    def test_valid_reason_special_chars_except_newline(self):
        valid, msg = validate_reason("!@#$%^&*()")
        assert valid is True
    
    def test_valid_reason_with_leading_trailing_spaces_stripped(self):
        # Input: "  reason  " → after strip: "reason"
        valid, msg = validate_reason("  reason  ")
        assert valid is True
    
    # Invalid reasons
    def test_invalid_reason_too_long(self):
        valid, msg = validate_reason("a" * 21)
        assert valid is False
        assert "20자" in msg
    
    def test_invalid_reason_contains_newline(self):
        valid, msg = validate_reason("reason\nwith newline")
        assert valid is False
        assert "줄바꿈" in msg or "포함" in msg
    
    def test_invalid_reason_contains_carriage_return(self):
        valid, msg = validate_reason("reason\rline")
        assert valid is False
    
    def test_invalid_reason_contains_both_newlines(self):
        valid, msg = validate_reason("reason\r\nwindows")
        assert valid is False
    
    def test_non_string_input_reason(self):
        valid, msg = validate_reason(123)
        assert valid is False


class TestValidatorEdgeCases:
    """Edge cases and integration scenarios"""
    
    def test_password_with_all_special_chars_except_space(self):
        # Plan says: 공백 미포함 (space excluded), but other special chars OK
        valid, _ = validate_password("p@ss!#$%^&*()")
        assert valid is True
    
    def test_date_all_three_separators_individually(self):
        # Each should work individually, but not mixed
        cases = [
            ("2026-01-01", True),
            ("2026.01.01", True),
            ("2026 01 01", True),
        ]
        for date_str, expected in cases:
            valid, _, _ = validate_date_plan(date_str)
            assert valid == expected
    
    def test_time_both_valid_slots_only(self):
        cases = [
            ("09:00", True),
            ("0900", True),
            ("18:00", True),
            ("1800", True),
            ("09:30", False),
            ("10:00", False),
            ("17:00", False),
        ]
        for time_str, expected in cases:
            valid, _, _ = validate_time_plan(time_str)
            assert valid == expected
    
    def test_equipment_all_valid_types(self):
        valid_types = ["NB", "PJ", "WC", "CB"]
        for type_code in valid_types:
            for number in ["001", "002", "003"]:
                valid, msg = validate_equipment_serial(f"{type_code}-{number}")
                assert valid is True, f"Failed: {type_code}-{number}: {msg}"
    
    def test_reason_boundary_20_chars(self):
        # Exactly 20 chars should pass
        valid, msg = validate_reason("12345678901234567890")
        assert valid is True
        # 21 chars should fail
        valid, msg = validate_reason("123456789012345678901")
        assert valid is False
