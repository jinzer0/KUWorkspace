# KUWorkspace Rule Reference (Deprecated)

이 문서는 현재 구현과 동기화되지 않아 더 이상 기준 문서로 사용하지 않습니다.

현재 동작 기준은 다음 두 곳입니다.

- 저장소 루트의 최신 기획 문서
- 실제 구현 코드(`main.py`, `src/`, `tests/`)

특히 다음 항목은 이 문서보다 코드와 최신 기획 문서를 우선합니다.

- 파이프(`|`) 구분 텍스트 저장 형식
- `users.txt`, `rooms.txt`, `equipments.txt`, `room_bookings.txt`, `equipment_booking.txt`, `penalties.txt`, `audit_log.txt`
- 시작 시점 입력의 표시 형식(`YYYY-MM-DD`)과 유연한 날짜 파싱
- 회의실/장비 예약 제한의 독립 카운트 규칙
- 문의/신고 서브시스템 제거
