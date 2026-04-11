"""도메인 필드 문법 규칙 검증기."""

from __future__ import annotations

import re


def has_whitespace(value: str) -> bool:
    return any(char.isspace() for char in value)


def validate_username_text(username: str) -> None:
    if not isinstance(username, str) or not username.strip():
        raise ValueError("사용자명을 입력해주세요.")
    if has_whitespace(username):
        raise ValueError("사용자명에 공백을 포함할 수 없습니다.")
    if len(username) < 3:
        raise ValueError("사용자명은 3자 이상이어야 합니다.")
    if len(username) > 20:
        raise ValueError("사용자명은 20자 이하여야 합니다.")
    if not re.fullmatch(r"[A-Za-z0-9_]+", username):
        raise ValueError("사용자명은 영문, 숫자, 밑줄(_)만 사용 가능합니다.")


def validate_password_text(password: str) -> None:
    if not isinstance(password, str) or not password.strip():
        raise ValueError("비밀번호를 입력해주세요.")
    if has_whitespace(password):
        raise ValueError("비밀번호에 공백을 포함할 수 없습니다.")
    if len(password) < 4:
        raise ValueError("비밀번호는 4자 이상이어야 합니다.")
    if len(password) > 50:
        raise ValueError("비밀번호는 50자 이하여야 합니다.")


def validate_reason_text(reason: str, field_name: str = "사유") -> None:
    if not isinstance(reason, str):
        raise ValueError(f"{field_name}는 텍스트여야 합니다.")
    if "\n" in reason or "\r" in reason:
        raise ValueError(f"{field_name}에 줄바꿈을 포함할 수 없습니다.")
    if len(reason) > 20:
        raise ValueError(f"{field_name}는 20자 이하여야 합니다.")


def validate_room_name(name: str) -> None:
    if not isinstance(name, str) or not name:
        raise ValueError("회의실 이름을 입력해주세요.")
    if not re.fullmatch(r"회의실[0-9][A-Z]", name):
        raise ValueError("회의실 이름은 '회의실' + 숫자 1자리 + 대문자 1자 형식이어야 합니다.")


def validate_room_capacity(capacity: int) -> None:
    if capacity < 1:
        raise ValueError("회의실 수용 인원은 1 이상이어야 합니다.")


def validate_room_location(location: str) -> None:
    if not isinstance(location, str) or not re.fullmatch(r"[0-9]층", location):
        raise ValueError("회의실 위치는 숫자 1자리 + '층' 형식이어야 합니다.")


def validate_room_description(description: str) -> None:
    if not isinstance(description, str):
        raise ValueError("회의실 설명은 텍스트여야 합니다.")
    if "\n" in description or "\r" in description:
        raise ValueError("회의실 설명에 줄바꿈을 포함할 수 없습니다.")
    if len(description) < 1 or len(description) > 10:
        raise ValueError("회의실 설명은 1자 이상 10자 이하여야 합니다.")


def validate_equipment_name(name: str) -> None:
    if not isinstance(name, str) or not name:
        raise ValueError("장비 이름을 입력해주세요.")
    if has_whitespace(name):
        raise ValueError("장비 이름에 공백을 포함할 수 없습니다.")
    if len(name) < 1 or len(name) > 10:
        raise ValueError("장비 이름은 1자 이상 10자 이하여야 합니다.")


def validate_equipment_asset_type(asset_type: str) -> None:
    if not isinstance(asset_type, str) or not asset_type:
        raise ValueError("장비 종류를 입력해주세요.")
    if has_whitespace(asset_type):
        raise ValueError("장비 종류에 공백을 포함할 수 없습니다.")
    if len(asset_type) < 1 or len(asset_type) > 10:
        raise ValueError("장비 종류는 1자 이상 10자 이하여야 합니다.")


def validate_equipment_serial(serial_number: str) -> None:
    if not isinstance(serial_number, str) or not serial_number:
        raise ValueError("장비 시리얼 번호를 입력해주세요.")
    if has_whitespace(serial_number):
        raise ValueError("장비 시리얼 번호에 공백을 포함할 수 없습니다.")
    if len(serial_number) > 10:
        raise ValueError("장비 시리얼 번호는 10자 이하여야 합니다.")
    if not re.fullmatch(r"[A-Z]{2}-\d{3}", serial_number):
        raise ValueError("장비 시리얼 번호는 'AA-000' 형식이어야 합니다.")


def validate_equipment_description(description: str) -> None:
    if not isinstance(description, str):
        raise ValueError("장비 설명은 텍스트여야 합니다.")
    if "\n" in description or "\r" in description:
        raise ValueError("장비 설명에 줄바꿈을 포함할 수 없습니다.")
    if len(description) > 10:
        raise ValueError("장비 설명은 10자 이하여야 합니다.")
