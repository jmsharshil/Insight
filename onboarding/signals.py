"""
onboarding/signals.py

NOTE: Student profile creation is handled explicitly by StudentService.create_from_admission()
called inside AdmissionApproveView (onboarding/views.py).

This signal file is intentionally left as a no-op to avoid duplicate creation conflicts.
Do NOT add post_save logic here for Student creation — use the service layer instead.
"""

import logging

logger = logging.getLogger(__name__)
