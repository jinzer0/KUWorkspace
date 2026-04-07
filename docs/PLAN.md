# 공유 오피스 예약 및 장비 대여 관리 프로그램 계획서

## 문서 목적

- 이 문서는 코딩 에이전트와 개발자가 구현 기준으로 사용할 수 있도록 정리한 최종 계획 문서다.
- 본 문서는 기존 초안, 예시 화면, 이미지보다 우선한다.
- 저장소의 현재 구현과 문서가 충돌할 경우, 별도 지시가 없는 한 본 문서를 기준으로 해석한다.
- 본 문서는 저장소 루트의 최신 기획 문서를 기준으로 재정리했으며, 다음 사용자 확정 사항을 함께 반영한다.
  - 장비 파일명은 `data/equipments.txt`, `data/equipment_booking.txt`를 사용한다.
  - 사용자 계정의 고유 식별자는 `username`만 사용한다. 사용자 UUID는 사용하지 않는다.
  - 운영 시점은 `data/system_clock.txt`에 저장하며, 초기값은 `0000-00-00T00:00`이다.

## 1. 기본 원칙

### 1.1 프로그램 형태

- 프로그램은 Python 기반 CLI 프로그램이다.
- 진입점은 `main.py`다.
- 저장소는 데이터베이스를 사용하지 않고 `data/` 아래 텍스트 파일을 사용한다.
- 모든 시간 처리의 기준은 실제 시각이 아니라 프로그램 내부 운영 시점이다.

### 1.2 운영 시점

- 운영 시점은 `09:00`, `18:00` 두 슬롯만 존재한다.
- 시점 이동 순서는 `당일 09:00 -> 당일 18:00 -> 다음날 09:00`로 고정한다.
- 여러 슬롯을 한 번에 건너뛰는 이동은 허용하지 않는다.
- 운영 시점은 `data/system_clock.txt`에 저장한다.
- `data/system_clock.txt`의 초기값은 `0000-00-00T00:00`이다.
- 운영 시점 파일에 초기값이 저장된 경우에만 프로그램 시작 시 운영 시작 시점을 입력받는다.
- 운영 시점 파일에 초기값이 아닌 값이 저장된 경우, 프로그램은 그 값을 현재 운영 시점으로 사용하며 다시 입력받지 않는다.

### 1.3 역할

- 게스트: 로그인하지 않은 사용자
- 유저: `user` 역할 계정
- 관리자: `admin` 역할 계정

### 1.4 잠금 및 저장

- 모든 쓰기 작업은 전역 잠금 아래 수행한다.
- 데이터 파일은 텍스트 파일로 유지하며, 프로그램 실행 중 사용자가 직접 수정하는 경우 정상 동작을 보장하지 않는다.

## 2. 용어

- 운영 시점: 시스템이 사용하는 이산 시간 단위
- 현재 운영 시점: 현재 시스템이 기준으로 삼는 시점
- 시점 전환: 현재 운영 시점에서 다음 운영 시점으로 이동하는 과정
- 패널티 점수: 사용자 위반 이력에 따라 누적되는 정수 점수
- 사용자 상태: 패널티 점수에 따른 상태. `normal`, `restricted`, `banned`
- 조기 퇴실/조기 반납: 예약 종료 전 관리자를 통해 사용 종료 처리하는 행위
- 활성 예약:
  - 회의실: `reserved`, `checkin_requested`, `checked_in`, `checkout_requested`
  - 장비: `reserved`, `pickup_requested`, `checked_out`, `return_requested`

## 3. 입력 공통 규칙

### 3.1 목록 선택 입력

- 목록 선택은 `0` 또는 `1..N`의 십진 정수만 허용한다.
- `0`은 취소 또는 상위 메뉴 복귀를 의미한다.
- 숫자가 아닌 입력은 `숫자를 입력해주세요.`를 출력하고 재입력 받는다.
- 범위를 벗어난 정수는 `1~N 사이의 번호를 입력해주세요.`를 출력하고 재입력 받는다.

### 3.2 확인 입력

- 확인 입력은 `y`, `yes`, `예`, `ㅇ`, `n`, `no`, `아니오`, `ㄴ`을 허용한다.
- 영문 입력은 대소문자를 구분하지 않는다.
- 긍정 입력은 진행, 부정 입력은 취소로 처리한다.
- 그 외 입력은 `y 또는 n을 입력해주세요.`를 출력하고 재입력 받는다.

