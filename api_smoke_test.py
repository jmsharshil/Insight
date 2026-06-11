"""Smoke-test every API endpoint."""
import os, sys, json, uuid
os.environ['DJANGO_SETTINGS_MODULE'] = 'insight.settings'
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import django
django.setup()

from django.test.client import Client
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken

User = get_user_model()

# ── helpers ──────────────────────────────────────────────────────────────────
PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"
results = {"pass": 0, "fail": 0, "skip": 0}

def header(section):
    print(f"\n{'='*60}\n  {section}\n{'='*60}")

def test(method, url, client, data=None, expect=None):
    """Fire a request, print result."""
    expect = expect or [200, 201]
    try:
        if method == "GET":
            resp = client.get(f'/api/v1/{url}')
        elif method == "POST":
            resp = client.post(f'/api/v1/{url}', data=json.dumps(data or {}), content_type='application/json')
        elif method == "PATCH":
            resp = client.patch(f'/api/v1/{url}', data=json.dumps(data or {}), content_type='application/json')
        elif method == "DELETE":
            resp = client.delete(f'/api/v1/{url}')
        else:
            print(f"  {SKIP} {method} {url} (unknown method)")
            results["skip"] += 1
            return None

        status = resp.status_code
        ok = status in expect
        tag = PASS if ok else FAIL
        body_preview = ""
        try:
            body = resp.json()
            msg = body.get("message", body.get("detail", ""))
            if not ok:
                body_preview = f'  → {msg}'
                if 'errors' in body:
                    body_preview += f' {body["errors"]}'
        except Exception:
            pass
        print(f"  {tag} {method:6s} /api/v1/{url}  [{status}]{body_preview}")
        if ok:
            results["pass"] += 1
        else:
            results["fail"] += 1
        return resp
    except Exception as e:
        print(f"  {FAIL} {method:6s} /api/v1/{url}  [EXCEPTION: {e}]")
        results["fail"] += 1
        return None


# ── bootstrap data ───────────────────────────────────────────────────────────
print("Bootstrapping test data ...")

# Get or create admin user
admin_user, _ = User.objects.get_or_create(
    username='smoke_admin',
    defaults=dict(email='smoke@test.com', role='super_admin', is_active=True, is_staff=True, is_superuser=True)
)
admin_user.set_password('Test1234!')
admin_user.role = 'super_admin'
admin_user.save()

token = str(AccessToken.for_user(admin_user))
client = Client(HTTP_AUTHORIZATION=f'Bearer {token}')

# ═════════════════════════════════════════════════════════════════════════════
#  1. COURSES
# ═════════════════════════════════════════════════════════════════════════════
header("COURSES")
test("GET", "courses/", client)

resp = test("POST", "courses/", client, data={
    "name": "Smoke CSEET",
    "code": f"SMK{uuid.uuid4().hex[:4].upper()}",
})
course_id = None
if resp and resp.status_code == 201:
    course_id = resp.json().get("data", {}).get("id") or resp.json().get("id")

if course_id:
    test("GET", f"courses/{course_id}/", client)
    test("PATCH", f"courses/{course_id}/", client, data={"description": "Updated smoke description"})
else:
    print(f"  {SKIP} Skipping course detail/patch (no course_id)")
    results["skip"] += 2

# ═════════════════════════════════════════════════════════════════════════════
#  2. COURSE LEVELS
# ═════════════════════════════════════════════════════════════════════════════
header("COURSE LEVELS")
level_id = None
if course_id:
    test("GET", f"courses/{course_id}/levels/", client)
    resp = test("POST", f"courses/{course_id}/levels/", client, data={
        "name": "Module 1",
        "course_type": "cseet",
        "fee_amount": 30000,
        "order": 1,
    })
    if resp and resp.status_code == 201:
        level_id = resp.json().get("data", {}).get("id") or resp.json().get("id")
    if level_id:
        test("GET", f"courses/{course_id}/levels/{level_id}/", client)
        test("PATCH", f"courses/{course_id}/levels/{level_id}/", client, data={"fee_amount": 35000})
    else:
        print(f"  {SKIP} Skipping level detail (no level_id)")
        results["skip"] += 2
else:
    print(f"  {SKIP} Skipping levels (no course)")
    results["skip"] += 4

# ═════════════════════════════════════════════════════════════════════════════
#  3. SUBJECTS
# ═════════════════════════════════════════════════════════════════════════════
header("SUBJECTS")
test("GET", "subjects/", client)

subject_id = None
if level_id:
    resp = test("POST", "subjects/", client, data={
        "level": level_id,
        "name": "Business Laws",
        "code": f"BL{uuid.uuid4().hex[:3].upper()}",
        "total_hours": 40,
    })
    if resp and resp.status_code == 201:
        subject_id = resp.json().get("data", {}).get("id") or resp.json().get("id")
