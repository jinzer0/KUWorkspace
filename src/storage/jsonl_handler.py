"""
JSONL (JSON Lines) 파일 처리 모듈
"""

import json


def read_jsonl(file_path, from_json):
    """
    JSONL 파일에서 모든 레코드 읽기

    Args:
        file_path: 파일 경로
        from_json: JSON 문자열을 객체로 변환하는 함수

    Returns:
        객체 리스트
    """
    if not file_path.exists():
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()
        return []

    records = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:  # 빈 줄 무시
                records.append(from_json(line))
    return records


def write_jsonl(file_path, records, to_json):
    """
    JSONL 파일에 레코드 전체 쓰기 (덮어쓰기)

    Args:
        file_path: 파일 경로
        records: 저장할 객체 리스트
        to_json: 객체를 JSON 문자열로 변환하는 함수
    """
    # 부모 디렉토리가 없으면 생성
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with open(file_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(to_json(record) + "\n")


def append_jsonl(file_path, record, to_json):
    """
    JSONL 파일에 레코드 추가 (append)

    Args:
        file_path: 파일 경로
        record: 추가할 객체
        to_json: 객체를 JSON 문자열로 변환하는 함수
    """
    # 부모 디렉토리가 없으면 생성
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with open(file_path, "a", encoding="utf-8") as f:
        f.write(to_json(record) + "\n")


def read_jsonl_raw(file_path):
    """
    JSONL 파일을 딕셔너리 리스트로 읽기

    Args:
        file_path: 파일 경로

    Returns:
        딕셔너리 리스트
    """
    if not file_path.exists():
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()
        return []

    records = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def write_jsonl_raw(file_path, records):
    """
    딕셔너리 리스트를 JSONL 파일로 쓰기

    Args:
        file_path: 파일 경로
        records: 딕셔너리 리스트
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with open(file_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
