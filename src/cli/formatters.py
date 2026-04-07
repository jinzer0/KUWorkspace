"""
CLI 출력 포맷터 유틸리티
"""

import sys
from datetime import datetime


CLEAR_SCREEN_SEQUENCE = "\033[2J\033[H"


def format_datetime(dt_str, fmt="%Y-%m-%d %H:%M"):
    """ISO datetime 문자열을 읽기 쉬운 형식으로 변환"""
    if dt_str is None:
        return "-"
    try:
        dt = datetime.fromisoformat(dt_str)
        return dt.strftime(fmt)
    except (ValueError, TypeError):
        return dt_str


def format_date(dt_str):
    """ISO datetime 문자열에서 날짜만 추출"""
    return format_datetime(dt_str, "%Y-%m-%d")


def format_time(dt_str):
    """ISO datetime 문자열에서 시간만 추출"""
    return format_datetime(dt_str, "%H:%M")


def format_table(headers, rows, col_widths=None):
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

    # 열 너비 계산
    if col_widths is None:
        col_widths = []
        for i, header in enumerate(headers):
            max_width = len(str(header))
            for row in rows:
                if i < len(row):
                    max_width = max(max_width, len(str(row[i])))
            col_widths.append(min(max_width + 2, 40))  # 최대 40자

    # 헤더 행
    header_line = ""
    for i, header in enumerate(headers):
        header_line += str(header).ljust(col_widths[i])

    # 구분선
    separator = "-" * sum(col_widths)

    # 데이터 행
    data_lines = []
    for row in rows:
        line = ""
        for i, col in enumerate(row):
            if i < len(col_widths):
                cell = str(col) if col is not None else "-"
                # 긴 텍스트 자르기
                if len(cell) > col_widths[i] - 2:
                    cell = cell[: col_widths[i] - 5] + "..."
                line += cell.ljust(col_widths[i])
        data_lines.append(line)

    result = [header_line, separator] + data_lines
    return "\n".join(result)


def format_status_badge(status):
    """상태값을 한글 배지로 변환"""
    status_map = {
        # 회의실 예약 상태
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


def format_penalty_status(points, is_banned, is_restricted):
    """패널티 상태 요약"""
    if is_banned:
        return f"⛔ 이용 금지 (누적 {points}점)"
    if is_restricted:
        return f"⚠️ 예약 제한 (누적 {points}점)"
    if points > 0:
        return f"📝 패널티 {points}점"
    return "✅ 양호"


def clear_screen():
    is_tty = getattr(sys.stdout, "isatty", None)
    if not callable(is_tty) or not is_tty():
        return

    sys.stdout.write(CLEAR_SCREEN_SEQUENCE)
    sys.stdout.flush()


def print_header(title):
    """섹션 헤더 출력"""
    clear_screen()
    print()
    print("=" * 50)
    print(f"  {title}")
    print("=" * 50)


def print_subheader(title):
    """서브 섹션 헤더 출력"""
    print()
    print(f"--- {title} ---")


def print_success(message):
    """성공 메시지 출력"""
    print(f"✓ {message}")


def print_error(message):
    """에러 메시지 출력"""
    print(f"✗ {message}")


def print_warning(message):
    """경고 메시지 출력"""
    print(f"⚠ {message}")


def print_info(message):
    """정보 메시지 출력"""
    print(f"ℹ {message}")


def format_booking_time_range(start, end):
    """예약 시간 범위 포맷"""
    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)

    if start_dt.date() == end_dt.date():
        return f"{start_dt.strftime('%Y-%m-%d')} {start_dt.strftime('%H:%M')}~{end_dt.strftime('%H:%M')}"
    else:
        return f"{start_dt.strftime('%Y-%m-%d %H:%M')} ~ {end_dt.strftime('%Y-%m-%d %H:%M')}"
