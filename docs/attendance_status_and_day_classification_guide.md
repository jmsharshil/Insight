# Employee Attendance Logic & Status Classification Guide

This document describes the complete business logic, conditions, priority hierarchies, and calculation rules for employee attendance statuses in the Insight platform. **This document contains only conceptual and operational business logic without code snippets.**

---

## 1. Attendance Status Master Reference

| Status | Display Label | Description | Counts as Absent? | Included in Working Days? | Penalizes Attendance %? |
| :--- | :--- | :--- | :---: | :---: | :---: |
| **Present** | Present | Employee attended work, checked in, and checked out. | **No** | **Yes** | **No** (Counts as attended) |
| **Late** | Late | Employee checked in after the grace period and completed their shift. | **No** | **Yes** | **No** (Counts as attended) |
| **Half Day** | Half Day | Employee completed between 5 and 8 hours on a regular working day. | **No** | **Yes** | **No** (Counts as attended) |
| **Check-in Pending** | Check-in | Employee has checked in and their work session is currently active. | **No** | **Yes** | **No** (Active session) |
| **Week Off** | Week Off | Scheduled off-day: Sunday, designated Saturday off, or weekly schedule day off. | **No** | **No (Excluded)** | **No** (Neutral) |
| **Public Holiday** | Public Holiday | Recognized official organization or branch holiday. | **No** | **No (Excluded)** | **No** (Neutral) |
| **Sick Leave** | Sick Leave | Approved medical/health leave application. | **No** | **No (Excluded)** | **No** (Neutral) |
| **Paid Leave** | Paid Leave | Approved paid annual/earned leave application. | **No** | **No (Excluded)** | **No** (Neutral) |
| **Casual Leave** | Casual Leave | Approved casual/personal leave application. | **No** | **No (Excluded)** | **No** (Neutral) |
| **Absent** | Absent | Scheduled working day where the employee did not attend and had no approved leave. | **YES** | **YES** | **YES** (Reduces %) |

---

## 2. Day Status Evaluation Hierarchy

When the system checks an employee's status for a date where no active check-in took place (such as during End-of-Day automated processing, attendance history retrieval, or cleanup of stale records), it evaluates conditions in the following **strict sequential order**:

```
[Start Evaluation for Employee & Date]
                   │
                   ▼
       1. Is it a Public Holiday?
          ├── YES ──► Assign status: Public Holiday
          └── NO
                   │
                   ▼
       2. Is there an Approved Leave?
          ├── YES ──► Assign status: Specific Leave Type (Sick, Paid, Casual, etc.)
          └── NO
                   │
                   ▼
       3. Is the day a Sunday?
          ├── YES ──► Assign status: Week Off
          └── NO
                   │
                   ▼
       4. Is it a Scheduled Day Off (Saturday / Weekly Schedule)?
          ├── YES ──► Assign status: Week Off
          └── NO
                   │
                   ▼
       5. Default Fallback
          └───► Assign status: Absent
```

---

### Step-by-Step Evaluation Conditions

### Step 1: Public Holiday Check
* **Condition**:
  * An official holiday is recorded for the given date.
  * The holiday applies either to the employee's specific branch, the employee's organization, or is an all-branch organization-wide holiday.
* **Outcome**:
  * The date is classified as **Public Holiday**.
  * It is treated as an official non-working day.
  * It is completely excluded from working days and absent counts.
  * It never triggers any attendance or no-show violation.

---

### Step 2: Approved Leave Check
* **Condition**:
  * The employee has an approved leave request whose date range covers this day.
  * The leave status must be officially marked as Approved (pending or rejected leaves do not qualify).
* **Outcome**:
  * The date receives the specific approved leave type:
    * Medical / Health leave $\rightarrow$ **Sick Leave**
    * Annual / Earned leave $\rightarrow$ **Paid Leave**
    * Casual / Personal leave $\rightarrow$ **Casual Leave**
    * Any other specific leave category $\rightarrow$ That specific category leave
  * It is treated as an authorized absence.
  * It is excluded from total working days and absent counts.
  * It never reduces the employee's attendance percentage.

---

### Step 3: Sunday Check
* **Condition**:
  * The day of the week is Sunday.
  * The employee did not work on this Sunday.
  * The Sunday is not covered by an official public holiday or approved leave.
* **Outcome**:
  * The date is classified as **Week Off**.
  * Sunday is treated as a standard non-working off-day across the system.
  * It is excluded from working days and absent counts.
  * It does not penalize attendance percentage or trigger violations.

---

### Step 4: Scheduled Week Off Check (Saturday Rules & Weekly Schedule)
* **Condition**:
  * The day is not Sunday, but is configured as an off-day for the employee:
  * **Saturday Rules**:
    * **Odd Rule**: The 1st, 3rd, and 5th Saturdays of the month are working days; the 2nd and 4th Saturdays are off-days (**Week Off**).
    * **Even Rule**: The 2nd and 4th Saturdays of the month are working days; the 1st, 3rd, and 5th Saturdays are off-days (**Week Off**).
    * **Off Rule**: All Saturdays of the month are off-days (**Week Off**).
    * **All Rule**: All Saturdays of the month are regular working days.
  * **Custom Weekly Schedule**:
    * Any day of the week (Monday through Saturday) where the employee's profile explicitly defines that day as an off-day.
* **Outcome**:
  * The date is classified as **Week Off**.
  * It is excluded from working days and absent counts.

---

### Step 5: Regular Working Day (Absent)
* **Condition**:
  * The day is a regular working day for the employee.
  * The employee did not check in.
  * No public holiday was declared.
  * No approved leave request exists.
