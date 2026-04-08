# Cleanup Follow-up Ledger

이번 cleanup 패스에서 **직접 수정하지 않은** 애매한 항목과 동작 차이를 정리한다.

## Ambiguous final_plan mismatches

### 1) 체크인/픽업 요청 목록 노출 조건이 실제 요청 가능 시점보다 넓음
- path / area: `src/cli/user_menu.py:382-423`, `src/cli/user_menu.py:730-760`
- evidence summary:
  - CLI는 `reserved` 상태 예약을 모두 요청 후보로 노출한다.
  - 실제 서비스 게이트는 정확한 운영 시점 일치를 요구한다: `src/domain/room_service.py:147-163`, `src/domain/equipment_service.py:142-158`
- final_plan anchor:
  - `final_plan.md` §6.5.1.6 회의실 입실 신청
  - `final_plan.md` §6.5.2.6 장비 픽업 신청
- why the item is ambiguous or deferred:
  - 목록 노출 자체를 현재 시점 기준으로 더 좁혀야 하는지, 아니면 선택 후 에러 메시지로 처리하는 UX가 허용되는지 해석 여지가 있다.
- recommended next action:
  - 별도 spec-alignment 패스에서 메뉴 노출 조건과 서비스 게이트를 함께 검토한다.

### 2) 요청 cutoff 상수(10/19시)가 이산 운영 시점(09/18시) 모델과 중첩됨
- path / area: `src/config.py:34-39`, `src/domain/room_service.py:147-163`, `src/domain/equipment_service.py:142-158`
- evidence summary:
  - 운영 시계는 09:00 / 18:00 두 시점만 허용한다.
  - 요청 게이트는 추가로 `START_REQUEST_CUTOFF_HOUR = 10`, `END_REQUEST_CUTOFF_HOUR = 19`를 검사한다.
- final_plan anchor:
  - `final_plan.md` §6.3.1.2 시점 구성
  - `final_plan.md` §6.3.1.3 시점 진행 방식
  - `final_plan.md` §6.5.1.6 / §6.5.1.7
  - `final_plan.md` §6.5.2.6 / §6.5.2.7
- why the item is ambiguous or deferred:
  - 현재 구현에서는 “정확한 시점 일치”가 이미 더 강한 제약이라 cutoff 상수가 사실상 중복처럼 보이지만, 메시지/정책 설명을 위해 남겨둔 것일 수도 있다.
- recommended next action:
  - 운영 시계/정책 semantics만 따로 검토하는 후속 계획을 만든다.

### 3) 직접 관리자 완료 헬퍼가 요청-승인 흐름과 병존함
- path / area: `src/domain/room_service.py:748-786`, `src/domain/equipment_service.py:742-786`
- evidence summary:
  - `check_out()` / `return_equipment()`는 직접 완료 경로를 제공한다.
  - 최종 명세는 사용자 요청 후 관리자 승인 흐름을 중심으로 서술한다.
- final_plan anchor:
  - `final_plan.md` §6.6.1.4 회의실 퇴실 승인 처리
  - `final_plan.md` §6.6.2.4 장비 반납 승인 처리
- why the item is ambiguous or deferred:
  - 테스트와 현재 서비스 구조에서 실제로 사용 중이며, 제거하면 동작 의미가 달라질 수 있다.
- recommended next action:
  - 유지/통합/제거 중 어느 방향이 맞는지 별도 합의 후 조정한다.

## Deferred behavior differences

### 1) 지연 처리 로그의 “분 단위 지연” 의미
- path / area: `src/domain/room_service.py:788-829`, `src/domain/equipment_service.py:788-830`
- evidence summary:
  - 지연 퇴실/반납 처리에서 `delay_minutes`를 계산하고 감사 로그에 남긴다.
  - 현 패스에서는 동작을 건드리지 않고 보존했다.
- final_plan anchor:
  - `final_plan.md` §6.6.3.5 회의실 퇴실 지연 처리
  - `final_plan.md` §6.6.3.6 장비 반납 지연 처리
- why the item is ambiguous or deferred:
  - 로그 의미만 정리해도 되는지, 계산 자체를 바꿔야 하는지 판단하려면 정책 재해석이 필요하다.
- recommended next action:
  - 패널티/감사 로그 의미를 함께 검토하는 후속 spec-alignment 작업으로 넘긴다.

## Legacy reference candidates

### 1) 샘플 데이터의 과거 no-show/15분 문구
- path / area: `data/audit_log.txt`, `data/penalties.txt`
- evidence summary:
  - 저장 데이터에 과거 자동 노쇼/15분 문구가 남아 있을 가능성이 있다.
  - 이번 패스는 실행 데이터 의미를 바꾸지 않기 위해 건드리지 않았다.
- final_plan anchor:
  - `final_plan.md` §5.5 패널티 파일
  - `final_plan.md` §5.6 감사 로그 파일
- why the item is ambiguous or deferred:
  - 샘플 데이터 정리인지, 테스트 fixture/기준 데이터 갱신인지 범위 판단이 필요하다.
- recommended next action:
  - 데이터 파일 정리 여부를 별도 결정한다.

## Rejected deletion candidates

### 1) `src/domain/room_service.py:748-786` `check_out`
- evidence summary:
  - `rg` 기준 서비스/테스트 참조가 존재한다.
- why kept:
  - 현재 동작 경로와 테스트에서 사용 중이라 “확실한 미사용”이 아니다.

### 2) `src/domain/equipment_service.py:742-786` `return_equipment`
- evidence summary:
  - `rg` 기준 서비스/테스트 참조가 존재한다.
- why kept:
  - 현재 동작 경로와 테스트에서 사용 중이라 “확실한 미사용”이 아니다.
