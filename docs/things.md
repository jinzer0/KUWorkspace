# PLAN 감사 노트

## 확인된 불일치

### 1. 지연 종료 패널티 점수는 고정이지만, 지연 분 단위 계산 흔적이 여전히 남아 있음
- `docs/PLAN.md:210`-`docs/PLAN.md:214`는 cutoff 경과 후 지연 퇴실/반납에 대해 고정 `+2` 패널티를 정의합니다.
- 현재 코드의 패널티 점수는 실제로 고정값입니다.
  - `src/domain/penalty_service.py:179`-`src/domain/penalty_service.py:202`는 항상 `LATE_RETURN_PENALTY`를 사용합니다.
- 그러나 지연 종료 처리 서비스는 여전히 분 단위 지연 정보를 계산하고 기록합니다.
  - `src/domain/room_service.py:789`-`src/domain/room_service.py:821`
  - `src/domain/equipment_service.py:794`-`src/domain/equipment_service.py:825`
- 또한 계산된 지연이 `<= 0`이면 `delay_minutes = 60`으로 강제하는데, 이 규칙은 `PLAN.md`에 명시되어 있지 않습니다.
- 결론: 패널티 점수는 PLAN과 일치하지만, 주변 의미와 로그에는 구(legacy) 분 단위 모델의 흔적이 남아 있습니다.

### 2. 요청 메뉴가 실제 요청 가능성 대신 상태값만으로 대상을 노출함
- `src/cli/user_menu.py:388`-`src/cli/user_menu.py:413`는 `reserved` 상태인 회의실 예약을 체크인 요청 대상으로 일괄 표시합니다.
- 실제 서비스 게이트는 더 엄격합니다. `src/domain/room_service.py:719`의 `_require_start_request_window()`가 허용 시간 밖 요청을 차단합니다.
- 즉, CLI에서 선택 가능한 항목처럼 보이더라도 실제 요청 시점에 실패할 수 있습니다.
- 같은 패턴이 장비 픽업/반납 메뉴에도 있는지 후속 점검이 필요합니다.

### 3. 저장소 산출물에 과거 15분 자동 노쇼 정책 흔적이 남아 있음
- 현재 기준 계획은 노쇼 자동 확정을 하지 않고, cutoff 기반 수동 관리자 처리 모델입니다: `docs/PLAN.md:202`-`docs/PLAN.md:206`, `docs/PLAN.md:239`.
- 그러나 런타임/샘플 데이터에는 과거 자동 노쇼 흔적이 있습니다.
  - `data/audit_log.txt`에 `auto_no_show_room` / `auto_no_show_equipment` 항목 존재
  - `data/penalties.txt`에 `예약 시작 후 15분 내 미출석` 메모 존재
- 과거에는 `tests/unit/test_models.py`의 audit-log roundtrip 예시도 `action="auto_no_show"`를 사용했지만, cleanup 패스에서 중립 샘플값으로 정리했습니다.
- 결론: 실행 데이터 샘플에는 아직 pre-PLAN 노쇼 모델 흔적이 남아 있어 개발자/독자를 혼동시킬 수 있습니다.

### 4. 코드 주석/테스트에 `PLAN2.md` 참조가 남아 있음
- cleanup 패스 전에는 `tests/e2e/test_admin_scenarios.py`, `src/storage/repositories.py`, `src/storage/atomic_writer.py`에 `PLAN2.md` 참조가 남아 있었습니다.
- 해당 주석/테스트 wording은 정리했지만, 관련 감사 노트와 데이터 산출물의 legacy 흔적은 여전히 추적 대상입니다.
- 결론: 소스 코드 내부의 직접 참조는 줄었지만, 레거시 기준 문서 흔적 자체는 완전히 해소되지 않았습니다.

