# 공유 오피스 CLI 프로그램 동시성 및 상태 처리 설계안

## Summary
- 저장소는 `여러 JSON Lines .txt 파일`을 사용하되, 쓰기 작업은 모두 `전역 락 1개` 아래에서 처리한다.
- 상태 설계는 `최소 상태만 저장`하고, `점유 중/제재 중/예약 가능 여부` 같은 값은 가능한 한 예약 데이터와 시각 정보로 계산한다.
- 사용자 예약은 `reserved 상태일 때만` 변경/취소 가능하고, 관리자는 `미래 예약만` 시간 변경 가능하다. 진행 중이거나 종료된 예약은 상태 처리만 수행한다.

## Concurrency
- 잠금 전략
  - `data/.lock` 같은 전역 잠금 파일 1개를 둔다.
  - 예약 생성, 예약 변경, 예약 취소, 체크인/반납, 패널티 부여, 자원 상태 변경, 자동 정책 점검은 모두 전역 락을 잡고 수행한다.
  - 단순 조회는 락 없이 읽되, 쓰기 직전에는 반드시 최신 파일을 다시 읽어 검증한다.
- 쓰기 절차
  - 전역 락 획득
  - 관련 txt 파일 전체 로드
  - 메모리에서 정책 검증 및 수정
  - 각 파일을 `*.tmp`에 저장
  - 검증 완료 후 원본 파일로 원자적 교체
  - 감사 로그까지 저장한 뒤 락 해제
- 충돌 처리
  - 같은 자원에 대해 동시 예약이 들어오면, 먼저 락을 잡은 요청만 성공한다.
  - 뒤늦게 들어온 요청은 최신 상태 재검증에서 충돌을 감지하고 `즉시 실패` 처리한다.
  - 사용자에게는 “방금 다른 사용자가 먼저 예약함, 목록을 다시 조회하라”는 메시지를 보여준다.
- 자동 정책 점검
  - 앱 시작, 로그인 직후, 예약 관련 작업 직전, 관리자 예약 관리 메뉴 진입 시 실행한다.
  - 점검도 일반 쓰기 작업과 동일하게 전역 락 아래에서 수행한다.
  - 노쇼 판정, 90일 초기화, 6점 이상 사용자 미래 예약 취소, 제재 종료 반영을 담당한다.

## State Model
- 사용자 데이터
  - 저장 필드: `role`, `penalty_points`, `normal_use_streak`, `restriction_until`
  - 별도 `user_status`는 저장하지 않는다.
  - 해석 규칙
    - `restriction_until > now`: 이용 제한 중
    - `penalty_points >= 3 and < 6`: 7일간 예약 1건 제한 대상
    - `penalty_points < 3`: 정상 이용
- 회의실 데이터
  - 상태: `available`, `maintenance`, `disabled`
  - `in_use`는 저장하지 않는다. 현재 점유 여부는 `room_bookings.txt`에서 `checked_in` 상태와 현재 시각으로 계산한다.
  - `maintenance` 또는 `disabled`면 신규 예약 불가
  - 해당 상태로 바뀌는 시점에 미래 예약은 자동 취소하고 패널티는 부여하지 않는다.
- 장비 데이터
  - 상태: `available`, `maintenance`, `disabled`
  - `checked_out`는 자산 상태로 저장하지 않는다. 현재 대여 중 여부는 `equipment_bookings.txt`의 `checked_out` 상태로 계산한다.
  - `maintenance` 또는 `disabled`면 신규 예약 불가
  - 상태 변경 시 미래 예약 자동 취소, 패널티 없음
- 회의실 예약 데이터
  - 상태: `reserved`, `checked_in`, `completed`, `cancelled`, `no_show`, `admin_cancelled`
  - 전이 규칙
    - 생성: `reserved`
    - 관리자 체크인: `reserved -> checked_in`
    - 관리자 퇴실 완료: `checked_in -> completed`
    - 사용자 취소: `reserved -> cancelled`
    - 관리자 취소: `reserved -> admin_cancelled`
    - 자동 노쇼 판정: `reserved -> no_show`
  - 변경 가능 범위
    - 사용자: `reserved` 상태만 변경/취소 가능
    - 관리자: 미래 시점의 `reserved` 예약만 시간 변경 가능
    - `checked_in`, `completed`, `no_show`, `cancelled`, `admin_cancelled`는 시간 변경 불가
