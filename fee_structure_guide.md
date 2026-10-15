# Creating a Fee Structure

This guide explains how Fee Structures work and how their amounts are calculated, taking into account the different course levels (CSEET vs CS Executive/Professional) and the module selections.

## 1. Course Levels and Calculations

### CSEET
For the **CSEET** course level, the module system does not apply.
- You must enter the **Total Amount** directly.
- The system will preserve whatever amount is entered as the total. If left completely blank, it will attempt to fallback to the sum of all other fee components.

### CS Executive & CS Professional
These courses are broken down into modules (1 through 5). The `total_amount` is calculated intelligently based on what institute fees are provided.

## 2. Institute Fee Module Breakdown

When creating a Fee Structure for Executive or Professional levels, you have the following Institute Fee fields available:
- `institute_fees_module_1`
- `institute_fees_module_2`
- `institute_fees_module_3`
- `institute_fees_module_4`
- `institute_fees_module_5`
- `institute_fees_all_modules`

## 3. How the "Total Amount" is Calculated

If you are setting up a Fee Structure for CS Executive or CS Professional, you do not need to manually calculate the `total_amount`. The system handles it automatically:

- **Scenario A (Specific Modules Only):** 
  If you enter fees for individual modules (e.g., Module 1 = ₹10,000 and Module 2 = ₹12,000) but leave `institute_fees_all_modules` blank, the system will:
  1. Add them together (₹10,000 + ₹12,000 = ₹22,000)
  2. Automatically set `institute_fees_all_modules` to ₹22,000
  3. Set the `total_amount` to ₹22,000

- **Scenario B (All Modules Provided):**
  If you enter a specific bulk amount for `institute_fees_all_modules` (e.g., a discounted bulk price of ₹20,000), the system will:
  1. Set the `total_amount` to exactly what you entered in `institute_fees_all_modules` (₹20,000).

## 4. Selecting the `group_module`

When associating a student, lead, or batch, you can specify the `group_module` they are enrolling in. The available options have been expanded to include:
- `all` (All Modules)
- `both` (Both Modules - kept for backward compatibility)
- `module_1` (1st Module)
- `module_2` (2nd Module)
- `module_3` (3rd Module)
- `module_4` (4th Module)
- `module_5` (5th Module)

## 5. Other Fees & Token Amount

You can also track other fees and configure the token amount:
- ICSI Registration Fees (via CSEET or Direct)
- ICSI Exam Fees
- **Token Amount**: Configured per fee structure. When a student chooses token payment, this amount is used for the Razorpay link; when choosing full payment, module fees apply.

*Note: For CS Executive/Professional, the `total_amount` strictly follows the Institute Fees calculation, while `token_amount` specifies the initial token portion.*

## 6. Syllabus Selection & Module Inspection

Fee structures now support selecting a **Syllabus** (`syllabus`):
- **Syllabus Field**: Link a Fee Structure to a specific academic syllabus (e.g., `2026 CS Executive Syllabus`).
- **Dynamic Module Count**:
  - Whenever a syllabus is selected, the system automatically inspects how many active modules belong to it (`modules_count`).
  - Returns the list of modules (`modules`: `[{ "id": "...", "name": "Module 1", "order": 1 }, ...]`).
- **Endpoints for Syllabus & Modules**:
  - `GET /api/v1/syllabuses/<syllabus_id>/modules/` — Returns the module count and module list for a selected syllabus.
  - `GET /api/v1/syllabuses/<syllabus_id>/` — Direct syllabus inspection returning `modules_count` and `modules`.
  - `GET /api/v1/batches/dropdowns/` — Preloads all active syllabuses with their precomputed `modules_count` and module list for instant frontend selection.

