from datetime import datetime, timedelta

from src.storage.file_lock import global_lock
from src.storage.integrity import DataIntegrityError


ALLOWED_CLOCK_SLOTS = {(9, 0), (18, 0)}

_active_clock = None
_runtime_clock = None


class ClockError(Exception):
    """가상 시계 처리 중 발생하는 오류입니다."""


def _persist_runtime_clock(current_time):
    from src.clock_bootstrap import persist_clock

    persist_clock(current_time)


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
        _save_persisted_time(self._current_time)

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
        _save_persisted_time(self._current_time)
        return self._current_time

    def set_time(self, new_time):
        self._current_time = normalize_slot(new_time)
        _save_persisted_time(self._current_time)
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
            return next_time


def _load_persisted_time():
    from src.clock_bootstrap import load_persisted_clock

    try:
        return load_persisted_clock()
    except DataIntegrityError:
        return None


def _save_persisted_time(current_time):
    from src.clock_bootstrap import persist_clock

    persist_clock(normalize_slot(current_time))


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