### 5. `PLAN.md`의 cutoff 워크플로우를 현재 슬롯 시계로는 충실히 표현하기 어려움
- `docs/PLAN.md:107`-`docs/PLAN.md:113`는 시작/종료 cutoff를 각각 `10:00`, `19:00`로 정의합니다.
- `src/runtime_clock.py:4`-`src/runtime_clock.py:25`는 실제 운영 시점을 `09:00`, `18:00`으로만 허용합니다.
- 동시에 요청/지연처리/노쇼 처리 관련 서비스 가드는 정확한 경계 시각 일치를 요구합니다.
  - `src/domain/room_service.py:142`-`src/domain/room_service.py:156`
  - `src/domain/room_service.py:789`-`src/domain/room_service.py:814`
  - `src/domain/room_service.py:910`-`src/domain/room_service.py:938`
  - `src/domain/equipment_service.py:136`-`src/domain/equipment_service.py:159`
  - `src/domain/equipment_service.py:794`-`src/domain/equipment_service.py:817`
  - `src/domain/equipment_service.py:914`-`src/domain/equipment_service.py:942`
- 결론: 이 항목은 단순 문구 애매함이 아니라, PLAN과 구현 사이의 실질적인 충돌입니다.

## 명세의 애매점 / 내부 충돌

### 1. 요청 우선 흐름과 직접 관리자 완료 헬퍼가 공존함
- CLI와 기준 PLAN은 요청-승인 기반 시작/종료 흐름을 설명합니다.
- 반면 서비스에는 직접 관리자 완료 헬퍼가 여전히 존재합니다.
  - `src/domain/room_service.py:737` `check_out()`
  - `src/domain/equipment_service.py:736` `return_equipment()`
- 이 자체가 반드시 잘못은 아니지만, 테스트나 향후 코드 경로에서 요청 우선 라이프사이클을 우회할 가능성을 키웁니다.

### 2. 이산 시계 모델에서 시작 요청 의미가 명확히 고정되어 있지 않음
- `docs/PLAN.md:110`, `docs/PLAN.md:187`은 시작 cutoff 이전 사용자 시작 요청을 허용한다고 기술합니다.
- `src/domain/room_service.py:704`-`src/domain/room_service.py:735`, `src/domain/equipment_service.py:703`-`src/domain/equipment_service.py:734`는 현재 운영 시각으로 요청 가능 창을 강제합니다.
- 현재 슬롯 모델에서는 "cutoff 이전"이 사실상 "시작 슬롯 시점"으로 수렴되지만, PLAN 본문은 이를 명시적으로 못 박지 않습니다.

## 감사 중 확인된 커버리지 공백

### 1. 시작 시점 입력 검증의 명시 테스트가 부족했음
- 초기에는 CLI/bootstrap 계층에서 잘못된 날짜 형식, 잘못된 슬롯, "저장 최신 시각보다 이른 시작 시각" 거절을 명시 검증하는 테스트가 부족했습니다.

### 2. 게스트 운영 시계 read-only 보장이 간접 검증 위주였음
- `src/cli/guest_menu.py:57`-`src/cli/guest_menu.py:60`는 `allow_advance=False`를 넘기지만, 초기에는 guest만 조회 가능함을 강하게 증명하는 acceptance 테스트가 부족했습니다.

### 3. cutoff 이후 부정 케이스 테스트가 부족했음
- 사용자의 시작/종료 요청 불가(후속 시점)와 관리자 지연 종료 처리 정책에 대한 명시 케이스가 보강 필요 상태였습니다.

### 4. 시스템 취소 무패널티 규칙 명시 검증이 필요했음
- PLAN은 자원 상태 변경으로 인한 시스템 취소에 사용자 패널티를 부여하지 않는다고 정의하므로, 이를 명시 회귀 테스트로 고정할 필요가 있었습니다.

## 전체 테스트 스위트 기준선

### 1. 현재 `pytest` 상태
- 최초 감사 기준선: `213 passed, 30 failed`.
- 이후 stale 테스트 정렬, 누락 흐름 보강, 잔여 검증 공백 해소를 거쳐 현재 스위트는 `297 passed, 0 failed`.
- 단, 테스트가 녹색이라는 사실이 PLAN-구현 충돌 자체를 해소했다는 뜻은 아닙니다. 현재 구현 기준과 테스트 기대치가 일관된 상태라는 의미입니다.

### 2. 수동 CLI QA 근거
- `python main.py`를 스크립트 입력으로 실행했습니다.
- 실제 콘솔에서 다음 동작을 확인했습니다.
  - 잘못된 시작 날짜 형식 거절
  - 유효한 시작 슬롯 수용
  - 게스트 read-only 운영 시계 접근
  - 현재/다음 시점 미리보기 출력
  - 정상 종료 확인

