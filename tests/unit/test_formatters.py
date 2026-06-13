import unicodedata

from src.cli.formatters import format_table


def display_width(text: object) -> int:
    width = 0
    for char in str(text):
        codepoint = ord(char)
        if unicodedata.combining(char):
            continue
        if char == "\u200d" or 0xFE00 <= codepoint <= 0xFE0F:
            continue
        if 0xE0100 <= codepoint <= 0xE01EF:
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
    return width


def test_korean_headers_and_cells_match_separator_display_width():
    table = format_table(
        ["이름", "종류", "시리얼번호", "상태"],
        [["프로젝터", "영상장비", "EQ-001", "[사용가능]"]],
    )

    header_line, separator, data_line = table.splitlines()

    assert display_width(separator) == display_width(header_line)
    assert display_width(separator) == display_width(data_line)
    assert display_width(separator) <= 80


def test_korean_cell_padding_aligns_following_ascii_columns_by_display_width():
    table = format_table(
        ["이름", "코드"],
        [
            ["노트북", "A1"],
            ["ABCD", "B2"],
        ],
    )

    _, _, korean_row, ascii_row = table.splitlines()

    korean_code_column = display_width(korean_row[: korean_row.index("A1")])
    ascii_code_column = display_width(ascii_row[: ascii_row.index("B2")])
    assert korean_code_column == ascii_code_column


def test_ascii_table_output_stays_compatible():
    table = format_table(["ID", "Name"], [["1", "Desk"]])

    assert table == "ID  Name  \n----------\n1   Desk  "


def test_long_korean_text_truncates_with_ellipsis_within_display_width():
    long_name = "가나다라마바사아자차카타파하거너더러머버"
    table = format_table(["이름"], [[long_name]])

    _, separator, data_line = table.splitlines()

    assert "..." in data_line
    assert display_width(data_line) == display_width(separator) == 40
    assert display_width(data_line.rstrip()) <= 38
