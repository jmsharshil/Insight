# Payroll Module — API Documentation

The `payroll` module automates monthly salary calculations. It accounts for basic salary, hour-based teaching (from `SessionReport` records), late penalties, leave deductions, and bonuses.

---

## Data Model

| Model | Purpose |
|---|---|
| `LateEntryPolicy` | Branch-level config for late penalties (grace period, deduction per minute, auto half-day config) |
| `PayrollRun` | A monthly payroll cycle (Draft, Pending Approval, Approved, Disbursed) |
| `PaySlip` | Individual salary slip for a faculty member |
| `SessionLatePenaltyLog` | Audit log for late session penalties applied on a payslip |

---

## API Endpoints

### 1. Late Entry Policy
**`GET /api/v1/payroll/late-policy/`**
**`GET / PATCH /api/v1/payroll/late-policy/<uuid>/`**
Manage rules that penalize faculty for starting sessions late.

### 2. Payroll Runs
**`GET /api/v1/payroll/`**
**`POST /api/v1/payroll/`**
Generate a new `PayrollRun` for a specific month and year. This calculates `PaySlip`s for all faculty.

**`GET /api/v1/payroll/<payroll_id>/`**

### 3. Approval & Disbursement
**`POST /api/v1/payroll/<payroll_id>/approve/`**
Lock the payroll run.

**`POST /api/v1/payroll/<payroll_id>/disburse/`**
Mark the payroll run as paid/disbursed.

### 4. Payslips
**`GET /api/v1/payroll/<payroll_id>/payslips/`**
List all payslips generated in a specific payroll run.

**`PATCH /api/v1/payroll/<payroll_id>/payslips/<slip_id>/`**
Adjust payslip deductions or bonuses manually before approval.

### 5. Faculty Views
**`GET /api/v1/faculty/<faculty_id>/payslips/`**
Allows a faculty member to see all their historical payslips.

**`GET /api/v1/faculty/<faculty_id>/salary-preview/`**
Provides an estimated preview of the current month's salary based on sessions conducted so far.

### 6. Extra Hours Approval
**`GET /api/v1/payroll/extra-hours/`**
List all extra hours requests. Automatically generated when a faculty's total teaching time for a chapter exceeds the chapter's allocated duration.

**`PATCH /api/v1/payroll/extra-hours/<approval_id>/`**
Allows a Super Admin to approve or reject extra teaching hours. Approved hours are automatically added to the draft payroll for the month.
