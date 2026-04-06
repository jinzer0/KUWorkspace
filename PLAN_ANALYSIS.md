# Final Plan Analysis: Affected Modules & Implementation Mapping

**Analysis Date:** 2026-04-06  
**Repository:** opencode_kuwork  
**Scope:** Identify existing modules, services, routes, validators affected by final_plan.md requirements  
**Approach:** Preserve current modularization, flag ambiguities for clarification

---

## Executive Summary

The final_plan.md specifies a Korean language CLI for a shared office booking system with:
- 3 user roles: Guest (비로그인), User (일반사용자), Admin (관리자)
- 2 resources: Rooms (회의실) and Equipment (장비)
- Discrete time slots: 09:00 and 18:00 only
- Complex penalty policies with restriction levels
- Data validation with specific grammar/semantic rules

**Key Finding:** Large-scale implementation needed; modularization remains unchanged.

---

## 1. PLAN STRUCTURE → EXISTING CODEBASE MAPPING

### 1.1 Overall Architecture Alignment

| Plan Section | Current Module | Status | Notes |
|---|---|---|---|
| **2.1-2.3** Program Environment, Config, Install | `src/config.py`, `main.py` | ✓ Exists | Python 3.13+, entry via main.py, data/ directory |
| **3.1-3.3** User Flows (Guest/User/Admin) | `src/cli/` menu modules | ✓ Partial | Guest, User, Admin menus exist; need expansion |
| **4.1-4.4** Data Elements (ID, Password, Date, Reason) | `src/cli/validators.py` | ⚠ Partial | Basic validators exist; need comprehensive grammar rules |
| **5.1-5.7** Data Files (JSONL Storage, Format) | `src/storage/` | ✓ Exists | JSONL format in `data/*.txt`; field escaping, mandatory file checks |
| **6.1-6.4** Main Menu, Login, Clock, Quit | `src/cli/menu.py`, `guest_menu.py`, `clock_menu.py` | ✓ Exists | Runtime clock management in `src/runtime_clock.py` |
| **6.5 User Menus (Rooms/Equipment/Info)** | `src/cli/user_menu.py` | ⚠ Partial | Room/equipment menus exist; need full spec compliance |
| **6.6 Admin Menus (Room/Equipment/User Mgmt)** | `src/cli/admin_menu.py` | ⚠ Partial | Admin menus exist; need full spec compliance |

---

## 2. DETAILED MODULE-BY-MODULE MAPPING

### 2.1 CLI Layer: Validators (`src/cli/validators.py`)

**Purpose:** Input validation with Korean error messages  
**Current State:** Basic validators present  
**Plan Requirements (4.1-4.4):**

| Requirement | Validator Needed | Current | Status |
|---|---|---|---|
| **4.1.1 Username (ID)** | `validate_username()` | ? | Needs: 3-20 chars, alphanumeric + `_`, case-sensitive uniqueness |
| **4.1.2 Password** | `validate_password()` | ? | Needs: 4-50 chars, no spaces, exact match (case-sensitive) |
| **4.2.1 Date** | `validate_date()` | ? | Needs: YYYY-MM-DD/YYYY.MM.DD/YYYY MM DD, no mixed separators, pad month/day, valid calendar day |
| **4.2.2 Time** | `validate_time()` | ? | Needs: 09:00 or 18:00 only (HH:MM or HHMM format) |
| **4.3.1-4.3.2 Equipment** | Serial validation | ? | Needs: Pattern [TYPE]-[NUMBER] (e.g., PJ-001, CB-001, NB-001, WC-001) |
| **4.4 Reason (Memo)** | `validate_reason()` | ? | Needs: 0-20 chars, no newlines, can be empty string |

**Test Location:** `tests/unit/test_validators.py` (likely exists)

**Critical Edge Cases to Validate:**
- Date: Leap year 2/29, month-end edge cases (30 vs 31 days)
- Date: Mixed separators (e.g., "2099-01.03" should fail)
- Username: Case sensitivity (Computer ≠ computer)
- Password: All special chars except space allowed
- Time: ONLY 09:00 and 18:00, reject 10:00, 17:00, etc.

---

### 2.2 CLI Layer: Guest Menu (`src/cli/guest_menu.py`)

**Purpose:** Unauthenticated user interaction (signup, login, clock, quit)  
**Current State:** Exists (basic implementation)  
**Plan Requirements (6.2-6.3, 6.2.3):**

| Feature | Spec Section | Current Status | Changes Needed |
|---|---|---|---|
| Register (회원가입) | 6.2.1 | ✓ Exists | Validate ID/password per 4.1; confirm password match; error on duplicate ID |
| Login (로그인) | 6.2.2 | ✓ Exists | Case-sensitive ID/password; error msg "존재하지 않는 사용자입니다" |
| Guest Clock (게스트 운영시계) | 6.2.3 | ✓ Exists | Limited: only view current time (6.3.2), not time advance (6.3.3) |
| Quit (종료) | 6.4 | ✓ Exists | Y/N confirmation: accept y/yes/예/ㅇ (case-insensitive), reject n/no/아니오/ㄴ |

**Test Location:** `tests/unit/test_guest_menu_clock.py`

**Validator Calls Needed:**
- `validate_username()` for registration
- `validate_password()` for registration + confirmation
- No password confirmation match → retry

---

