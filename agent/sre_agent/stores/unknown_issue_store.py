"""
Unknown Issue Store - Persistent storage for unknown issues.

Stores unknown issues for:
- Recurrence tracking
- Pattern discovery
- Human feedback collection
- Progressive learning
"""

import json
import asyncio
import aiosqlite
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from pathlib import Path

from sre_agent.models.diagnosis import Diagnosis
from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class UnknownIssue:
    """Represents an unknown issue tracked in the store."""

    def __init__(
        self,
        fingerprint: str,
        first_seen: datetime,
        last_seen: datetime,
        occurrence_count: int,
        category: str,
        observation_data: dict,
        error_patterns: List[str],
        investigation_notes: str,
        severity_score: float,
        resolved: bool = False,
        resolution_data: Optional[dict] = None
    ):
        self.fingerprint = fingerprint
        self.first_seen = first_seen
        self.last_seen = last_seen
        self.occurrence_count = occurrence_count
        self.category = category
        self.observation_data = observation_data
        self.error_patterns = error_patterns
        self.investigation_notes = investigation_notes
        self.severity_score = severity_score
        self.resolved = resolved
        self.resolution_data = resolution_data


class UnknownIssueStore:
    """
    Persistent store for unknown issues.

    Features:
    - SQLite-based storage
    - Deduplication by fingerprint
    - Recurrence tracking
    - Resolution tracking
    - Pattern extraction
    """

    def __init__(self, db_path: str = "/data/unknown_issues.db"):
        """
        Initialize unknown issue store.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._initialized = False

    async def initialize(self):
        """Initialize database schema."""
        if self._initialized:
            return

        # Create directory if needed
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS unknown_issues (
                    fingerprint TEXT PRIMARY KEY,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    occurrence_count INTEGER DEFAULT 1,
                    category TEXT NOT NULL,
                    observation_data TEXT NOT NULL,
                    error_patterns TEXT NOT NULL,
                    investigation_notes TEXT,
                    severity_score REAL NOT NULL,
                    resolved INTEGER DEFAULT 0,
                    resolution_data TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_last_seen
                ON unknown_issues(last_seen)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_resolved
                ON unknown_issues(resolved)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_occurrence_count
                ON unknown_issues(occurrence_count DESC)
            """)

            await db.commit()

        self._initialized = True
        logger.info("Unknown issue store initialized", db_path=self.db_path)

    async def store_unknown(
        self,
        fingerprint: str,
        diagnosis: Diagnosis,
        error_patterns: List[str],
        investigation_notes: str,
        severity_score: float
    ) -> bool:
        """
        Store or update an unknown issue.

        Args:
            fingerprint: Unique fingerprint hash
            diagnosis: Diagnosis object
            error_patterns: Extracted error patterns
            investigation_notes: Investigation template
            severity_score: Severity score 0-10

        Returns:
            True if new issue, False if updated existing
        """
        await self.initialize()

        now = datetime.utcnow().isoformat()

        # Serialize observation data
        observation_data = {
            "namespace": diagnosis.observation.namespace,
            "resource_name": diagnosis.observation.resource_name,
            "resource_kind": diagnosis.observation.resource_kind,
            "evidence": diagnosis.observation.evidence,
            "timestamp": diagnosis.observation.timestamp.isoformat()
        }

        async with aiosqlite.connect(self.db_path) as db:
            # Check if fingerprint exists
            cursor = await db.execute(
                "SELECT occurrence_count FROM unknown_issues WHERE fingerprint = ?",
                (fingerprint,)
            )
            existing = await cursor.fetchone()

            if existing:
                # Update existing issue
                new_count = existing[0] + 1
                await db.execute("""
                    UPDATE unknown_issues
                    SET last_seen = ?,
                        occurrence_count = ?,
                        observation_data = ?,
                        severity_score = ?,
                        updated_at = ?
                    WHERE fingerprint = ?
                """, (
                    now,
                    new_count,
                    json.dumps(observation_data),
                    severity_score,
                    now,
                    fingerprint
                ))

                await db.commit()

                logger.info(
                    "Updated unknown issue recurrence",
                    fingerprint=fingerprint,
                    occurrence_count=new_count
                )

                return False
            else:
                # Insert new issue
                await db.execute("""
                    INSERT INTO unknown_issues (
                        fingerprint,
                        first_seen,
                        last_seen,
                        occurrence_count,
                        category,
                        observation_data,
                        error_patterns,
                        investigation_notes,
                        severity_score,
                        resolved,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    fingerprint,
                    now,
                    now,
                    1,
                    diagnosis.category.value,
                    json.dumps(observation_data),
                    json.dumps(error_patterns),
                    investigation_notes,
                    severity_score,
                    0,
                    now,
                    now
                ))

                await db.commit()

                logger.info(
                    "Stored new unknown issue",
                    fingerprint=fingerprint,
                    category=diagnosis.category.value
                )

                return True

    async def mark_resolved(
        self,
        fingerprint: str,
        resolution_data: dict
    ) -> bool:
        """
        Mark an unknown issue as resolved.

        Args:
            fingerprint: Issue fingerprint
            resolution_data: Resolution information (root cause, fix, etc.)

        Returns:
            True if marked resolved, False if not found
        """
        await self.initialize()

        now = datetime.utcnow().isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT fingerprint FROM unknown_issues WHERE fingerprint = ?",
                (fingerprint,)
            )
            existing = await cursor.fetchone()

            if not existing:
                return False

            await db.execute("""
                UPDATE unknown_issues
                SET resolved = 1,
                    resolution_data = ?,
                    updated_at = ?
                WHERE fingerprint = ?
            """, (
                json.dumps(resolution_data),
                now,
                fingerprint
            ))

            await db.commit()

            logger.info(
                "Marked unknown issue as resolved",
                fingerprint=fingerprint,
                resolution=resolution_data.get("summary", "")
            )

            return True

    async def get_unresolved_issues(
        self,
        min_occurrences: int = 1,
        limit: int = 100
    ) -> List[UnknownIssue]:
        """
        Get unresolved unknown issues.

        Args:
            min_occurrences: Minimum occurrence count
            limit: Maximum number to return

        Returns:
            List of unknown issues
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT * FROM unknown_issues
                WHERE resolved = 0
                  AND occurrence_count >= ?
                ORDER BY severity_score DESC, occurrence_count DESC
                LIMIT ?
            """, (min_occurrences, limit))

            rows = await cursor.fetchall()

            issues = []
            for row in rows:
                issues.append(UnknownIssue(
                    fingerprint=row["fingerprint"],
                    first_seen=datetime.fromisoformat(row["first_seen"]),
                    last_seen=datetime.fromisoformat(row["last_seen"]),
                    occurrence_count=row["occurrence_count"],
                    category=row["category"],
                    observation_data=json.loads(row["observation_data"]),
                    error_patterns=json.loads(row["error_patterns"]),
                    investigation_notes=row["investigation_notes"],
                    severity_score=row["severity_score"],
                    resolved=bool(row["resolved"]),
                    resolution_data=json.loads(row["resolution_data"]) if row["resolution_data"] else None
                ))

            return issues

    async def get_issue_by_fingerprint(self, fingerprint: str) -> Optional[UnknownIssue]:
        """Get unknown issue by fingerprint."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM unknown_issues WHERE fingerprint = ?",
                (fingerprint,)
            )
            row = await cursor.fetchone()

            if not row:
                return None

            return UnknownIssue(
                fingerprint=row["fingerprint"],
                first_seen=datetime.fromisoformat(row["first_seen"]),
                last_seen=datetime.fromisoformat(row["last_seen"]),
                occurrence_count=row["occurrence_count"],
                category=row["category"],
                observation_data=json.loads(row["observation_data"]),
                error_patterns=json.loads(row["error_patterns"]),
                investigation_notes=row["investigation_notes"],
                severity_score=row["severity_score"],
                resolved=bool(row["resolved"]),
                resolution_data=json.loads(row["resolution_data"]) if row["resolution_data"] else None
            )

    async def get_stats(self) -> dict:
        """Get statistics about unknown issues."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            # Total unknowns
            cursor = await db.execute("SELECT COUNT(*) FROM unknown_issues")
            total = (await cursor.fetchone())[0]

            # Unresolved
            cursor = await db.execute(
                "SELECT COUNT(*) FROM unknown_issues WHERE resolved = 0"
            )
            unresolved = (await cursor.fetchone())[0]

            # Resolved
            resolved = total - unresolved

            # Recent (last 24 hours)
            yesterday = (datetime.utcnow() - timedelta(days=1)).isoformat()
            cursor = await db.execute(
                "SELECT COUNT(*) FROM unknown_issues WHERE last_seen > ?",
                (yesterday,)
            )
            recent = (await cursor.fetchone())[0]

            # High occurrence (>= 5)
            cursor = await db.execute(
                "SELECT COUNT(*) FROM unknown_issues WHERE occurrence_count >= 5"
            )
            high_occurrence = (await cursor.fetchone())[0]

            return {
                "total": total,
                "unresolved": unresolved,
                "resolved": resolved,
                "recent_24h": recent,
                "high_occurrence": high_occurrence,
                "resolution_rate": f"{(resolved/total*100) if total > 0 else 0:.1f}%"
            }


# Global instance
_unknown_store: Optional[UnknownIssueStore] = None


def get_unknown_store(db_path: str = "/data/unknown_issues.db") -> UnknownIssueStore:
    """Get global unknown issue store instance."""
    global _unknown_store
    if _unknown_store is None:
        _unknown_store = UnknownIssueStore(db_path)
    return _unknown_store
