import pytest

from src.storage.file_lock import global_lock
from src.storage.repositories import UnitOfWork, UserRepository
from src.storage.integrity import DataIntegrityError


def test_unit_of_work_requires_global_lock(temp_data_dir, user_factory):
    """잠금 없이 UnitOfWork를 열면 실패하는지 확인합니다."""
    repo = UserRepository(file_path=temp_data_dir / "users.txt")
    user = user_factory(username="uow-no-lock")

    with pytest.raises(RuntimeError, match="global lock"):
        with UnitOfWork():
            repo.add(user)


def test_unit_of_work_commits_under_global_lock(temp_data_dir, user_factory):
    """전역 잠금 아래에서는 UnitOfWork 커밋이 성공하는지 확인합니다."""
    repo = UserRepository(file_path=temp_data_dir / "users.txt")
    user = user_factory(username="uow-with-lock")

    with global_lock(), UnitOfWork():
        repo.add(user)

    assert repo.get_by_username("uow-with-lock") is not None


def test_unit_of_work_fails_fast_on_write_permission_error(
    temp_data_dir, user_factory, monkeypatch
):
    repo = UserRepository(file_path=temp_data_dir / "users.txt")
    user = user_factory(username="uow-write-fail")

    def fail_save(*_args, **_kwargs):
        raise DataIntegrityError("필수 데이터 파일을 생성할 수 없습니다: permission denied")

    monkeypatch.setattr("src.storage.repositories.atomic_write_jsonl", fail_save)

    with pytest.raises(DataIntegrityError, match="permission denied"):
        with global_lock():
            repo.add(user)