### 2.3 CLI Layer: Clock Menu (`src/cli/clock_menu.py`)

**Purpose:** Virtual time management (current time view, advance time slot)  
**Current State:** Basic implementation  
**Plan Requirements (6.3):**

| Feature | Spec Section | Current Status | Changes Needed |
|---|---|---|---|
| View Current Time | 6.3.2 | ✓ Exists | Show: current time, next time, predicted events (user vs admin different) |
| Advance to Next Time | 6.3.3 | ✓ Exists | Transitions: 09:00 → 18:00 (same day), 18:00 → 09:00 (next day), trigger all system events |
| Event Summary | 6.3.2 | ⚠ Partial | User: own events only; Admin: system-wide events |

**System Events on Time Advance:**
- Room booking transitions (reserved → checkin_requested → checked_in → checkout_requested → completed)
- Equipment booking transitions (reserved → pickup_requested → checked_out → return_requested → returned)
- Auto-approval if missed deadlines (09:00 checkins, 18:00 checkouts)
- Penalty applications (no-show, late return, etc.)
- Restriction level changes (normal → restricted → banned)
- Penalty resets (10-streak normal use → -1 penalty point)

**Bootstrap Requirement (6.1):**
- On first run: prompt for initial date & time slot
- Stored in persistent config
- Subsequent runs use stored value

**Test Location:** `tests/unit/test_guest_menu_clock.py`, integration event tests

---

### 2.4 CLI Layer: User Menu (`src/cli/user_menu.py`)

**Purpose:** Authenticated user features (room/equipment booking, status, info)  
**Current State:** Partial implementation  
**Plan Requirements (6.5):**

#### 2.4.1 Room Booking Submenu (6.5.1)

| Feature | Spec | Current | Changes |
|---|---|---|---|
| List Rooms (회의실 목록 조회) | 6.5.1.1 | ✓ | Show: name, capacity, location, status ([사용가능]/[점검중]/[사용불가]) |
| Reserve Room (회의실 예약하기) | 6.5.1.2 | ✓ | Complex: date range validation, capacity matching, conflict check, user state check |
| View My Reservations (회의실 예약 조회) | 6.5.1.3 | ✓ | List: 20 max, sorted by start_time DESC, show ID (first 8 chars), room name, dates, status |
| Modify Reservation (회의실 예약 변경) | 6.5.1.4 | ✓ | Change dates only, not room; validate same constraints |
| Cancel Reservation (회의실 예약 취소) | 6.5.1.5 | ⚠ | **Critical:** Same-day cancel (당일 예약 09:00) → +2 penalty points |
| Request Check-in (회의실 입실 신청) | 6.5.1.6 | ✓ | Status: reserved → checkin_requested, time must match current_time exactly |
| Request Check-out (회의실 퇴실 신청) | 6.5.1.7 | ✓ | Status: checked_in → checkout_requested |

**Validator Requirements:**
- Date format validation (3 formats, no mixed separators)
- Occupancy check (1-8 only)
- Past/future date checks relative to current_time
- 180-day max booking horizon
- 14-day max duration per booking
- Overlapping reservation conflict detection
- User state checks (banned, restricted with active booking)

**User State Validations:**
- **Banned:** No new reservations, show "이용이 금지된 상태입니다. 해제일: YYYY-MM-DD"
- **Restricted:** Max 1 active booking (across room + equipment combined), show "패널티로 인해 추가 예약이 불가합니다"
- **Normal:** Unlimited active bookings

**Edge Cases:**
- Capacity greedy algorithm: Prefer smaller room that fits → error if larger selected
- Same-day 09:00 cancel = +2 penalty (confirm dialog required)
- Early checkout (조기 퇴실): Affects status transitions and maintenance window

**Test Locations:**
- `tests/unit/test_user_menu.py`
- `tests/unit/test_room_service.py`
- `tests/unit/test_policy_service.py`
- `tests/unit/test_penalty_service.py`

---

#### 2.4.2 Equipment Booking Submenu (6.5.2)

| Feature | Spec | Current | Changes |
|---|---|---|---|
| List Equipment (장비 목록 조회) | 6.5.2.1 | ✓ | Show: by type (PJ, NB, CB, WC), serial number, status |
| Reserve Equipment (장비 예약하기) | 6.5.2.2 | ✓ | Select type → select instance → date range; no time input (auto 09:00-18:00) |
| View My Equipment Reservations (장비 예약 조회) | 6.5.2.3 | ✓ | Show: ID, type, duration, status |
| Modify Equipment Reservation (장비 예약 변경) | 6.5.2.4 | ✓ | Change dates only, same serial |
| Cancel Equipment Reservation (장비 예약 취소) | 6.5.2.5 | ✓ | Status: reserved → cancelled |
| Request Equipment Pickup (장비 픽업 신청) | 6.5.2.6 | ✓ | Status: reserved → pickup_requested, time must match current exactly |
| Request Equipment Return (장비 반납 신청) | 6.5.2.7 | ✓ | Status: checked_out → return_requested |

**Equipment Inventory:**
- Projector (PJ): 3 units (PJ-001, PJ-002, PJ-003)
- Laptop (NB): 3 units (NB-001, NB-002, NB-003)
- Cable (CB): 3 units (CB-001, CB-002, CB-003)
- Webcam (WC): 3 units (WC-001, WC-002, WC-003)