### 3. 주요 실패 묶음: 구 direct admin 시작/종료 가정 테스트
- 상태: 테스트에서 해결됨.
- 현재 코드는 요청 상태 선행을 요구합니다.
  - `src/domain/room_service.py:664`-`src/domain/room_service.py:676`: admin 체크인 전 `checkin_requested` 필요
  - `src/domain/equipment_service.py:703`-`src/domain/equipment_service.py:734`: 시작 승인 전 `pickup_requested` 필요
- 과거에는 다수 테스트가 `reserved`에서 곧바로 admin 시작/종료를 호출하고 있었습니다.
  - `tests/unit/test_room_service.py:606`-`tests/unit/test_room_service.py:613`
  - `tests/unit/test_equipment_service.py` checkout/return 테스트
  - `tests/e2e/test_user_scenarios.py:69`-`tests/e2e/test_user_scenarios.py:86`

### 4. 주요 실패 묶음: non-admin 노쇼 헬퍼 가정 테스트
- 상태: 테스트에서 해결됨.
- 현재 코드는 노쇼 처리에 admin 컨텍스트를 요구합니다.
  - `src/domain/room_service.py:896`-`src/domain/room_service.py:903`
  - `src/domain/equipment_service.py:900`-`src/domain/equipment_service.py:907`
- 과거 테스트는 admin/actor 없이 `mark_no_show()`를 호출하고 있었습니다.
  - `tests/unit/test_room_service.py:818`-`tests/unit/test_room_service.py:861`
  - `tests/unit/test_equipment_service.py` no-show 테스트

### 5. 주요 실패 묶음: 분 단위 지연 점수 기대 테스트
- 상태: 테스트에서 해결됨.
- 현재 코드는 고정 `LATE_RETURN_PENALTY`를 반환합니다.
  - `src/domain/penalty_service.py:179`-`src/domain/penalty_service.py:202`
- 과거 테스트는 `ceil(delay/10)` 동작을 기대하고 있었습니다.
  - `tests/unit/test_penalty_service.py:86`-`tests/unit/test_penalty_service.py:136`

### 6. 실패 묶음: blocker 메시지/상태 기대 드리프트
- 상태: 테스트에서 해결됨.
- 현재 코드 blocker 문구는 요청 상태를 포함합니다. 예: `체크인 요청 또는 노쇼`.
- 과거 테스트 일부는 `체크인 또는 노쇼`를 기대하거나 `reserved` 즉시 admin 시작을 가정하고 있었습니다.

## 추가로 정리할 경계 의미

### 1. 직전 취소 경계가 현재 inclusive임
- `src/domain/room_service.py:543`, `src/domain/equipment_service.py:537`는 `<= LATE_CANCEL_THRESHOLD_MINUTES`를 사용합니다.
- 즉, 정확히 `60분 전` 취소도 직전 취소로 처리됩니다.
- 정책 의도가 exclusive(`60분 미만`)라면 코드/테스트 정렬이 필요하고, inclusive 의도라면 일부 문구/테스트를 그 기준으로 고정해야 합니다.

## 런타임 증거 참고 사항

### 1. 현재 샘플 데이터는 정책 드리프트 흔적을 포함함
- `data/audit_log.txt`, `data/penalties.txt`에 과거 `15분`/자동 노쇼 모델 흔적이 남아 있습니다.
- 이 데이터는 현행 `PLAN.md` 정책 구현의 정합성을 증명하는 근거로 단독 사용하면 안 됩니다.

## 후속 검증 작업
- 감사 후 전체 테스트 스위트를 재실행하고 pass/fail 상태를 기록.
- 시작 입력 검증, guest read-only 시계, cutoff 이후 요청 차단, 시스템 취소 무패널티를 테스트로 보강.
- `PLAN2.md` / `auto_no_show` / `15분` 흔적을 legacy로 남길지 제거할지 결정 후 정리.

## 명시적 PLAN 흐름 인벤토리 및 테스트 매핑

