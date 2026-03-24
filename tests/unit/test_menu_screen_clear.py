import io
import sys

from src.cli.formatters import CLEAR_SCREEN_SEQUENCE, print_header
from src.cli.menu import BaseMenu, MenuRouter


class FakeStdout(io.StringIO):
    def __init__(self, is_tty):
        super().__init__()
        self._is_tty = is_tty
        self.flushed = False

    def isatty(self):
        return self._is_tty

    def flush(self):
        self.flushed = True
        super().flush()


class StubMenu(BaseMenu):
    def get_title(self):
        return "테스트 메뉴"

    def get_options(self):
        return [("1", "조회"), ("0", "종료")]

    def handle_choice(self, choice):
        return choice != 0


def test_print_header_clears_tty_before_rendering(monkeypatch):
    fake_stdout = FakeStdout(is_tty=True)
    monkeypatch.setattr(sys, "stdout", fake_stdout)

    print_header("메인 화면")

    output = fake_stdout.getvalue()
    assert output.startswith(CLEAR_SCREEN_SEQUENCE)
    assert "메인 화면" in output
    assert fake_stdout.flushed is True


def test_print_header_skips_clear_when_stdout_is_not_tty(monkeypatch):
    fake_stdout = FakeStdout(is_tty=False)
    monkeypatch.setattr(sys, "stdout", fake_stdout)

    print_header("메인 화면")

    output = fake_stdout.getvalue()
    assert not output.startswith(CLEAR_SCREEN_SEQUENCE)
    assert "메인 화면" in output


def test_base_menu_display_uses_shared_header(monkeypatch):
    titles = []
    monkeypatch.setattr("src.cli.menu.print_header", titles.append)

    StubMenu().display()

    assert titles == ["테스트 메뉴"]


def test_menu_router_display_uses_shared_header(monkeypatch):
    titles = []
    monkeypatch.setattr("src.cli.menu.print_header", titles.append)

    router = MenuRouter("관리 메뉴")
    router.add_option("1", "사용자 조회", lambda: None)
    router.set_exit("0", "종료")
    router.display()

    assert titles == ["관리 메뉴"]
