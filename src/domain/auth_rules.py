"""인증 입력 규칙을 정의합니다."""

import re


def normalize_credential(value):
    """문자열 자격 증명을 공백 제거 후 반환합니다."""
    if not isinstance(value, str):
        return ""
    return value.strip()


def validate_username(username):
    """사용자명을 검증합니다."""
    username = normalize_credential(username)

    if not username:
        return False, "사용자명을 입력해주세요."

    if len(username) < 3:
        return False, "사용자명은 3자 이상이어야 합니다."

    if len(username) > 20:
        return False, "사용자명은 20자 이하여야 합니다."

    if not re.match(r"^[a-zA-Z0-9_]+$", username):
        return False, "사용자명은 영문, 숫자, 밑줄(_)만 사용 가능합니다."

    return True, ""


def validate_password(password):
    """비밀번호를 검증합니다."""
    password = normalize_credential(password)

    if not password:
        return False, "비밀번호를 입력해주세요."

    if len(password) < 4:
        return False, "비밀번호는 4자 이상이어야 합니다."

    if len(password) > 50:
        return False, "비밀번호는 50자 이하여야 합니다."

    return True, ""