### 진입 및 역할 라우팅
- `프로그램 시작 -> 데이터 파일 준비`: `tests/unit/test_config.py::test_ensure_data_dir_creates_all_data_files`로 검증.
- `운영 시작 시점 입력`의 날짜/슬롯/최신 데이터 검증: `tests/unit/test_main.py::test_prompt_initial_clock_retries_on_invalid_date`, `tests/unit/test_main.py::test_prompt_initial_clock_retries_on_invalid_slot`, `tests/unit/test_main.py::test_prompt_initial_clock_retries_when_earlier_than_latest_data`로 검증.
- `로그인 성공 -> 역할별 메뉴 분기 -> 로그아웃 -> 게스트 메뉴 복귀`: `tests/unit/test_main.py::test_main_routes_user_to_user_menu_and_returns_to_guest`, `tests/unit/test_main.py::test_main_routes_admin_to_admin_menu`로 검증.

### 게스트 흐름
- `로그인`: `tests/e2e/test_user_scenarios.py::TestUserSignupLoginFlow::test_signup_and_login_flow`, `tests/e2e/test_user_scenarios.py::TestUserSignupLoginFlow::test_signup_duplicate_then_login`, `tests/unit/test_auth_service.py::TestLogin::*`, `tests/unit/test_menu_policy_errors.py::TestGuestMenuPolicyChecks::test_login_handles_penalty_error_from_status_lookup`로 검증.
- `회원가입`: `tests/unit/test_auth_service.py::TestSignup::*`, `tests/unit/test_guest_menu_clock.py::test_guest_menu_signup_creates_user`로 검증.
- `운영 시계 조회만 가능`: `tests/unit/test_guest_menu_clock.py::test_guest_menu_opens_clock_in_read_only_mode`, `tests/unit/test_guest_menu_clock.py::test_clock_menu_read_only_mode_shows_blockers_instead_of_advancing`로 검증.
- `종료`: `tests/unit/test_guest_menu_clock.py::test_guest_menu_exit_returns_none_when_confirmed`로 검증.

### 사용자 흐름
- `사용자 메뉴에서 각 액션으로 분기`: `tests/unit/test_menu_dispatch.py::test_user_menu_dispatches_actions`, `tests/unit/test_menu_dispatch.py::test_user_menu_opens_clock_with_user_actor`로 검증.
- `회의실 목록 조회`: `tests/unit/test_menu_dispatch.py::test_user_menu_dispatches_actions[1-_show_rooms]`로 검증.
- `회의실 예약`: `tests/e2e/test_user_scenarios.py::TestBookingCompleteFlow::test_room_booking_complete_flow`, `tests/unit/test_room_service.py::TestCreateBooking::*`, `tests/unit/test_daily_booking_flow.py::test_room_daily_booking_success`로 검증.
- `회의실 예약 변경`: `tests/e2e/test_user_scenarios.py::TestBookingModificationFlow::test_modify_booking_flow`, `tests/unit/test_room_service.py::TestModifyBooking::*`로 검증.
- `회의실 예약 취소`: `tests/e2e/test_user_scenarios.py::TestBookingModificationFlow::test_cancel_booking_normal_flow`, `tests/unit/test_room_service.py::TestCancelBooking::*`로 검증.
- `내 회의실 예약 조회`: `tests/unit/test_menu_dispatch.py::test_user_menu_dispatches_actions[3-_show_my_room_bookings]`, `tests/unit/test_room_service.py::TestBookingQueries::*`, `tests/unit/test_user_menu.py::TestUserMenuRefresh::test_show_my_room_bookings_returns_early_when_refresh_fails`로 검증.
- `회의실 체크인 요청`: `tests/e2e/test_user_scenarios.py::TestBookingCompleteFlow::test_room_booking_complete_flow`, `tests/unit/test_room_service.py::TestAuditLogging::test_request_room_checkin_logs_audit_action`로 검증.
- `회의실 퇴실 신청`: `tests/e2e/test_user_scenarios.py::TestBookingCompleteFlow::test_room_booking_complete_flow`, `tests/unit/test_daily_booking_flow.py::test_room_checkout_request_and_approval_completes_without_delay_penalty`로 검증.
- `장비 목록 조회`: `tests/unit/test_menu_dispatch.py::test_user_menu_dispatches_actions[8-_show_equipment]`로 검증.
- `장비 예약`: `tests/e2e/test_user_scenarios.py::TestBookingCompleteFlow::test_equipment_booking_complete_flow`, `tests/unit/test_equipment_service.py::TestCreateEquipmentBooking::*`, `tests/unit/test_daily_booking_flow.py::test_policy_allows_one_room_and_one_equipment_separately`로 검증.
- `장비 예약 변경`: `tests/unit/test_equipment_service.py::TestModifyEquipmentBooking::*`로 검증.
- `장비 예약 취소`: `tests/unit/test_equipment_service.py::TestCancelEquipmentBooking::*`로 검증.
- `내 장비 예약 조회`: `tests/unit/test_menu_dispatch.py::test_user_menu_dispatches_actions[10-_show_my_equipment_bookings]`, `tests/unit/test_equipment_service.py::TestEquipmentBookingQueries::*`로 검증.
- `장비 픽업 요청`: `tests/e2e/test_user_scenarios.py::TestBookingCompleteFlow::test_equipment_booking_complete_flow`로 검증.
- `장비 반납 신청`: `tests/e2e/test_user_scenarios.py::TestBookingCompleteFlow::test_equipment_booking_complete_flow`, `tests/unit/test_daily_booking_flow.py::test_equipment_return_request_and_approval_completes_without_delay_penalty`로 검증.
- `내 상태 조회`: `tests/unit/test_menu_dispatch.py::test_user_menu_dispatches_actions[15-_show_my_status]`, `tests/unit/test_user_menu.py::TestUserMenuRefresh::test_show_my_status_handles_query_error_after_refresh`, `tests/unit/test_penalty_service.py::TestUserStatus::*`로 검증.
- `운영 시계 접근 및 실제 이동 가능`: `tests/unit/test_menu_dispatch.py::test_user_menu_opens_clock_with_user_actor`, `tests/unit/test_policy_service.py::TestClockAdvance::test_advance_time_moves_clock_and_logs_event`로 검증.
- `로그아웃`: `tests/unit/test_main.py::test_main_routes_user_to_user_menu_and_returns_to_guest`, `tests/unit/test_menu_dispatch.py`의 `0` 종료 경로로 검증.
- `메뉴 진입 전/주요 작업 직전 정책 점검`: `tests/unit/test_menu_policy_errors.py`, `tests/unit/test_user_menu.py::TestUserMenuRefresh::test_run_returns_true_when_status_lookup_fails_after_refresh`, 그리고 액션 시점 정책 게이트를 검증하는 서비스 테스트로 확인.

