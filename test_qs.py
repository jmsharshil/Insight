import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "insight.settings")
django.setup()

from auth_user.models import Organization, User
from branch.models import Branch
from batches.models import Course, Subject, Batch, Classroom
from faculty.models import FacultyProfile
from students.models import Student
from exams.models import Exam
from leave.models import LeavePolicy

def test_qs():
    print("Testing User...")
    list(User.objects.values('id', 'name', 'email', 'role', 'branch_id')[:1])
    
    print("Testing Branch...")
    list(Branch.objects.values('id', 'name', 'organization_id', 'city')[:1])

    print("Testing Student...")
    list(Student.objects.values('id', 'user__name', 'user__email', 'admission_number', 'branch_id')[:1])

    print("Testing FacultyProfile...")
    list(FacultyProfile.objects.values('id', 'user__name', 'employee_id', 'branch_id')[:1])

    print("Testing Course...")
    list(Course.objects.values('id', 'name', 'organization_id', 'duration_months')[:1])

    print("Testing Subject...")
    list(Subject.objects.values('id', 'name', 'course_id', 'code')[:1])

    print("Testing Batch...")
    list(Batch.objects.values('id', 'name', 'course_id', 'organization_id')[:1])

    print("Testing Classroom...")
    list(Classroom.objects.values('id', 'name', 'capacity', 'organization_id')[:1])

    print("Testing Exam...")
    list(Exam.objects.values('id', 'title', 'exam_type', 'status', 'branch_id')[:1])

    print("Testing LeavePolicy...")
    list(LeavePolicy.objects.values('id', 'leave_type', 'annual_quota', 'branch_id')[:1])
    
    print("ALL OK!")

test_qs()
