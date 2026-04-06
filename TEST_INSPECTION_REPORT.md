# Test Suite & Input-Validation Inspection Report

**Date:** April 6, 2026  
**Scope:** Current test conventions, input validation modules, test coverage gaps, and reusable fixtures for final_plan.md implementation  
**Focus:** CLI input flows, domain validation, and edge-case handling

---

## 1. Current Test Structure

### Directory Layout
```
tests/
├── conftest.py              # Shared pytest fixtures (datetime mocking, factories, services)
├── unit/                    # 18 unit test files (8,506 total lines)
│   ├── test_auth_service.py
│   ├── test_user_menu.py
│   ├── test_admin_menu.py
│   ├── test_room_service.py
│   ├── test_equipment_service.py
│   ├── test_daily_booking_flow.py
│   ├── test_guest_menu_clock.py
│   ├── test_penalty_service.py
│   ├── test_policy_service.py
│   ├── test_message_service.py
│   ├── test_models.py
│   ├── test_menu_dispatch.py
│   ├── test_menu_policy_errors.py
│   ├── test_main.py
│   ├── test_jsonl_handler.py
│   ├── test_config.py
│   └── test_menu_screen_clear.py
├── integration/             # 3 integration test files
│   ├── test_repositories.py
│   ├── test_concurrency.py
│   └── test_uow_lock_enforcement.py
└── e2e/                     # 2 end-to-end test files
    ├── test_user_scenarios.py
    └── test_admin_scenarios.py
```

### Test Execution
- **Framework:** pytest
- **Run command:** `pytest` (runs all tests)
- **Estimated test count:** 25+ auth-related + 38+ input/validation-related tests
- **Key fixtures location:** `tests/conftest.py` (680+ lines)

---

## 2. Current Test Conventions & Patterns

### 2.1 Fixture-Based Approach (conftest.py)

**Datetime Mocking Pattern:**
```python
# Mock targets (conftest.py lines 44-52)
DATETIME_PATCH_TARGETS = [
    "src.runtime_clock.datetime",
    "src.domain.room_service.datetime",
    "src.domain.equipment_service.datetime",
    "src.domain.penalty_service.datetime",
    "src.domain.policy_service.datetime",
    "src.domain.models.datetime",
    "src.domain.restriction_rules.datetime",
]

# Usage in tests
def test_something(mock_now):
    fixed_time = datetime(2024, 6, 15, 10, 0, 0)
    with mock_now(fixed_time):
        # Test code here
```

**Factory Fixtures:**
- `create_test_user()` - Creates isolated test users
- `create_test_room()` - Creates isolated test rooms  
- `create_test_equipment()` - Creates isolated test equipment
- `auth_service`, `room_service`, `equipment_service`, etc. - Service instances with isolated storage

**Storage Isolation:**
- Each test gets a dedicated temporary directory via pytest's tmpdir
- `global_lock` is managed per-test
- No cross-test data contamination

### 2.2 Auth Service Tests (test_auth_service.py: 256 lines)

**Test Classes:**
- `TestSignup` - Tests registration with validation
- `TestLogin` - Tests authentication flows
- `TestUserLookup` - Tests user retrieval and updates

**Example Test Patterns:**
```python
def test_signup_success(self, auth_service):
    user = auth_service.signup(username="newuser", password="password123")
    assert user.username == "newuser"

def test_signup_blank_username_fails(self, auth_service):
    with pytest.raises(AuthError) as exc_info:
        auth_service.signup(username="   ", password="password123")
    assert "사용자명을 입력" in str(exc_info.value)

def test_signup_strips_surrounding_whitespace(self, auth_service):
    user = auth_service.signup(username="  spaced_user  ", password="  pass1234  ")
    assert user.username == "spaced_user"
```

### 2.3 Room Service Tests (test_room_service.py: 1,619 lines)

**Coverage Areas:**
- Daily booking date validation (start date after today, end date >= start date, max 14 days)
- Capacity and resource filtering
- State transitions (reserved → checkin_requested → checked_in → checkout_requested → completed)
- Conflict detection (overlapping bookings)
- Admin operations (status changes, cancellations)