- 장비 예약 데이터
  - 상태: `reserved`, `checked_out`, `returned`, `cancelled`, `no_show`, `admin_cancelled`
  - 전이 규칙
    - 생성: `reserved`
    - 관리자 대여 시작: `reserved -> checked_out`
    - 관리자 반납 완료: `checked_out -> returned`
    - 사용자 취소: `reserved -> cancelled`
    - 관리자 취소: `reserved -> admin_cancelled`
    - 자동 노쇼 판정: `reserved -> no_show`
  - 변경 가능 범위는 회의실 예약과 동일하게 적용
- 패널티 데이터
  - 상태 필드는 두지 않고 `append-only 이력`으로 저장
  - 필드: `reason`, `points`, `related_type`, `related_id`, `created_at`, `memo`
  - 사용자 총점은 매번 합산하거나, 사용자 파일의 누적 점수와 함께 동기화한다
- 감사 로그
  - 상태 없음, `append-only`
  - 관리자 조작과 자동 정책 처리를 모두 남긴다

## State Processing Rules
- 노쇼
  - 예약 시작 후 15분이 지났는데 회의실은 `checked_in`, 장비는 `checked_out`이 아니면 `no_show`
  - 즉시 `+3점`
- 직전 취소
  - 예약 시작 1시간 이내에 사용자가 `reserved -> cancelled` 하면 `+2점`
  - 관리자 취소나 시스템 취소는 패널티 없음
- 지연 퇴실/반납
  - 완료 처리 시 실제 완료 시각이 예약 종료 시각보다 늦으면 `ceil(지연 분 / 10)`점 부여
  - 상태는 별도 `overdue`를 두지 않고 완료 시점에 계산
- 파손/오염
  - 관리자 입력으로만 부여
  - 상태값 추가 없이 패널티 이력에 기록, `1~5점`
- 이용 제한
  - `3점 이상 6점 미만`: 7일간 전체 활성 예약 1건만 허용
  - `6점 이상`: 30일간 이용 불가, 미래 예약 자동 취소
  - 마지막 패널티 발생일로부터 90일 경과 시 점수 초기화
  - 정상 이용 10회 연속이면 완료 시점에 `1점 차감`
- 시스템 사유 취소
  - 회의실/장비가 `maintenance` 또는 `disabled`로 바뀌면 관련 미래 예약을 `admin_cancelled`로 바꾸고 로그 남김
  - 사용자 패널티는 부여하지 않음

## Test Plan
- 두 인스턴스가 동시에 같은 회의실 또는 같은 장비를 예약할 때 한쪽만 성공하는지 확인
- 예약 생성 중 프로그램이 중단되어도 원본 txt가 손상되지 않는지 확인
- 회의실/장비 상태 변경 시 미래 예약 자동 취소와 무패널티 처리 확인
- `reserved` 상태에서만 사용자 변경/취소가 가능한지 확인
- 진행 중이거나 종료된 예약은 관리자도 시간 변경이 막히는지 확인
- 노쇼, 직전 취소, 지연 반납, 파손/오염 점수 반영 확인
- 3점 구간의 예약 1건 제한과 6점 구간의 30일 제한 확인
- 90일 초기화와 정상 이용 10회 감점 확인

## Assumptions
- 사용자 계정은 별도 `inactive` 상태를 두지 않고 항상 활성 계정으로 본다.
- 점유 중 상태는 회의실/장비 자체 상태에 저장하지 않고 예약 상태에서 계산한다.
- 시스템 취소는 모두 사용자 책임이 아닌 것으로 처리한다.
- 현재 범위에서는 `deleted`, `archived`, `overdue` 같은 추가 상태는 두지 않는다.
