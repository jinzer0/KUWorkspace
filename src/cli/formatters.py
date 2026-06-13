"""
CLI 출력 포맷터 유틸리티
"""

import sys
import unicodedata
from collections.abc import Sequence
from datetime import datetime


CLEAR_SCREEN_SEQUENCE = "\033[2J\033[H"


def _char_display_width(char: str) -> int:
    codepoint = ord(char)
    if unicodedata.combining(char):
        return 0
    if char == "\u200d" or 0xFE00 <= codepoint <= 0xFE0F:
        return 0
    if 0xE0100 <= codepoint <= 0xE01EF:
        return 0
    if unicodedata.east_asian_width(char) in {"F", "W"}:
        return 2
    return 1


def _display_width(value: object) -> int:
    return sum(_char_display_width(char) for char in str(value))


def _pad_display(text: str, width: int) -> str:
    return text + " " * max(width - _display_width(text), 0)


def _truncate_display(text: str, width: int) -> str:
    if _display_width(text) <= width:
        return text
    if width <= 0:
        return ""
    if width <= 3:
        return "." * width

    target = width - 3
    result: list[str] = []
    current_width = 0
    for char in text:
        char_width = _char_display_width(char)
        if current_width + char_width > target:
            break
        result.append(char)
        current_width += char_width
    return "".join(result) + "..."


def _legacy_padded_display_width(text: str, width: int) -> int:
    return _display_width(text) + max(width - len(text), 0)


def _normalize_col_widths(
    headers: Sequence[object],
    rows: Sequence[Sequence[object | None]],
    col_widths: Sequence[int],
) -> list[int]:
    normalized = list(col_widths)
    for i, width in enumerate(normalized):
        if i < len(headers):
            header = str(headers[i])
            normalized[i] = max(normalized[i], _legacy_padded_display_width(header, width))
        for row in rows:
            if i < len(row):
                cell = str(row[i]) if row[i] is not None else "-"
                if len(cell) <= width - 2:
                    normalized[i] = max(
                        normalized[i], _legacy_padded_display_width(cell, width)
                    )
    return normalized


def format_datetime(dt_str: str | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """ISO datetime 문자열을 읽기 쉬운 형식으로 변환"""
    if dt_str is None:
        return "-"
    try:
        dt = datetime.fromisoformat(dt_str)
        return dt.strftime(fmt)
    except (ValueError, TypeError):
        return dt_str


def format_table(
    headers: Sequence[object],
    rows: Sequence[Sequence[object | None]],
    col_widths: Sequence[int] | None = None,
) -> str:
    """
    고정폭 텍스트 테이블 생성

    Args:
        headers: 헤더 목록
        rows: 데이터 행 목록
        col_widths: 열 너비 (None이면 자동 계산)

    Returns:
        포맷된 테이블 문자열
    """
    if not headers:
        return ""

    if col_widths is None:
        resolved_widths: list[int] = []
        for i, header in enumerate(headers):
            max_width = _display_width(header)
            for row in rows:
                if i < len(row):
                    cell = str(row[i]) if row[i] is not None else "-"
                    max_width = max(max_width, _display_width(cell))
            resolved_widths.append(min(max_width + 2, 40))
    else:
        resolved_widths = _normalize_col_widths(headers, rows, col_widths)

    header_line = ""
    for i, header in enumerate(headers):
        header_line += _pad_display(str(header), resolved_widths[i])

    separator = "-" * sum(resolved_widths)

    data_lines: list[str] = []
    for row in rows:
        line = ""
        for i, col in enumerate(row):
            if i < len(resolved_widths):
                cell = str(col) if col is not None else "-"
                if _display_width(cell) > resolved_widths[i] - 2:
                    cell = _truncate_display(cell, resolved_widths[i] - 2)
                line += _pad_display(cell, resolved_widths[i])
        data_lines.append(line)

    result = [header_line, separator] + data_lines
    return "\n".join(result)


def format_status_badge(status: str) -> str:
    """상태값을 한글 배지로 변환"""
    status_map = {
        # 회의실 예약 상태
        "pending": "[예약 대기중]",
        "reserved": "[예약됨]",
        "checkin_requested": "[체크인요청]",
        "checked_in": "[입실]",
        "checkout_requested": "[퇴실승인대기]",
        "completed": "[완료]",
        "cancelled": "[취소]",
        "admin_cancelled": "[관리자취소]",
        # 장비 예약 상태
        "pickup_requested": "[픽업요청]",
        "checked_out": "[대여중]",
        "return_requested": "[반납승인대기]",
        "returned": "[반납완료]",
        # 리소스 상태
        "available": "[사용가능]",
        "maintenance": "[점검중]",
        "disabled": "[사용불가]",
        # 사용자 역할
        "user": "[일반]",
        "admin": "[관리자]",
    }
    return status_map.get(status, f"[{status}]")


def format_penalty_status(points: int, is_banned: bool, is_restricted: bool) -> str:
    """패널티 상태 요약"""
    if is_banned:
        return f"⛔ 이용 금지 (누적 {points}점)"
    if is_restricted:
        return f"⚠️ 예약 제한 (누적 {points}점)"
    if points > 0:
        return f"📝 패널티 {points}점"
    return "✅ 양호"


def clear_screen() -> None:
    is_tty = getattr(sys.stdout, "isatty", None)
    if not callable(is_tty) or not is_tty():
        return

    _ = sys.stdout.write(CLEAR_SCREEN_SEQUENCE)
    _ = sys.stdout.flush()


def print_header(title: str) -> None:
    """섹션 헤더 출력"""
    clear_screen()
    print()
    print("=" * 50)
    print(f"  {title}")
    print("=" * 50)


def print_subheader(title: str) -> None:
    """서브 섹션 헤더 출력"""
    print()
    print(f"--- {title} ---")


def print_success(message: str) -> None:
    """성공 메시지 출력"""
    print(f"✓ {message}")


def print_error(message: str) -> None:
    """에러 메시지 출력"""
    print(f"✗ {message}")


def print_warning(message: str) -> None:
    """경고 메시지 출력"""
    print(f"⚠ {message}")


def print_info(message: str) -> None:
    """정보 메시지 출력"""
    print(f"ℹ {message}")


def format_booking_time_range(start: str, end: str) -> str:
    """예약 시간 범위 포맷"""
    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)

    if start_dt.date() == end_dt.date():
        return f"{start_dt.strftime('%Y-%m-%d')} {start_dt.strftime('%H:%M')}~{end_dt.strftime('%H:%M')}"
    else:
        return f"{start_dt.strftime('%Y-%m-%d %H:%M')} ~ {end_dt.strftime('%Y-%m-%d %H:%M')}"