**Key Test Pattern (daily booking):**
```python
def test_room_daily_booking_blocks_same_day(room_service, create_test_user, create_test_room, mock_now):
    fixed_time = datetime(2024, 6, 15, 10, 0, 0)
    with mock_now(fixed_time):
        with pytest.raises(RoomBookingError) as exc_info:
            room_service.create_daily_booking(
                user=user, room_id=room.id,
                start_date=date(2024, 6, 15),  # Same as today
                end_date=date(2024, 6, 16),
                attendee_count=4
            )
        assert "당일 예약" in str(exc_info.value)
```

### 2.4 User Menu Tests (test_user_menu.py: 539 lines)

**Coverage:**
- Policy checks and error handling
- User refresh/lookup failures
- Menu-level input dispatch
- Early exits on validation failures

**Pattern for Input Error Handling:**
```python
def test_run_policy_checks_returns_false_on_penalty_error(
    self, monkeypatch, auth_service, ..., create_test_user
):
    user = create_test_user()
    menu = UserMenu(user=user, auth_service=auth_service, ...)
    monkeypatch.setattr(
        menu.policy_service,
        "run_all_checks",
        lambda: (_ for _ in ()).throw(PenaltyError("exists"))
    )
    result = menu._run_policy_checks()
    assert result is False
```

### 2.5 Admin Menu Tests (test_admin_menu.py: 1,638 lines)

**Coverage:**
- Admin-specific operations (room/equipment state management, penalty assignment)
- Reason/memo input handling
- Error messages and early exits

---

## 3. Input-Validation Modules (Reusable Components)

### 3.1 CLI Validators (src/cli/validators.py: 257 lines)

**Core Functions:**

| Function | Purpose | Input Format | Return Value |
|----------|---------|--------------|--------------|
| `validate_username(username)` | Check username rules (3-20 chars, alphanumeric + underscore, no spaces) | string | (bool, error_msg) |
| `validate_password(password)` | Check password rules (4-50 chars, no spaces) | string | (bool, error_msg) |
| `validate_date_input(date_str)` | Parse date in YYYY-MM-DD format, check range (2026-2100), validate calendar day | string | (bool, datetime_obj, error_msg) |
| `validate_time_input(time_str)` | Parse HH:MM format, check 30-min slots (currently) | string | (bool, time_obj, error_msg) |
| `validate_datetime_input(date_str, time_str)` | Combined date+time validation | two strings | (bool, datetime_obj, error_msg) |
| `validate_positive_int(value_str, min_val, max_val)` | Integer range validation (e.g., attendee count 1-8) | string | (bool, int_value, error_msg) |
| `validate_menu_choice(choice, max_option)` | Menu option validation (0-N) | string | (bool, choice_int, error_msg) |
| `validate_daily_booking_dates(start_date, end_date, now)` | Domain-level daily booking logic (from daily_booking_rules.py) | date, date, datetime | (bool, error_msg, duration_days) |

**Interactive Input Wrappers (Blocking Loops):**
- `get_date_input(prompt)` - Returns datetime or None
- `get_time_input(prompt)` - Returns time or None
- `get_datetime_input(date_prompt, time_prompt)` - Returns datetime or None
- `get_positive_int_input(prompt, min_val, max_val)` - Returns int or None
- `get_daily_date_range_input(start_prompt, end_prompt)` - Returns (start_date, end_date) or (None, None)

**Key Example:**
```python
def validate_username(username):
    username = normalize_credential(username)
    if not username:
        return False, "사용자명을 입력해주세요."
    if len(username) < 3:
        return False, "사용자명은 3자 이상이어야 합니다."
    if len(username) > 20:
        return False, "사용자명은 20자 이하여야 합니다."
    if not re.match(r"^[a-zA-Z0-9_]+$", username):
        return False, "사용자명은 영문, 숫자, 밑줄(_)만 사용 가능합니다."
    return True, ""
```

### 3.2 Domain-Level Validation (src/domain/)

**auth_rules.py (45 lines):**
- `normalize_credential(value)` - Strips whitespace from usernames/passwords
- `validate_username(username)` - Rules from final_plan.md §4.1.1 (3-20 chars, alphanumeric+underscore)
- `validate_password(password)` - Rules from final_plan.md §4.1.2 (4-50 chars, no spaces)

