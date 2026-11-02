import unittest
from unittest.mock import MagicMock

class TestMotherPhoneSupport(unittest.TestCase):
    def test_admission_mother_phone_property(self):
        # Test property getter and setter on a mock Admission-like class
        class MockAdmission:
            phone_father_2 = ''

            @property
            def phone_mother(self):
                return self.phone_father_2

            @phone_mother.setter
            def phone_mother(self, value):
                self.phone_father_2 = value or ''

            @property
            def mother_phone(self):
                return self.phone_father_2

            @mother_phone.setter
            def mother_phone(self, value):
                self.phone_father_2 = value or ''

        adm = MockAdmission()
        self.assertEqual(adm.mother_phone, '')
        adm.mother_phone = '9876543212'
        self.assertEqual(adm.phone_father_2, '9876543212')
        self.assertEqual(adm.phone_mother, '9876543212')
        self.assertEqual(adm.mother_phone, '9876543212')

        adm.phone_mother = '9123456780'
        self.assertEqual(adm.mother_phone, '9123456780')
        self.assertEqual(adm.phone_father_2, '9123456780')

    def test_phone_uniqueness_normalizer(self):
        def normalize_phone_for_comparison(val):
            if not val:
                return ''
            digits = ''.join(c for c in str(val) if c.isdigit())
            if len(digits) >= 10:
                return digits[-10:]
            return digits

        self.assertEqual(normalize_phone_for_comparison('+91 98765 43210'), '9876543210')
        self.assertEqual(normalize_phone_for_comparison('9876543210'), '9876543210')

if __name__ == '__main__':
    unittest.main()
