"""
Audit logging utility.

All operations (read/write) are logged to SQLite for compliance and security.
Audit logs are IMMUTABLE and MUST NOT contain secrets (scrub before logging).
"""

import aiosqlite
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional
import json

from sre_agent.models.audit import AuditEntry, OperationType
from sre_agent.utils.secret_scrubber import SecretScrubber
from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class AuditLogger:
    """
    Async audit logger with SQLite backend.

    All operations are logged with full context for security audits.
    Logs are automatically scrubbed for secrets before storage.
    """

    def __init__(self, db_path: str = "/data/audit.db"):
        """
        Initialize audit logger.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._initialized = False
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """
        Initialize database schema.

        Creates audit_logs table if it doesn't exist.
        Safe to call multiple times (idempotent).
        """
        async with self._lock:
            if self._initialized:
                return

            # Ensure directory exists
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS audit_logs (
                        id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        operation_type TEXT NOT NULL,
                        resource_kind TEXT,
                        resource_name TEXT,
                        namespace TEXT,
                        action TEXT NOT NULL,
                        success INTEGER NOT NULL,
                        error TEXT,
                        diagnosis_id TEXT,
                        remediation_id TEXT,
                        observation_id TEXT,
                        command TEXT,
                        result_summary TEXT,
                        service_account TEXT,
                        rbac_check_passed INTEGER NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)

                # Create indexes for common queries
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_timestamp
                    ON audit_logs(timestamp)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_operation_type
                    ON audit_logs(operation_type)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_resource
                    ON audit_logs(namespace, resource_name)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_success
                    ON audit_logs(success)
                """)

                await db.commit()

            self._initialized = True
            logger.info(f"Audit logger initialized: {self.db_path}")

    async def log(self, entry: AuditEntry) -> None:
        """
        Log an audit entry.

        Entry is AUTOMATICALLY SCRUBBED for secrets before storage.

        Args:
            entry: AuditEntry to log
        """
        if not self._initialized:
            await self.initialize()

        # CRITICAL: Scrub secrets before logging
        scrubbed_entry = self._scrub_entry(entry)

        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO audit_logs (
                        id, timestamp, operation_type, resource_kind, resource_name,
                        namespace, action, success, error, diagnosis_id, remediation_id,
                        observation_id, command, result_summary, service_account,
                        rbac_check_passed, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    scrubbed_entry.id,
                    scrubbed_entry.timestamp.isoformat(),
                    scrubbed_entry.operation_type.value,
                    scrubbed_entry.resource_kind,
                    scrubbed_entry.resource_name,
                    scrubbed_entry.namespace,
                    scrubbed_entry.action,
                    1 if scrubbed_entry.success else 0,
                    scrubbed_entry.error,
                    scrubbed_entry.diagnosis_id,
                    scrubbed_entry.remediation_id,
                    scrubbed_entry.observation_id,
                    scrubbed_entry.command,
                    scrubbed_entry.result_summary,
                    scrubbed_entry.service_account,
                    1 if scrubbed_entry.rbac_check_passed else 0,
                    datetime.utcnow().isoformat()
                ))
                await db.commit()

            logger.debug(
                f"Audit log written: {scrubbed_entry.to_summary()}",
                operation_type=scrubbed_entry.operation_type.value,
                resource_kind=scrubbed_entry.resource_kind,
                resource_name=scrubbed_entry.resource_name,
                namespace=scrubbed_entry.namespace
            )

        except Exception as e:
            # NEVER fail the operation due to audit logging errors
            # Just log the error and continue
            logger.error(
                f"Failed to write audit log: {e}",
                exc_info=True,
                audit_entry_id=scrubbed_entry.id
            )

    def _scrub_entry(self, entry: AuditEntry) -> AuditEntry:
        """
        Scrub secrets from audit entry.

        Args:
            entry: Original entry

        Returns:
            New entry with scrubbed fields
        """
        return AuditEntry(
            id=entry.id,
            timestamp=entry.timestamp,
            operation_type=entry.operation_type,
            resource_kind=entry.resource_kind,
            resource_name=entry.resource_name,
            namespace=entry.namespace,
            action=entry.action,
            success=entry.success,
            error=SecretScrubber.scrub(entry.error) if entry.error else None,
            diagnosis_id=entry.diagnosis_id,
            remediation_id=entry.remediation_id,
            observation_id=entry.observation_id,
            command=SecretScrubber.scrub(entry.command) if entry.command else None,
            result_summary=SecretScrubber.scrub(entry.result_summary) if entry.result_summary else None,
            service_account=entry.service_account,
            rbac_check_passed=entry.rbac_check_passed
        )

    async def log_operation(
        self,
        operation_type: OperationType,
        action: str,
        success: bool,
        resource_kind: Optional[str] = None,
        resource_name: Optional[str] = None,
        namespace: Optional[str] = None,
        error: Optional[str] = None,
        command: Optional[str] = None,
        result_summary: Optional[str] = None,
        diagnosis_id: Optional[str] = None,
        remediation_id: Optional[str] = None,
        observation_id: Optional[str] = None,
        service_account: Optional[str] = None,
        rbac_check_passed: bool = True
    ) -> None:
        """
        Convenience method to log an operation without creating AuditEntry manually.

        Args:
            operation_type: Type of operation (READ, WRITE, etc.)
            action: Action performed (get, patch, delete, etc.)
            success: Whether operation succeeded
            resource_kind: Kubernetes resource kind
            resource_name: Resource name
            namespace: Namespace
            error: Error message if failed
            command: Command executed
            result_summary: Brief result summary
            diagnosis_id: Associated diagnosis ID
            remediation_id: Associated remediation ID
            observation_id: Associated observation ID
            service_account: Service account used
            rbac_check_passed: Whether RBAC check passed
        """
        entry = AuditEntry(
            operation_type=operation_type,
            action=action,
            success=success,
            resource_kind=resource_kind,
            resource_name=resource_name,
            namespace=namespace,
            error=error,
            command=command,
            result_summary=result_summary,
            diagnosis_id=diagnosis_id,
            remediation_id=remediation_id,
            observation_id=observation_id,
            service_account=service_account,
            rbac_check_passed=rbac_check_passed
        )
        await self.log(entry)

    async def query(
        self,
        operation_type: Optional[OperationType] = None,
        namespace: Optional[str] = None,
        resource_name: Optional[str] = None,
        success: Optional[bool] = None,
        limit: int = 100
    ) -> list[dict]:
        """
        Query audit logs.

        Args:
            operation_type: Filter by operation type
            namespace: Filter by namespace
            resource_name: Filter by resource name
            success: Filter by success status
            limit: Maximum number of results

        Returns:
            List of audit log entries as dicts
        """
        if not self._initialized:
            await self.initialize()

        query = "SELECT * FROM audit_logs WHERE 1=1"
        params = []

        if operation_type:
            query += " AND operation_type = ?"
            params.append(operation_type.value)
        if namespace:
            query += " AND namespace = ?"
            params.append(namespace)
        if resource_name:
            query += " AND resource_name = ?"
            params.append(resource_name)
        if success is not None:
            query += " AND success = ?"
            params.append(1 if success else 0)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_stats(self) -> dict:
        """
        Get audit log statistics.

        Returns:
            Dict with statistics (total logs, success/fail counts, etc.)
        """
        if not self._initialized:
            await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM audit_logs") as cursor:
                total = (await cursor.fetchone())[0]

            async with db.execute("SELECT COUNT(*) FROM audit_logs WHERE success = 1") as cursor:
                success_count = (await cursor.fetchone())[0]

            async with db.execute("SELECT COUNT(*) FROM audit_logs WHERE success = 0") as cursor:
                failed_count = (await cursor.fetchone())[0]

            async with db.execute("""
                SELECT operation_type, COUNT(*) as count
                FROM audit_logs
                GROUP BY operation_type
            """) as cursor:
                operations = {row[0]: row[1] for row in await cursor.fetchall()}

            return {
                "total_logs": total,
                "success_count": success_count,
                "failed_count": failed_count,
                "operations": operations
            }