**Serial Number Display Order:** Ascending by serial (e.g., CB-001, CB-002, CB-003)

**Test Locations:**
- `tests/unit/test_user_menu.py`
- `tests/unit/test_equipment_service.py`

---

#### 2.4.3 User Info Submenu (6.5.3)

| Feature | Spec | Current | Changes |
|---|---|---|---|
| View My Status (유저 정보 조회) | 6.5.3.1 | ✓ | Show: username, role, penalty status, reservation summary, penalty history |
| View Clock (운영 시계) | 6.5.3.2 | ✓ | Same as 6.3 (guest only sees current; user can advance if admin role—wait, this is USER menu?) |

**Clarification Needed:**
- Section 6.5.3.2 says "운영 시계 메뉴는 6.3절의 운영 시계 메뉴와 동일하다" (operational clock is same as 6.3)
- Does this mean user can ADVANCE time slot? Or only VIEW? Plan 6.2.3 says guest only views (no advance).
- **Ambiguity Flag:** Confirm whether USER role can trigger time advance or only view.

**Test Location:** `tests/unit/test_user_menu.py`

---

### 2.5 CLI Layer: Admin Menu (`src/cli/admin_menu.py`)

**Purpose:** Administrative features (approval, status management, penalty mgmt)  
**Current State:** Partial implementation  
**Plan Requirements (6.6):**

#### 2.5.1 Room Management (6.6.1)

| Feature | Spec | Current | Changes |
|---|---|---|---|
| View All Room Reservations | 6.6.1.1 | ✓ | Show: name, capacity, location, status (사용중/예약있음/예약없음), booking dates |
| List & Change Room Status | 6.6.1.2 | ✓ | Options: [사용가능]/[점검중] (not [사용불가]) |
| Approve Room Check-ins | 6.6.1.3 | ✓ | List: rooms with checkin_requested status, time must match 09:00, auto-approve if missed |
| Approve Room Check-outs | 6.6.1.4 | ✓ | List: rooms with checkout_requested status, time must match 18:00, auto-approve if missed |
| Modify Room Reservation (Admin) | 6.6.1.5 | ✓ | Change booking dates, same constraints as user; 180-day from original start_time |
| Cancel Room Reservation (Admin) | 6.6.1.6 | ✓ | Requires memo (사유), 0-20 chars, no newlines |

**Room Status Transitions (Rules 6.6.1 & 6.6.2):**
- After last booking ends at 09:00 next day → auto-reset [점검중]/[사용불가] → [사용가능]
- Admin can set [점검중] at 18:00 after user checkout
- During early checkout: can set [점검중] at 18:00, then reset [사용가능] at 09:00

**Auto-Approval Logic:**
- On time advance to 09:00: Auto-approve all checkin_requested by 09:00 if start_time matches
- On time advance to 18:00: Auto-approve all checkout_requested by 18:00 if end_time matches
- Status: checkin_requested → checked_in, checkout_requested → completed

**Test Location:** `tests/unit/test_admin_menu.py`

---

#### 2.5.2 Equipment Management (6.6.2)

| Feature | Spec | Current | Changes |
|---|---|---|---|
| View All Equipment Reservations | 6.6.2.1 | ✓ | Show: serial, type, user, duration, status; sorted by end_time DESC |
| List & Change Equipment Status | 6.6.2.2 | ✓ | Options: [사용가능]/[점검중]; sort by serial ASC |
| Approve Equipment Pickup | 6.6.2.3 | ✓ | List: equipment with pickup_requested, time match 09:00, auto-approve if missed |
| Approve Equipment Return | 6.6.2.4 | ✓ | List: equipment with return_requested, time match 18:00, auto-approve if missed |
| Modify Equipment Reservation (Admin) | 6.6.2.5 | ✓ | Same as room: change dates, 180-day window |
| Cancel Equipment Reservation (Admin) | 6.6.2.6 | ✓ | Requires memo |

**Equipment Status Transitions:** Same rules as rooms (auto-reset after booking ends)

**Test Location:** `tests/unit/test_admin_menu.py`

---

#### 2.5.3 User Management (6.6.3)

| Feature | Spec | Current | Changes |
|---|---|---|---|
| List Users | 6.6.3.1 | ✓ | Show all users + penalty status |
| View User Details | 6.6.3.2 | ✓ | Full profile + penalty history |
| Penalty Policy Management | 6.6.3.3 | ✓ | Complex: status tiers, rewards, resets |
| Apply Damage/Contamination Penalty | 6.6.3.4 | ✓ | Admin-issued penalty (not automatic) |
| Handle Late Check-out | 6.6.3.5 | ✓ | Auto-triggered on time advance |
| Handle Late Equipment Return | 6.6.3.6 | ✓ | Auto-triggered on time advance |
| Handle Last-Minute Cancellation | 6.6.3.7 | ✓ | Auto-triggered: same-day 09:00 cancel = +2 points |
| View Clock | 6.6.3.8 | ✓ | Same as user clock (advance capabilities?) |

**Test Location:** `tests/unit/test_admin_menu.py`, `tests/unit/test_penalty_service.py`

---

### 2.6 Domain Layer: Services

#### 2.6.1 Authentication (`src/domain/auth_service.py`)

**Purpose:** User registration, login, role management  
**Current State:** Exists  
**Plan Additions:**

