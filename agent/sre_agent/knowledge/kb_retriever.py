"""
Main KB Retriever with Tiered Strategy.

Orchestrates 3-tier KB article retrieval:
- Tier 1: Hardcoded curated links (0ms, 100% reliable)
- Tier 2: RAG internal knowledge (50-200ms, high quality)
- Tier 3: Real-time Red Hat KB search (1-3s, comprehensive)
"""

import os
from typing import List, Dict, Optional
from datetime import timedelta

from sre_agent.models.diagnosis import Diagnosis
from sre_agent.knowledge.hardcoded_kb import get_hardcoded_links, get_all_categories
from sre_agent.knowledge.rag_engine_lite import get_rag_engine_lite
from sre_agent.knowledge.redhat_search import get_redhat_search
from sre_agent.knowledge.kb_cache import get_kb_cache
from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class KBRetriever:
    """
    Tiered Knowledge Base article retriever.

    Strategy:
    1. Try Tier 1 (hardcoded) - fastest, most reliable
    2. If not found, try Tier 2 (RAG) - internal knowledge
    3. If still not found, try Tier 3 (real-time search) - comprehensive

    Features:
    - Anti-hallucination: validates all URLs
    - Caching: Tier 3 results cached for 30 days
    - Graceful degradation: continues if a tier fails
    - Observability: logs which tier was used
    """

    def __init__(self):
        """Initialize KB retriever with all tiers."""
        # Tier 1: Always available (hardcoded)
        self.tier1_categories = get_all_categories()

        # Tier 2: Lightweight RAG (optional, no heavy ML dependencies)
        self.rag_enabled = os.getenv("RAG_ENABLED", "false").lower() == "true"
        if self.rag_enabled:
            self.rag_engine = get_rag_engine_lite()
        else:
            self.rag_engine = None

        # Tier 3: Real-time search (optional)
        self.tier3_enabled = os.getenv("REDHAT_KB_SEARCH_ENABLED", "false").lower() == "true"
        if self.tier3_enabled:
            self.redhat_search = get_redhat_search()
            self.kb_cache = get_kb_cache()
        else:
            self.redhat_search = None
            self.kb_cache = None

        # Anti-hallucination: trusted domains
        self.trusted_domains = [
            "access.redhat.com",
            "docs.openshift.com",
            "kubernetes.io",
            "console.redhat.com"
        ]

        logger.info(
            "KB Retriever initialized",
            tier1_categories=len(self.tier1_categories),
            tier2_enabled=self.rag_enabled,
            tier3_enabled=self.tier3_enabled
        )

    async def get_kb_articles(
        self,
        diagnosis: Diagnosis,
        max_articles: int = 3
    ) -> List[Dict[str, str]]:
        """
        Get KB articles for diagnosis using tiered strategy.

        Args:
            diagnosis: Diagnosis with category and root cause
            max_articles: Maximum articles to return

        Returns:
            List of KB articles with title, url, description, tier
        """
        category = diagnosis.category.value
        root_cause = diagnosis.root_cause

        logger.info(
            f"Retrieving KB articles for {category}",
            category=category,
            confidence=diagnosis.confidence.value
        )

        articles = []

        # ====================
        # TIER 1: Hardcoded
        # ====================
        tier1_results = self._tier1_hardcoded(category)
        if tier1_results:
            logger.info(
                f"Tier 1 hit: {len(tier1_results)} articles",
                category=category,
                tier="hardcoded"
            )
            articles.extend(tier1_results[:max_articles])

            # If we have enough, return early
            if len(articles) >= max_articles:
                return articles[:max_articles]

        # ====================
        # TIER 2: RAG
        # ====================
        if self.rag_enabled and self.rag_engine and self.rag_engine.enabled:
            tier2_results = await self._tier2_rag(root_cause, max_articles)
            if tier2_results:
                logger.info(
                    f"Tier 2 hit: {len(tier2_results)} articles",
                    tier="rag"
                )
                # Add RAG results that aren't duplicates
                for article in tier2_results:
                    if not self._is_duplicate(article, articles):
                        articles.append(article)

                if len(articles) >= max_articles:
                    return articles[:max_articles]

        # ====================
        # TIER 3: Real-time Search (with cache)
        # ====================
        if self.tier3_enabled and self.redhat_search and self.kb_cache:
            tier3_results = await self._tier3_realtime(root_cause, category, max_articles)
            if tier3_results:
                logger.info(
                    f"Tier 3 hit: {len(tier3_results)} articles",
                    tier="realtime_search"
                )
                # Add search results that aren't duplicates
                for article in tier3_results:
                    if not self._is_duplicate(article, articles):
                        articles.append(article)

        # Validate all URLs (anti-hallucination)
        validated_articles = [
            article for article in articles
            if self._validate_url(article.get("url", ""))
        ]

        if len(validated_articles) < len(articles):
            logger.warning(
                f"Filtered {len(articles) - len(validated_articles)} invalid URLs",
                original=len(articles),
                validated=len(validated_articles)
            )

        return validated_articles[:max_articles]

    def _tier1_hardcoded(self, category: str) -> List[Dict[str, str]]:
        """
        Tier 1: Get hardcoded KB links.

        Args:
            category: Diagnosis category

        Returns:
            List of KB articles
        """
        try:
            articles = get_hardcoded_links(category)

            # Add tier metadata
            for article in articles:
                article["tier"] = 1
                article["source"] = "hardcoded"

            return articles

        except Exception as e:
            logger.error(f"Tier 1 failed: {e}", exc_info=True)
            return []

    async def _tier2_rag(self, query: str, top_k: int) -> List[Dict[str, str]]:
        """
        Tier 2: Search internal knowledge using RAG.

        Args:
            query: Root cause or error message
            top_k: Max results

        Returns:
            List of KB articles from internal runbooks
        """
        try:
            if not self.rag_engine or not self.rag_engine.enabled:
                return []

            articles = await self.rag_engine.search(
                query=query,
                top_k=top_k,
                threshold=0.7
            )

            # Add tier metadata
            for article in articles:
                article["tier"] = 2
                if "source" not in article:
                    article["source"] = "internal_rag"

            return articles

        except Exception as e:
            logger.error(f"Tier 2 failed: {e}", exc_info=True)
            return []

    async def _tier3_realtime(
        self,
        query: str,
        category: str,
        top_k: int
    ) -> List[Dict[str, str]]:
        """
        Tier 3: Real-time Red Hat KB search (with caching).

        Args:
            query: Root cause or error message
            category: Diagnosis category (for cache key)
            top_k: Max results

        Returns:
            List of KB articles from Red Hat KB
        """
        try:
            if not self.redhat_search or not self.kb_cache:
                return []

            # Check cache first
            cache_key = f"{category}:{query[:100]}"
            cached_results = self.kb_cache.get(cache_key)

            if cached_results:
                logger.info("Tier 3 cache hit", category=category)
                # Add tier metadata
                for article in cached_results:
                    article["tier"] = 3
                return cached_results

            # Cache miss - perform real-time search
            logger.info("Tier 3 cache miss - searching", category=category)

            articles = await self.redhat_search.search(
                query=query,
                product="Red Hat OpenShift Container Platform",
                top_k=top_k
            )

            # Add tier metadata
            for article in articles:
                article["tier"] = 3
                if "source" not in article:
                    article["source"] = "redhat_kb_search"

            # Cache results for 30 days
            if articles:
                self.kb_cache.set(
                    cache_key,
                    articles,
                    ttl=timedelta(days=30)
                )

            return articles

        except Exception as e:
            logger.error(f"Tier 3 failed: {e}", exc_info=True)
            return []

    def _validate_url(self, url: str) -> bool:
        """
        Validate URL is from trusted domain (anti-hallucination).

        Args:
            url: URL to validate

        Returns:
            True if valid and trusted
        """
        if not url:
            return False

        # File URLs are OK (internal runbooks)
        if url.startswith("file://"):
            return True

        # Check if from trusted domain
        for domain in self.trusted_domains:
            if domain in url:
                return True

        logger.warning(f"Untrusted URL filtered: {url}")
        return False

    def _is_duplicate(
        self,
        article: Dict[str, str],
        existing: List[Dict[str, str]]
    ) -> bool:
        """
        Check if article is duplicate of existing.

        Args:
            article: Article to check
            existing: List of existing articles

        Returns:
            True if duplicate
        """
        url = article.get("url", "")
        title = article.get("title", "").lower()

        for existing_article in existing:
            existing_url = existing_article.get("url", "")
            existing_title = existing_article.get("title", "").lower()

            # Same URL
            if url and url == existing_url:
                return True

            # Very similar title
            if title and existing_title and title in existing_title:
                return True

        return False

    async def index_internal_docs(self) -> int:
        """
        Index internal documentation for RAG (Tier 2).

        Returns:
            Number of documents indexed
        """
        if not self.rag_enabled or not self.rag_engine:
            logger.warning("RAG not enabled - cannot index documents")
            return 0

        logger.info("Starting internal documentation indexing")
        count = await self.rag_engine.index_documents(force_reindex=False)

        logger.info(f"Indexed {count} document chunks")
        return count

    async def cleanup_cache(self) -> int:
        """
        Cleanup expired cache entries (Tier 3).

        Returns:
            Number of entries removed
        """
        if not self.tier3_enabled or not self.kb_cache:
            logger.warning("Tier 3 cache not enabled")
            return 0

        logger.info("Cleaning up KB cache")
        count = self.kb_cache.cleanup_expired()

        logger.info(f"Removed {count} expired cache entries")
        return count

    def get_stats(self) -> Dict:
        """
        Get KB retriever statistics.

        Returns:
            Stats dict with tier information
        """
        stats = {
            "tier1": {
                "enabled": True,
                "categories": len(self.tier1_categories)
            },
            "tier2": {
                "enabled": self.rag_enabled,
                "engine_available": self.rag_engine is not None
            },
            "tier3": {
                "enabled": self.tier3_enabled,
                "search_available": self.redhat_search is not None
            }
        }

        # Add cache stats if available
        if self.kb_cache:
            stats["tier3"]["cache"] = self.kb_cache.get_stats()

        return stats


# Global singleton
_kb_retriever: Optional[KBRetriever] = None


def get_kb_retriever() -> KBRetriever:
    """Get or create global KB retriever instance."""
    global _kb_retriever
    if _kb_retriever is None:
        _kb_retriever = KBRetriever()
    return _kb_retriever
