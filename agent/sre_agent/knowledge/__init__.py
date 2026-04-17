"""
Knowledge Base module for tiered KB article retrieval.

Implements a 3-tier strategy:
- Tier 1: Hardcoded curated links (fastest, most reliable)
- Tier 2: RAG-based internal knowledge search
- Tier 3: Real-time Red Hat KB search (fallback)
"""

from sre_agent.knowledge.kb_retriever import KBRetriever, get_kb_retriever

__all__ = ["KBRetriever", "get_kb_retriever"]
