"""
원자적 파일 쓰기 모듈

임시 파일에 쓰고 원본 파일로 교체하여 데이터 무결성 보장

현재 저장 계층 쓰기 절차:
1. 전역 락 획득
2. 관련 txt 파일 전체 로드
3. 메모리에서 정책 검증 및 수정
4. 각 파일을 *.tmp에 저장
5. 검증 완료 후 원본 파일로 원자적 교체
6. 감사 로그까지 저장한 뒤 락 해제
"""

import os
import tempfile

from src.storage.integrity import DataIntegrityError
from src.storage.jsonl_handler import encode_record


def atomic_write(file_path, content):
    """
    원자적 파일 쓰기

    1. 임시 파일에 내용 쓰기
    2. fsync로 디스크 동기화
    3. 원본 파일로 교체 (os.replace - 원자적)

    Args:
        file_path: 대상 파일 경로
        content: 쓸 내용
    """
    # 부모 디렉토리가 없으면 생성
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise DataIntegrityError(
            f"데이터 파일을 저장할 수 없습니다: {file_path} ({error})"
        ) from error

    # 같은 디렉토리에 임시 파일 생성 (다른 파일시스템으로 이동 방지)
    dir_path = file_path.parent

    try:
        fd, tmp_path = tempfile.mkstemp(dir=str(dir_path), suffix=".tmp")
    except OSError as error:
        raise DataIntegrityError(
            f"데이터 파일을 저장할 수 없습니다: {file_path} ({error})"
        ) from error
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        # 원자적 교체
        os.replace(tmp_path, file_path)
    except OSError as error:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise DataIntegrityError(
            f"데이터 파일을 저장할 수 없습니다: {file_path} ({error})"
        ) from error
    except Exception:
        # 실패 시 임시 파일 삭제
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_jsonl(file_path, records, to_json):
    """
    JSONL 형식으로 원자적 쓰기

    Args:
        file_path: 대상 파일 경로
        records: 저장할 객체 리스트
        to_json: 객체를 JSON 문자열로 변환하는 함수
    """
    lines = [encode_record(to_json(record)) for record in records]
    content = "\n".join(lines) + "\n" if lines else ""
    atomic_write(file_path, content)


def staged_atomic_write_multi(file_contents):
    """
    여러 파일을 단계적으로 원자적 쓰기

    1. 모든 파일을 *.tmp에 먼저 저장 (staging)
    2. 기존 원본 파일을 *.bak에 백업 (롤백 대비)
    3. 모든 tmp 파일을 원본으로 교체
    4. 교체 중 실패 시 백업에서 원본 복원, 새 파일 삭제 (롤백)
    5. 성공 시 백업 파일 삭제
    """
    if not file_contents:
        return

    import shutil

    staged_files = []  # (tmp_path, target_path, existed_before)
    backup_files = {}  # {target_path: bak_path}
    replaced_files = []

    try:
        # Phase 1: Stage all files to *.tmp and track existence
        for file_path, content in file_contents.items():
            file_path.parent.mkdir(parents=True, exist_ok=True)
            dir_path = file_path.parent
            existed_before = file_path.exists()

            fd, tmp_path = tempfile.mkstemp(dir=str(dir_path), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                staged_files.append((tmp_path, file_path, existed_before))
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

        # Phase 2: Backup existing files to *.bak
        for tmp_path, target_path, existed_before in staged_files:
            if existed_before:
                fd, bak_path = tempfile.mkstemp(
                    dir=str(target_path.parent), suffix=".bak"
                )
                os.close(fd)
                try:
                    shutil.copy2(str(target_path), bak_path)
                    backup_files[target_path] = bak_path
                except Exception:
                    try:
                        os.unlink(bak_path)
                    except OSError:
                        pass
                    raise

        # Phase 3: Atomic replace with full rollback on failure
        try:
            for tmp_path, target_path, existed_before in staged_files:
                os.replace(tmp_path, target_path)
                replaced_files.append(target_path)
        except Exception as replace_error:
            _rollback_replaced_files(replaced_files, backup_files, staged_files)
            raise replace_error

        # Phase 4: Success - cleanup backups
        for bak_path in backup_files.values():
            try:
                os.unlink(bak_path)
            except OSError:
                pass

    except DataIntegrityError:
        raise
    except OSError as error:
        for tmp_path, _, _ in staged_files:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        for bak_path in backup_files.values():
            try:
                os.unlink(bak_path)
            except OSError:
                pass
        raise DataIntegrityError(
            f"데이터 파일을 저장할 수 없습니다: {error}"
        ) from error
    except Exception:
        # Staging or backup failed - cleanup tmp and bak files
        for tmp_path, _, _ in staged_files:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        for bak_path in backup_files.values():
            try:
                os.unlink(bak_path)
            except OSError:
                pass
        raise


def _rollback_replaced_files(replaced_files, backup_files, staged_files):
    """
    Rollback replaced files: restore from backup or delete if new.
    Raises RuntimeError if any rollback operation fails.
    """
    rollback_errors = []

    for target_path in replaced_files:
        if target_path in backup_files:
            # Existed before - restore from backup
            try:
                os.replace(backup_files[target_path], target_path)
            except OSError as e:
                rollback_errors.append(f"Failed to restore {target_path}: {e}")
        else:
            # New file - delete it to rollback
            try:
                os.unlink(target_path)
            except OSError as e:
                rollback_errors.append(f"Failed to delete new file {target_path}: {e}")

    # Cleanup unreplaced tmp files
    for tmp_path, target_path, _ in staged_files:
        if target_path not in replaced_files:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # Cleanup remaining backups
    for target_path, bak_path in backup_files.items():
        if target_path not in replaced_files:
            try:
                os.unlink(bak_path)
            except OSError:
                pass

    if rollback_errors:
        raise RuntimeError(f"Rollback failed: {'; '.join(rollback_errors)}")


def staged_atomic_write_jsonl_multi(file_records):
    """
    여러 파이프 구분 텍스트 파일을 단계적으로 원자적 쓰기

    Args:
        file_records: {파일경로: (레코드리스트, to_json함수)} 딕셔너리
    """
    file_contents = {}
    for file_path, (records, to_json) in file_records.items():
        lines = [encode_record(to_json(record)) for record in records]
        content = "\n".join(lines) + "\n" if lines else ""
        file_contents[file_path] = content

    staged_atomic_write_multi(file_contents)