### 관리자 흐름
- `관리자 메뉴에서 각 액션으로 분기`: `tests/unit/test_menu_dispatch.py::test_admin_menu_dispatches_actions`, `tests/unit/test_menu_dispatch.py::test_admin_menu_opens_clock_with_admin_actor`로 검증.
- `유저 목록 및 상태 조회`: `tests/e2e/test_admin_scenarios.py::TestAdminUserManagement::*`, `tests/unit/test_menu_dispatch.py::test_admin_menu_dispatches_actions[15-_show_users]`, `tests/unit/test_menu_dispatch.py::test_admin_menu_dispatches_actions[16-_show_user_detail]`로 검증.
- `회의실 목록 조회`: `tests/unit/test_menu_dispatch.py::test_admin_menu_dispatches_actions[1-_show_rooms]`로 검증.
- `장비 목록 조회`: `tests/unit/test_menu_dispatch.py::test_admin_menu_dispatches_actions[8-_show_equipment]`로 검증.
- `전체 회의실 예약 조회`: `tests/unit/test_menu_dispatch.py::test_admin_menu_dispatches_actions[3-_show_all_room_bookings]`로 검증.
- `전체 장비 예약 조회`: `tests/unit/test_menu_dispatch.py::test_admin_menu_dispatches_actions[10-_show_all_equipment_bookings]`로 검증.
- `미래 예약 변경/취소`: `tests/e2e/test_admin_scenarios.py::TestAdminBookingCancellation::*`, `tests/e2e/test_admin_scenarios.py::TestAdminModifyBooking::test_admin_modifies_user_booking`, `tests/unit/test_room_service.py::TestAdminFunctions::*`, `tests/unit/test_equipment_service.py::TestAdminEquipmentFunctions::*`로 검증.
- `회의실 체크인 승인`: `tests/e2e/test_user_scenarios.py::TestBookingCompleteFlow::test_room_booking_complete_flow`, `tests/unit/test_room_service.py::TestCheckInOut::*`로 검증.
- `장비 대여 시작 승인`: `tests/e2e/test_user_scenarios.py::TestBookingCompleteFlow::test_equipment_booking_complete_flow`, `tests/unit/test_equipment_service.py::TestCheckoutReturn::*`로 검증.
- `회의실 퇴실 승인`: `tests/e2e/test_user_scenarios.py::TestBookingCompleteFlow::test_room_booking_complete_flow`, `tests/unit/test_daily_booking_flow.py::test_room_checkout_request_and_approval_completes_without_delay_penalty`로 검증.
- `장비 반납 승인`: `tests/e2e/test_user_scenarios.py::TestBookingCompleteFlow::test_equipment_booking_complete_flow`, `tests/unit/test_daily_booking_flow.py::test_equipment_return_request_and_approval_completes_without_delay_penalty`로 검증.
- `회의실 노쇼 수동 처리`: `tests/unit/test_room_service.py::TestNoShow::*`로 검증.
- `장비 노쇼 수동 처리`: `tests/unit/test_equipment_service.py::TestNoShowEquipment::*`로 검증.
- `회의실 지연 종료 처리`: `tests/unit/test_room_service.py::TestCheckInOut::test_force_complete_room_checkout_applies_late_penalty`로 검증.
- `장비 지연 종료 처리`: `tests/unit/test_equipment_service.py::TestCheckoutReturn::test_force_complete_equipment_return_applies_late_penalty`로 검증.
- `파손/오염 패널티 부여`: `tests/e2e/test_admin_scenarios.py::TestAdminPenaltyManagement::*`, `tests/unit/test_penalty_service.py::TestDamagePenalty::*`로 검증.
- `운영 시계`: `tests/unit/test_menu_dispatch.py::test_admin_menu_opens_clock_with_admin_actor`, `tests/unit/test_policy_service.py::TestClockAdvance::*`로 검증.
- `로그아웃`: `tests/unit/test_main.py::test_main_routes_admin_to_admin_menu`, `tests/unit/test_menu_dispatch.py`의 `0` 종료 경로로 검증.