### 3.3 날짜 입력

- 허용 형식:
  - `YYYY-MM-DD`
  - `YYYY.MM.DD`
  - `YYYY MM DD`
- 한 문자열 안에서 구분자를 혼합할 수 없다.
- 연도는 `2026..2100` 범위 정수만 허용한다.
- 월은 `01..12`, 일은 `01..31` 형식을 사용한다.
- 월과 일은 한 자리 수여도 앞에 `0`을 붙여야 한다.
- 문자열 앞뒤 공백은 허용하지 않는다.
- 실제 존재하지 않는 날짜는 허용하지 않는다.
- 저장 시에는 `YYYY-MM-DD` 형식으로 표준화한다.

### 3.4 시간 입력

- 운영 시점이나 예약 경계 시간 입력은 다음 형식만 허용한다.
  - `HH:MM`
  - `HHMM`
- 운영 시점에서 허용되는 시간은 `09:00`, `18:00`뿐이다.
- 저장 시에는 `HH:MM` 형식으로 표준화한다.
- 날짜와 시간을 함께 저장하는 경우 `YYYY-MM-DDTHH:MM` 형식으로 저장한다.

### 3.5 사유 문자열

- 빈 문자열 허용
- 줄바꿈 금지
- 최대 길이 20자

## 4. 데이터 요소

### 4.1 계정 정보

#### 4.1.1 아이디(username)

- 길이 `3..20`
- 허용 문자: 영문 대소문자, 숫자, `_`
- 공백 금지
- 다른 계정과 중복 불가
- 로그인 및 중복 체크는 정확히 일치 비교한다.
- 대소문자는 서로 다른 문자로 간주한다.

#### 4.1.2 비밀번호(password)

- 길이 `4..50`
- 공백 금지
- 로그인 인증에 사용한다.
- 비교는 정확히 일치 비교한다.

### 4.2 날짜 및 시간

- 회의실/장비 예약의 시작 시각, 종료 시각, 생성 시각, 수정 시각, 운영 시점 등에 사용한다.
- 예약 기간은 날짜 기반으로 입력받고, 실제 이용 시간은 다음처럼 고정한다.
  - 시작일 `09:00`
  - 종료일 `18:00`

### 4.3 장비

#### 4.3.1 장비 종류

- 장비 종류는 다음 네 가지다.
  - `노트북`
  - `프로젝터`
  - `웹캠`
  - `케이블`
- 각 종류별로 3개씩 보유한다.

#### 4.3.2 시리얼 번호

- 형식: `[영문 대문자 약어]-[고유번호 3자리]`
- 예시:
  - 프로젝터 1번: `PJ-001`
  - 노트북 1번: `NB-001`

### 4.4 사유

- 예약 취소, 자원 교체, 패널티 부과 등에서 사용한다.
- 빈 문자열 허용
- 줄바꿈 금지
- 최대 길이 20자

## 5. 데이터 파일

### 5.1 공통 문법 규칙

