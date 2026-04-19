"""
설정 및 상수 정의
"""

from pathlib import Path

from src.storage.integrity import DataIntegrityError

# 경로 설정
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"

# 데이터 파일 경로
LOCK_FILE = DATA_DIR / ".lock"
USERS_FILE = DATA_DIR / "users.txt"
ROOMS_FILE = DATA_DIR / "rooms.txt"
EQUIPMENTS_FILE = DATA_DIR / "equipments.txt"
ROOM_BOOKINGS_FILE = DATA_DIR / "room_bookings.txt"
EQUIPMENT_BOOKING_FILE = DATA_DIR / "equipment_booking.txt"
PENALTIES_FILE = DATA_DIR / "penalties.txt"
AUDIT_LOG_FILE = DATA_DIR / "audit_log.txt"
CLOCK_FILE = DATA_DIR / "clock.txt"
CLOCK_SENTINEL = "0000-00-00T00:00"

DATA_FILES = [
    USERS_FILE,
    ROOMS_FILE,
    EQUIPMENTS_FILE,
    ROOM_BOOKINGS_FILE,
    EQUIPMENT_BOOKING_FILE,
    PENALTIES_FILE,
    AUDIT_LOG_FILE,
    CLOCK_FILE,
]

# 예약 정책 상수
MAX_BOOKING_DAYS = 14
BOOKING_WINDOW_DAYS = 180
FIXED_BOOKING_START_HOUR = 9
FIXED_BOOKING_START_MINUTE = 0
FIXED_BOOKING_END_HOUR = 18
FIXED_BOOKING_END_MINUTE = 0
START_REQUEST_CUTOFF_HOUR = 10
END_REQUEST_CUTOFF_HOUR = 19
TIME_SLOT_MINUTES = 30
MAX_ACTIVE_ROOM_BOOKINGS = 1  # 회의실 최대 활성 예약 수
MAX_ACTIVE_EQUIPMENT_BOOKINGS = 1  # 장비 최대 활성 예약 수

# 패널티 상수
LATE_CANCEL_PENALTY = 2  # 직전 취소 패널티 점수
LATE_RETURN_PENALTY = 2  # 지연 퇴실/반납 패널티 점수
MAX_DAMAGE_PENALTY = 5  # 파손/오염 최대 패널티 점수
LATE_CANCEL_THRESHOLD_MINUTES = 60  # 직전 취소 기준 시간 (분)

# 이용 제한 상수
PENALTY_WARNING_THRESHOLD = 3  # 경고 기준 점수
PENALTY_RESTRICTION_THRESHOLD = 3  # 예약 1건 제한 기준 점수
PENALTY_BAN_THRESHOLD = 6  # 이용 금지 기준 점수
RESTRICTION_DURATION_DAYS = 7  # 예약 제한 기간 (일)
BAN_DURATION_DAYS = 30  # 이용 금지 기간 (일)
PENALTY_RESET_DAYS = 90  # 패널티 초기화 기간 (일)
STREAK_BONUS_COUNT = 10  # 정상 이용 연속 횟수 (1점 차감)

# 파일 잠금 설정
LOCK_TIMEOUT = 30  # 잠금 대기 타임아웃 (초)


def ensure_data_dir():
    global CLOCK_FILE, DATA_FILES

    clock_file = DATA_DIR / CLOCK_FILE.name
    CLOCK_FILE = clock_file
    data_files = list(DATA_FILES)
    if clock_file not in data_files:
        data_files.append(clock_file)

    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        for file_path in data_files:
            file_path.touch(exist_ok=True)
        if not clock_file.read_text(encoding="utf-8").strip():
            clock_file.write_text(CLOCK_SENTINEL, encoding="utf-8")
    except OSError as error:
        raise DataIntegrityError(
            f"필수 데이터 파일을 생성할 수 없습니다: {error}"
        ) from error
