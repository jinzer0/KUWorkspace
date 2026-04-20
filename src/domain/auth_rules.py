"""인증 입력 규칙을 정의합니다."""

from src.domain.field_rules import validate_password_text, validate_username_text


def normalize_credential(value):
    """문자열 자격 증명을 그대로 반환합니다."""
    if not isinstance(value, str):
        return ""
    return value


def validate_username(username):
    """사용자명을 검증합니다."""
    try:
        validate_username_text(username)
        return True, ""
    except ValueError as error:
        return False, str(error)


def validate_password(password):
    """비밀번호를 검증합니다."""
    try:
        validate_password_text(password)
        return True, ""
    except ValueError as error:
        return False, str(error)