* **Outcome**:
  * The date is classified as **Absent**.
  * It is included in working days.
  * It directly reduces the employee's attendance percentage.
  * It is flagged as an unexcused absence ("No Show") in employee violation reports.

---

## 3. Logic When an Employee Works on a Sunday or Week-Off

When an employee voluntarily comes in to work on a Sunday or their scheduled week-off, the following logic applies:

### 1. Automatic Removal of Placeholder Records
* Before the employee arrives, automated system jobs or previous syncs may have created an unattended placeholder record with status `Week Off`, `Holiday`, or `Absent` (with no check-in timestamp).
* When the employee scans or checks in:
  * The system immediately detects and purges the unattended placeholder record.
  * A single, clean active session is established with the employee's actual arrival time.
  * This guarantees that duplicate or contradictory entries never appear on the same date.

### 2. Status Assigned on Check-Out
* When the employee checks out, their attendance status is recorded as **Present**.

### 3. Voluntary Work Protection (No Demotion to Absent or Half Day)
* On a regular working day, an employee who works less than 5 hours is normally demoted to Absent.
* **On an off-day (Sunday or Week Off)**: Because this is voluntary or overtime attendance, the standard 5-hour threshold rule does **not** demote the employee.
* Even if the employee only works for 2, 3, or 4 hours on their off-day, their status remains **Present**.

### 4. Zero Required Hours & No Shortfall Penalties
* On a scheduled off-day or Sunday, the required shift duration for the employee is **0 hours**.
* Because the required hours are zero:
  * No shift shortfall is calculated.
  * No shortfall penalty or warning is issued.

### 5. Impact on Summaries and Reports
* In monthly or date-range summaries:
  * The day is counted as **1 Present Day**.
  * The day is counted as **1 Working Day** (since the employee actively worked).
  * The day is **not** counted as a week-off or absence.
  * Attendance percentage for that day is **100%**.

---

## 4. Shift Duration & Half-Day Rules on Regular Working Days

On regular scheduled working days, the duration of time between check-in and check-out determines the final status:

| Actual Hours Worked | Final Status Assigned | System Explanation |
| :--- | :--- | :--- |
| **Fewer than 5.0 hours** | **Absent** | Did not meet the minimum half-day threshold of 5 hours. |
| **5.0 hours up to 8.0 hours** | **Half Day** | Met the minimum threshold for half-day attendance. Counted as attended in summary statistics. |
| **8.0 hours or more** | **Present** | Completed full working shift. |

### Half-Day Leave Exception
* If an employee has applied for and received approval for a **Half-Day Leave**:
  * Their required shift duration for that day is automatically reduced to **5.0 hours**.
  * Completing 5.0 hours satisfies their work requirement for the day and does not generate a shortfall violation.

---

## 5. Attendance Statistics & Mathematical Formulas

The system separates calendar days into working days versus non-working days so that employees are never penalized for days they were not scheduled to work.

### Definition of Working Days
Working days represent only the dates on which the employee was actually expected to work:

$$\text{Working Days} = \text{Total Calendar Days} - (\text{Public Holidays} + \text{Week Offs} + \text{Approved Leaves})$$

Equivalently, in terms of recorded attendance:

$$\text{Working Days} = \text{Present Days} + \text{Late Days} + \text{Half Days} + \text{Absent Days}$$

### Definition of Attended Days
Days on which the employee fulfilled work duties:

$$\text{Attended Days} = \text{Present Days} + \text{Late Days} + \text{Half Days}$$

### Attendance Percentage Formula
$$\text{Attendance Percentage} = \left(\frac{\text{Attended Days}}{\text{Working Days}}\right) \times 100$$

*(If $\text{Working Days} = 0$, $\text{Attendance Percentage} = 0.0\%$)*

### Why Holidays, Week-Offs, and Leaves Do Not Penalize the Percentage:
* Public holidays, Sundays, scheduled week-offs, and approved leaves are subtracted from both the numerator and the denominator.
* **Example**:
  * In a 30-day month with 4 Sundays, 2 alternate Saturday week-offs, 1 public holiday, and 1 approved sick leave:
    * Non-working days = $4 + 2 + 1 + 1 = 8$ days.
    * Actual working days = $30 - 8 = 22$ days.
    * If the employee is present for all 22 working days, their attendance percentage is $\frac{22}{22} \times 100 = \mathbf{100.0\%}$ (not $\frac{22}{30} = 73.3\%$).
    * If the employee misses 1 working day unexcused (1 absent day):
      * Present = 21 days, Absent = 1 day, Working days = 22 days.
      * Percentage = $\frac{21}{22} \times 100 = \mathbf{95.5\%}$.

---

## 6. End-of-Day (EOD) Processing & Stale Record Sync

### Automated Daily Processing
* Every evening at the conclusion of standard operating hours, the automated system reviews all active staff members.
* For each employee:
  * If the employee has already checked in or checked out, their record is left intact (**Present** is preserved).
  * If the employee has no attendance record for the day, the system evaluates the **5-step Day Status Evaluation Hierarchy** and automatically marks the day as `Week Off`, `Public Holiday`, specific `Leave Type`, or `Absent`.

### Automatic Stale Record Correction
* Whenever an employee or administrator opens attendance history or detail screens, the system automatically checks for any historical anomalies:
  * Any historical unexcused `Absent` entry that coincidentally fell on a Sunday, scheduled week-off, public holiday, or approved leave is automatically updated to its correct status.
  * Any legacy Sunday entry previously recorded as `Holiday` is updated to `Week Off` (unless an official public holiday fell on that date).
  * Valid, administrator-entered public holidays on regular weekdays are preserved.
