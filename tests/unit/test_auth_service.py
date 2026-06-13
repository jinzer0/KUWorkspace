"""
인증 서비스 테스트

테스트 대상:
- 회원가입 (signup): 정상 가입, 중복 username 거부
- 로그인 (login): 정상 로그인, 잘못된 username, 잘못된 password
- 사용자 조회/업데이트
- 관리자 여부 확인
"""

import pytest

from src.domain.auth_service import AuthError
from src.domain.models import UserRole
from src.storage.jsonl_handler import encode_record


class TestSignup:
    """회원가입 테스트"""

    def test_signup_success(self, auth_service):
        """정상 회원가입"""
        user = auth_service.signup(username="NewUser1", password="password123")

        assert user.id is not None
        assert user.username == "NewUser1"
        assert user.password == "password123"  # 평문 저장
        assert user.role == UserRole.USER
        assert user.penalty_points == 0
        assert user.normal_use_streak == 0
        assert user.restriction_until is None

    def test_signup_admin_role(self, auth_service):
        """관리자 역할로 회원가입"""
        admin = auth_service.signup(
            username="AdminUser1", password="adminpass1", role=UserRole.ADMIN
        )

        assert admin.role == UserRole.ADMIN

    def test_signup_duplicate_username_fails(self, auth_service):
        """중복 username으로 가입 시 실패"""
        # 첫 번째 가입
        auth_service.signup(username="Duplicate1", password="pass1")

        # 같은 username으로 다시 가입 시도
        with pytest.raises(AuthError) as exc_info:
            auth_service.signup(username="Duplicate1", password="pass2")

        assert "이미 존재하는 사용자명입니다" in str(exc_info.value)

    def test_signup_persists_user(self, auth_service, user_repo):
        """가입 후 저장소에 사용자가 저장되는지 확인"""
        auth_service.signup(username="Persisted1", password="pass1")

        # 저장소에서 직접 조회
        found = user_repo.get_by_username("Persisted1")
        assert found is not None
        assert found.username == "Persisted1"

    def test_signup_persists_ten_field_user_record(self, auth_service, user_repo):
        auth_service.signup(username="RecordUser1", password="pass1234")

        raw = user_repo.file_path.read_text(encoding="utf-8").strip()

        assert len(raw.split("|")) == 10

    def test_signup_blank_username_fails(self, auth_service):
        with pytest.raises(AuthError) as exc_info:
            auth_service.signup(username="   ", password="password123")

        assert "사용자명을 입력" in str(exc_info.value)

    def test_signup_invalid_username_fails(self, auth_service):
        with pytest.raises(AuthError) as exc_info:
            auth_service.signup(username="bad user", password="password123")

        assert "공백" in str(exc_info.value)

    @pytest.mark.parametrize(
        ("username", "expected"),
        [
            ("lowercase1", "대문자"),
            ("Ab", "3자 이상"),
            ("A" + "a" * 20, "20자 이하"),
            ("Invalid-Name1", "영문, 숫자, 밑줄"),
        ],
    )
    def test_signup_rejects_plan_username_rules(self, auth_service, user_repo, username, expected):
        with pytest.raises(AuthError) as exc_info:
            auth_service.signup(username=username, password="password123")

        assert expected in str(exc_info.value)
        assert user_repo.get_all() == []

    @pytest.mark.parametrize(
        ("password", "expected"),
        [
            ("1234", "영문"),
            ("Password", "숫자"),
        ],
    )
    def test_signup_rejects_plan_password_rules(self, auth_service, user_repo, password, expected):
        with pytest.raises(AuthError) as exc_info:
            auth_service.signup(username="PasswordRule1", password=password)

        assert expected in str(exc_info.value)
        assert user_repo.get_all() == []

    def test_signup_duplicate_username_does_not_write_extra_user(self, auth_service, user_repo):
        auth_service.signup(username="UniqueUser1", password="pass1234")
        before = user_repo.get_all()

        with pytest.raises(AuthError) as exc_info:
            auth_service.signup(username="UniqueUser1", password="other1234")

        assert "이미 존재하는 사용자명" in str(exc_info.value)
        assert [user.username for user in user_repo.get_all()] == [user.username for user in before]

    def test_signup_short_password_fails(self, auth_service):
        with pytest.raises(AuthError) as exc_info:
            auth_service.signup(username="ShortPass1", password="123")

        assert "4자 이상" in str(exc_info.value)

    def test_signup_rejects_whitespace_in_username_or_password(self, auth_service):
        with pytest.raises(AuthError) as exc_info:
            auth_service.signup(username="  spaced_user  ", password="  pass1234  ")

        assert "공백" in str(exc_info.value)


