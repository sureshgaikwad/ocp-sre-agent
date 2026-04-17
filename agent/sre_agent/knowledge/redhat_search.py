"""
Tier 3: Real-Time Red Hat KB Search.

Searches Red Hat Customer Portal for relevant KB articles.
Uses web scraping as fallback (no official public API available).
"""

import os
import asyncio
import hashlib
from typing import List, Dict, Optional
from urllib.parse import quote_plus

import aiohttp
from bs4 import BeautifulSoup

from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class RedHatKBSearch:
    """
    Search Red Hat Knowledge Base for articles.

    Note: Red Hat Customer Portal doesn't have a public API.
    This implementation uses web scraping as a fallback.
    For production, consider using Red Hat Support API with customer credentials.
    """

    def __init__(self, enabled: bool = True):
        """
        Initialize Red Hat KB search.

        Args:
            enabled: Enable/disable real-time search
        """
        self.enabled = enabled
        self.base_url = "https://access.redhat.com"
        self.search_url = f"{self.base_url}/search/"

        # Optional: Red Hat API credentials (if available)
        self.api_key = os.getenv("REDHAT_API_KEY", "")
        self.api_enabled = bool(self.api_key)

        logger.info(
            "Red Hat KB search initialized",
            enabled=enabled,
            api_available=self.api_enabled
        )

    async def search(
        self,
        query: str,
        product: str = "Red Hat OpenShift Container Platform",
        top_k: int = 3
    ) -> List[Dict[str, str]]:
        """
        Search Red Hat KB for articles.

        Args:
            query: Search query (error message, issue description)
            product: Product filter
            top_k: Number of results to return

        Returns:
            List of KB articles with title, url, description
        """
        if not self.enabled:
            logger.debug("Red Hat KB search disabled")
            return []

        try:
            # If API available, use it (placeholder for future API integration)
            if self.api_enabled:
                return await self._search_via_api(query, product, top_k)

            # Otherwise, use web scraping
            return await self._search_via_web(query, product, top_k)

        except Exception as e:
            logger.error(f"Red Hat KB search failed: {e}", exc_info=True)
            return []

    async def _search_via_api(
        self,
        query: str,
        product: str,
        top_k: int
    ) -> List[Dict[str, str]]:
        """
        Search using Red Hat Support API (if credentials available).

        Note: Requires Red Hat customer portal account and API access.
        """
        logger.warning("Red Hat API search not fully implemented - using web fallback")
        return await self._search_via_web(query, product, top_k)

    async def _search_via_web(
        self,
        query: str,
        product: str,
        top_k: int
    ) -> List[Dict[str, str]]:
        """
        Search using web scraping (fallback method).

        Args:
            query: Search query
            product: Product filter
            top_k: Max results

        Returns:
            List of KB articles
        """
        try:
            # Build search URL
            # Format: /search/#/q=<query>&p=1&rows=10&product=<product>&documentKind=Solution
            encoded_query = quote_plus(query)
            encoded_product = quote_plus(product)

            # Use simple search URL (more reliable than advanced search)
            search_url = f"{self.search_url}?q={encoded_query}"

            logger.info(
                f"Searching Red Hat KB via web",
                query=query[:100],
                url=search_url
            )

            # Fetch search results
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    search_url,
                    timeout=aiohttp.ClientTimeout(total=10),
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; OpenShift-SRE-Agent/1.0)"
                    }
                ) as response:
                    if response.status != 200:
                        logger.error(f"Red Hat search HTTP {response.status}")
                        return []

                    html = await response.text()

            # Parse results
            articles = self._parse_search_results(html, top_k)

            logger.info(
                f"Red Hat KB search completed: {len(articles)} results",
                query=query[:100],
                results_count=len(articles)
            )

            return articles

        except asyncio.TimeoutError:
            logger.error("Red Hat KB search timed out")
            return []
        except Exception as e:
            logger.error(f"Red Hat KB web search failed: {e}", exc_info=True)
            return []

    def _parse_search_results(self, html: str, top_k: int) -> List[Dict[str, str]]:
        """
        Parse Red Hat search results page.

        Args:
            html: Search results HTML
            top_k: Max results to extract

        Returns:
            List of parsed articles
        """
        try:
            soup = BeautifulSoup(html, 'html.parser')
            articles = []

            # Red Hat search results structure (may change, needs maintenance)
            # Look for result items
            result_items = soup.find_all('div', class_=['result-item', 'search-result'], limit=top_k)

            for item in result_items:
                try:
                    # Extract title and link
                    title_elem = item.find('a', class_='result-title')
                    if not title_elem:
                        title_elem = item.find('a')

                    if not title_elem:
                        continue

                    title = title_elem.get_text(strip=True)
                    url = title_elem.get('href', '')

                    # Make URL absolute
                    if url and not url.startswith('http'):
                        url = f"{self.base_url}{url}"

                    # Extract description
                    desc_elem = item.find('div', class_=['result-description', 'description'])
                    description = desc_elem.get_text(strip=True) if desc_elem else title

                    # Filter: Only include relevant KB articles/solutions
                    if url and ('/solutions/' in url or '/articles/' in url or '/documentation/' in url):
                        articles.append({
                            "title": title[:200],
                            "url": url,
                            "description": description[:300],
                            "source": "redhat_kb_web"
                        })

                except Exception as e:
                    logger.debug(f"Failed to parse result item: {e}")
                    continue

            # Fallback: If web scraping failed, return generic links
            if not articles:
                logger.warning("Web scraping returned no results - using fallback")
                articles = [
                    {
                        "title": "Red Hat KB Search",
                        "url": f"{self.search_url}?q={quote_plus(query)}",
                        "description": "Search Red Hat Knowledge Base for more information",
                        "source": "redhat_kb_fallback"
                    }
                ]

            return articles[:top_k]

        except Exception as e:
            logger.error(f"Failed to parse search results: {e}", exc_info=True)
            return []


# Global singleton
_redhat_search: Optional[RedHatKBSearch] = None


def get_redhat_search() -> RedHatKBSearch:
    """Get or create global Red Hat KB search instance."""
    global _redhat_search
    if _redhat_search is None:
        enabled = os.getenv("REDHAT_KB_SEARCH_ENABLED", "false").lower() == "true"
        _redhat_search = RedHatKBSearch(enabled=enabled)
    return _redhat_search