**daily_booking_rules.py (65 lines):**
- `validate_daily_booking_dates(start_date, end_date, now)` - Enforces:
  - Start date must be tomorrow or later (no same-day bookings)
  - Start date must be within BOOKING_WINDOW_MONTHS (default 6 months)
  - End date must be >= start date
  - Duration must be <= MAX_BOOKING_DAYS (default 14 days)
  - Returns error message and duration days

**models.py (Enums & Dataclasses):**
- `RoomBookingStatus` enum (reserved, checkin_requested, checked_in, checkout_requested, completed, cancelled, no_show, admin_cancelled)
- `EquipmentBookingStatus` enum (similar state transitions)
- `ResourceStatus` enum (available, maintenance, disabled)
- `UserRole` enum (user, admin)
- `PenaltyReason` enum (no_show, late_cancel, late_return, damage, contamination, other)

**Key Service Error Patterns:**
```python
# From room_service.py / equipment_service.py
class RoomBookingError(Exception):
    pass

class EquipmentBookingError(Exception):
    pass

# From auth_service.py
class AuthError(Exception):
    pass
```

### 3.3 Final Plan Input Requirements from final_plan.md

**Date Input (§4.2.1):**
- **Syntax:** YYYY-MM-DD, YYYY.MM.DD, YYYY MM DD (separators must be consistent, no mixing)
- **Range:** Year 2026-2100, Month 01-12, Day 01-31 (with zero-padding)
- **Semantic:** Must be a valid calendar date (e.g., no Feb 31)
- **Current Implementation Gap:** Validators support only YYYY-MM-DD format; final_plan requires flexible separator support

**Time Input (§4.2.2):**
- **Syntax:** HH:MM or HHMM (separators must be consistent)
- **Values:** Hours must be 09 or 18, Minutes must be 00 (for operational times)
- **Current Implementation Gap:** Validators accept 30-minute intervals; final_plan requires only 09:00 and 18:00

**Username (§4.1.1):**
- **Syntax:** 3-20 characters, alphanumeric + underscore, **no spaces**
- **Semantics:** Case-sensitive uniqueness (Computer ≠ computer)
- **Current State:** ✓ Implemented and tested (test_auth_service.py)

**Password (§4.1.2):**
- **Syntax:** 4-50 characters, **no spaces**
- **Semantics:** Case-sensitive exact match
- **Current State:** ✓ Implemented and tested

**Reason/Memo (§4.4):**
- **Syntax:** 0-20 characters, no newlines, empty string allowed ("")
- **Current Implementation Gap:** No dedicated validator; used in penalty/cancellation flows

---

## 4. Test Coverage Gaps & Edge Cases

### 4.1 Date Input Edge Cases (MISSING in final_plan context)

| Edge Case | Current Status | Final Plan Requirement | Priority |
|-----------|---|---|---|
| Mixed separators (2026-01.01) | Not tested | Must reject | HIGH |
| Trailing/leading whitespace (` 2026-01-01 `) | Not tested | Must reject | HIGH |
| Month without zero-padding (2026-1-01) | Not tested | Must reject | HIGH |
| Day without zero-padding (2026-01-1) | Not tested | Must reject | HIGH |
| Year < 2026 (2025-01-01) | Not tested | Must reject | HIGH |
| Year > 2100 (2101-01-01) | Not tested | Must reject | HIGH |
| Invalid month (2026-13-01) | Not tested | Must reject | HIGH |
| Invalid day for month (2026-02-31) | Not tested | Must reject | HIGH |
| Dot separator (2026.01.01) | Not tested (planned syntax) | Must parse | HIGH |
| Space separator (2026 01 01) | Not tested (planned syntax) | Must parse | HIGH |

### 4.2 Time Input Edge Cases (MISSING in final_plan context)

| Edge Case | Current Status | Final Plan Requirement | Priority |
|-----------|---|---|---|
| Hour != 09 or 18 (08:00, 19:00) | Not explicitly tested | Must reject for operational times | HIGH |
| Minute != 00 (09:30, 18:15) | Not explicitly tested | Must reject for operational times | HIGH |
| Mixed separators (09-00) | Not tested | Must reject | MEDIUM |
| Space separator (09 00) | Not tested (planned syntax) | Must parse | HIGH |
| Hour > 23 (25:00) | Not tested | Must reject | MEDIUM |
| Minute > 59 (09:99) | Not tested | Must reject | MEDIUM |

### 4.3 Authentication Edge Cases (Partially Tested)

