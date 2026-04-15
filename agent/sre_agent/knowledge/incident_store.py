"""
Incident Knowledge Store.

Stores and retrieves knowledge from past incidents for learning and reuse.
"""

import json
import hashlib
from datetime import datetime
from typing import Optional, List
import aiosqlite

from sre_agent.models.observation import Observation
from sre_agent.models.diagnosis import Diagnosis
from sre_agent.models.remediation import RemediationResult
from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class IncidentRecord:
    """Record of a past incident with its resolution."""

    def __init__(
        self,
        incident_id: str,
        observation: Observation,
        diagnosis: Diagnosis,
        remediation: RemediationResult,
        outcome: str,
        mttr_seconds: float,
        timestamp: datetime
    ):
        self.incident_id = incident_id
        self.observation = observation
        self.diagnosis = diagnosis
        self.remediation = remediation
        self.outcome = outcome  # "success", "failed", "partial"
        self.mttr_seconds = mttr_seconds
        self.timestamp = timestamp

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "incident_id": self.incident_id,
            "observation": self.observation.model_dump(),
            "diagnosis": self.diagnosis.model_dump(),
            "remediation": self.remediation.model_dump(),
            "outcome": self.outcome,
            "mttr_seconds": self.mttr_seconds,
            "timestamp": self.timestamp.isoformat()
        }