### 시계 및 상태머신 정책 분기
- `09:00 -> 18:00 -> 다음날 09:00`만 허용: `tests/unit/test_policy_service.py::TestClockAdvance::test_advance_time_moves_clock_and_logs_event`로 검증.
- `시작 경계에서 사용자 요청 + 관리자 승인`: `tests/e2e/test_user_scenarios.py::TestBookingCompleteFlow::*`, `tests/unit/test_daily_booking_flow.py::*approval*`로 검증.
- `종료 경계에서 사용자 신청 + 관리자 승인`: 동일한 complete-flow 및 approval 테스트로 검증.
- `미승인 시작/종료 요청 잔존 시 시점 이동 차단`: `tests/unit/test_policy_service.py::TestClockAdvance::test_prepare_advance_blocks_room_start_without_admin_action`, `tests/unit/test_policy_service.py::TestClockAdvance::test_prepare_advance_blocks_equipment_end_without_user_request`, `tests/e2e/test_admin_scenarios.py::TestAdminPolicyExecution::test_admin_clock_advance_is_blocked_by_unprocessed_start_booking`로 검증.
- `시점 이동 성공/차단 감사 로그`: `tests/unit/test_policy_service.py::TestClockAdvance::test_advance_time_moves_clock_and_logs_event`, `tests/unit/test_policy_service.py::TestClockAdvance::test_advance_time_blocked_writes_audit_log`로 검증.
- `정상 시작/종료는 요청+승인으로만 허용`: room/equipment complete-flow 및 approval 테스트로 검증.

