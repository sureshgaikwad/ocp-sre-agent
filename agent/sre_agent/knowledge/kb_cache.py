"""
KB Cache for Tier 3 search results.

Caches Red Hat KB search results to minimize API calls and latency.
Uses SQLite for persistent storage across restarts.
"""

import os
import json
import sqlite3
import hashlib
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from pathlib import Path

from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class KBCache:
    """
    Persistent cache for KB search results.

    Features:
    - SQLite-based persistent storage
    - Configurable TTL (time-to-live)
    - Automatic cleanup of expired entries
    - Query normalization for better hit rate
    """

    def __init__(
        self,
        db_path: str = "/data/kb_cache.db",
        default_ttl_days: int = 30
    ):
        """
        Initialize KB cache.

        Args:
            db_path: Path to SQLite database
            default_ttl_days: Default TTL for cache entries (days)
        """
        self.db_path = Path(db_path)
        self.default_ttl = timedelta(days=default_ttl_days)

        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_db()

        logger.info(
            "KB cache initialized",
            db_path=str(self.db_path),
            ttl_days=default_ttl_days
        )

    def _init_db(self):
        """Initialize cache database schema."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS kb_cache (
                    query_hash TEXT PRIMARY KEY,
                    query_text TEXT NOT NULL,
                    results TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    hit_count INTEGER DEFAULT 0
                )
            """)

            # Index for cleanup
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_expires_at
                ON kb_cache(expires_at)
            """)

            conn.commit()
            conn.close()

            logger.debug("KB cache database initialized")

        except Exception as e:
            logger.error(f"Failed to initialize KB cache database: {e}", exc_info=True)

    def _normalize_query(self, query: str) -> str:
        """
        Normalize query for better cache hit rate.

        Args:
            query: Original query

        Returns:
            Normalized query
        """
        # Lowercase, strip whitespace, remove punctuation
        normalized = query.lower().strip()

        # Remove common variations
        normalized = normalized.replace("openshift container platform", "openshift")
        normalized = normalized.replace("  ", " ")

        return normalized

    def _hash_query(self, query: str) -> str:
        """
        Generate hash for query.

        Args:
            query: Normalized query

        Returns:
            SHA256 hash
        """
        return hashlib.sha256(query.encode()).hexdigest()[:16]

    def get(self, query: str) -> Optional[List[Dict[str, str]]]:
        """
        Get cached results for query.

        Args:
            query: Search query

        Returns:
            Cached results if found and not expired, None otherwise
        """
        try:
            normalized = self._normalize_query(query)
            query_hash = self._hash_query(normalized)

            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # Get cached entry
            cursor.execute("""
                SELECT results, expires_at, hit_count
                FROM kb_cache
                WHERE query_hash = ?
            """, (query_hash,))

            row = cursor.fetchone()

            if row:
                results_json, expires_at_str, hit_count = row
                expires_at = datetime.fromisoformat(expires_at_str)

                # Check if expired
                if datetime.utcnow() > expires_at:
                    logger.debug(f"Cache entry expired for query: {query[:50]}")
                    conn.close()
                    return None

                # Update hit count
                cursor.execute("""
                    UPDATE kb_cache
                    SET hit_count = ?
                    WHERE query_hash = ?
                """, (hit_count + 1, query_hash))
                conn.commit()

                conn.close()

                results = json.loads(results_json)
                logger.info(
                    f"Cache hit for query: {query[:50]}",
                    query_hash=query_hash,
                    hit_count=hit_count + 1
                )
                return results

            conn.close()
            logger.debug(f"Cache miss for query: {query[:50]}")
            return None

        except Exception as e:
            logger.error(f"Cache get failed: {e}", exc_info=True)
            return None

    def set(
        self,
        query: str,
        results: List[Dict[str, str]],
        ttl: Optional[timedelta] = None
    ):
        """
        Cache results for query.

        Args:
            query: Search query
            results: KB articles to cache
            ttl: Time-to-live (defaults to default_ttl)
        """
        try:
            if not results:
                logger.debug("Not caching empty results")
                return

            normalized = self._normalize_query(query)
            query_hash = self._hash_query(normalized)

            ttl = ttl or self.default_ttl
            created_at = datetime.utcnow()
            expires_at = created_at + ttl

            results_json = json.dumps(results)

            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # Insert or replace
            cursor.execute("""
                INSERT OR REPLACE INTO kb_cache
                (query_hash, query_text, results, created_at, expires_at, hit_count)
                VALUES (?, ?, ?, ?, ?, 0)
            """, (
                query_hash,
                query[:500],  # Store truncated query for debugging
                results_json,
                created_at.isoformat(),
                expires_at.isoformat()
            ))

            conn.commit()
            conn.close()

            logger.info(
                f"Cached {len(results)} results for query: {query[:50]}",
                query_hash=query_hash,
                ttl_days=ttl.days
            )

        except Exception as e:
            logger.error(f"Cache set failed: {e}", exc_info=True)

    def cleanup_expired(self) -> int:
        """
        Remove expired cache entries.

        Returns:
            Number of entries removed
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            now = datetime.utcnow().isoformat()

            cursor.execute("""
                DELETE FROM kb_cache
                WHERE expires_at < ?
            """, (now,))

            deleted = cursor.rowcount
            conn.commit()
            conn.close()

            if deleted > 0:
                logger.info(f"Cleaned up {deleted} expired cache entries")

            return deleted

        except Exception as e:
            logger.error(f"Cache cleanup failed: {e}", exc_info=True)
            return 0

    def get_stats(self) -> Dict[str, int]:
        """
        Get cache statistics.

        Returns:
            Dict with total, expired, hit counts
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # Total entries
            cursor.execute("SELECT COUNT(*) FROM kb_cache")
            total = cursor.fetchone()[0]

            # Expired entries
            now = datetime.utcnow().isoformat()
            cursor.execute("""
                SELECT COUNT(*) FROM kb_cache
                WHERE expires_at < ?
            """, (now,))
            expired = cursor.fetchone()[0]

            # Total hits
            cursor.execute("SELECT SUM(hit_count) FROM kb_cache")
            total_hits = cursor.fetchone()[0] or 0

            conn.close()

            return {
                "total_entries": total,
                "expired_entries": expired,
                "total_hits": total_hits,
                "valid_entries": total - expired
            }

        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}", exc_info=True)
            return {}


# Global singleton
_kb_cache: Optional[KBCache] = None


def get_kb_cache() -> KBCache:
    """Get or create global KB cache instance."""
    global _kb_cache
    if _kb_cache is None:
        _kb_cache = KBCache()
    return _kb_cache
