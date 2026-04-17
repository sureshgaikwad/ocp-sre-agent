"""
Event Deduplicator - Prevents duplicate events and reduces noise.

Tracks observations and diagnoses to determine if an issue is:
- New (never seen before)
- Transient (seen once, may be temporary)
- Persistent (seen multiple times or lasted long)
"""

import hashlib
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass
from sre_agent.models.observation import Observation
from sre_agent.models.diagnosis import Diagnosis
from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


@dataclass
class IssueTracker:
    """Tracks an issue over time."""
    fingerprint: str
    category: str
    first_seen: datetime
    last_seen: datetime
    occurrence_count: int
    alerted: bool = False
    remediation_requested: bool = False
    diagnosis_id: str = ""  # Track most recent diagnosis ID


class EventDeduplicator:
    """
    Deduplicates events and filters noise.

    Only creates alerts for issues that are:
    - Seen for the first time AND high severity
    - Persistent (> 5 minutes)
    - Recurring (> 3 occurrences)
    """

    def __init__(
        self,
        persistence_threshold_minutes: int = 5,
        occurrence_threshold: int = 3,
        ttl_minutes: int = 60
    ):
        """
        Initialize EventDeduplicator.

        Args:
            persistence_threshold_minutes: Issue must persist for this long to alert
            occurrence_threshold: Issue must occur this many times to alert
            ttl_minutes: How long to remember resolved issues
        """
        self.persistence_threshold = timedelta(minutes=persistence_threshold_minutes)
        self.occurrence_threshold = occurrence_threshold
        self.ttl = timedelta(minutes=ttl_minutes)

        # Track issues: fingerprint -> IssueTracker
        self._issues: dict[str, IssueTracker] = {}

        # Track diagnosis_id -> fingerprint mapping for approval lookup
        self._diagnosis_id_map: dict[str, str] = {}

    def _generate_fingerprint(self, diagnosis: Diagnosis) -> str:
        """
        Generate unique fingerprint for a diagnosis.

        Fingerprint includes:
        - namespace
        - resource_name
        - resource_kind
        - category

        Args:
            diagnosis: Diagnosis to fingerprint

        Returns:
            SHA256 fingerprint
        """
        evidence = diagnosis.evidence
        components = [
            evidence.get("namespace", "cluster-wide"),
            evidence.get("resource_kind", "unknown"),
            evidence.get("resource_name", "unknown"),
            diagnosis.category.value
        ]

        key = "|".join(components)
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def should_alert(self, diagnosis: Diagnosis) -> tuple[bool, str]:
        """
        Determine if we should create an alert for this diagnosis.

        Args:
            diagnosis: Diagnosis to check

        Returns:
            Tuple of (should_alert, reason)
        """
        fingerprint = self._generate_fingerprint(diagnosis)
        now = datetime.utcnow()

        # Check if we've seen this issue before
        if fingerprint in self._issues:
            tracker = self._issues[fingerprint]

            # Update tracking
            tracker.last_seen = now
            tracker.occurrence_count += 1
            tracker.diagnosis_id = diagnosis.id
            self._diagnosis_id_map[diagnosis.id] = fingerprint

            # Already alerted? Don't spam
            if tracker.alerted:
                logger.debug(
                    f"Suppressing duplicate alert for known issue",
                    fingerprint=fingerprint,
                    category=diagnosis.category.value,
                    occurrence_count=tracker.occurrence_count
                )
                return False, "already_alerted"

            # Check if issue is now persistent (time-based)
            duration = now - tracker.first_seen
            if duration >= self.persistence_threshold:
                logger.info(
                    f"Issue is persistent (duration threshold met)",
                    fingerprint=fingerprint,
                    category=diagnosis.category.value,
                    duration_minutes=duration.total_seconds() / 60,
                    threshold_minutes=self.persistence_threshold.total_seconds() / 60
                )
                tracker.alerted = True
                return True, f"persistent_{duration.total_seconds()//60}min"

            # Check if issue is recurring (count-based)
            if tracker.occurrence_count >= self.occurrence_threshold:
                logger.info(
                    f"Issue is recurring (occurrence threshold met)",
                    fingerprint=fingerprint,
                    category=diagnosis.category.value,
                    occurrence_count=tracker.occurrence_count,
                    threshold=self.occurrence_threshold
                )
                tracker.alerted = True
                return True, f"recurring_{tracker.occurrence_count}x"

            # Still within transient window
            logger.debug(
                f"Issue may be transient, not alerting yet",
                fingerprint=fingerprint,
                category=diagnosis.category.value,
                duration_minutes=duration.total_seconds() / 60,
                occurrence_count=tracker.occurrence_count
            )
            return False, f"transient_{tracker.occurrence_count}x_{duration.total_seconds()//60}min"

        else:
            # New issue - create tracker
            self._issues[fingerprint] = IssueTracker(
                fingerprint=fingerprint,
                category=diagnosis.category.value,
                first_seen=now,
                last_seen=now,
                occurrence_count=1,
                diagnosis_id=diagnosis.id
            )
            self._diagnosis_id_map[diagnosis.id] = fingerprint

            # Alert immediately for CRITICAL issues with HIGH confidence
            from sre_agent.models.diagnosis import Confidence, DiagnosisCategory

            critical_categories = [
                DiagnosisCategory.OOM_KILLED,
                DiagnosisCategory.CLUSTER_OPERATOR_DEGRADED,
                DiagnosisCategory.NODE_DISK_PRESSURE,
                DiagnosisCategory.APPLICATION_ERROR
            ]

            if diagnosis.category in critical_categories and diagnosis.confidence == Confidence.HIGH:
                logger.info(
                    f"New CRITICAL issue detected - alerting immediately",
                    fingerprint=fingerprint,
                    category=diagnosis.category.value,
                    confidence=diagnosis.confidence.value
                )
                self._issues[fingerprint].alerted = True
                return True, "new_critical"

            # For non-critical issues, wait to see if they persist
            logger.info(
                f"New issue detected - monitoring for persistence",
                fingerprint=fingerprint,
                category=diagnosis.category.value,
                confidence=diagnosis.confidence.value
            )
            return False, "new_monitoring"

    def mark_remediation_requested(self, diagnosis: Diagnosis):
        """
        Mark that user has requested remediation for this issue.

        Args:
            diagnosis: Diagnosis that was approved for remediation
        """
        fingerprint = self._generate_fingerprint(diagnosis)
        if fingerprint in self._issues:
            self._issues[fingerprint].remediation_requested = True
            logger.info(
                f"Remediation requested for issue",
                fingerprint=fingerprint,
                category=diagnosis.category.value
            )

    def approve_remediation_by_id(self, diagnosis_id: str) -> bool:
        """
        Approve remediation by diagnosis ID.

        Args:
            diagnosis_id: Diagnosis ID to approve

        Returns:
            True if approved, False if diagnosis not found
        """
        if diagnosis_id in self._diagnosis_id_map:
            fingerprint = self._diagnosis_id_map[diagnosis_id]
            if fingerprint in self._issues:
                self._issues[fingerprint].remediation_requested = True
                logger.info(
                    f"Remediation approved via diagnosis_id",
                    diagnosis_id=diagnosis_id,
                    fingerprint=fingerprint,
                    category=self._issues[fingerprint].category
                )
                return True

        logger.warning(
            f"Cannot approve - diagnosis_id not found",
            diagnosis_id=diagnosis_id
        )
        return False

    def is_remediation_requested(self, diagnosis: Diagnosis) -> bool:
        """
        Check if remediation has been requested for this issue.

        Args:
            diagnosis: Diagnosis to check

        Returns:
            True if user approved remediation
        """
        fingerprint = self._generate_fingerprint(diagnosis)
        if fingerprint in self._issues:
            return self._issues[fingerprint].remediation_requested
        return False

    def cleanup_old_issues(self):
        """Remove issues that haven't been seen recently."""
        now = datetime.utcnow()
        stale_issues = []

        for fingerprint, tracker in self._issues.items():
            age = now - tracker.last_seen
            if age > self.ttl:
                stale_issues.append(fingerprint)

        for fingerprint in stale_issues:
            logger.debug(
                f"Removing stale issue from tracker",
                fingerprint=fingerprint,
                category=self._issues[fingerprint].category
            )
            del self._issues[fingerprint]

        if stale_issues:
            logger.info(f"Cleaned up {len(stale_issues)} stale issues")

    def get_stats(self) -> dict:
        """Get deduplicator statistics."""
        return {
            "total_tracked_issues": len(self._issues),
            "alerted_issues": sum(1 for t in self._issues.values() if t.alerted),
            "pending_issues": sum(1 for t in self._issues.values() if not t.alerted),
            "remediation_requested": sum(1 for t in self._issues.values() if t.remediation_requested)
        }


# Global singleton
_deduplicator: Optional[EventDeduplicator] = None


def get_event_deduplicator() -> EventDeduplicator:
    """Get or create global EventDeduplicator instance."""
    global _deduplicator
    if _deduplicator is None:
        _deduplicator = EventDeduplicator(
            persistence_threshold_minutes=5,
            occurrence_threshold=3,
            ttl_minutes=60
        )
    return _deduplicator
