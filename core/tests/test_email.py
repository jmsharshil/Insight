import os
from django.test import TestCase
from django.core import mail
from auth_user.models import Organization
from core.email import send_email

class EmailTemplateTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(
            name='Test Org',
            logo_url='http://example.com/logo.png',
            footer_text='Custom Footer',
            primary_color='#ff0000',
            website_url='http://example.com'
        )

    def test_send_email_no_template(self):
        send_email(
            to='test@example.com',
            subject='Test Subject',
            text='Test Text',
            organization=self.org
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, 'Test Subject')
        self.assertEqual(mail.outbox[0].body, 'Test Text')
        self.assertEqual(mail.outbox[0].to, ['test@example.com'])
        self.assertFalse(hasattr(mail.outbox[0], 'alternatives') and mail.outbox[0].alternatives)

    def test_send_email_with_template(self):
        send_email(
            to='test@example.com',
            subject='Test Template Subject',
            text='Fallback Text',
            template='emails/otp.html',
            template_context={'user_name': 'John Doe', 'otp_code': '123456'},
            organization=self.org
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, 'Test Template Subject')
        self.assertEqual(mail.outbox[0].body, 'Fallback Text')
        
        # Check alternatives
        self.assertTrue(len(mail.outbox[0].alternatives) == 1)
        html_content = mail.outbox[0].alternatives[0][0]
        
        # Check if variables were injected
        self.assertIn('John Doe', html_content)
        self.assertIn('123456', html_content)
        
        # Check if branding was injected
        self.assertIn('http://example.com/logo.png', html_content)
        self.assertIn('Custom Footer', html_content)
        self.assertIn('#ff0000', html_content)

    def test_send_email_no_org(self):
        send_email(
            to='test@example.com',
            subject='Test No Org',
            text='Fallback',
            template='emails/otp.html',
            template_context={'user_name': 'Jane', 'otp_code': '654321'}
        )
        self.assertEqual(len(mail.outbox), 1)
        html_content = mail.outbox[0].alternatives[0][0]
        self.assertIn('Insight ERP', html_content) # Default fallback org name
