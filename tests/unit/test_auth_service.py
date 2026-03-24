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


class TestSignup:
    """회원가입 테스트"""

    def test_signup_success(self, auth_service):
        """정상 회원가입"""
        user = auth_service.signup(username="newuser", password="password123")

        assert user.id is not None
        assert user.username == "newuser"
        assert user.password == "password123"  # 평문 저장
        assert user.role == UserRole.USER
        assert user.penalty_points == 0
        assert user.normal_use_streak == 0
        assert user.restriction_until is None

    def test_signup_admin_role(self, auth_service):
        """관리자 역할로 회원가입"""
        admin = auth_service.signup(
            username="adminuser", password="adminpass", role=UserRole.ADMIN
        )

        assert admin.role == UserRole.ADMIN

    def test_signup_duplicate_username_fails(self, auth_service):
        """중복 username으로 가입 시 실패"""
        # 첫 번째 가입
        auth_service.signup(username="duplicate", password="pass1")

        # 같은 username으로 다시 가입 시도
        with pytest.raises(AuthError) as exc_info:
            auth_service.signup(username="duplicate", password="pass2")

        assert "이미 존재하는 사용자명입니다" in str(exc_info.value)

    def test_signup_persists_user(self, auth_service, user_repo):
        """가입 후 저장소에 사용자가 저장되는지 확인"""
        auth_service.signup(username="persisted", password="pass")

        # 저장소에서 직접 조회
        found = user_repo.get_by_username("persisted")
        assert found is not None
        assert found.username == "persisted"

    def test_signup_blank_username_fails(self, auth_service):
        with pytest.raises(AuthError) as exc_info:
            auth_service.signup(username="   ", password="password123")

        assert "사용자명을 입력" in str(exc_info.value)

    def test_signup_invalid_username_fails(self, auth_service):
        with pytest.raises(AuthError) as exc_info:
            auth_service.signup(username="bad user", password="password123")

        assert "밑줄" in str(exc_info.value)

    def test_signup_short_password_fails(self, auth_service):
        with pytest.raises(AuthError) as exc_info:
            auth_service.signup(username="shortpass", password="123")

        assert "4자 이상" in str(exc_info.value)

    def test_signup_strips_surrounding_whitespace(self, auth_service):
        user = auth_service.signup(username="  spaced_user  ", password="  pass1234  ")

        assert user.username == "spaced_user"
        assert user.password == "pass1234"


class TestLogin:
    """로그인 테스트"""

    def test_login_success(self, auth_service):
        """정상 로그인"""
        # 먼저 회원가입
        auth_service.signup(username="loginuser", password="correctpass")

        # 로그인
        user = auth_service.login(username="loginuser", password="correctpass")

        assert user.username == "loginuser"

    def test_login_wrong_username(self, auth_service):
        """존재하지 않는 username으로 로그인 시 실패"""
        with pytest.raises(AuthError) as exc_info:
            auth_service.login(username="nonexistent", password="anypass")

        assert "존재하지 않는 사용자" in str(exc_info.value)

    def test_login_wrong_password(self, auth_service):
        """잘못된 password로 로그인 시 실패"""
        auth_service.signup(username="passuser", password="rightpass")

        with pytest.raises(AuthError) as exc_info:
            auth_service.login(username="passuser", password="wrongpass")

        assert "비밀번호가 일치하지 않습니다" in str(exc_info.value)

    def test_login_blank_username_fails(self, auth_service):
        with pytest.raises(AuthError) as exc_info:
            auth_service.login(username="   ", password="pass")

        assert "사용자명을 입력" in str(exc_info.value)

    def test_login_strips_surrounding_whitespace(self, auth_service):
        auth_service.signup(username="trimmed", password="secret123")

        user = auth_service.login(username="  trimmed  ", password="  secret123  ")

        assert user.username == "trimmed"


class TestUserQueries:
    """사용자 조회 테스트"""

    def test_get_user_by_id(self, auth_service):
        """ID로 사용자 조회"""
        created = auth_service.signup(username="idquery", password="pass")

        found = auth_service.get_user(created.id)

        assert found is not None
        assert found.id == created.id
        assert found.username == "idquery"

    def test_get_user_by_id_not_found(self, auth_service):
        with pytest.raises(AuthError) as exc_info:
            auth_service.get_user("nonexistent-id")

        assert "존재하지 않는 사용자" in str(exc_info.value)

    def test_get_user_by_username(self, auth_service):
        """username으로 사용자 조회"""
        auth_service.signup(username="namequery", password="pass")

        found = auth_service.get_user_by_username("namequery")

        assert found is not None
        assert found.username == "namequery"

    def test_get_user_by_username_not_found(self, auth_service):
        with pytest.raises(AuthError) as exc_info:
            auth_service.get_user_by_username("missing-user")

        assert "존재하지 않는 사용자" in str(exc_info.value)

    def test_get_all_users(self, auth_service):
        """모든 사용자 조회"""
        auth_service.signup(username="user1", password="pass")
        auth_service.signup(username="user2", password="pass")
        auth_service.signup(username="user3", password="pass")
        admin = auth_service.signup(
            username="admin_query", password="pass", role=UserRole.ADMIN
        )

        all_users = auth_service.get_all_users(admin)

        assert len(all_users) == 4
        usernames = {u.username for u in all_users}
        assert "user1" in usernames
        assert "user2" in usernames
        assert "user3" in usernames


class TestUserUpdate:
    """사용자 업데이트 테스트"""

    def test_update_user(self, auth_service):
        """사용자 정보 업데이트"""
        user = auth_service.signup(username="updateme", password="pass")

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
            username="admin", password="pass", role=UserRole.ADMIN
        )

        assert auth_service.is_admin(admin) is True

    def test_is_admin_false(self, auth_service):
        """일반 사용자는 관리자가 아님"""
        user = auth_service.signup(
            username="normaluser", password="pass", role=UserRole.USER
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
        user = auth_service.signup(username="regular", password="pass")

        with pytest.raises(AuthError) as exc_info:
            auth_service.get_all_users(user)

        assert "관리자 권한" in str(exc_info.value)

    def test_get_all_users_rejects_nonexistent_admin(self, auth_service, user_factory):
        fake_admin = user_factory(role=UserRole.ADMIN)

        with pytest.raises(AuthError) as exc_info:
            auth_service.get_all_users(fake_admin)

        assert "존재하지 않는 사용자" in str(exc_info.value)