| Method | Spec | Changes |
|---|---|---|
| `register(username, password)` | 4.1.1, 4.1.2, 6.2.1 | Validate per rules, check uniqueness (case-insensitive for duplicates? **Ambiguity Flag**) |
| `login(username, password)` | 4.1.1, 4.1.2, 6.2.2 | Case-sensitive match, error msg format |
| `get_role(user_id)` | 6.5, 6.6 | Return UserRole.USER or UserRole.ADMIN |

**Critical Edge Case (Ambiguity):**
- Plan 4.1.1 says "회원가입시 입력하는 아이디와 로그인시 입력하는 아이디의 동치 비교는 각 문자의 순서와 내용이 정확히 일치해야 한다."
- But for **duplicate checking**: "중복 여부를 검사하는 경우, 대소문자는 서로 다른 문자로 간주한다."
- **Question:** Does this mean duplicate checking is case-SENSITIVE? Example: "Computer" and "computer" allowed as 2 different IDs?
- **Assumption:** Allowing both = case-sensitive storage, case-sensitive uniqueness

**Test Location:** `tests/unit/test_auth_service.py`

---

#### 2.6.2 Room Service (`src/domain/room_service.py`)

**Purpose:** Room CRUD, availability, booking logic  
**Current State:** Large implementation  
**Plan Additions:**

| Method | Spec Section | Changes |
|---|---|---|
| `list_rooms()` | 6.5.1.1, 6.6.1.2 | Filter by status, show capacity/location |
| `get_available_rooms(start, end, min_capacity)` | 6.5.1.2 | Conflict detection, capacity sort ASC, greedy check |
| `book_room(user_id, room_id, start, end)` | 6.5.1.2 | State: reserved; timestamps: created_at, updated_at |
| `change_booking_dates(booking_id, new_start, new_end)` | 6.5.1.4 | Validate conflicts, same user, reserved status |
| `cancel_booking(booking_id, memo?)` | 6.5.1.5 | Set status: cancelled, record cancelled_at; check for same-day penalty |
| `request_checkin(booking_id)` | 6.5.1.6 | State: reserved → checkin_requested, record requested_checkin_at |
| `request_checkout(booking_id)` | 6.5.1.7 | State: checked_in → checkout_requested, record requested_checkout_at |
| `approve_checkin(booking_id)` | 6.6.1.3 | State: checkin_requested → checked_in, record checked_in_at, timestamp now_iso |
| `approve_checkout(booking_id)` | 6.6.1.4 | State: checkout_requested → completed, record completed_at |
| `admin_cancel(booking_id, memo)` | 6.6.1.6 | Set status: admin_cancelled |
| `admin_modify_dates(booking_id, new_start, new_end)` | 6.6.1.5 | Similar to user modify, different 180-day window base |

**State Transition Table (6.5.1.0):**

| From → To | Record Fields |
|---|---|
| reserved (create) | created_at, updated_at |
| reserved → checkin_requested | requested_checkin_at, updated_at |
| checkin_requested → checked_in | checked_in_at, updated_at |
| checked_in → checkout_requested | requested_checkout_at, updated_at |
| checkout_requested → completed | completed_at, updated_at |
| reserved → cancelled | cancelled_at, updated_at |

**Test Location:** `tests/unit/test_room_service.py`

---

#### 2.6.3 Equipment Service (`src/domain/equipment_service.py`)

**Purpose:** Equipment CRUD, availability, booking logic  
**Current State:** Large implementation  
**Plan Additions:** (Parallel to room service, adjusted for equipment)

| Method | Spec Section | Changes |
|---|---|---|
| `list_equipment()` | 6.5.2.1 | Group by type, show serial ASC, status |
| `get_available_equipment(asset_type, start, end)` | 6.5.2.2 | Return sorted by serial ASC |
| `book_equipment(user_id, serial_id, start, end)` | 6.5.2.2 | State: reserved |
| `change_booking_dates(booking_id, new_start, new_end)` | 6.5.2.4 | Validate conflicts |
| `cancel_booking(booking_id, memo?)` | 6.5.2.5 | Set status: cancelled |
| `request_pickup(booking_id)` | 6.5.2.6 | State: reserved → pickup_requested, time must match exactly |
| `request_return(booking_id)` | 6.5.2.7 | State: checked_out → return_requested |
| `approve_pickup(booking_id)` | 6.6.2.3 | State: pickup_requested → checked_out, record checked_out_at |
| `approve_return(booking_id)` | 6.6.2.4 | State: return_requested → returned, record returned_at |

**State Transition (similar to rooms):**
- Booking: reserved → pickup_requested → checked_out → return_requested → returned
- Cancel: reserved/pickup_requested → cancelled

**Test Location:** `tests/unit/test_equipment_service.py`

---

#### 2.6.4 Penalty Service (`src/domain/penalty_service.py`)

**Purpose:** Penalty calculation, scoring, restriction management  
**Current State:** Exists  
**Plan Requirements (Complex):**

**Penalty Scoring Table:**

| Reason | Points | Trigger | Auto/Manual |
|---|---|---|---|
| No-show (노쇼) | 3 | Booking end reached, no checkin/checkout → auto-transition to no_show | Auto (on time advance) |
| Late cancel (직전 취소) | 2 | Same-day 09:00 cancel | Auto (on user action) |
| Late return (반납 지연) | ceil(delay_minutes / 10) | Return > end_time | Auto (on time advance, calculate delay) |
| Late checkout (퇴실 지연) | ceil(delay_minutes / 10) | Checkout > end_time (room only) | Auto (on time advance) |
| Damage (파손) | Admin-set | Admin observes damage | Manual |
| Contamination (오염) | Admin-set | Admin observes contamination | Manual |

