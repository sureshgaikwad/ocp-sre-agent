"""
SRE Agent for OpenShift.

A comprehensive autonomous agent for OpenShift operations following
the Observe → Diagnose → Remediate → Verify loop.
"""

__version__ = "0.1.0"
__author__ = "SRE Team"

# Export key classes for easy imports
from sre_agent.models.observation import Observation, ObservationType, Severity
from sre_agent.models.diagnosis import Diagnosis, DiagnosisCategory, Confidence
from sre_agent.models.remediation import RemediationResult, RemediationStatus
from sre_agent.models.audit import AuditEntry, OperationType

from sre_agent.utils.secret_scrubber import SecretScrubber, scrub_secrets
from sre_agent.utils.json_logger import get_logger
from sre_agent.utils.audit_logger import get_audit_logger

from sre_agent.config.settings import get_settings

__all__ = [
    # Models
    "Observation",
    "ObservationType",
    "Severity",
    "Diagnosis",
    "DiagnosisCategory",
    "Confidence",
    "RemediationResult",
    "RemediationStatus",
    "AuditEntry",
    "OperationType",
    # Utils
    "SecretScrubber",
    "scrub_secrets",
    "get_logger",
    "get_audit_logger",
    # Config
    "get_settings",
]