class TestLogin:
    """로그인 테스트"""

    def test_login_success(self, auth_service):
        """정상 로그인"""
        # 먼저 회원가입
        auth_service.signup(username="LoginUser1", password="correctpass1")

        # 로그인
        user = auth_service.login(username="LoginUser1", password="correctpass1")

        assert user.username == "LoginUser1"

    def test_seed_admin_login_remains_valid(self, auth_service):
        admin = auth_service.signup(
            username="AdminSeed1", password="admin123", role=UserRole.ADMIN
        )

        assert admin.role == UserRole.ADMIN

        user = auth_service.login(username="AdminSeed1", password="admin123")

        assert user.username == "AdminSeed1"
        assert user.role == UserRole.ADMIN

    def test_legacy_lowercase_admin_login_remains_valid(self, auth_service, temp_data_dir):
        users_file = temp_data_dir / "users.txt"
        users_file.write_text(
            encode_record(
                [
                    "admin",
                    "admin123",
                    "admin",
                    "0",
                    "0",
                    None,
                    "2026-03-20T09:00",
                    "2026-03-20T09:00",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        user = auth_service.login("admin", "admin123")

        assert user.username == "admin"
        assert user.role == UserRole.ADMIN

    def test_login_wrong_username(self, auth_service):
        """존재하지 않는 username으로 로그인 시 실패"""
        with pytest.raises(AuthError) as exc_info:
            auth_service.login(username="nonexistent", password="anypass")

        assert "존재하지 않는 사용자" in str(exc_info.value)

    def test_login_wrong_password(self, auth_service):
        """잘못된 password로 로그인 시 실패"""
        auth_service.signup(username="PassUser1", password="rightpass1")

        with pytest.raises(AuthError) as exc_info:
            auth_service.login(username="PassUser1", password="wrongpass1")

        assert "비밀번호가 일치하지 않습니다" in str(exc_info.value)

    def test_login_blank_username_fails(self, auth_service):
        with pytest.raises(AuthError) as exc_info:
            auth_service.login(username="   ", password="pass1")

        assert "사용자명을 입력" in str(exc_info.value)

    def test_login_rejects_whitespace_in_credentials(self, auth_service):
        auth_service.signup(username="Trimmed1", password="secret1234")

        with pytest.raises(AuthError) as exc_info:
            auth_service.login(username="  trimmed  ", password="  secret123  ")

        assert "공백" in str(exc_info.value)


class TestUserQueries:
    """사용자 조회 테스트"""

    def test_get_user_by_id(self, auth_service):
        """ID로 사용자 조회"""
        created = auth_service.signup(username="IdQuery1", password="pass1")

        found = auth_service.get_user(created.id)

        assert found is not None
        assert found.id == created.id
        assert found.username == "IdQuery1"

    def test_get_user_by_id_not_found(self, auth_service):
        with pytest.raises(AuthError) as exc_info:
            auth_service.get_user("nonexistent-id")

        assert "존재하지 않는 사용자" in str(exc_info.value)

    def test_get_user_by_username(self, auth_service):
        """username으로 사용자 조회"""
        auth_service.signup(username="NameQuery1", password="pass1")

        found = auth_service.get_user_by_username("NameQuery1")

        assert found is not None
        assert found.username == "NameQuery1"

    def test_get_user_by_username_not_found(self, auth_service):
        with pytest.raises(AuthError) as exc_info:
            auth_service.get_user_by_username("missing-user")

        assert "존재하지 않는 사용자" in str(exc_info.value)

    def test_get_all_users(self, auth_service):
        """모든 사용자 조회"""
        auth_service.signup(username="User1A", password="pass1")
        auth_service.signup(username="User2A", password="pass1")
        auth_service.signup(username="User3A", password="pass1")
        admin = auth_service.signup(
            username="AdminQuery1", password="pass1", role=UserRole.ADMIN
        )

        all_users = auth_service.get_all_users(admin)

        assert len(all_users) == 4
        usernames = {u.username for u in all_users}
        assert "User1A" in usernames
        assert "User2A" in usernames
        assert "User3A" in usernames


class TestUserUpdate:
    """사용자 업데이트 테스트"""

    def test_update_user(self, auth_service):
        """사용자 정보 업데이트"""
        user = auth_service.signup(username="UpdateMe1", password="pass1")

        # 패널티 점수 변경
        from dataclasses import replace

        updated_user = replace(user, penalty_points=5)

        result = auth_service.update_user(updated_user)

        assert result.penalty_points == 5

        # 다시 조회해서 확인
        refetched = auth_service.get_user(user.id)
        assert refetched.penalty_points == 5

    def test_update_nonexistent_user_fails(self, auth_service, user_factory):
        """존재하지 않는 사용자 업데이트 시 실패"""
        fake_user = user_factory(id="nonexistent-id")

        with pytest.raises(AuthError) as exc_info:
            auth_service.update_user(fake_user)

        assert "사용자를 찾을 수 없습니다" in str(exc_info.value)


class TestAdminCheck:
    """관리자 여부 확인 테스트"""

    def test_is_admin_true(self, auth_service):
        """관리자 사용자 확인"""
        admin = auth_service.signup(
            username="AdminRole1", password="pass1", role=UserRole.ADMIN
        )

        assert auth_service.is_admin(admin) is True

    def test_is_admin_false(self, auth_service):
        """일반 사용자는 관리자가 아님"""
        user = auth_service.signup(
            username="NormalUser1", password="pass1", role=UserRole.USER
        )

        assert auth_service.is_admin(user) is False

    def test_is_admin_nonexistent_user_fails(self, auth_service, user_factory):
        fake_user = user_factory(role=UserRole.ADMIN)

        with pytest.raises(AuthError) as exc_info:
            auth_service.is_admin(fake_user)

        assert "존재하지 않는 사용자" in str(exc_info.value)


class TestAdminOnlyAccess:
    """관리자 전용 API 접근 제어 테스트"""

    def test_get_all_users_rejects_non_admin(self, auth_service):
        """일반 사용자가 전체 사용자 조회 시 거부"""
        user = auth_service.signup(username="Regular1", password="pass1")

        with pytest.raises(AuthError) as exc_info:
            auth_service.get_all_users(user)

        assert "관리자 권한" in str(exc_info.value)

    def test_get_all_users_rejects_nonexistent_admin(self, auth_service, user_factory):
        fake_admin = user_factory(role=UserRole.ADMIN)

        with pytest.raises(AuthError) as exc_info:
            auth_service.get_all_users(fake_admin)

        assert "존재하지 않는 사용자" in str(exc_info.value)