# Global singleton instance
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger(db_path: str = "/data/audit.db") -> AuditLogger:
    """
    Get global audit logger instance.

    Args:
        db_path: Path to SQLite database

    Returns:
        AuditLogger instance
    """
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger(db_path)
    return _audit_logger


if __name__ == "__main__":
    # Demo
    async def demo():
        logger = get_audit_logger("/tmp/test_audit.db")
        await logger.initialize()

        # Log a read operation
        await logger.log_operation(
            operation_type=OperationType.READ,
            action="get",
            success=True,
            resource_kind="Pod",
            resource_name="my-pod",
            namespace="default",
            command="oc get pod my-pod -n default -o json"
        )

        # Log a write operation with secret (will be scrubbed)
        await logger.log_operation(
            operation_type=OperationType.WRITE,
            action="patch",
            success=True,
            resource_kind="Pod",
            resource_name="my-pod",
            namespace="default",
            command="oc patch pod my-pod --password=secret123",  # Will be scrubbed
            result_summary="Pod patched successfully"
        )

        # Query logs
        logs = await logger.query(limit=10)
        print(f"Recent logs: {len(logs)}")
        for log in logs:
            print(f"  {log['timestamp']}: {log['action']} {log['resource_name']} - {'SUCCESS' if log['success'] else 'FAILED'}")

        # Get stats
        stats = await logger.get_stats()
        print(f"Stats: {stats}")

    asyncio.run(demo())