else:
    print(f"  {SKIP} Skipping subject create (no level)")
    results["skip"] += 1

if subject_id:
    test("GET", f"subjects/{subject_id}/", client)
else:
    print(f"  {SKIP} Skipping subject detail (no subject_id)")
    results["skip"] += 1

# ═════════════════════════════════════════════════════════════════════════════
#  4. CHAPTERS
# ═════════════════════════════════════════════════════════════════════════════
header("CHAPTERS")
chapter_id = None
if subject_id:
    test("GET", f"subjects/{subject_id}/chapters/", client)
    resp = test("POST", f"subjects/{subject_id}/chapters/", client, data={
        "name": "Sources of Law",
        "order": 1,
        "duration_hours": 5,
    })
    if resp and resp.status_code == 201:
        chapter_id = resp.json().get("data", {}).get("id") or resp.json().get("id")
    if chapter_id:
        test("GET", f"subjects/{subject_id}/chapters/{chapter_id}/", client)
        test("PATCH", f"subjects/{subject_id}/chapters/{chapter_id}/", client, data={"name": "Updated Chapter"})
    else:
        print(f"  {SKIP} Skipping chapter detail (no chapter_id)")
        results["skip"] += 2
else:
    print(f"  {SKIP} Skipping chapters (no subject)")
    results["skip"] += 4

# ═════════════════════════════════════════════════════════════════════════════
#  5. BATCHES
# ═════════════════════════════════════════════════════════════════════════════
header("BATCHES")
test("GET", "batches/", client)

batch_id = None
if course_id:
    resp = test("POST", "batches/", client, data={
        "course": course_id,
        "name": "Smoke Batch",
        "batch_code": f"SMK-B-{uuid.uuid4().hex[:4].upper()}",
        "start_date": "2024-06-01",
        "end_date": "2025-06-01",
        "max_students": 50,
    })
    if resp and resp.status_code == 201:
        batch_id = resp.json().get("data", {}).get("id") or resp.json().get("id")

if batch_id:
    test("GET", f"batches/{batch_id}/", client)
    test("PATCH", f"batches/{batch_id}/", client, data={"max_students": 60})
else:
    print(f"  {SKIP} Skipping batch detail (no batch_id)")
    results["skip"] += 2

# ═════════════════════════════════════════════════════════════════════════════
#  6. CLASSROOMS
# ═════════════════════════════════════════════════════════════════════════════
header("CLASSROOMS")
test("GET", "classrooms/", client)

resp = test("POST", "classrooms/", client, data={
    "name": "Room Smoke",
    "capacity": 40,
})
classroom_id = None
if resp and resp.status_code == 201:
    classroom_id = resp.json().get("data", {}).get("id") or resp.json().get("id")

if classroom_id:
    test("GET", f"classrooms/{classroom_id}/", client)
else:
    print(f"  {SKIP} Skipping classroom detail (no classroom_id)")
    results["skip"] += 1

# ═════════════════════════════════════════════════════════════════════════════
#  7. TIMETABLE EXAM TYPES
# ═════════════════════════════════════════════════════════════════════════════
header("TIMETABLE EXAM TYPES")
test("GET", "timetable/exam-types/", client)

resp = test("POST", "timetable/exam-types/", client, data={
    "name": f"Weekly Test {uuid.uuid4().hex[:4]}",
    "description": "Short weekly assessment",
})
exam_type_id = None
if resp and resp.status_code == 201:
    exam_type_id = resp.json().get("data", {}).get("id") or resp.json().get("id")

if exam_type_id:
    test("GET", f"timetable/exam-types/{exam_type_id}/", client)
else:
    print(f"  {SKIP} Skipping exam type detail (no exam_type_id)")
    results["skip"] += 1

# ═════════════════════════════════════════════════════════════════════════════
#  8. TIMETABLE SLOTS
# ═════════════════════════════════════════════════════════════════════════════
header("TIMETABLE SLOTS")
test("GET", "timetable/", client)

# Create faculty profile for timetable
from faculty.models import FacultyProfile
from branch.models import Branch
branch_obj, _ = Branch.objects.get_or_create(
    name='Smoke Branch',
    defaults=dict(address='Test', city='Test', state='Test', pincode='000000'),
)
fac_user, _ = User.objects.get_or_create(
    username='smoke_fac',
    defaults=dict(email='smokefac@test.com', role='faculty', is_active=True),
)
fac_user.set_password('Test1234!')
fac_user.save()
fac_profile, _ = FacultyProfile.objects.get_or_create(
    user=fac_user,
    defaults=dict(
        branch=branch_obj,
        qualification='M.Com',
        specialization='Accounting',
        joining_date='2024-01-01',
    ),
)

