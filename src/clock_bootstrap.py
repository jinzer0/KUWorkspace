import json
import atexit
from datetime import datetime

from src.config import CLOCK_STATE_FILE
from src.cli.validators import validate_date_plan
from src.runtime_clock import (
    SystemClock,
    set_active_clock,
    get_active_clock,
    ClockError,
)

from src.storage.repositories import (
    UserRepository,
    RoomRepository,
    EquipmentAssetRepository,
    RoomBookingRepository,
    EquipmentBookingRepository,
    PenaltyRepository,
    AuditLogRepository,
)


def _iter_datetime_strings(record):
    for value in vars(record).values():
        if not isinstance(value, str):
            continue
        try:
            yield datetime.fromisoformat(value)
        except ValueError:
            continue


def get_latest_data_timestamp():
    repositories = [
        UserRepository(),
        RoomRepository(),
        EquipmentAssetRepository(),
        RoomBookingRepository(),
        EquipmentBookingRepository(),
        PenaltyRepository(),
        AuditLogRepository(),
    ]

    latest = None
    for repository in repositories:
        for record in repository.get_all():
            for timestamp in _iter_datetime_strings(record):
                if latest is None or timestamp > latest:
                    latest = timestamp
    return latest


def load_saved_clock_timestamp():
    if not CLOCK_STATE_FILE.exists():
        return None

    content = CLOCK_STATE_FILE.read_text(encoding="utf-8").strip()
    if not content:
        return None

    try:
        payload = json.loads(content)
        saved_time = payload.get("current_time")
        if not saved_time:
            return None
        return datetime.fromisoformat(saved_time)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def save_clock_timestamp(current_time):
    payload = {"current_time": current_time.isoformat()}
    CLOCK_STATE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def prompt_initial_clock():
    """프로그램 시작 시 운영 시작 시점을 입력받습니다."""
    latest_data_time = get_latest_data_timestamp()
    saved_clock_time = load_saved_clock_timestamp()

    if saved_clock_time is not None:
        print(
            "\n이전 종료 시점부터 운영을 재개합니다. "
            f"({saved_clock_time.strftime('%Y-%m-%d %H:%M')})"
        )
        return SystemClock(saved_clock_time)

    while True:
        print("\n최초 실행이므로 운영 시작 시점을 설정합니다.")
        date_str = input("시작 날짜 (YYYY-MM-DD): ").strip()
        slot_str = input("시작 슬롯 (09:00 또는 18:00): ").strip()

        valid, base_date, error = validate_date_plan(date_str)
        if not valid or base_date is None:
            print(f"✗ {error}")
            continue

        if slot_str not in ("09:00", "18:00"):
            print("✗ 시작 슬롯은 09:00 또는 18:00만 가능합니다.")
            continue

        hour, minute = [int(part) for part in slot_str.split(":")]
        start_time = datetime(
            base_date.year,
            base_date.month,
            base_date.day,
            hour,
            minute,
        )

        if latest_data_time is not None and start_time < latest_data_time:
            print(
                "✗ 시작 시점이 기존 데이터의 최신 시각보다 빠릅니다. "
                f"(최신 기록: {latest_data_time.strftime('%Y-%m-%d %H:%M')})"
            )
            continue

        try:
            return SystemClock(start_time)
        except ClockError as error:
            print(f"✗ {error}")


def persist_clock_state():
    """프로그램 종료 시 현재 운영 시점을 저장합니다."""
    active_clock = get_active_clock()
    if active_clock is None:
        return
    save_clock_timestamp(active_clock.now())


def initialize_runtime_clock():
    """운영 시계를 초기화하고 종료 시 자동 저장을 등록합니다."""
    set_active_clock(prompt_initial_clock())
    atexit.register(persist_clock_state)