**Restriction Levels:**

| Level | Penalty Points | Booking Limit | Duration | Transition |
|---|---|---|---|---|
| Normal (정상) | 0-2 | Unlimited active | N/A | 0-2 pts |
| Restricted (제한) | 3-5 | 1 active (room + equipment combined) | N/A | 3-5 pts |
| Banned (이용금지) | 6+ | 0 (all denied) | 30 days from trigger | 6+ pts → future bookings auto-cancel |

**Rewards & Resets:**
- **10-Streak Reward:** 10 consecutive normal uses (completed without penalty) → -1 penalty point (min 0)
- **90-Day Reset:** Admin reset command (6.6.3.3.3) → 0 points + 0 streak
- **Restriction End:** On 30-day timer expiry, auto-lift ban status

**Methods Needed:**

| Method | Spec | Logic |
|---|---|---|
| `calculate_total_points(user_id)` | 6.6.3.3.1 | Sum all active penalty records |
| `get_user_status(user_id)` | 6.6.3.3.1 | Return: NORMAL \| RESTRICTED \| BANNED |
| `apply_penalty(user_id, reason, points, related_type, related_id, memo)` | 6.6.3.4-7 | Create penalty record, update user status |
| `apply_no_show_penalty(booking_id, resource_type)` | 6.3.3 (event) | Auto-apply +3 on time advance if no checkin/checkout |
| `apply_late_penalty(booking_id, delay_minutes)` | 6.3.3 (event) | Auto-apply ceil(delay_minutes/10) |
| `reward_normal_use(user_id)` | 6.3.3 (event) | On booking complete: increment streak; if streak==10, apply -1 point + reset streak to 0 |
| `reset_penalties(user_id, admin_id)` | 6.6.3.3.3 | Set points→0, streak→0, restriction_until→None |
| `lift_ban_if_expired(user_id)` | 6.3.3 (event) | Check restriction_until vs current_time; if expired, clear restriction_until |
| `auto_cancel_future_bookings(user_id)` | 6.3.3 (event) | When user → BANNED, cancel all future reserved/pickup_requested bookings |

**Critical Edge Case (Ambiguity):**
- Plan 6.6.3.3.2 mentions "정상 이용 보상" but doesn't specify exact trigger. Assumption: Booking transitioned to "completed" status = 1 count toward 10-streak.
- **Question:** Does this include early checkout bookings? Or only full-duration?
- **Assumption:** Any completed booking counts as 1 normal use.

**Test Location:** `tests/unit/test_penalty_service.py`, integration tests

---

#### 2.6.5 Policy Service (`src/domain/policy_service.py`)

**Purpose:** Business logic enforcement (user state checks, booking rules, auto-transitions)  
**Current State:** Exists  
**Plan Additions:**

| Method | Spec | Logic |
|---|---|---|
| `can_user_book_room(user_id)` | 6.5.1.2 | Check: BANNED → deny with msg; RESTRICTED + active room booking → deny; else allow |
| `can_user_book_equipment(user_id)` | 6.5.2.2 | Same |
| `validate_room_dates(start, end)` | 6.5.1.2 | Today check, 180-day horizon, 14-day max, valid calendar |
| `validate_equipment_dates(start, end)` | 6.5.2.2 | Same |
| `on_time_advance(old_time, new_time)` | 6.3.3 | Orchestrate all state transitions, penalties, auto-approvals |

**Orchestration Logic (on_time_advance):**

1. **Fetch all bookings** (room + equipment) with events in time window
2. **For each room booking:**
   - If start_time == old_time & status == reserved: → LATE CANCEL if old_time is 09:00 on start date, else check_for_no_show
   - If start_time == new_time & status == checkin_requested: → auto-approve (checked_in)
   - If end_time == new_time & status == checkout_requested: → auto-approve (completed), apply no-show/late-checkout penalties if needed
3. **For each equipment booking:** (similar)
4. **Room/Equipment status auto-reset:** For each resource, if last booking end_time < new_time AND status ∈ [maintenance, disabled]: → status = available
5. **Penalty processing:**
   - Calculate no-show (end reached without checkin/checkout)
   - Calculate late penalties (delay from end_time)
   - Apply points, update restriction level
   - If user → BANNED: auto-cancel future bookings
6. **Reward processing:**
   - For each completed booking: increment streak
   - If streak == 10: apply -1 point, reset streak
7. **Restriction lifting:** Check all banned users; if restriction_until expired, clear

**Test Location:** `tests/unit/test_policy_service.py`, integration tests

---

#### 2.6.6 Message Service (`src/domain/message_service.py`)

**Purpose:** User inquiries & reports (optional feature?)  
**Current State:** Minimal implementation  
**Plan References:** Sections 6.5.3.1 mentions "패널티 이력" but no detail on message handling.
**Status:** Not explicitly required by plan; **Ambiguity Flag:** Confirm scope.

**Test Location:** `tests/unit/test_message_service.py`

---

### 2.7 Storage Layer (`src/storage/`)

