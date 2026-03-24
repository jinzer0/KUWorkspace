"""
기본 메뉴 클래스 및 유틸리티
"""

from abc import ABC, abstractmethod

from src.cli.formatters import print_header


class BaseMenu(ABC):
    """메뉴 기본 클래스"""

    def __init__(self):
        self.running = True

    @abstractmethod
    def get_title(self):
        """메뉴 제목"""

    @abstractmethod
    def get_options(self):
        """
        메뉴 옵션 목록

        Returns:
            [(번호, 설명), ...]
        """

    @abstractmethod
    def handle_choice(self, choice):
        """
        선택 처리

        Args:
            choice: 선택된 번호

        Returns:
            계속 실행 여부
        """

    def display(self):
        """메뉴 출력"""
        print_header(self.get_title())

        for num, desc in self.get_options() or []:
            print(f"  {num}. {desc}")

        print("-" * 50)

    def get_input(self):
        """사용자 입력 받기"""
        while True:
            try:
                choice = input("선택: ").strip()
                if not choice:
                    continue
                return int(choice)
            except ValueError:
                print("  숫자를 입력해주세요.")

    def run(self):
        """메뉴 실행 루프"""
        self.running = True
        while self.running:
            self.display()
            choice = self.get_input()
            try:
                self.running = self.handle_choice(choice)
            except Exception as e:
                print(f"\n오류가 발생했습니다: {e}")
                self.running = True


class MenuRouter:
    """메뉴 라우터 - 동적 메뉴 구성용"""

    def __init__(self, title):
        self.title = title
        self.options = []
        self.exit_option = None

    def add_option(self, num, desc, handler):
        """옵션 추가"""
        self.options.append((num, desc, handler))
        return self

    def set_exit(self, num, desc):
        """종료 옵션 설정"""
        self.exit_option = (num, desc)
        return self

    def display(self):
        """메뉴 출력"""
        print_header(self.title)

        for num, desc, _ in self.options:
            print(f"  {num}. {desc}")

        if self.exit_option:
            print(f"  {self.exit_option[0]}. {self.exit_option[1]}")

        print("-" * 50)

    def run(self):
        """
        메뉴 실행

        Returns:
            종료 선택 여부 (True면 상위로 복귀)
        """
        self.display()

        while True:
            try:
                choice = input("선택: ").strip()
                if not choice:
                    continue
                choice_int = int(choice)
                break
            except ValueError:
                print("  숫자를 입력해주세요.")

        # 종료 옵션 확인
        if self.exit_option and str(choice_int) == self.exit_option[0]:
            return True

        # 핸들러 찾기
        for num, _, handler in self.options:
            if str(choice_int) == num:
                handler()
                return False

        print("  잘못된 선택입니다.")
        return False


def confirm(prompt):
    """확인 입력 받기"""
    while True:
        response = input(f"{prompt} (y/n): ").strip().lower()
        if response in ("y", "yes", "예", "ㅇ"):
            return True
        if response in ("n", "no", "아니오", "ㄴ"):
            return False
        print("  y 또는 n을 입력해주세요.")


def pause():
    """계속하려면 Enter 입력"""
    input("\n계속하려면 Enter를 누르세요...")


def select_from_list(items, prompt="선택", allow_cancel=True):
    """
    목록에서 항목 선택

    Args:
        items: [(id, display_text), ...]
        prompt: 입력 프롬프트
        allow_cancel: 취소 허용 여부

    Returns:
        선택된 항목의 ID (취소 시 None)
    """
    if not items:
        print("  선택 가능한 항목이 없습니다.")
        return None

    print()
    for i, (item_id, text) in enumerate(items, 1):
        print(f"  {i}. {text}")

    if allow_cancel:
        print(f"  0. 취소")

    while True:
        try:
            choice = input(f"\n{prompt} (번호): ").strip()
            if not choice:
                continue

            choice_int = int(choice)

            if allow_cancel and choice_int == 0:
                return None

            if 1 <= choice_int <= len(items):
                return items[choice_int - 1][0]

            print(f"  1~{len(items)} 사이의 번호를 입력해주세요.")
        except ValueError:
            print("  숫자를 입력해주세요.")
