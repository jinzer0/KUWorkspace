"""
인증 서비스 - 회원가입, 로그인 처리
"""

from src.domain.models import User, UserRole
from src.domain.auth_rules import (
    normalize_credential,
    validate_username,
    validate_password,
)
from src.storage.repositories import UserRepository
from src.storage.file_lock import global_lock


class AuthError(Exception):
    """인증 관련 예외"""


class AuthService:
    """인증 서비스"""

    def __init__(self, user_repo=None):
        self.user_repo = user_repo or UserRepository()

    def signup(self, username, password, role=UserRole.USER):
        """
        회원가입

        Args:
            username: 사용자명
            password: 비밀번호
            role: 역할 (기본값: user)

        Returns:
            생성된 사용자

        Raises:
            AuthError: 사용자명 중복 시
        """
        username = normalize_credential(username)
        password = normalize_credential(password)

        valid, error = validate_username(username)
        if not valid:
            raise AuthError(error)

        valid, error = validate_password(password)
        if not valid:
            raise AuthError(error)

        with global_lock():
            # 중복 확인
            if self.user_repo.username_exists(username):
                raise AuthError(f"이미 존재하는 사용자명입니다: {username}")

            # 사용자 생성
            user = User(
                id=username, username=username, password=password, role=role
            )

            self.user_repo.add(user)
            return user

    def login(self, username, password):
        """
        로그인

        Args:
            username: 사용자명
            password: 비밀번호

        Returns:
            로그인된 사용자

        Raises:
            AuthError: 사용자명 또는 비밀번호 불일치 시
        """
        username = normalize_credential(username)
        password = normalize_credential(password)

        valid, error = validate_username(username)
        if not valid:
            raise AuthError(error)

        valid, error = validate_password(password)
        if not valid:
            raise AuthError(error)

        user = self.user_repo.get_by_username(username)

        if user is None:
            raise AuthError("존재하지 않는 사용자입니다.")

        if user.password != password:
            raise AuthError("비밀번호가 일치하지 않습니다.")

        return user

    def get_user(self, user_id):
        """사용자 조회"""
        user = self.user_repo.get_by_id(user_id)
        if user is None:
            raise AuthError("존재하지 않는 사용자입니다.")
        return user

    def get_user_by_username(self, username):
        """사용자명으로 조회"""
        user = self.user_repo.get_by_username(normalize_credential(username))
        if user is None:
            raise AuthError("존재하지 않는 사용자입니다.")
        return user

    def update_user(self, user):
        """사용자 정보 업데이트"""
        with global_lock():
            updated = self.user_repo.update(user)
            if updated is None:
                raise AuthError(f"사용자를 찾을 수 없습니다: {user.id}")
            return updated

    def get_all_users(self, admin):
        """모든 사용자 조회 (관리자용)"""
        current_admin = self.user_repo.get_by_id(admin.id)
        if current_admin is None:
            raise AuthError("존재하지 않는 사용자입니다.")
        if admin.role != UserRole.ADMIN:
            raise AuthError("관리자 권한이 필요합니다.")
        if current_admin.role != UserRole.ADMIN:
            raise AuthError("관리자 권한이 필요합니다.")
        return self.user_repo.get_all()

    def is_admin(self, user):
        """관리자 여부 확인"""
        current_user = self.user_repo.get_by_id(user.id)
        if current_user is None:
            raise AuthError("존재하지 않는 사용자입니다.")
        return current_user.role == UserRole.ADMIN
