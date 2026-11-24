import os, sys, django
sys.path.insert(0, r'c:\Users\Admin\OneDrive - JMS Advisory Services Private Limited\Desktop\Insight')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'insight.settings')
django.setup()

from rest_framework.test import APIClient
from rest_framework import status
from faculty.models import FacultyProfile
from auth_user.models import User

client = APIClient()

fp = FacultyProfile.objects.filter(employee_id='EMP-7E78-0002').first()
assert fp is not None, "FacultyProfile EMP-7E78-0002 should exist"
user = fp.user
client.force_authenticate(user=user)

endpoints = [
    '/api/v1/faculty/checkout-session-report/',
    '/api/v1/faculty/session-reports/autofill/',
    '/api/v1/faculty/qr-checkin/',
    f'/api/v1/faculty/checkout-session-report/?qr_data={fp.employee_id}',
    f'/api/v1/faculty/qr-checkin/?qr_data={fp.employee_id}',
]

for url in endpoints:
    resp = client.get(url)
    print(f"Testing {url} -> Status: {resp.status_code}")
    assert resp.status_code == status.HTTP_200_OK, f"Failed on {url}: {resp.data}"
    data = resp.data['data']
    assert data['faculty_id'] == str(fp.id)
    assert data['employee_id'] == fp.employee_id
    # Check top-level direct fields for checkout submission
    assert 'batch_id' in data
    assert 'subject_id' in data
    assert 'chapter_ids' in data
    assert 'topics_covered' in data
    print(f"  OK: batch={data['batch_name']}, subject={data['subject_name']}, chapter_ids={data['chapter_ids']}, topics={data['topics_covered']}")

print("\nALL VERIFICATIONS PASSED!")
