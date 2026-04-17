"""
Tier 2: Lightweight RAG (Retrieval-Augmented Generation) Engine.

Uses TF-IDF for semantic search over internal runbooks - NO heavy ML dependencies.
Fully compatible with UBI9's SQLite version, drastically smaller image size.
"""

import os
import json
import sqlite3
import hashlib
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path
from collections import Counter
import math
import re

from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)


class TFIDFVectorizer:
    """Lightweight TF-IDF vectorizer without sklearn dependency."""

    def __init__(self):
        self.vocabulary = {}
        self.idf = {}
        self.doc_count = 0

    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenization."""
        text = text.lower()
        # Remove special chars, keep alphanumeric and spaces
        text = re.sub(r'[^a-z0-9\s]', ' ', text)
        tokens = text.split()
        # Filter stop words and short tokens
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been', 'being'}
        return [t for t in tokens if len(t) > 2 and t not in stop_words]

    def fit(self, documents: List[str]):
        """Build vocabulary and calculate IDF values."""
        self.doc_count = len(documents)
        doc_frequency = Counter()

        # Build vocabulary
        for doc in documents:
            tokens = set(self._tokenize(doc))
            for token in tokens:
                doc_frequency[token] += 1
                if token not in self.vocabulary:
                    self.vocabulary[token] = len(self.vocabulary)

        # Calculate IDF
        for term, freq in doc_frequency.items():
            self.idf[term] = math.log(self.doc_count / (1 + freq))

    def transform(self, text: str) -> Dict[int, float]:
        """Convert text to TF-IDF vector (sparse representation)."""
        tokens = self._tokenize(text)
        if not tokens:
            return {}

        # Calculate term frequency
        term_freq = Counter(tokens)
        doc_length = len(tokens)

        # Calculate TF-IDF
        vector = {}
        for term, freq in term_freq.items():
            if term in self.vocabulary:
                tf = freq / doc_length
                idf = self.idf.get(term, 0)
                tfidf = tf * idf
                if tfidf > 0:
                    vector[self.vocabulary[term]] = tfidf

        return vector

    def cosine_similarity(self, vec1: Dict[int, float], vec2: Dict[int, float]) -> float:
        """Calculate cosine similarity between two sparse vectors."""
        if not vec1 or not vec2:
            return 0.0

        # Dot product
        dot_product = sum(vec1.get(k, 0) * vec2.get(k, 0) for k in set(vec1.keys()) | set(vec2.keys()))

        # Magnitudes
        mag1 = math.sqrt(sum(v * v for v in vec1.values()))
        mag2 = math.sqrt(sum(v * v for v in vec2.values()))

        if mag1 == 0 or mag2 == 0:
            return 0.0

        return dot_product / (mag1 * mag2)


class LightweightRAGEngine:
    """
    Lightweight RAG engine using TF-IDF for semantic search.

    Benefits:
    - No ChromaDB dependency (SQLite compatibility issues)
    - No sentence-transformers (reduces image size by 5+ GB)
    - Pure Python + SQLite (already in UBI9)
    - Fast indexing and search
    - Persistent storage
    """

    def __init__(
        self,
        docs_path: str = "/data/internal-runbooks",
        db_path: str = "/data/rag_lite.db",
        enabled: bool = True
    ):
        """
        Initialize lightweight RAG engine.

        Args:
            docs_path: Path to internal documentation (markdown files)
            db_path: Path to SQLite database for vector storage
            enabled: Enable/disable RAG (via config)
        """
        self.docs_path = Path(docs_path)
        self.db_path = Path(db_path)
        self.enabled = enabled
        self.vectorizer = TFIDFVectorizer()

        if not self.enabled:
            logger.info("Lightweight RAG engine disabled")
            return

        try:
            # Initialize SQLite database
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_database()

            # Load vectorizer from database if exists
            self._load_vectorizer()

            logger.info(
                "Lightweight RAG engine initialized",
                docs_path=str(self.docs_path),
                db_path=str(self.db_path),
                document_count=self._get_document_count()
            )

        except Exception as e:
            logger.error(f"Failed to initialize lightweight RAG engine: {e}", exc_info=True)
            self.enabled = False

    def _init_database(self):
        """Initialize SQLite database schema."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Documents table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                file_path TEXT NOT NULL,
                content TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                vector TEXT NOT NULL,
                indexed_at TEXT NOT NULL
            )
        """)

        # Vectorizer state table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vectorizer_state (
                id INTEGER PRIMARY KEY,
                vocabulary TEXT NOT NULL,
                idf TEXT NOT NULL,
                doc_count INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Create index for faster searches
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_title ON documents(title)
        """)

        conn.commit()
        conn.close()

    def _load_vectorizer(self):
        """Load vectorizer state from database."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("SELECT vocabulary, idf, doc_count FROM vectorizer_state ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()

        if row:
            self.vectorizer.vocabulary = json.loads(row[0])
            self.vectorizer.idf = json.loads(row[1])
            self.vectorizer.doc_count = row[2]
            logger.info(f"Loaded vectorizer state: {self.vectorizer.doc_count} documents, {len(self.vectorizer.vocabulary)} terms")

        conn.close()

    def _save_vectorizer(self):
        """Save vectorizer state to database."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO vectorizer_state (vocabulary, idf, doc_count, updated_at)
            VALUES (?, ?, ?, ?)
        """, (
            json.dumps(self.vectorizer.vocabulary),
            json.dumps(self.vectorizer.idf),
            self.vectorizer.doc_count,
            datetime.utcnow().isoformat()
        ))

        conn.commit()
        conn.close()

    def _get_document_count(self) -> int:
        """Get number of indexed documents."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM documents")
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except:
            return 0

    async def search(
        self,
        query: str,
        top_k: int = 3,
        threshold: float = 0.3
    ) -> List[Dict[str, str]]:
        """
        Search internal knowledge base using TF-IDF similarity.

        Args:
            query: Search query (root cause, error message, etc.)
            top_k: Number of results to return
            threshold: Minimum similarity score (0-1)

        Returns:
            List of relevant documents with metadata
        """
        if not self.enabled:
            logger.debug("RAG search skipped - disabled")
            return []

        try:
            # Check if we have indexed documents
            if self.vectorizer.doc_count == 0:
                logger.debug("RAG search skipped - no indexed documents")
                return []

            # Vectorize query
            query_vector = self.vectorizer.transform(query)
            if not query_vector:
                logger.debug("Query produced empty vector")
                return []

            # Search database
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, file_path, content, vector FROM documents")

            results = []
            for row in cursor.fetchall():
                doc_id, title, file_path, content, vector_json = row
                doc_vector = json.loads(vector_json)
                # Convert back to int keys
                doc_vector = {int(k): v for k, v in doc_vector.items()}

                # Calculate similarity
                similarity = self.vectorizer.cosine_similarity(query_vector, doc_vector)

                if similarity >= threshold:
                    results.append({
                        "id": doc_id,
                        "title": title,
                        "url": f"file://{file_path}",
                        "description": content[:200] + ("..." if len(content) > 200 else ""),
                        "similarity": round(similarity, 3),
                        "tier": 2,
                        "source": "internal_rag_lite"
                    })

            conn.close()

            # Sort by similarity and take top_k
            results.sort(key=lambda x: x["similarity"], reverse=True)
            results = results[:top_k]

            logger.info(
                f"RAG Lite search completed: {len(results)} results",
                query=query[:100],
                top_k=top_k,
                threshold=threshold,
                results_count=len(results)
            )

            return results

        except Exception as e:
            logger.error(f"RAG Lite search failed: {e}", exc_info=True)
            return []

    async def index_documents(self, force_reindex: bool = False) -> int:
        """
        Index markdown documents from docs_path.

        Args:
            force_reindex: Force re-indexing even if already indexed

        Returns:
            Number of document chunks indexed
        """
        if not self.enabled:
            logger.warning("RAG Lite indexing skipped - disabled")
            return 0

        try:
            # Check if already indexed
            current_count = self._get_document_count()
            if current_count > 0 and not force_reindex:
                logger.info(f"RAG Lite database already has {current_count} chunks, skipping indexing")
                return current_count

            # Find all markdown files
            if not self.docs_path.exists():
                logger.warning(f"Docs path does not exist: {self.docs_path}")
                self.docs_path.mkdir(parents=True, exist_ok=True)
                # Create sample runbook
                self._create_sample_runbook()

            md_files = list(self.docs_path.rglob("*.md"))
            if not md_files:
                logger.warning(f"No markdown files found in {self.docs_path}")
                return 0

            logger.info(f"Indexing {len(md_files)} markdown files")

            # Collect all documents
            all_documents = []
            document_metadata = []

            for md_file in md_files:
                try:
                    content = md_file.read_text(encoding='utf-8')
                    chunks = self._split_document(content)

                    for i, chunk in enumerate(chunks):
                        all_documents.append(chunk)
                        document_metadata.append({
                            "title": md_file.stem.replace("-", " ").replace("_", " ").title(),
                            "file_path": str(md_file),
                            "chunk_index": i,
                            "content": chunk
                        })

                except Exception as e:
                    logger.error(f"Failed to process {md_file}: {e}")
                    continue

            if not all_documents:
                logger.warning("No documents to index")
                return 0

            # Fit vectorizer on all documents
            logger.info(f"Building TF-IDF model for {len(all_documents)} chunks")
            self.vectorizer.fit(all_documents)

            # Save vectorizer state
            self._save_vectorizer()

            # Insert documents into database
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # Clear existing documents if force reindex
            if force_reindex:
                cursor.execute("DELETE FROM documents")

            for doc, metadata in zip(all_documents, document_metadata):
                # Generate vector
                vector = self.vectorizer.transform(doc)

                # Create document ID
                doc_id = hashlib.md5(
                    f"{metadata['file_path']}_{metadata['chunk_index']}".encode()
                ).hexdigest()[:16]

                # Insert into database
                cursor.execute("""
                    INSERT OR REPLACE INTO documents (id, title, file_path, content, chunk_index, vector, indexed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    doc_id,
                    metadata["title"],
                    metadata["file_path"],
                    metadata["content"],
                    metadata["chunk_index"],
                    json.dumps(vector),
                    datetime.utcnow().isoformat()
                ))

            conn.commit()
            conn.close()

            logger.info(
                f"Successfully indexed {len(all_documents)} chunks from {len(md_files)} files",
                file_count=len(md_files),
                chunk_count=len(all_documents),
                vocabulary_size=len(self.vectorizer.vocabulary)
            )

            return len(all_documents)

        except Exception as e:
            logger.error(f"Document indexing failed: {e}", exc_info=True)
            return 0

    def _split_document(self, content: str, chunk_size: int = 500) -> List[str]:
        """
        Split document into chunks.

        Args:
            content: Document content
            chunk_size: Approximate characters per chunk

        Returns:
            List of content chunks
        """
        # Simple paragraph-based splitting
        paragraphs = content.split('\n\n')
        chunks = []
        current_chunk = []
        current_size = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            para_size = len(para)

            if current_size + para_size > chunk_size and current_chunk:
                chunks.append('\n\n'.join(current_chunk))
                current_chunk = [para]
                current_size = para_size
            else:
                current_chunk.append(para)
                current_size += para_size

        if current_chunk:
            chunks.append('\n\n'.join(current_chunk))

        return chunks

    def _create_sample_runbook(self):
        """Create a sample runbook for demonstration."""
        sample_content = """# OOMKilled Pod Remediation

## Symptoms
- Pod shows CrashLoopBackOff status
- Exit code 137 in pod events
- Container terminates unexpectedly

## Root Cause
The pod's container exceeded its memory limit and was killed by the kernel's OOM (Out of Memory) killer.

## Remediation Steps

### 1. Verify the Issue
```bash
oc describe pod <pod-name> -n <namespace>
# Look for: "Last State: Terminated, Reason: OOMKilled, Exit Code: 137"
```

### 2. Check Current Memory Limit
```bash
oc get deployment <deployment-name> -n <namespace> -o jsonpath='{.spec.template.spec.containers[0].resources.limits.memory}'
```

### 3. Increase Memory Limit
```bash
oc set resources deployment/<deployment-name> -n <namespace> --limits=memory=512Mi --requests=memory=512Mi
```

## Prevention
- Set appropriate memory limits based on application profiling
- Use HPA with memory-based metrics
- Monitor memory usage trends

## Related Issues
- ImagePullBackOff: Different issue, check image availability
- CrashLoopBackOff (non-OOM): Check application logs for errors
"""

        sample_file = self.docs_path / "oomkilled-remediation.md"
        sample_file.write_text(sample_content)
        logger.info(f"Created sample runbook: {sample_file}")


# Global singleton
_rag_engine_lite: Optional[LightweightRAGEngine] = None


def get_rag_engine_lite() -> LightweightRAGEngine:
    """Get or create global lightweight RAG engine instance."""
    global _rag_engine_lite
    if _rag_engine_lite is None:
        enabled = os.getenv("RAG_ENABLED", "false").lower() == "true"
        _rag_engine_lite = LightweightRAGEngine(enabled=enabled)
    return _rag_engine_lite
