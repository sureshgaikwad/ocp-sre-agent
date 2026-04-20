"""
Event Deduplicator - Prevents duplicate events and reduces noise.

Tracks observations and diagnoses to determine if an issue is:
- New (never seen before)
- Transient (seen once, may be temporary)
- Persistent (seen multiple times or lasted long)

Approvals are persisted to SQLite to survive agent restarts.
"""

import hashlib
import aiosqlite
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass
from pathlib import Path
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

    Approvals are persisted to SQLite to survive agent restarts.
    """

    def __init__(
        self,
        persistence_threshold_minutes: int = 5,
        occurrence_threshold: int = 3,
        ttl_minutes: int = 60,
        db_path: str = "/data/approvals.db"
    ):
        """
        Initialize EventDeduplicator.

        Args:
            persistence_threshold_minutes: Issue must persist for this long to alert
            occurrence_threshold: Issue must occur this many times to alert
            ttl_minutes: How long to remember resolved issues
            db_path: Path to SQLite database for persisting approvals
        """
        self.persistence_threshold = timedelta(minutes=persistence_threshold_minutes)
        self.occurrence_threshold = occurrence_threshold
        self.ttl = timedelta(minutes=ttl_minutes)
        self.db_path = db_path

        # Track issues: fingerprint -> IssueTracker
        self._issues: dict[str, IssueTracker] = {}

        # Track diagnosis_id -> fingerprint mapping for approval lookup
        self._diagnosis_id_map: dict[str, str] = {}

        # Initialize database synchronously
        asyncio.create_task(self._init_db())
        asyncio.create_task(self._load_approvals())

    async def _init_db(self):
        """Initialize SQLite database for persisting approvals."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS approvals (
                        fingerprint TEXT PRIMARY KEY,
                        category TEXT,
                        approved INTEGER,
                        timestamp TEXT
                    )
                """)
                await db.commit()
                logger.info("Approval database initialized", db_path=self.db_path)
        except Exception as e:
            logger.error("Failed to initialize approval database", error=str(e))

    async def _load_approvals(self):
        """Load all approvals from SQLite on startup."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute("SELECT fingerprint, category FROM approvals WHERE approved = 1") as cursor:
                    rows = await cursor.fetchall()
                    for row in rows:
                        fingerprint, category = row
                        # If we have this issue in memory, mark it as approved
                        if fingerprint in self._issues:
                            self._issues[fingerprint].remediation_requested = True
                            logger.info(
                                "Loaded approval from database",
                                fingerprint=fingerprint,
                                category=category
                            )
            if rows:
                logger.info(f"Loaded {len(rows)} approvals from database")
        except Exception as e:
            logger.error("Failed to load approvals from database", error=str(e))

    async def _persist_approval(self, fingerprint: str, category: str, approved: bool):
        """Persist approval state to SQLite."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT OR REPLACE INTO approvals (fingerprint, category, approved, timestamp)
                    VALUES (?, ?, ?, ?)
                    """,
                    (fingerprint, category, 1 if approved else 0, datetime.utcnow().isoformat())
                )
                await db.commit()
                logger.debug(
                    "Persisted approval to database",
                    fingerprint=fingerprint,
                    category=category,
                    approved=approved
                )
        except Exception as e:
            logger.error(
                "Failed to persist approval to database",
                fingerprint=fingerprint,
                error=str(e)
            )

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
            # Persist to database
            asyncio.create_task(
                self._persist_approval(fingerprint, diagnosis.category.value, True)
            )
            logger.info(
                f"Remediation requested for issue",
                fingerprint=fingerprint,
                category=diagnosis.category.value
            )

    def approve_remediation_by_id(self, diagnosis_id: str) -> bool:
        """
        Approve remediation by diagnosis ID or fingerprint.

        Args:
            diagnosis_id: Diagnosis ID or fingerprint to approve

        Returns:
            True if approved, False if diagnosis not found
        """
        # Try diagnosis_id first (works if agent hasn't restarted)
        if diagnosis_id in self._diagnosis_id_map:
            fingerprint = self._diagnosis_id_map[diagnosis_id]
            if fingerprint in self._issues:
                self._issues[fingerprint].remediation_requested = True
                # Persist to database
                asyncio.create_task(
                    self._persist_approval(fingerprint, self._issues[fingerprint].category, True)
                )
                logger.info(
                    f"Remediation approved via diagnosis_id",
                    diagnosis_id=diagnosis_id,
                    fingerprint=fingerprint,
                    category=self._issues[fingerprint].category
                )
                return True

        # Try as fingerprint directly (works across agent restarts)
        if diagnosis_id in self._issues:
            self._issues[diagnosis_id].remediation_requested = True
            # Persist to database
            asyncio.create_task(
                self._persist_approval(diagnosis_id, self._issues[diagnosis_id].category, True)
            )
            logger.info(
                f"Remediation approved via fingerprint",
                fingerprint=diagnosis_id,
                category=self._issues[diagnosis_id].category
            )
            return True

        logger.warning(
            f"Cannot approve - diagnosis_id not found (tried as both diagnosis_id and fingerprint)",
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

        # Check in-memory first
        if fingerprint in self._issues:
            if self._issues[fingerprint].remediation_requested:
                return True

        # Check database (in case approval happened before restart)
        try:
            # Use sync approach since this is called from sync context
            import sqlite3
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT approved FROM approvals WHERE fingerprint = ? AND approved = 1",
                (fingerprint,)
            )
            row = cursor.fetchone()
            conn.close()

            if row:
                logger.info(
                    "Found approval in database (survived restart)",
                    fingerprint=fingerprint,
                    category=diagnosis.category.value
                )
                # Update in-memory state if issue exists
                if fingerprint in self._issues:
                    self._issues[fingerprint].remediation_requested = True
                return True
        except Exception as e:
            logger.error(
                "Failed to check approval in database",
                fingerprint=fingerprint,
                error=str(e)
            )

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

        # Clean up old approvals from database (older than 7 days)
        asyncio.create_task(self._cleanup_old_approvals())

    async def _cleanup_old_approvals(self):
        """Remove approvals older than 7 days from database."""
        try:
            cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    "DELETE FROM approvals WHERE timestamp < ?",
                    (cutoff,)
                )
                deleted = cursor.rowcount
                await db.commit()
                if deleted > 0:
                    logger.info(f"Cleaned up {deleted} old approvals from database")
        except Exception as e:
            logger.error("Failed to clean up old approvals", error=str(e))

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
