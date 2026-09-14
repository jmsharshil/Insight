# Sales Module Full Flow

This document outlines the complete lifecycle and flow of the Sales/Leads Module, organized from the perspective of a salesperson's daily routine, along with the backend operations that power it.

## 1. Beginning of the Day (Attendance Check-In)

When the salesperson starts their workday, they take a selfie to log their attendance.

*   **Endpoint:** `POST /api/v1/sales/photos/` *(Generic Endpoint)*
*   **Action:** Hit this endpoint with `photo_type: "start_selfie"`.
*   **Backend Behavior:** Because no specific event ID is passed, the backend automatically looks for (or creates) a general bucket called **"Daily Field Operations"** for today and attaches this selfie. 
*   **Attendance Trigger:** Uploading the `start_selfie` instantly captures their GPS location and creates an `EmployeeAttendanceRecord` marking them as "Checked In".

## 2. Planning the Day (`SalesDailyPlan`)

Sales staff schedule the schools or clients they will visit during the day.

*   **Endpoint:** `POST /api/v1/sales/plans/`
*   **Fields:** `plan_date`, `start_time`, `end_time`, `type` (e.g., 'School Visit'), `place`, `description`.
*   **Validation:** 
    *   `end_time` must be after `start_time`.
    *   **Time Conflict Check:** The system verifies that the new event's time slot does not overlap with any existing events for that user on the same day. Overlapping events are rejected (`400 Bad Request`).
*   **Backend Behavior:** Creates a `SalesDailyPlan`. Automatically generates a linked `SalesDailyActivity` container. This container will hold all the field work photos (and the odometer) specific to this visit.

## 3. During the Day (Field Work & Odometer)

When a salesperson departs for or arrives at a scheduled visit, they capture photos specific to that event, **including their travel odometer readings**.

*   **Endpoint:** `POST /api/v1/sales/activities/<uuid:activity_id>/photos/` *(Specific Event Endpoint)*
*   **Fields:** `photo_type`, `photo`, `latitude`, `longitude`, `name` (optional label), `odometer_kms` (for odometer photos), `vehicle_type` (for start odometer).
*   **Available Types:** `start_odometer`, `end_odometer`, `school_interior`, `school_exterior`, `exhibition`, `venue`, `meeting`.
*   **Action Flow for an Event:**
    1.  **Departing for Event:** Upload `start_odometer` (with `odometer_kms` and `vehicle_type`). The system creates a pending `OdometerReading` specifically linked to this event.
    2.  **At the Event:** Upload `venue`, `meeting`, or `school_exterior` photos.
    3.  **Leaving the Event:** Upload `end_odometer` (with `odometer_kms`). The system updates the `OdometerReading` for this event, calculates total distance, and computes the travel expense (₹5/km for 2-wheelers, ₹12/km for 4-wheelers).

## 4. End of the Day (Attendance Check-Out)

The salesperson finishes their route, goes home, and ends their day in the app.

*   **Endpoint:** `POST /api/v1/sales/photos/` *(Generic Endpoint)*
*   **Action:** Hit this endpoint with `photo_type: "end_selfie"`.
*   **Backend Behavior:** The `end_selfie` finds their attendance record from the morning and updates it with a "Checked Out" time and GPS coordinates.

## 5. Monthly Approval & Payroll Integration

Instead of approving expenses day-by-day, managers can approve all odometer readings for a user for an entire month in one go.

*   **Endpoint:** `POST /api/v1/sales/odometer/monthly/approve/`
*   **Backend Behavior:** 
    1.  Finds all `pending` daily readings for the user in that month (from every event they visited) and marks them `approved`.
    2.  **Payroll Integration:** If a `draft` or `pending_approval` payslip exists for the user for that month, the system **immediately** adds the total travel expense to the payslip's `reimbursements_amount` and `net_salary`.
    3.  If no payslip exists yet, the readings wait until the payroll run is generated, at which point the system automatically pulls them in.
    4.  Sends an aggregated push/WhatsApp notification to the employee summarizing the approved kilometers and total amount.

## 6. Automated Background Tasks (Safety Nets)

*   **Reminders:** `send_sales_plan_reminders()` runs daily at 8:00 AM IST. It sends WhatsApp/In-App reminders for events scheduled for:
    1.  Today
    2.  Tomorrow
    3.  The day after tomorrow
*   **Auto Geo-Attendance Fallback:** `auto_mark_sales_attendance()` runs daily at 11:55 PM IST. If a salesperson forgot to officially check-in, but they uploaded photos from the field during the day, the system steps in. It hunts down their earliest and latest photos across *all* activities for that day and forces an attendance Check-In and Check-Out using those GPS coordinates.