#### 2.7.1 File Lock & Atomic Writer (`file_lock.py`, `atomic_writer.py`)

**Purpose:** Concurrent file access, multi-file transactions  
**Current State:** Exists  
**Plan References:** 5.7 (Integrity check)  
**No Changes Needed:** Existing implementation sufficient.

**Test Location:** `tests/integration/test_concurrency.py`

---

#### 2.7.2 JSONL Handler & Repositories (`jsonl_handler.py`, `repositories.py`)

**Purpose:** Data file I/O with field escaping  
**Current State:** Exists  
**Plan References (5.1):**

| Requirement | Current | Status |
|---|---|---|
| Field separator: `\|` | ✓ | Exists |
| Escape `\|` → `\\|` | ✓ | Exists |
| Escape `\\` → `\\\\` | ✓ | Exists |
| Null value: `\-` | ✓ | Exists |
| Empty string: ` ` (no char) | ✓ | Exists |
| No empty lines | ✓ | Exists |
| Date format: YYYY-MM-DD | ✓ | Exists |
| Time format: HH:MM | ✓ | Exists |
| DateTime format: YYYY-MM-DDTHH:MM | ✓ | Exists |
| UTF-8 encoding | ✓ | Exists |
| Unix line endings (LF) | ? | **Verify** |

**Mandatory Files on Startup (5.7):**
- `data/users.txt` (with admin seed?)
- `data/rooms.txt` (with 9 rooms seed?)
- `data/equipment_assets.txt` (with 12 equipment seed?)
- `data/room_bookings.txt`
- `data/equipment_bookings.txt`
- `data/penalties.txt`
- `data/audit_log.txt`

**Test Location:** `tests/unit/test_jsonl_handler.py`

---

### 2.8 Runtime Clock (`src/runtime_clock.py`)

**Purpose:** Virtual time management, time advance events  
**Current State:** Exists  
**Plan References (6.3):**

| Feature | Spec | Current Status |
|---|---|---|
| Bootstrap (first run) | 6.1 | Store initial date & slot in config |
| Current time getter | 6.3.2 | get_current_time() → datetime |
| Time advance logic | 6.3.3 | Transition 09:00 ↔ 18:00, auto-date increment |
| Event orchestration | 6.3.3 | Trigger all penalties, auto-approvals, resets |

**Test Location:** `tests/unit/test_config.py`, integration tests

---

### 2.9 Config & Bootstrap (`src/config.py`, `src/clock_bootstrap.py`)

**Purpose:** Program configuration, initial setup  
**Current State:** Basic implementation  
**Plan References (2.1, 6.1):**

| Setting | Spec | Current |
|---|---|---|
| Python 3.13+ requirement | 2.1 | ? (Document in README) |
| Data directory path | 2.2 | `./data/` |
| Initial time slot | 6.1 | **Must store** on first run |
| Admin seed account | Script | Via `scripts/seed_data.py` |

**Test Location:** `tests/unit/test_config.py`

---

## 3. TEST MATRIX & COVERAGE

**Test Files to Create/Expand:**

| Test File | Purpose | Spec Coverage | Priority |
|---|---|---|---|
| `test_validators.py` | Input grammar rules | 4.1-4.4 | **HIGH** |
| `test_user_menu.py` | User workflows (room/equipment/info) | 6.5 | **HIGH** |
| `test_admin_menu.py` | Admin workflows (approval, status, penalty) | 6.6 | **HIGH** |
| `test_room_service.py` | Room booking state machine | 6.5.1, 6.6.1 | **HIGH** |
| `test_equipment_service.py` | Equipment booking state machine | 6.5.2, 6.6.2 | **HIGH** |
| `test_penalty_service.py` | Penalty scoring, restrictions, rewards | 6.6.3 | **HIGH** |
| `test_policy_service.py` | Business rules, time advance events | 6.3.3, 6.6.3 | **HIGH** |
| `test_auth_service.py` | Registration, login, uniqueness | 4.1, 6.2.1-6.2.2 | **MEDIUM** |
| `test_guest_menu_clock.py` | Guest signup/login/clock | 6.2, 6.2.3 | **MEDIUM** |
| Integration suite | End-to-end flows, concurrency | All | **HIGH** |

---

## 4. EXPLICIT EDGE CASES & VALIDATION RULES

### 4.1 Date Validation (4.2.1)

**Grammar (Must All Pass):**
- Format: YYYY-MM-DD OR YYYY.MM.DD OR YYYY MM DD (no mixed)
- Year: 2026-2100 (inclusive)
- Month: 01-12 (no leading zero dropping; "2099-1-1" FAILS)
- Day: 01-31 (depends on month)

**Semantic (Calendar-aware):**
- February 29 only valid in leap years
- February max 28/29
- April, June, September, November max 30
- Jan, March, May, July, Aug, Oct, Dec max 31

**Examples (Plan 4.2.1):**
- ✓ 2099-01-01, 2099.01.01, 2099 01 01
- ✗ 2099-1-1 (no leading zero)
- ✗ 2099-01.01 (mixed separators)
- ✗ 2100-02-30 (invalid day)
- ✗ 2099-04-31 (April max 30)

### 4.2 Time Validation (4.2.2)

**Grammar:**
- Format: HH:MM OR HHMM (no mixed)
- Value: ONLY "09:00" or "18:00" (strict for booking times)