class IncidentKnowledgeStore:
    """
    Stores and retrieves incident knowledge for learning and reuse.

    Features:
    - Stores past incidents with diagnoses and remediations
    - Similarity search to find related past incidents
    - Runbook generation from successful patterns
    - MTTR tracking and analytics
    """

    def __init__(self, db_path: str):
        """
        Initialize knowledge store.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        """Initialize database schema."""
        self._db = await aiosqlite.connect(self.db_path)

        # Enable WAL mode for better concurrency
        await self._db.execute("PRAGMA journal_mode=WAL")

        # Create incidents table
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                incident_id TEXT PRIMARY KEY,
                observation_id TEXT NOT NULL,
                observation_type TEXT NOT NULL,
                observation_data TEXT NOT NULL,
                diagnosis_id TEXT NOT NULL,
                diagnosis_category TEXT NOT NULL,
                diagnosis_data TEXT NOT NULL,
                remediation_id TEXT NOT NULL,
                remediation_tier INTEGER NOT NULL,
                remediation_data TEXT NOT NULL,
                outcome TEXT NOT NULL,
                mttr_seconds REAL NOT NULL,
                namespace TEXT,
                resource_kind TEXT,
                resource_name TEXT,
                fingerprint TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create indexes for fast lookups
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_incidents_fingerprint
            ON incidents(fingerprint)
        """)

        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_incidents_category
            ON incidents(diagnosis_category)
        """)

        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_incidents_resource
            ON incidents(namespace, resource_kind, resource_name)
        """)

        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_incidents_timestamp
            ON incidents(timestamp DESC)
        """)

        # Create runbooks table
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS runbooks (
                runbook_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                diagnosis_category TEXT NOT NULL,
                steps TEXT NOT NULL,
                success_count INTEGER DEFAULT 0,
                last_used TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await self._db.commit()

        logger.info(f"Knowledge store initialized at {self.db_path}")

    async def store_incident(
        self,
        observation: Observation,
        diagnosis: Diagnosis,
        remediation: RemediationResult
    ) -> str:
        """
        Store an incident for future learning.

        Args:
            observation: The observation that triggered the incident
            diagnosis: The diagnosis produced
            remediation: The remediation result

        Returns:
            Incident ID
        """
        if not self._db:
            await self.initialize()

        # Generate incident ID
        incident_id = f"incident-{observation.id[:8]}-{diagnosis.id[:8]}"

        # Calculate MTTR
        mttr_seconds = 0.0
        if remediation.timestamp and observation.timestamp:
            mttr_seconds = (remediation.timestamp - observation.timestamp).total_seconds()

        # Generate fingerprint for similarity matching
        fingerprint = self._generate_fingerprint(observation, diagnosis)

        # Determine outcome
        outcome = "success" if remediation.status.value == "success" else "failed"

        try:
            await self._db.execute("""
                INSERT INTO incidents (
                    incident_id, observation_id, observation_type, observation_data,
                    diagnosis_id, diagnosis_category, diagnosis_data,
                    remediation_id, remediation_tier, remediation_data,
                    outcome, mttr_seconds, namespace, resource_kind, resource_name,
                    fingerprint, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                incident_id,
                observation.id,
                observation.type.value,
                json.dumps(observation.model_dump(), default=str),
                diagnosis.id,
                diagnosis.category.value,
                json.dumps(diagnosis.model_dump(), default=str),
                remediation.id,
                remediation.tier,
                json.dumps(remediation.model_dump(), default=str),
                outcome,
                mttr_seconds,
                observation.namespace,
                observation.resource_kind,
                observation.resource_name,
                fingerprint,
                observation.timestamp.isoformat()
            ))

            await self._db.commit()

            logger.info(
                f"Stored incident {incident_id}",
                incident_id=incident_id,
                category=diagnosis.category.value,
                outcome=outcome,
                mttr_seconds=mttr_seconds
            )

            return incident_id

        except Exception as e:
            logger.error(f"Failed to store incident: {e}", exc_info=True)
            raise

    async def find_similar_incidents(
        self,
        observation: Observation,
        limit: int = 5
    ) -> List[IncidentRecord]:
        """
        Find similar past incidents.

        Args:
            observation: Current observation to match
            limit: Maximum number of similar incidents to return

        Returns:
            List of similar incident records, sorted by relevance
        """
        if not self._db:
            await self.initialize()

        fingerprint = self._generate_fingerprint(observation, None)

        try:
            # First try exact fingerprint match
            cursor = await self._db.execute("""
                SELECT * FROM incidents
                WHERE fingerprint = ?
                AND outcome = 'success'
                ORDER BY timestamp DESC
                LIMIT ?
            """, (fingerprint, limit))

            rows = await cursor.fetchall()

            if rows:
                logger.info(
                    f"Found {len(rows)} exact fingerprint matches",
                    fingerprint=fingerprint
                )
                return [self._row_to_incident_record(row) for row in rows]

            # If no exact match, search by resource type and observation type
            cursor = await self._db.execute("""
                SELECT * FROM incidents
                WHERE observation_type = ?
                AND resource_kind = ?
                AND outcome = 'success'
                ORDER BY timestamp DESC
                LIMIT ?
            """, (observation.type.value, observation.resource_kind, limit))

            rows = await cursor.fetchall()

            logger.info(
                f"Found {len(rows)} similar incidents by type",
                observation_type=observation.type.value,
                resource_kind=observation.resource_kind
            )

            return [self._row_to_incident_record(row) for row in rows]

        except Exception as e:
            logger.error(f"Failed to find similar incidents: {e}", exc_info=True)
            return []

    def _generate_fingerprint(
        self,
        observation: Observation,
        diagnosis: Optional[Diagnosis] = None
    ) -> str:
        """
        Generate a fingerprint for incident similarity matching.

        Fingerprint includes:
        - Observation type
        - Resource kind
        - Key error patterns (if available)

        Args:
            observation: Observation
            diagnosis: Optional diagnosis

        Returns:
            SHA256 hash fingerprint
        """
        components = [
            observation.type.value,
            observation.resource_kind or "unknown"
        ]

        # Add diagnosis category if available
        if diagnosis:
            components.append(diagnosis.category.value)

        # Create hash
        fingerprint_str = "|".join(components)
        return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:16]

    def _row_to_incident_record(self, row) -> IncidentRecord:
        """
        Convert database row to IncidentRecord.

        Args:
            row: Database row tuple

        Returns:
            IncidentRecord object
        """
        # Row columns: incident_id, observation_id, observation_type, observation_data, ...
        observation_data = json.loads(row[3])
        diagnosis_data = json.loads(row[6])
        remediation_data = json.loads(row[9])

        # Reconstruct objects
        observation = Observation(**observation_data)
        diagnosis = Diagnosis(**diagnosis_data)
        remediation = RemediationResult(**remediation_data)

        return IncidentRecord(
            incident_id=row[0],
            observation=observation,
            diagnosis=diagnosis,
            remediation=remediation,
            outcome=row[10],
            mttr_seconds=row[11],
            timestamp=datetime.fromisoformat(row[16])
        )

    async def get_mttr_stats(self, diagnosis_category: Optional[str] = None) -> dict:
        """
        Get MTTR statistics.

        Args:
            diagnosis_category: Optional category to filter by

        Returns:
            Dict with MTTR statistics
        """
        if not self._db:
            await self.initialize()

        if diagnosis_category:
            cursor = await self._db.execute("""
                SELECT
                    AVG(mttr_seconds) as avg_mttr,
                    MIN(mttr_seconds) as min_mttr,
                    MAX(mttr_seconds) as max_mttr,
                    COUNT(*) as incident_count
                FROM incidents
                WHERE diagnosis_category = ? AND outcome = 'success'
            """, (diagnosis_category,))
        else:
            cursor = await self._db.execute("""
                SELECT
                    AVG(mttr_seconds) as avg_mttr,
                    MIN(mttr_seconds) as min_mttr,
                    MAX(mttr_seconds) as max_mttr,
                    COUNT(*) as incident_count
                FROM incidents
                WHERE outcome = 'success'
            """)

        row = await cursor.fetchone()

        return {
            "avg_mttr_seconds": row[0] or 0,
            "min_mttr_seconds": row[1] or 0,
            "max_mttr_seconds": row[2] or 0,
            "incident_count": row[3] or 0,
            "category": diagnosis_category
        }

    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None


# Global knowledge store instance
_knowledge_store: Optional[IncidentKnowledgeStore] = None


def get_knowledge_store(db_path: str) -> IncidentKnowledgeStore:
    """
    Get global knowledge store instance.

    Args:
        db_path: Path to knowledge database

    Returns:
        IncidentKnowledgeStore instance
    """
    global _knowledge_store
    if _knowledge_store is None:
        _knowledge_store = IncidentKnowledgeStore(db_path)
    return _knowledge_store
