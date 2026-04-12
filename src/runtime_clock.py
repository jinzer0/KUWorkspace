import json
import os
from datetime import datetime, timedelta

from src.config import CLOCK_STATE_FILE
from src.storage.file_lock import global_lock


ALLOWED_CLOCK_SLOTS = {(9, 0), (18, 0)}

_active_clock = None
_runtime_clock = None


class ClockError(Exception):
    """가상 시계 처리 중 발생하는 오류입니다."""


def normalize_slot(dt):
    if (dt.hour, dt.minute) not in ALLOWED_CLOCK_SLOTS:
        raise ClockError("운영 시점은 09:00 또는 18:00만 사용할 수 있습니다.")

    return dt.replace(second=0, microsecond=0)


def compute_next_slot(dt):
    current = normalize_slot(dt)
    if current.hour == 9:
        return current.replace(hour=18, minute=0)
    return (current + timedelta(days=1)).replace(hour=9, minute=0)


class SystemClock:
    """세션 단위 가상 시계입니다."""

    def __init__(self, start_time):
        self._current_time = normalize_slot(start_time)

    def now(self):
        return self._current_time

    def now_iso(self):
        return self.now().isoformat()

    def current_slot(self):
        return self.now().strftime("%H:%M")

    def next_slot(self):
        return compute_next_slot(self._current_time)

    def advance(self):
        self._current_time = self.next_slot()
        return self._current_time

    def set_time(self, new_time):
        self._current_time = normalize_slot(new_time)
        return self._current_time


class RuntimeClock:
    """현재 활성 시계를 투명하게 위임하는 런타임 시계입니다."""

    def now(self):
        _sync_active_clock_from_state()
        if _active_clock is not None:
            return _active_clock.now()
        return datetime.now().replace(microsecond=0)

    def now_iso(self):
        return self.now().isoformat()

    def current_slot(self):
        return self.now().strftime("%H:%M")

    def next_slot(self):
        return compute_next_slot(self.now())

    def advance(self):
        with global_lock():
            _sync_active_clock_from_state()
            if _active_clock is None:
                raise ClockError("활성 가상 시계가 설정되지 않았습니다.")
            next_time = _active_clock.advance()
            _save_persisted_time(next_time)
            return next_time


def _load_persisted_time():
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
        return normalize_slot(datetime.fromisoformat(saved_time))
    except (json.JSONDecodeError, TypeError, ValueError, ClockError):
        return None


def _save_persisted_time(current_time):
    payload = {"current_time": normalize_slot(current_time).isoformat()}
    temp_path = CLOCK_STATE_FILE.with_suffix(f"{CLOCK_STATE_FILE.suffix}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(temp_path, CLOCK_STATE_FILE)


def _sync_active_clock_from_state():
    saved_time = _load_persisted_time()
    if saved_time is None or _active_clock is None:
        return

    if _active_clock.now() != saved_time:
        _active_clock.set_time(saved_time)


def set_active_clock(clock):
    global _active_clock
    _active_clock = clock
    with global_lock():
        _sync_active_clock_from_state()
        if _active_clock is not None:
            _save_persisted_time(_active_clock.now())
    return _active_clock


def clear_active_clock():
    global _active_clock
    _active_clock = None


def get_active_clock():
    return _active_clock


def get_runtime_clock():
    global _runtime_clock
    if _runtime_clock is None:
        _runtime_clock = RuntimeClock()
    return _runtime_clock


def get_current_time():
    return get_runtime_clock().now()