**Examples:**
- ✓ 09:00, 0900
- ✓ 18:00, 1800
- ✗ 10:00, 17:00, 09:30 (not allowed for booking)
- ✗ 09-00, 9:00 (wrong format)

### 4.3 Username Validation (4.1.1)

**Grammar:**
- Length: 3-20 characters
- Chars: a-z, A-Z, 0-9, `_` only
- No spaces

**Semantic:**
- Case-sensitive uniqueness (Computer ≠ computer, both allowed)
- Error on duplicate

**Examples:**
- ✓ user123, User_123, student_2024
- ✗ ab (too short)
- ✗ user@123 (special char)
- ✗ user name (space)

### 4.4 Password Validation (4.1.2)

**Grammar:**
- Length: 4-50 characters
- No spaces (other chars OK)

**Semantic:**
- Case-sensitive equality

**Examples:**
- ✓ Pass123!, abc@, PASSWORD
- ✗ Pass (too short)
- ✗ pass word (space)
- ✗ abc (too short)

### 4.5 Occupancy Validation (6.5.1.2)

**Range:** 1-8 only  
**Error Messages:**
- "숫자를 입력해주세요." (not a number)
- "1 이상의 인원을 입력해주세요." (≤ 0)
- "수용 가능한 최대 인원은 8명입니다." (≥ 9)

### 4.6 Date Range Validation (6.5.1.2)

**Start Date Checks:**
- No today: "당일 예약은 불가합니다. 내일부터 예약 가능합니다."
- No past: "과거 날짜는 예약할 수 없습니다."
- Max +180 days: "예약 시작일은 오늘로부터 180일 이내여야 합니다."

**End Date Checks:**
- Not before start: "종료일은 시작일보다 빠를 수 없습니다."
- Max 14-day duration: "예약 기간은 최대 14일까지 가능합니다."

**Special Cases:**
- Same-day booking: NOT allowed (당일 예약은 불가)
- Time auto-fixed: All bookings are 09:00 ~ 18:00 (固定)
- Duration: Spans midnight (e.g., 1/10 09:00 ~ 1/11 18:00 = 2 calendar days = valid)

### 4.7 Room Selection (6.5.1.2)

**Capacity Matching:**
- Sort available by capacity ASC
- Prefer smallest fitting room
- If larger selected while smaller available: "더 작은 회의실이 예약 가능합니다. 해당 회의실을 먼저 이용해주세요."

**Conflict Detection:**
- No overlapping "active" (reserved, checkin_requested, checked_in, checkout_requested) bookings on same room
- Completed/cancelled/admin_cancelled don't conflict

**Availability Criteria:**
- Status: available (not maintenance/disabled)
- Capacity: ≥ occupancy
- No conflicts in [start, end] range

### 4.8 User State Enforcement (6.5.1.2, 6.5.2.2)

**BANNED (이용금지):**
- No new bookings
- Error: "이용이 금지된 상태입니다. 해제일: YYYY-MM-DD"
- Release date = restriction_until field

**RESTRICTED (제한) with Active Booking:**
- Max 1 active room booking (not affected by equipment booking count)
- Max 1 active equipment booking (not affected by room booking count)
- Wait, spec says "회의실 활성 예약과 장비 활성 예약은 각각 독립적으로 카운트한다" (counted separately)
- So user can have 1 room + 1 equipment active simultaneously, but not 2 room + 1 equipment
- Error: "패널티로 인해 추가 예약이 불가합니다."

**Clarification Needed:**
- Plan 6.5.1.2 says "제한(restricted) 상태에서 회의실 활성 예약이 1건 이상인 경우" - this means if already have 1 active room booking, can't book another room
- But can still book equipment (separate count)
- **Assumption:** Active counts: (active_rooms) and (active_equipment) tracked independently; max 1 each when RESTRICTED

### 4.9 Same-Day Cancel Penalty (6.5.1.5, 6.5.1.0)

**Trigger:**
- Cancel where start_time == current_time (same 09:00 slot)
- Status: reserved → cancelled
- Penalty: +2 points

**Confirmation Dialog:**
- "직전 취소로 인해 패널티 2점이 부과됩니다. 그래도 취소하시겠습니까?"
- User must confirm again; if n/no/아니오/ㄴ → cancel aborted, no penalty

**Recording:**
- Penalty record: reason="late_cancel", points=2, related_type="room_booking"
- Booking record: cancelled_at=current_time, status=cancelled

---

## 5. AMBIGUITIES & CLARIFICATIONS NEEDED

