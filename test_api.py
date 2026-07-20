import os, sys, django, json
os.environ['DJANGO_SETTINGS_MODULE'] = 'insight.settings'
django.setup()

from rest_framework.test import APIRequestFactory
from attendance.views import QRScanView
from students.models import Student
from django.contrib.auth import get_user_model

User = get_user_model()
student = Student.objects.first()
user = student.user if hasattr(student, 'user') else User.objects.filter(role='student').first()
if not user:
    print("No student user found")
    sys.exit()

factory = APIRequestFactory()
url = '/api/attendance/scan/'
data = {
    'qr_data': str(student.id),
    'scan_type': 'check_in'
}
request = factory.post(url, data, format='json')
from rest_framework.authtoken.models import Token
token, _ = Token.objects.get_or_create(user=user)
request.META['HTTP_AUTHORIZATION'] = f'Token {token.key}'

# Call the view
try:
    view = QRScanView.as_view()
    response = view(request)
    print(f"Status Code: {response.status_code}")
    print(f"Response Data: {response.data}")
except Exception as e:
    import traceback
    print("CRASH!")
    traceback.print_exc()
