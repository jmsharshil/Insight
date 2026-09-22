# Leave Approval Flow

This document outlines the updated leave approval workflow and notification logic for employees in the organization.

## Notification on Leave Application

When an employee submits a leave application, initial notifications are sent to the designated approvers based on the applicant's role:

| Applicant Role | Notified Approvers |
|---|---|
| `counsellor`, `sales_senior_executive`, `sales_executive` | `cmo` and `super_admin` |
| All other employees (including `admin_senior_executive`) | `head_coordinator` and `branch_manager` |

## Leave Approval Workflow

The approval process consists of a mandatory two-step workflow. Both steps must be completed for a leave application to be marked as `approved`.

### 1. Sales Team Flow
Applies to: `counsellor`, `sales_senior_executive`, `sales_executive`

*   **Step 1 Approval:** Must be completed by the `cmo`.
*   **Step 2 (Final) Approval:** Must be completed by the `super_admin`.

### 2. Regular Employee Flow
Applies to: All other roles (e.g., `admin_senior_executive`, `tele_caller`, etc.)

*   **Step 1 Approval:** Must be completed by the `head_coordinator`.
*   **Step 2 (Final) Approval:** Must be completed by the `branch_manager`.

### 3. Head Coordinator Flow
Applies to: `head_coordinator`

*   **Step 1 Approval:** Must be completed by the `branch_manager`.
*   **Step 2 (Final) Approval:** Must be completed by the `super_admin`.

> [!NOTE]
> If a Step 2 approver does not exist for a given branch or organization, the system will automatically finalize the approval after Step 1 is completed.

## Top-Level Exceptions
Leaves applied by the following top-level roles are subject to a single-step approval process:
*   **`branch_manager`:** Can only be approved directly by a `super_admin`.

## Leave Rejection
Any user with an authorized approval role (`branch_manager`, `cmo`, `head_coordinator`, `super_admin`) can reject a pending leave application. A push notification and WhatsApp message (if applicable) will be sent to the applicant containing the rejection reason.

## System Automated Actions
*   Upon final approval, the applicant's leave balance is automatically deducted.
*   The applicant receives a push notification and WhatsApp message confirming the status change (Approved/Rejected).