| # | Issue | Spec Section | Impact | Assumption |
|---|---|---|---|---|
| 1 | Username duplicate checking: case-sensitive or insensitive? | 4.1.1 | HIGH | Both "Computer" and "computer" allowed (case-SENSITIVE) |
| 2 | User role can advance time slot? | 6.5.3.2 vs 6.2.3 | MEDIUM | Users CAN advance time (admin feature implied to be accessible by admins) |
| 3 | Normal use streak counter: include early checkout? | 6.6.3.3.2 | LOW | Yes, any completed booking counts as 1 use |
| 4 | Equipment serial format enforcement | 4.3.2 | MEDIUM | Format [TYPE]-[NUMBER] enforced, not free-form |
| 5 | Memo/Reason field: empty string allowed on all fields? | 4.4 | LOW | Yes, 0-20 chars includes 0 (empty) |
| 6 | Room state [사용불가] visibility to users | 6.5.1.1 | LOW | Show as [사용불가] but also show note "예약 불가 (문의: 관리자에게 연락하세요)" |
| 7 | Penalty points negative allowed? | 6.6.3.3.2 | MEDIUM | No, min 0; reward can't go below 0 |
| 8 | Early checkout penalty: how to calculate actual delay? | 6.3.3, 6.6.3.5-6 | HIGH | **Urgent clarification:** If user checks out BEFORE end_time, is there a penalty? Or is "late return/checkout" only if AFTER? |
| 9 | Auto-cancel future bookings on ban: include overlapping? | 6.6.3 | MEDIUM | Auto-cancel all future (reserved, pickup_requested) bookings for banned user |
| 10 | Admin approval deadlines (09:00, 18:00): what if admin offline? | 6.6.1, 6.6.2 | MEDIUM | Auto-approval logic handles this (on time advance by any actor, system processes) |

---

## 6. IMPLEMENTATION PRIORITY & ORDER

### Phase 1 (Foundation): Validators & Models
1. Expand `src/cli/validators.py`: All grammar/semantic validators (4.1-4.4)
2. Verify `src/domain/models.py`: Enum consistency, dataclass fields match plan

### Phase 2 (Core Services): Business Logic
3. Expand `src/domain/room_service.py`: State machine, conflict detection
4. Expand `src/domain/equipment_service.py`: Parallel to room service
5. Expand `src/domain/penalty_service.py`: Scoring, restriction levels, rewards
6. Expand `src/domain/policy_service.py`: Business rule checks, time advance orchestration

### Phase 3 (UI/CLI): Menu Handlers
7. Expand `src/cli/user_menu.py`: Room/equipment submenus with full validation
8. Expand `src/cli/admin_menu.py`: Approval/penalty/status management
9. Expand `src/cli/guest_menu.py`: Registration/login with error messages

### Phase 4 (Integration & Testing)
10. Create comprehensive test suite (unit + integration + E2E)
11. Verify storage layer, concurrency handling
12. Bootstrap & seed data script validation

---

## 7. SUMMARY TABLE: AFFECTED FILES

| File Path | Module | Spec Coverage | Change Type | Priority |
|---|---|---|---|---|
| `src/cli/validators.py` | Input validation | 4.1-4.4 | **EXPAND** | HIGH |
| `src/cli/user_menu.py` | User workflows | 6.5 | **EXPAND** | HIGH |
| `src/cli/admin_menu.py` | Admin workflows | 6.6 | **EXPAND** | HIGH |
| `src/cli/guest_menu.py` | Guest flows | 6.2.1-6.2.3 | **EXPAND** | MEDIUM |
| `src/cli/clock_menu.py` | Time management | 6.3 | **VERIFY** | MEDIUM |
| `src/domain/auth_service.py` | Authentication | 4.1, 6.2 | **MINOR** | MEDIUM |
| `src/domain/room_service.py` | Room bookings | 6.5.1, 6.6.1 | **EXPAND** | HIGH |
| `src/domain/equipment_service.py` | Equipment bookings | 6.5.2, 6.6.2 | **EXPAND** | HIGH |
| `src/domain/penalty_service.py` | Penalty management | 6.6.3 | **EXPAND** | HIGH |
| `src/domain/policy_service.py` | Business rules | 6.3.3, 6.6.3 | **EXPAND** | HIGH |
| `src/domain/message_service.py` | User messages | ? | ? | LOW |
| `src/storage/repositories.py` | Data I/O | 5 | **VERIFY** | MEDIUM |
| `src/runtime_clock.py` | Virtual time | 6.3 | **VERIFY** | MEDIUM |
| `src/config.py` | Configuration | 2, 6.1 | **MINOR** | MEDIUM |
| `main.py` | Entry point | 2.3, 6.1 | **VERIFY** | LOW |
| `tests/unit/test_*.py` | Unit tests | All | **CREATE/EXPAND** | HIGH |
| `tests/integration/test_*.py` | Integration tests | Concurrency, flows | **CREATE/EXPAND** | HIGH |

---

## 8. EXISTING IMPLEMENTATION PATTERNS TO PRESERVE

1. **Modularization:** Keep cli/, domain/, storage/ separation
2. **State Machine:** Room/Equipment bookings use status enums, field recording on transitions
3. **JSONL Storage:** All data in `data/*.txt` with field escaping
4. **Runtime Clock:** Single global time source, no local time assumptions
5. **Error Messages:** Korean language, specific phrasing for each error type
6. **Menu Flow:** Input validation loop (retry on invalid input)
7. **Dataclass + Enum:** Type-safe models with JSON serialization
8. **File Locking:** Atomic multi-file writes via UnitOfWork

---

## 9. NO ARCHITECTURE CHANGES REQUIRED

- ✓ Current modularization appropriate
- ✓ No new module boundaries needed
- ✓ Service layer sufficient for business logic
- ✓ Storage layer supports all data structures
- ✓ CLI-layer menu dispatch works for expanded features

---

## END OF ANALYSIS

**Generated:** 2026-04-06  
**Analyzer:** OpenCode Sisyphus  
**Status:** Ready for implementation  
**Next Step:** Verify ambiguities (Section 5) with stakeholder; proceed with Phase 1 (validators)