slot_id = None
if batch_id and subject_id:
    resp = test("POST", "timetable/", client, data={
        "batch": batch_id,
        "subject": subject_id,
        "faculty": str(fac_profile.id),
        "classroom": str(classroom_id) if classroom_id else None,
        "day_of_week": 1,
        "session_date": "2024-06-01",
        "start_time": "09:00:00",
        "end_time": "11:00:00",
        "session_type": "regular",
        "slot_code": "P1",
    })
    if resp and resp.status_code == 201:
        slot_id = resp.json().get("data", {}).get("id") or resp.json().get("id")

    # Prelim test
    test("POST", "timetable/", client, data={
        "batch": batch_id,
        "subject": subject_id,
        "day_of_week": 2,
        "session_date": "2024-06-02",
        "start_time": "14:00:00",
        "end_time": "17:00:00",
        "session_type": "prelim",
        "examiner": str(fac_profile.id),
        "timetable_exam_type": exam_type_id if exam_type_id else None,
    })
else:
    print(f"  {SKIP} Skipping timetable create (missing batch/subject)")
    results["skip"] += 2

if slot_id:
    test("GET", f"timetable/{slot_id}/", client)
    test("PATCH", f"timetable/{slot_id}/", client, data={"start_time": "08:00:00", "slot_code": "P1"})
else:
    print(f"  {SKIP} Skipping timetable detail (no slot_id)")
    results["skip"] += 2

# Faculty timetable
test("GET", f"timetable/faculty/{fac_profile.id}/", client)

# ═════════════════════════════════════════════════════════════════════════════
#  9. BRANCHES
# ═════════════════════════════════════════════════════════════════════════════
header("BRANCHES")
test("GET", "branches/", client)

# ═════════════════════════════════════════════════════════════════════════════
#  10. LEADS
# ═════════════════════════════════════════════════════════════════════════════
header("LEADS")
test("GET", "leads/", client)

# ═════════════════════════════════════════════════════════════════════════════
#  11. ADMISSIONS
# ═════════════════════════════════════════════════════════════════════════════
header("ADMISSIONS")
test("GET", "admissions/", client)

# ═════════════════════════════════════════════════════════════════════════════
#  12. STUDENTS
# ═════════════════════════════════════════════════════════════════════════════
header("STUDENTS")
test("GET", "students/", client)

# ═════════════════════════════════════════════════════════════════════════════
#  13. FACULTY
# ═════════════════════════════════════════════════════════════════════════════
header("FACULTY")
test("GET", "faculty/", client)
test("GET", f"faculty/{fac_profile.id}/", client)

# ═════════════════════════════════════════════════════════════════════════════
#  14. FEES
# ═════════════════════════════════════════════════════════════════════════════
header("FEES")
test("GET", "fee-structures/", client)
test("GET", "student-fees/", client)
test("GET", "payments/", client)
test("GET", "installments/", client)
test("GET", "refunds/", client)

# ═════════════════════════════════════════════════════════════════════════════
#  15. ATTENDANCE
# ═════════════════════════════════════════════════════════════════════════════
header("ATTENDANCE")
test("GET", "attendance/", client)
test("GET", "attendance/violations/", client)

# ═════════════════════════════════════════════════════════════════════════════
#  16. LEAVE
# ═════════════════════════════════════════════════════════════════════════════
header("LEAVE")
test("GET", "leave/", client)
test("GET", "leave/policy/", client)
test("GET", "leave/public-holidays/", client)

# ═════════════════════════════════════════════════════════════════════════════
#  17. PAYROLL
# ═════════════════════════════════════════════════════════════════════════════
header("PAYROLL")
test("GET", "payroll/", client)
test("GET", "payroll/late-policy/", client)

# ═════════════════════════════════════════════════════════════════════════════
#  18. EXAMS
# ═════════════════════════════════════════════════════════════════════════════
header("EXAMS")
test("GET", "exams/", client)

# ═════════════════════════════════════════════════════════════════════════════
#  19. CHAT
# ═════════════════════════════════════════════════════════════════════════════
header("CHAT")
test("GET", "chat/rooms/", client)

# ═════════════════════════════════════════════════════════════════════════════
#  20. REPORTS
# ═════════════════════════════════════════════════════════════════════════════
header("REPORTS")
test("GET", "reports/dashboard/", client)

# ═════════════════════════════════════════════════════════════════════════════
#  21. DROPDOWNS
# ═════════════════════════════════════════════════════════════════════════════
header("DROPDOWNS")
test("GET", "dropdowns/auth/", client)
test("GET", "dropdowns/public/", client)

# ═════════════════════════════════════════════════════════════════════════════
#  SUMMARY
# ═════════════════════════════════════════════════════════════════════════════
print(f"\n{'═'*60}")
print(f"  RESULTS:  {PASS} {results['pass']}   {FAIL} {results['fail']}   {SKIP} {results['skip']}")
print(f"{'═'*60}")
