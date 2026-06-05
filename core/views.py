from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated

from auth_user.models import Organization, User
from branch.models import Branch
from batches.models import Course, Subject, Batch, Classroom
from faculty.models import FacultyProfile
from students.models import Student
from exams.models import Exam
from leave.models import LeavePolicy

class PublicDropdownsView(APIView):
    """
    API for unauthenticated users (without token).
    Returns basic organizational structures and courses.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        organizations = Organization.objects.values('id', 'name')
        branches = Branch.objects.values('id', 'name', 'organization_id', 'city')
        courses = Course.objects.values('id', 'name', 'organization_id')
        
        return Response({
            "success": True,
            "data": {
                "organizations": list(organizations),
                "branches": list(branches),
                "courses": list(courses),
                "roles": [{"value": r[0], "label": r[1]} for r in User.ROLE_CHOICES]
            }
        })

class AuthenticatedDropdownsView(APIView):
    """
    API for authenticated users (with token).
    Returns comprehensive dropdown data filtered by the user's organization.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        org_id = user.organization_id if user.organization else None
        
        # Base queries - filtered by organization if user has one
        # Users
        users_qs = User.objects.all()
        branches_qs = Branch.objects.all()
        students_qs = Student.objects.all()
        faculty_qs = FacultyProfile.objects.all()
        courses_qs = Course.objects.all()
        subjects_qs = Subject.objects.all()
        batches_qs = Batch.objects.all()
        classrooms_qs = Classroom.objects.all()
        exams_qs = Exam.objects.filter(is_deleted=False)
        leave_policies_qs = LeavePolicy.objects.filter(is_active=True)

        if org_id:
            users_qs = users_qs.filter(organization_id=org_id)
            branches_qs = branches_qs.filter(organization_id=org_id)
            students_qs = students_qs.filter(branch__organization_id=org_id)
            faculty_qs = faculty_qs.filter(branch__organization_id=org_id)
            courses_qs = courses_qs.filter(organization_id=org_id)
            subjects_qs = subjects_qs.filter(organization_id=org_id)
            batches_qs = batches_qs.filter(organization_id=org_id)
            classrooms_qs = classrooms_qs.filter(organization_id=org_id)
            exams_qs = exams_qs.filter(branch__organization_id=org_id)
            leave_policies_qs = leave_policies_qs.filter(branch__organization_id=org_id)

        # Build responses
        users = list(users_qs.values('id', 'name', 'email', 'role', 'branch_id'))
        branches = list(branches_qs.values('id', 'name', 'organization_id', 'city'))
        students = list(students_qs.values('id', 'user__name', 'user__email', 'admission_number', 'branch_id'))
        
        # Format students to use 'name' and 'email' directly
        for s in students:
            s['name'] = s.pop('user__name')
            s['email'] = s.pop('user__email')

        faculty = list(faculty_qs.values('id', 'user__name', 'employee_id', 'branch_id'))
        for f in faculty:
            f['name'] = f.pop('user__name')

        courses = list(courses_qs.values('id', 'name', 'organization_id', 'duration_months'))
        subjects = list(subjects_qs.values('id', 'name', 'course_id', 'code'))
        batches = list(batches_qs.values('id', 'name', 'course_id', 'organization_id'))
        classrooms = list(classrooms_qs.values('id', 'name', 'capacity', 'organization_id'))
        exams = list(exams_qs.values('id', 'title', 'exam_type', 'status', 'branch_id'))
        leave_policies = list(leave_policies_qs.values('id', 'leave_type', 'annual_quota', 'branch_id'))

        return Response({
            "success": True,
            "data": {
                "roles": [{"value": r[0], "label": r[1]} for r in User.ROLE_CHOICES],
                "users": users,
                "branches": branches,
                "students": students,
                "faculty": faculty,
                "courses": courses,
                "subjects": subjects,
                "batches": batches,
                "classrooms": classrooms,
                "exams": exams,
                "leave_policies": leave_policies,
            }
        })