- 모든 데이터 파일은 UTF-8 인코딩 텍스트 파일이다.
- 하나의 행은 정확히 하나의 레코드를 표현한다.
- 필드 구분자는 `|`다.
- 필드값 안에서 `|`, `\`를 표현해야 할 경우 각각 `\|`, `\\`로 이스케이프한다.
- 값이 존재하지 않는 경우 `\-`를 사용한다.
- 값이 빈 문자열인 경우 `||`처럼 구분자 사이를 비워 둔다.
- 빈 행은 허용하지 않는다.
- 날짜는 `YYYY-MM-DD`, 시간은 `HH:MM`, 날짜+시간은 `YYYY-MM-DDTHH:MM` 형식으로 저장한다.

### 5.2 사용자 계정 파일

- 경로: `data/users.txt`
- 형식:

```text
<username>|<password>|<role>|<penalty_points>|<normal_use_streak>|<restriction_until>|<created_at>|<updated_at>
admin|admin123|admin|0|0|\-|2026-03-20T09:00|2026-03-20T09:00
```

- 필드 규칙:
  - `username`: 사용자 아이디, 고유값
  - `password`: 비밀번호
  - `role`: `user`, `admin`
  - `penalty_points`: 0 이상의 정수
  - `normal_use_streak`: 0 이상의 정수
  - `restriction_until`: `\-` 또는 `YYYY-MM-DDTHH:MM`
  - `created_at`: 생성 시각
  - `updated_at`: 수정 시각

### 5.3 회의실 파일

#### 5.3.1 회의실 필드 규칙

- `name`: `회의실` + 1자리 정수 + 영문 대문자 1자
- `capacity`: 1 이상의 정수
- `location`: `N층` 형식
- `status`: `available`, `maintenance`, `disabled`
- `description`: 길이 `1..10`, 개행 금지
- `created_at`, `updated_at`: `YYYY-MM-DDTHH:MM`

#### 5.3.2 회의실 정보 파일

- 경로: `data/rooms.txt`
- 형식:

```text
<name>|<capacity>|<location>|<status>|<description>|<created_at>|<updated_at>
회의실2A|8|2층|available|모던스타일|2026-03-20T09:00|2026-03-20T09:00
```

#### 5.3.3 회의실 예약 파일

- 경로: `data/room_bookings.txt`
- 형식:

```text
<booking_id>|<username>|<room_id>|<start_time>|<end_time>|<status>|<checked_in_at>|<requested_checkin_at>|<requested_checkout_at>|<completed_at>|<cancelled_at>|<created_at>|<updated_at>
4dadd37f-1107-458f-a4cf-fb90c167a56c|user01|회의실2A|2027-06-15T11:00|2027-06-15T12:00|completed|2027-06-15T10:00|\-|\-|2027-06-15T12:00|\-|2027-06-15T10:00|2027-06-15T12:00
```

- 필드 규칙:
  - `booking_id`: 고유 예약 식별자
  - `username`: `users.txt`에 존재하는 username
  - `room_id`: `rooms.txt`에 존재하는 회의실 name
  - `start_time`, `end_time`: 날짜+시간
  - `start_time < end_time`
  - 동일 회의실 동일 기간 충돌 예약 금지
  - `status` 허용값:
    - `reserved`
    - `checkin_requested`
    - `checked_in`
    - `checkout_requested`
    - `completed`
    - `cancelled`
    - `admin_cancelled`
  - 나머지 시각 필드는 `\-` 또는 날짜+시간

### 5.4 장비 파일

#### 5.4.1 장비 필드 규칙

- `name`: 길이 `1..10`, 공백류 금지
- `asset_type`: 길이 `1..10`, 공백류 금지
- `serial_number`: 길이 `1..10`, 공백류 금지, 중복 불가
- `status`: `available`, `maintenance`, `disabled`
- `description`: 빈 문자열 또는 길이 `1..10`, 개행 금지
- `created_at`, `updated_at`: 날짜+시간

#### 5.4.2 장비 정보 파일

- 경로: `data/equipments.txt`
- 형식:

```text
<name>|<asset_type>|<serial_number>|<status>|<description>|<created_at>|<updated_at>
프로젝터|projector|PJ-001|available|HDMI포함|2026-03-20T09:00|2026-03-20T10:00
```

#### 5.4.3 장비 예약 파일

- 경로: `data/equipment_booking.txt`
- 형식:

```text
<booking_id>|<username>|<serial_id>|<start_time>|<end_time>|<status>|<checked_out_at>|<requested_pickup_at>|<requested_return_at>|<returned_at>|<cancelled_at>|<created_at>|<updated_at>
25c7cbb1-d5ff-4ba0-8b43-63c8f69cbbeb|student1|PJ-001|2026-04-10T09:00|2026-04-10T18:00|reserved|\-|\-|\-|\-|\-|2026-04-05T12:10|2026-04-05T12:10
```

- 필드 규칙:
  - `booking_id`: 고유 예약 식별자
  - `username`: `users.txt`에 존재하는 username
  - `serial_id`: `equipments.txt`에 존재하는 시리얼 번호
  - `start_time`, `end_time`: 날짜+시간
  - `start_time < end_time`
  - 동일 장비 동일 기간 충돌 예약 금지
  - `status` 허용값:
    - `reserved`
    - `pickup_requested`
    - `checked_out`
    - `return_requested`
    - `returned`
    - `cancelled`
    - `admin_cancelled`
  - 나머지 시각 필드는 `\-` 또는 날짜+시간

### 5.5 패널티 파일

- 경로: `data/penalties.txt`
- 형식:

```text
<penalty_id>|<username>|<reason>|<points>|<related_type>|<related_id>|<memo>|<created_at>|<updated_at>
0830d33f-326f-4e41-8cf3-024605558278|user001|contamination|3|room_booking|25c7cbb1-d5ff-4ba0-8b43-63c8f69cbbeb|오염|2026-04-12T18:00|2026-04-12T18:00
```

- 필드 규칙:
  - `penalty_id`: 고유 식별자
  - `username`: `users.txt`에 존재하는 username
  - `reason`: `late_cancel`, `late_return`, `damage`, `contamination`, `other`
  - `points`: 1 이상의 정수
  - `related_type`: `room_booking`, `equipment_booking`
  - `related_id`: 관련 예약 식별자
  - `memo`: 4.4 사유 규칙 준수
  - `created_at`, `updated_at`: 날짜+시간 또는 `\-`

### 5.6 감사 로그 파일

- 경로: `data/audit_log.txt`
- 형식:

```text
<log_id>|<actor>|<action>|<target_type>|<target_id>|<details>|<created_at>|<updated_at>
4d13bcca-bb3f-4536-a2cb-e331bbe099df|system|create_room_booking|room_booking|4dadd37f-1107-458f-a4cf-fb90c167a56c|회의실생성로그|2024-06-15T10:00|\-
```

- 필드 규칙:
  - `log_id`: 고유 식별자
  - `actor`: username 또는 `system`
  - `action`: 공백류를 `_`로 치환한 문자열
  - `target_type`: 공백류를 `_`로 치환한 문자열
  - `target_id`: 관련 식별자
  - `details`: 4.4 사유 규칙 준수
  - `created_at`, `updated_at`: 날짜+시간 또는 `\-`

### 5.7 운영 시점 파일

- 경로: `data/system_clock.txt`
- 형식:

```text
<current_time>
0000-00-00T00:00
```

- 필드 규칙:
  - `current_time` 허용값:
    - 초기 상태 `0000-00-00T00:00`
    - 또는 `YYYY-MM-DDTHH:MM`
  - 저장 가능한 시간 부분은 `09:00`, `18:00`만 허용

### 5.8 무결성 확인

- 필수 데이터 파일이 없으면 프로그램 시작 시 생성한다.
- 데이터 파일 문법이 깨졌으면 오류 메시지 출력 후 즉시 종료한다.
- 데이터 파일 생성 또는 읽기/쓰기에 필요한 권한이 없으면 오류 메시지 출력 후 즉시 종료한다.

### 5.9 범위 외 구현 메모

- 문의/신고 서브시스템은 제거되었으며 현재 저장소 범위에 포함되지 않는다.
- 별도 요구가 없는 한, 본 문서는 핵심 예약/장비/패널티/운영 시점 기능을 우선 범위로 삼는다.

## 6. 상태 모델

### 6.1 회의실 예약 상태

- `reserved`
- `checkin_requested`
- `checked_in`
- `checkout_requested`
- `completed`
- `cancelled`
- `admin_cancelled`

### 6.2 장비 예약 상태

- `reserved`
- `pickup_requested`
- `checked_out`
- `return_requested`
- `returned`
- `cancelled`
- `admin_cancelled`

### 6.3 상태 전이

#### 회의실

- 생성: `reserved`
- 사용자 체크인 요청: `reserved -> checkin_requested`
- 관리자 체크인 승인: `checkin_requested -> checked_in`
- 사용자 퇴실 신청: `checked_in -> checkout_requested`
- 관리자 퇴실 승인: `checkout_requested -> completed`
- 관리자 지연 종료 처리: `checked_in -> completed`
- 사용자 취소: `reserved -> cancelled`
- 관리자 취소: `reserved -> admin_cancelled`

#### 장비

- 생성: `reserved`
- 사용자 픽업 요청: `reserved -> pickup_requested`
- 관리자 대여 승인: `pickup_requested -> checked_out`
- 사용자 반납 신청: `checked_out -> return_requested`
- 관리자 반납 승인: `return_requested -> returned`
- 관리자 지연 종료 처리: `checked_out -> returned`
- 사용자 취소: `reserved -> cancelled`
- 관리자 취소: `reserved -> admin_cancelled`

### 6.4 상태 기록 필드

#### 회의실 예약

| 상태 전이 | 기록 필드 |
| --- | --- |
| 생성 | `created_at`, `updated_at` |
| `reserved -> checkin_requested` | `requested_checkin_at`, `updated_at` |
| `checkin_requested -> checked_in` | `checked_in_at`, `updated_at` |
| `checked_in -> checkout_requested` | `requested_checkout_at`, `updated_at` |
| `checkout_requested -> completed` | `completed_at`, `updated_at` |
| `reserved -> cancelled` | `cancelled_at`, `updated_at` |

#### 장비 예약

| 상태 전이 | 기록 필드 |
| --- | --- |
| 생성 | `created_at`, `updated_at` |
| `reserved -> pickup_requested` | `requested_pickup_at`, `updated_at` |
| `pickup_requested -> checked_out` | `checked_out_at`, `updated_at` |
| `checked_out -> return_requested` | `requested_return_at`, `updated_at` |
| `return_requested -> returned` | `returned_at`, `updated_at` |
| `reserved -> cancelled` | `cancelled_at`, `updated_at` |

## 7. 예약 및 자원 정책

### 7.1 예약 공통 규칙

- 예약은 날짜 범위 기반으로 입력한다.
- 실제 이용 시간은 매일 `09:00 ~ 18:00`으로 고정한다.
- 예약 시작일은 내일부터 가능하다.
- 시작일은 현재 날짜 기준 최대 180일 이내여야 한다.
- 예약 기간은 1일 이상 14일 이하이다.
- 정상 사용자의 활성 예약 한도는 회의실 1건, 장비 1건이다.
- 제한 사용자(`restricted`)는 전체 활성 예약 1건만 허용한다.
- 이용금지 사용자(`banned`)는 신규 예약 불가다.

### 7.2 회의실 규칙

- 회의실 예약 시 이용 인원을 입력받는다.
- 이용 인원은 `1..8` 정수만 허용한다.
- 예약 가능한 회의실은 다음 조건을 모두 만족해야 한다.
  - 상태가 `available`
  - 수용 인원이 입력 인원 이상
  - 해당 기간에 활성 예약 충돌이 없음
- 더 작은 수용 인원의 회의실이 가능한 경우 더 큰 회의실 선택을 제한한다.

### 7.3 장비 규칙

- 장비는 `asset_type`별 목록을 먼저 고른 뒤 개별 자산을 선택한다.
- 예약 가능한 장비는 다음 조건을 모두 만족해야 한다.
  - 상태가 `available`
  - 해당 기간에 활성 예약 충돌이 없음

### 7.4 자원 상태 변경

- 자원 상태는 `available`, `maintenance`, `disabled`다.
- `maintenance` 또는 `disabled` 상태인 자원은 신규 예약이 불가하다.
- 자원 상태가 `maintenance` 또는 `disabled`로 바뀌면 미래 예약은 `admin_cancelled` 처리한다.
- 시스템 사유 취소에는 사용자 패널티를 부여하지 않는다.

### 7.5 점검중/사용불가 자동 복귀 규칙

이 절은 최종 계획서 기준으로 유지한다.

- 회의실:
  - 유저의 기존 예약일 기준 마지막 예약일 다음 날 09:00에 상태가 `maintenance` 또는 `disabled`였다면 시스템이 자동으로 `available`로 변경한다.
  - 관리자는 점검 기간인 `18:00 ~ 다음날 09:00` 안에 문제를 해결해야 한다.
  - 관리자는 18:00에 회의실 상태를 `maintenance`로 변경할 수 있다.
- 장비:
  - 유저의 기존 예약일 기준 마지막 예약일 다음 날 09:00에 상태가 `maintenance` 또는 `disabled`였다면 시스템이 자동으로 `available`로 변경한다.
  - 관리자는 점검 기간인 `18:00 ~ 다음날 09:00` 안에 문제를 해결해야 한다.
  - 관리자는 18:00에 장비 상태를 `maintenance`로 변경할 수 있다.

## 8. 패널티 및 이용 제한

### 8.1 패널티 종류

- 직전 취소: `+2`
- 지연 퇴실/반납: `+2`
- 파손/오염: `1..5`

### 8.2 패널티 상태 기준

- `< 3점`: 정상
- `3점 이상 6점 미만`: 제한
- `6점 이상`: 이용금지

### 8.3 제한 효과

- 제한 상태: 향후 7일간 전체 활성 예약 1건만 허용
- 이용금지 상태: 향후 30일간 신규 예약 불가, 미래 예약 자동 취소

### 8.4 정상 이용 보상

- 정상 이용 10회를 연속 달성하면 패널티 점수 1점을 차감한다.
- 차감 후 연속 횟수는 0으로 초기화한다.

### 8.5 패널티 초기화

- 마지막 패널티 발생일로부터 90일이 지나면 누적 점수를 초기화한다.

## 9. 운영 시계와 자동 처리

### 9.1 시작/종료 cutoff

- 시작 cutoff: `10:00`
- 종료 cutoff: `19:00`

### 9.2 시점 전환 기준

- 시작 경계 `09:00`:
  - 사용자는 체크인 요청 또는 픽업 요청을 남긴다.
  - 관리자는 이를 승인해 실제 이용 상태로 전환한다.
- 종료 경계 `18:00`:
  - 사용자는 퇴실 신청 또는 반납 신청을 남긴다.
  - 관리자는 이를 승인해 종료한다.

### 9.3 미처리 건 처리

- 시작 요청이 없는 예약은 cutoff 이후 관리자가 노쇼 처리한다.
- 종료 요청이 없는 진행 중 예약은 cutoff 이후 관리자가 지연 종료 처리한다.
- 관리자 승인 및 퇴실 처리 규칙:
  - 관리자는 유저의 체크인/픽업 요청을 09:00에, 퇴실/반납 요청을 18:00에 처리해야 한다.
  - 다만 처리 시점을 넘겼고, 관리자가 시점 변경을 진행한 경우 시스템이 자동 승인 처리한다.

### 9.4 자동 점검 루틴

- 다음 시점에서 정책 점검 루틴을 수행한다.
  - 프로그램 시작 시
  - 로그인 직후
  - 예약 생성/변경/취소 직전
  - 관리자 예약 관리 메뉴 진입 시
- 점검 루틴 작업:
  - 90일 경과 패널티 초기화
  - 제한 기간 만료 반영
  - 6점 이상 사용자 미래 예약 자동 취소

## 10. 메뉴 구조

### 10.1 게스트 메뉴

- 로그인
- 회원가입
- 운영 시계 조회
- 종료

### 10.2 유저 메뉴

- 1 회의실 목록 조회
- 2 회의실 예약하기
- 3 내 회의실 예약 조회
- 4 회의실 예약 변경
- 5 회의실 예약 취소
- 6 회의실 입실 신청
- 7 회의실 퇴실 신청
- 8 장비 목록 조회
- 9 장비 예약하기
- 10 내 장비 예약 조회
- 11 장비 예약 변경
- 12 장비 예약 취소
- 13 장비 픽업 신청
- 14 장비 반납 신청
- 15 유저 정보 조회
- 16 운영 시계
- 0 로그아웃

### 10.3 관리자 메뉴

- 1 전체 회의실 예약 조회
- 2 회의실 목록 조회 및 상태 변경
- 3 회의실 체크인 승인 처리
- 4 회의실 퇴실 승인 처리
- 5 회의실 예약 변경
- 6 회의실 예약 취소
- 7 전체 장비 예약 조회
- 8 장비 목록 조회 및 상태 변경
- 9 장비 대여 승인 처리
- 10 장비 반납 승인 처리
- 11 장비 예약 변경
- 12 장비 예약 취소
- 13 사용자 목록
- 14 사용자 상세 조회
- 15 파손/오염 패널티 부여
- 16 회의실 퇴실 지연 처리
- 17 장비 반납 지연 처리
- 18 예약 직전 취소 처리
- 19 운영 시계
- 0 로그아웃

## 11. 기능 상세 규칙

### 11.1 회원가입

- `username`, `password`, `password 확인`을 입력받는다.
- 아이디와 비밀번호는 4절 규칙을 만족해야 한다.
- 비밀번호 확인이 일치해야 한다.

### 11.2 로그인

- 저장된 `username`, `password`와 정확히 일치해야 한다.
- 불일치 시 로그인 실패 메시지를 출력한다.

### 11.3 회의실 예약하기

- 입력 순서:
  - 이용 인원
  - 시작일
  - 종료일
  - 회의실 선택
- 예약 성공 시 `room_bookings.txt`에 새 레코드를 추가한다.
- 초기 상태는 `reserved`다.

### 11.4 회의실 예약 변경

- 본인 소유 `reserved` 상태 예약만 변경 가능
- 회의실 자체는 변경하지 않고 날짜만 변경
- 새 날짜가 기존과 동일하면 실패
- 새 날짜가 충돌하면 실패

### 11.5 회의실 예약 취소

- 본인 소유 `reserved` 상태 예약만 취소 가능
- 시작 시각과 같은 날 09:00 취소는 직전 취소 패널티 대상
- 취소 시 `cancelled_at`, `updated_at` 기록

### 11.6 회의실 체크인 요청

- 본인 소유 `reserved` 상태 예약만 가능
- 현재 운영 시점이 예약 시작 시각과 정확히 같아야 한다
- 성공 시 `checkin_requested`

### 11.7 회의실 퇴실 신청

- 본인 소유 `checked_in` 상태 예약만 가능
- 성공 시 `checkout_requested`

### 11.8 장비 예약하기

- 장비 종류 선택 후 개별 자산 선택
- 성공 시 `equipment_booking.txt`에 새 레코드를 추가한다.
- 초기 상태는 `reserved`다.

### 11.9 장비 예약 변경

- 본인 소유 `reserved` 상태 예약만 변경 가능
- 개별 장비 자체는 유지하고 날짜만 변경한다.

### 11.10 장비 예약 취소

- 본인 소유 `reserved` 상태 예약만 취소 가능
- 직전 취소 시 패널티 부여

### 11.11 장비 픽업 요청

- 본인 소유 `reserved` 상태 예약만 가능
- 현재 운영 시점이 예약 시작 시각과 정확히 같아야 한다
- 성공 시 `pickup_requested`

### 11.12 장비 반납 신청

- 본인 소유 `checked_out` 상태 예약만 가능
- 성공 시 `return_requested`

### 11.13 관리자 체크인/픽업 승인

- 각각 `checkin_requested`, `pickup_requested` 상태만 승인 가능
- 승인 시 실제 이용 상태로 전이한다.

### 11.14 관리자 퇴실/반납 승인

- 각각 `checkout_requested`, `return_requested` 상태만 승인 가능
- 승인 시 종료 상태로 전이한다.

### 11.15 관리자 상태 변경

- 회의실/장비 상태를 `available`, `maintenance`, `disabled`로 변경한다.
- `maintenance` 또는 `disabled`로 변경 시 미래 예약 자동 취소 경고를 먼저 출력한다.

### 11.16 관리자 예약 변경/취소

- 미래 예약만 대상으로 한다.
- 취소 사유 입력 가능
- 시스템 사유 취소에는 사용자 패널티를 부여하지 않는다.

## 12. 에러 처리 기준

- 형식 오류는 가능한 한 즉시 감지하고 재입력 기회를 제공한다.
- 의미 규칙 위반은 해당 작업을 실패 처리하고 안내 메시지를 출력한다.
- 필수 파일 생성 실패, 파일 권한 부족, 데이터 파일 문법 파손은 즉시 종료 사유가 된다.

## 13. 코딩 에이전트 구현 메모

- 본 문서는 구현 우선순위가 높은 규칙만 남기고 스크린샷/장문 예시는 제거한 버전이다.
- 구현 시 가장 먼저 맞춰야 할 축은 다음 네 가지다.
  - 데이터 파일 포맷
  - 상태 전이와 기록 필드
  - 운영 시점과 자동 처리
  - 메뉴별 입력 검증과 권한 규칙
- 문서에 없는 저장소 내부 보조 구조는 자유롭게 둘 수 있으나, 외부 동작과 파일 포맷은 본 문서를 따라야 한다.
