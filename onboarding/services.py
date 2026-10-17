"""
Onboarding Services Module.
Re-exports AdmissionService from onboarding.utils for clean architectural access and backward compatibility.
"""
from .utils import AdmissionService

__all__ = ['AdmissionService']