| Edge Case | Current Status | Test File | Notes |
|-----------|---|---|---|
| Duplicate username (case-sensitive) | ✓ Tested | test_auth_service.py::TestSignup::test_signup_duplicate_username_fails | Verified exact-match uniqueness |
| Whitespace stripping | ✓ Tested | test_auth_service.py::TestSignup::test_signup_strips_surrounding_whitespace | Works as expected |
| Username too short (< 3) | ✓ Tested | (implicit in test_signup_invalid_username_fails) | Caught |
| Username too long (> 20) | ✗ Not found | - | **GAP** |
| Username with special chars (!, @, #) | ✓ Tested | test_auth_service.py::TestSignup::test_signup_invalid_username_fails (checks "밑줄") | Rejected |
| Username with space | ✓ Tested | test_auth_service.py (implicit in regex check) | Rejected |
| Password too short (< 4) | ✓ Tested | test_auth_service.py::TestSignup::test_signup_short_password_fails | Caught |
| Password too long (> 50) | ✗ Not found | - | **GAP** |
| Password with space | ✗ Not found | - | **GAP** |
| Case sensitivity (login mismatch) | ✓ Tested | test_auth_service.py::TestLogin::test_login_case_sensitive_password_mismatch | Verified |

### 4.4 Booking Date Validation Edge Cases (Mostly Covered)

| Edge Case | Current Status | Test File | Notes |
|-----------|---|---|---|
| Same-day booking (start = today) | ✓ Tested | test_daily_booking_flow.py::test_room_daily_booking_blocks_same_day | "당일 예약" error |
| Past-date booking | ✓ Tested (implicit) | test_daily_booking_flow.py | Blocked by same-day rule |
| Booking > 6 months out | ✓ Tested | test_daily_booking_flow.py::test_daily_booking_blocks_over_6_month_window | "6개월" error |
| Duration > 14 days | ✓ Tested | test_daily_booking_flow.py::test_daily_booking_blocks_over_14_days | "14일" error |
| End date < start date | ✓ Tested (implicit) | test_daily_booking_flow.py (validate_daily_booking_dates) | Returns False |
| Attendee count edge cases (0, 1, 8, 9) | ✓ Tested | test_room_service.py | Capacity validation tested |

### 4.5 Reason/Memo Input Edge Cases (MISSING)

| Edge Case | Current Status | Final Plan Requirement | Priority |
|-----------|---|---|---|
| Empty string | Not explicitly tested | Must allow ("") | HIGH |
| Exactly 20 chars | Not tested | Must allow | MEDIUM |
| 21+ chars | Not tested | Must reject | HIGH |
| Newline character | Not tested | Must reject | HIGH |
| Special characters (!, @, #) | Not tested | Must allow (no restrictions mentioned) | LOW |
| Unicode/emoji | Not tested | Not specified | LOW |
| Leading/trailing whitespace | Not tested | May need clarification | MEDIUM |

---

## 5. Reusable Helpers & Fixtures

### 5.1 Key Fixtures in conftest.py

**Datetime Management (lines 40-143):**
```python
@pytest.fixture
def mock_now():
    """Context manager for mocking datetime.now() across all modules"""
    def _mock_now(fixed_time):
        mock_dt = create_datetime_mock(fixed_time)
        patches = [patch(target, mock_dt) for target in DATETIME_PATCH_TARGETS]
        class MockContext:
            def __enter__(self): ...
            def __exit__(self, *args): ...
        return MockContext()
    return _mock_now

# Usage: with mock_now(datetime(2024, 6, 15, 10, 0, 0)): ...
```

**Runtime Clock (lines 145-?):**
```python
@pytest.fixture
def fake_clock():
    """Direct session clock control fixture"""
    def _set(fixed_time):
        set_active_clock(SystemClock(fixed_time))
    yield _set
    clear_active_clock()
```

**Factory Fixtures (inferred from test usage):**
```python
@pytest.fixture
def create_test_user():
    """Create isolated test user"""
    def factory(username="testuser", password="testpass", role=UserRole.USER):
        return auth_service.signup(username, password, role)
    return factory

@pytest.fixture
def create_test_room():
    """Create isolated test room"""
    def factory(name="TestRoom", capacity=6, location="1층", status=ResourceStatus.AVAILABLE):
        # Creates via room_service
    return factory

@pytest.fixture
def create_test_equipment():
    """Create isolated test equipment"""
    def factory(name="TestEquip", asset_type="프로젝터", serial_number="PJ-001"):
        # Creates via equipment_service
    return factory
```

**Service Fixtures:**
```python
@pytest.fixture
def auth_service():
    """Isolated auth service instance"""
    return AuthService(user_repo)

@pytest.fixture
def room_service():
    """Isolated room service instance"""
    return RoomService(room_repo, room_booking_repo)

@pytest.fixture
def equipment_service():
    """Isolated equipment service instance"""
    return EquipmentService(equipment_repo, equipment_booking_repo)

# Similar for penalty_service, policy_service, message_service, etc.
```

### 5.2 Error Assertion Patterns (Reusable)

**Pattern 1: Service Exception Checking**
```python
def test_operation_fails_with_specific_error(self, auth_service):
    with pytest.raises(AuthError) as exc_info:
        auth_service.signup(username="invalid space", password="pass")
    assert "밑줄" in str(exc_info.value)
```

**Pattern 2: Menu Error Message Capture**
```python
def test_menu_shows_error_on_validation_failure(self, monkeypatch, menu):
    messages = []
    monkeypatch.setattr("src.cli.user_menu.print_error", messages.append)
    menu._some_operation()
    assert len(messages) > 0
    assert "error substring" in messages[0]
```

**Pattern 3: Input Loop Simulation**
```python
inputs = iter(["invalid_input", "valid_input"])
monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
# First call returns "invalid_input" → error printed
# Second call returns "valid_input" → accepted
```

---

## 6. Most Relevant Test Files for Extension

### Priority 1: EXTEND THESE

**1. tests/unit/test_auth_service.py (256 lines)**
- **What it covers:** Username/password validation, signup, login, user lookups
- **What to add:**
  - Username length boundaries (exactly 3, exactly 20, 21+)
  - Password length boundaries (exactly 4, exactly 50, 51+)
  - Password with embedded spaces validation
  - Case-sensitivity edge cases for login
- **Reusable patterns:** Exception assertion, normalization testing

**2. tests/unit/test_daily_booking_flow.py (201 lines)**
- **What it covers:** Date range validation, booking state transitions, capacity filtering
- **What to add:**
  - Multi-format date input (dot separator, space separator)
  - Date parsing with zero-padding enforcement
  - Time slot validation (09:00 and 18:00 only)
  - Invalid calendar dates (Feb 31, etc.)
  - Attendee count boundaries (0, 1, 8, 9)
- **Reusable patterns:** Daily booking rule testing, error message matching

**3. tests/unit/test_user_menu.py (539 lines)**
- **What it covers:** Menu dispatch, policy error handling, user state management
- **What to add:**
  - Reason/memo input validation (empty, 20 chars, 21+ chars, newlines)
  - Menu selection edge cases (non-numeric, out-of-range)
  - Input retry loops under failure conditions
- **Reusable patterns:** `monkeypatch` for input simulation, menu flow testing

### Priority 2: REFERENCE THESE

**4. tests/unit/test_admin_menu.py (1,638 lines)**
- Covers penalty reason handling, state changes, error propagation
- Good patterns for: reason/memo input, confirmation dialogs, admin-specific errors

**5. tests/integration/test_repositories.py**
- Data persistence validation
- Good patterns for: roundtrip testing (save → load → compare)

**6. tests/conftest.py**
- **Use directly:** `mock_now`, `fake_clock`, factory fixtures
- **Extend with:** Date/time parsing test helpers, input simulation utilities

---

## 7. Current Test Conventions Summary

| Convention | Location | Usage |
|---|---|---|
| Datetime mocking | conftest.py lines 44-143 | `with mock_now(dt): ...` |
| Factory pattern | conftest.py fixtures | `create_test_user()`, `create_test_room()`, etc. |
| Service isolation | conftest.py fixtures | Each test gets isolated service instances |
| Exception assertion | test_auth_service.py | `with pytest.raises(AuthError) as exc_info:` |
| Error message matching | Throughout unit tests | `assert "substring" in str(exc_info.value)` |
| Input mocking | test_user_menu.py | `monkeypatch.setattr("builtins.input", lambda: ...)` |
| Menu testing | test_user_menu.py, test_admin_menu.py | `monkeypatch` on print/input functions |
| Policy error handling | test_menu_policy_errors.py | Service exception → menu → user feedback |
| Integration: storage | test_repositories.py | Roundtrip persistence tests |
| Integration: locking | test_uow_lock_enforcement.py | Concurrent access with file locks |

---

## 8. Key Implementation Notes for final_plan.md

### Immediate Priorities

1. **Date Input Format Flexibility** (§4.2.1)
   - Current: Only `YYYY-MM-DD` supported
   - Required: `YYYY-MM-DD`, `YYYY.MM.DD`, `YYYY MM DD` (consistent separators)
   - **Test location to extend:** test_daily_booking_flow.py
   - **Validator to update:** src/cli/validators.py::validate_date_input()

2. **Time Input Constraints** (§4.2.2)
   - Current: 30-minute intervals accepted
   - Required: Only `09:00` and `18:00` for operational times
   - **Test location to extend:** test_daily_booking_flow.py or new test_time_validation.py
   - **Validator to create/update:** src/cli/validators.py::validate_operational_time()

3. **Reason/Memo Validation** (§4.4)
   - Current: No dedicated validator
   - Required: 0-20 chars, no newlines, empty string allowed
   - **Test location to extend:** test_admin_menu.py (penalty reason flow)
   - **Validator to create:** src/cli/validators.py::validate_reason_memo()

4. **Authentication Edge Cases**
   - Current gaps: Username length=21+, Password length=51+, Password with spaces
   - **Test location to extend:** test_auth_service.py
   - **Validators:** Already in src/domain/auth_rules.py, just need test coverage

5. **Input Confirmation Patterns** (§6.4 Exit, §6.5.1.4 Reservation Change Confirmation)
   - Current: Implemented in test_main.py, used in menus
   - Pattern: `confirm()` function returns bool based on y/n input
   - **Test location:** test_main.py (exit flow)
   - **Extend with:** All y/n/예/아니오/ㅇ/ㄴ (case-insensitive) variants

---

## Appendix: File Path Summary

| File Path | Lines | Purpose |
|-----------|-------|---------|
| src/cli/validators.py | 257 | CLI input validation functions (primary validation layer) |
| src/domain/auth_rules.py | 45 | Auth credential validation rules |
| src/domain/daily_booking_rules.py | 65 | Booking date range validation |
| src/domain/models.py | 361+ | Enums and dataclasses for all domain objects |
| tests/conftest.py | 680+ | Shared pytest fixtures, datetime mocking, factories |
| tests/unit/test_auth_service.py | 256 | Auth signup/login validation tests (25+ tests) |
| tests/unit/test_daily_booking_flow.py | 201 | Booking date and state transition tests |
| tests/unit/test_user_menu.py | 539 | Menu dispatch and error handling tests |
| tests/unit/test_admin_menu.py | 1,638 | Admin operations and penalty handling tests |
| tests/unit/test_room_service.py | 1,619 | Comprehensive room booking service tests |
| tests/unit/test_equipment_service.py | 1,235 | Comprehensive equipment booking service tests |
| tests/unit/test_menu_policy_errors.py | 333 | Policy-level error propagation in menus |
| tests/integration/test_repositories.py | - | Data persistence and roundtrip validation |
| tests/integration/test_uow_lock_enforcement.py | - | File locking and atomic write tests |

---

## Summary

**Current State:**
- ✓ Solid foundation with 25+ auth validation tests, 201-line booking flow tests
- ✓ Fixture-based approach (datetime mocking, service isolation, factory pattern)
- ✓ Auth and daily booking date logic mostly covered
- ✓ Menu-level error handling and policy checks tested

**Gaps for final_plan.md:**
- ✗ Multi-format date input (dot, space separators) - needs 3-4 test cases
- ✗ Time slot constraint (09:00, 18:00 only) - needs 4-5 test cases
- ✗ Reason/memo validation (0-20 chars, no newlines) - needs 5-6 test cases
- ✗ Auth edge cases (username/password length boundaries) - needs 4-5 test cases
- ✗ Confirmation input variants (y/n/예/아니오/ㅇ/ㄴ) - needs 6-8 test cases

**Recommended Test Expansion:** ~25-30 new test cases across 4-5 existing files, using established patterns from test_auth_service.py and test_daily_booking_flow.py