### 예약 및 이용 제한 정책 분기
- `즉시 확정`, `최대 6개월`, `최대 14일`, `내일부터`, `회의실 1건 + 장비 1건`: `tests/unit/test_daily_booking_flow.py::*`, `tests/e2e/test_user_scenarios.py::TestMultipleBookingsFlow::test_user_max_1_room_booking`로 검증.
- `reserved 상태에서만 사용자 변경/취소`: `tests/unit/test_room_service.py::TestModifyBooking::*`, `tests/unit/test_room_service.py::TestCancelBooking::*`, `tests/unit/test_equipment_service.py::TestModifyEquipmentBooking::*`, `tests/unit/test_equipment_service.py::TestCancelEquipmentBooking::*`로 검증.
- `3점 제한 / 6점 금지 / 90일 초기화 / 10회 정상 이용 차감`: `tests/unit/test_penalty_service.py::TestPenaltyThresholds::*`, `tests/unit/test_penalty_service.py::TestPenaltyReset90Days::*`, `tests/e2e/test_user_scenarios.py::TestPenaltyAccumulationFlow::*`, `tests/e2e/test_user_scenarios.py::TestStreakBonusFlow::test_streak_10_reduces_penalty`로 검증.
- `제한 기간 만료 반영` 및 `6점 이상 사용자 미래 예약 자동 취소`: `tests/unit/test_policy_service.py::TestRestrictionExpiry::*`, `tests/unit/test_policy_service.py::TestBannedUserBookingCancellation::*`로 검증.

### 패널티 분기
- `노쇼 +3점`: `tests/unit/test_penalty_service.py::TestNoShowPenalty::*`, `tests/unit/test_room_service.py::TestNoShow::*`, `tests/unit/test_equipment_service.py::TestNoShowEquipment::*`로 검증.
- `직전 취소 +2점`: `tests/unit/test_penalty_service.py::TestLateCancelPenalty::test_apply_late_cancel_adds_2_points`, `tests/unit/test_room_service.py::TestCancelBooking::test_cancel_booking_late_cancel`, `tests/unit/test_equipment_service.py::TestCancelEquipmentBooking::test_cancel_booking_late_cancel`로 검증.
- `지연 종료 +2점`: `tests/unit/test_penalty_service.py::TestLateReturnPenalty::*`, `tests/unit/test_room_service.py::TestCheckInOut::test_force_complete_room_checkout_applies_late_penalty`, `tests/unit/test_equipment_service.py::TestCheckoutReturn::test_force_complete_equipment_return_applies_late_penalty`로 검증.
- `파손/오염 1~5점`: 위 damage 패널티 테스트로 검증.

### 동시성/저장/감사 분기
- `동시 예약 충돌은 한쪽만 성공`: `tests/integration/test_concurrency.py::TestConcurrentBooking::test_concurrent_booking_only_one_succeeds`, `tests/integration/test_concurrency.py::TestConcurrentEquipmentBooking::test_concurrent_equipment_booking_only_one_succeeds`로 검증.
- `동시 회원가입 충돌`: `tests/integration/test_concurrency.py::TestConcurrentSignup::test_concurrent_signup_same_username_one_succeeds`로 검증.
- `원자적 쓰기 / tmp 정리 / lock 강제`: `tests/integration/test_concurrency.py::TestAtomicWriteSafety::*`, `tests/integration/test_uow_lock_enforcement.py::*`로 검증.
- `사용자 예약 상태 변경 감사 로그`: `tests/unit/test_room_service.py::TestAuditLogging::test_create_room_booking_logs_audit_action`, `tests/unit/test_room_service.py::TestAuditLogging::test_request_room_checkin_logs_audit_action`로 검증.
- `관리자 조작 감사 로그`: `tests/unit/test_room_service.py::TestAuditLogging::test_update_room_status_logs_admin_action`로 검증.
- `자동 정책 처리 감사 로그`: `tests/unit/test_policy_service.py::TestRestrictionExpiry::test_restriction_expiry_writes_audit_log`, `tests/unit/test_policy_service.py::TestBannedUserBookingCancellation::test_banned_user_auto_cancellation_writes_audit_log`로 검증.

### 명시적 매핑 이후 결론
- 현재 테스트 기준에서 `PLAN.md`에 정의된 사용자 흐름과 주요 정책/예외 분기는 모두 대응되는 테스트 근거를 확보했습니다.
- 다만 이것이 `PLAN.md`와 구현이 완전히 모순 없이 일치한다는 뜻은 아닙니다. 여전히 `10:00/19:00 cutoff`와 `09:00/18:00` 슬롯 시계의 충돌 같은 정책 수준 모순이 남아 있으며, 해당 항목은 위 `확인된 불일치` 및 `명세의 애매점 / 내부 충돌` 섹션에 유지합니다.
