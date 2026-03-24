"""
전역 파일 잠금 모듈

portalocker를 사용하여 동시 실행 인스턴스 간 데이터 무결성 보장
재진입(reentrant) 잠금 지원으로 중첩 호출 허용
"""

import portalocker
from portalocker import Lock, LockException
from contextlib import contextmanager
import threading
import os

from src.config import LOCK_FILE, DATA_DIR, LOCK_TIMEOUT


class LockAcquisitionError(Exception):
    """전역 파일 잠금을 획득하지 못했을 때 발생합니다."""

    pass


class ReentrantFileLock:
    """프로세스 내 재진입을 지원하는 전역 파일 잠금 래퍼입니다."""

    _instance = None
    _init_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    @classmethod
    def reset_instance(cls):
        with cls._init_lock:
            if cls._instance is not None:
                if cls._instance._lock:
                    try:
                        cls._instance._lock.release()
                    except Exception:
                        pass
                cls._instance = None

    def __init__(self, lock_file=None, timeout=LOCK_TIMEOUT):
        if self._initialized:
            return
        self.lock_file = lock_file or LOCK_FILE
        self.timeout = timeout
        self._lock = None
        self._thread_lock = threading.RLock()
        self._entry_count = 0
        self._owner_pid = None
        self._initialized = True

    def _ensure_lock_file(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not self.lock_file.exists():
            self.lock_file.touch()

    def acquire(self):
        current_pid = os.getpid()

        self._thread_lock.acquire()

        if self._entry_count > 0 and self._owner_pid == current_pid:
            self._entry_count += 1
            return True

        self._ensure_lock_file()

        try:
            self._lock = Lock(
                str(self.lock_file),
                mode="w",
                timeout=self.timeout,
                flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
            )
            self._lock.acquire()
            self._entry_count = 1
            self._owner_pid = current_pid
            return True
        except LockException:
            self._thread_lock.release()
            self._lock = None
            raise LockAcquisitionError(
                f"잠금 획득 실패: {self.timeout}초 타임아웃. "
                "다른 사용자가 작업 중입니다. 잠시 후 다시 시도하세요."
            )

    def release(self):
        if self._entry_count > 0:
            self._entry_count -= 1
            if self._entry_count == 0:
                self._owner_pid = None
                if self._lock:
                    try:
                        self._lock.release()
                    except Exception:
                        pass
                    finally:
                        self._lock = None
            self._thread_lock.release()


class FileLock:
    """재진입 파일 잠금을 일반 컨텍스트 매니저 형태로 제공합니다."""

    def __init__(self, lock_file=None, timeout=LOCK_TIMEOUT):
        self._reentrant_lock = ReentrantFileLock()

    def acquire(self):
        return self._reentrant_lock.acquire()

    def release(self):
        self._reentrant_lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


@contextmanager
def global_lock(timeout=LOCK_TIMEOUT):
    """전역 파일 잠금을 획득하는 컨텍스트를 제공합니다."""
    lock = ReentrantFileLock()
    try:
        lock.acquire()
        yield lock
    finally:
        lock.release()


def is_lock_held():
    """전역 락이 현재 프로세스에서 활성 상태인지 확인"""
    lock = ReentrantFileLock()
    return lock._entry_count > 0 and lock._owner_pid == os.getpid()


def with_lock(timeout=LOCK_TIMEOUT):
    """함수를 전역 파일 잠금 아래에서 실행하는 데코레이터를 만듭니다."""

    def decorator(func):
        def wrapper(*args, **kwargs):
            with global_lock(timeout=timeout):
                return func(*args, **kwargs)

        return wrapper

    return decorator
