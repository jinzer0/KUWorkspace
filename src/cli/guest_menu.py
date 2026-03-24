"""
비로그인 메뉴 (게스트 메뉴) - 로그인, 회원가입, 종료
"""

from src.domain.auth_service import AuthService, AuthError
from src.domain.policy_service import PolicyService
from src.domain.penalty_service import PenaltyError
from src.cli.menu import confirm, pause
from src.cli.formatters import print_header, print_success, print_error
from src.cli.validators import validate_username, validate_password


class GuestMenu:
    """비로그인 상태 메뉴"""

    def __init__(self, auth_service=None, policy_service=None):
        self.auth_service = auth_service or AuthService()
        self.policy_service = policy_service or PolicyService()
        self.current_user = None

    def _run_policy_checks(self):
        try:
            self.policy_service.run_all_checks()
            return True
        except PenaltyError as e:
            print_error(str(e))
            pause()
            return False

    def run(self):
        """
        게스트 메뉴 실행

        Returns:
            로그인된 사용자 (종료 시 None)
        """
        if not self._run_policy_checks():
            return None

        while True:
            print_header("공유 오피스 예약 시스템")
            print("  1. 로그인")
            print("  2. 회원가입")
            print("  0. 종료")
            print("-" * 50)

            choice = input("선택: ").strip()

            if choice == "1":
                user = self._login()
                if user:
                    return user
            elif choice == "2":
                self._signup()
            elif choice == "0":
                if confirm("정말 종료하시겠습니까?"):
                    print("\n프로그램을 종료합니다.")
                    return None
            else:
                print_error("잘못된 선택입니다.")

    def _login(self):
        """로그인 처리"""
        print_header("로그인")

        username = input("사용자명: ").strip()
        if not username:
            print_error("사용자명을 입력해주세요.")
            return None

        password = input("비밀번호: ").strip()
        if not password:
            print_error("비밀번호를 입력해주세요.")
            return None

        try:
            user = self.auth_service.login(username, password)
            if not self._run_policy_checks():
                return None
            user = self.auth_service.get_user(user.id)
            print_success(f"{user.username}님, 환영합니다!")

            status = self.policy_service.penalty_service.get_user_status(user)
            if status.get("warning_message"):
                print(f"  ⚠ {status['warning_message']}")

            pause()
            return user

        except (AuthError, PenaltyError) as e:
            print_error(str(e))
            pause()
            return None

    def _signup(self):
        """회원가입 처리"""
        print_header("회원가입")

        while True:
            username = input("사용자명 (3-20자, 영문/숫자/_): ").strip()
            if not username:
                print_error("사용자명을 입력해주세요.")
                continue

            valid, error = validate_username(username)
            if not valid:
                print_error(error)
                continue
            break

        while True:
            password = input("비밀번호 (4자 이상): ").strip()
            if not password:
                print_error("비밀번호를 입력해주세요.")
                continue

            valid, error = validate_password(password)
            if not valid:
                print_error(error)
                continue

            password_confirm = input("비밀번호 확인: ").strip()
            if password != password_confirm:
                print_error("비밀번호가 일치하지 않습니다.")
                continue
            break

        try:
            user = self.auth_service.signup(username, password)
            print_success(f"회원가입이 완료되었습니다. (사용자명: {user.username})")
            print("  로그인 후 서비스를 이용해주세요.")
            pause()

        except AuthError as e:
            print_error(str(e))
            pause()
