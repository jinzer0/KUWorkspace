"""인증 입력 규칙을 정의합니다."""

from src.domain.field_rules import (
    has_whitespace,
    validate_password_text,
    validate_username_text,
)


def normalize_credential(value):
    """문자열 자격 증명을 그대로 반환합니다."""
    if not isinstance(value, str):
        return ""
    return value


def validate_username(username):
    """회원가입용 사용자명을 검증합니다."""
    try:
        validate_username_text(username)
        return True, ""
    except ValueError as error:
        return False, str(error)


def validate_password(password):
    """회원가입용 비밀번호를 검증합니다."""
    try:
        validate_password_text(password)
        return True, ""
    except ValueError as error:
        return False, str(error)


def validate_login_username(username):
    """로그인용 사용자명을 검증합니다."""
    try:
        if not isinstance(username, str) or not username.strip():
            raise ValueError("사용자명을 입력해주세요.")
        if has_whitespace(username):
            raise ValueError("사용자명에 공백을 포함할 수 없습니다.")
        return True, ""
    except ValueError as error:
        return False, str(error)


def validate_login_password(password):
    """로그인용 비밀번호를 검증합니다."""
    try:
        if not isinstance(password, str) or not password.strip():
            raise ValueError("비밀번호를 입력해주세요.")
        if has_whitespace(password):
            raise ValueError("비밀번호에 공백을 포함할 수 없습니다.")
        return True, ""
    except ValueError as error:
        return False, str(error)
