"""
Tier 2: RAG (Retrieval-Augmented Generation) Engine.

Uses semantic search over internal runbooks and documentation.
Powered by ChromaDB for vector storage and sentence-transformers for embeddings.
"""

import os
import json
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path

from sre_agent.utils.json_logger import get_logger

logger = get_logger(__name__)

# Optional dependencies - gracefully degrade if not available
try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    logger.warning("ChromaDB not available - RAG disabled")

try:
    from sentence_transformers import SentenceTransformer
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    logger.warning("sentence-transformers not available - RAG disabled")


class RAGEngine:
    """
    RAG engine for semantic search over internal knowledge.

    Features:
    - Semantic search using sentence embeddings
    - Persistent vector storage with ChromaDB
    - Incremental indexing of markdown documents
    - Relevance scoring and filtering
    """

    def __init__(
        self,
        docs_path: str = "/data/internal-runbooks",
        embedding_model: str = "all-MiniLM-L6-v2",
        enabled: bool = True
    ):
        """
        Initialize RAG engine.

        Args:
            docs_path: Path to internal documentation (markdown files)
            embedding_model: Sentence transformer model name
            enabled: Enable/disable RAG (via config)
        """
        self.docs_path = Path(docs_path)
        self.embedding_model_name = embedding_model
        self.enabled = enabled and CHROMADB_AVAILABLE and EMBEDDINGS_AVAILABLE

        if not self.enabled:
            logger.info("RAG engine disabled")
            return

        try:
            # Initialize ChromaDB
            chroma_path = Path("/data/chromadb")
            chroma_path.mkdir(parents=True, exist_ok=True)

            self.client = chromadb.PersistentClient(
                path=str(chroma_path),
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )

            # Get or create collection
            self.collection = self.client.get_or_create_collection(
                name="internal_knowledge",
                metadata={"hnsw:space": "cosine"}
            )

            # Load embedding model (lazy loading)
            self.model = None

            logger.info(
                "RAG engine initialized",
                docs_path=str(self.docs_path),
                embedding_model=embedding_model,
                collection_size=self.collection.count()
            )

        except Exception as e:
            logger.error(f"Failed to initialize RAG engine: {e}", exc_info=True)
            self.enabled = False

    def _get_model(self):
        """Lazy load embedding model."""
        if self.model is None:
            logger.info(f"Loading embedding model: {self.embedding_model_name}")
            self.model = SentenceTransformer(self.embedding_model_name)
        return self.model

    async def search(
        self,
        query: str,
        top_k: int = 3,
        threshold: float = 0.7
    ) -> List[Dict[str, str]]:
        """
        Search internal knowledge base using semantic similarity.

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
            # Generate query embedding
            model = self._get_model()
            query_embedding = model.encode(query).tolist()

            # Search ChromaDB
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                include=["documents", "metadatas", "distances"]
            )

            # Filter by threshold and format results
            kb_articles = []
            if results and results['ids'] and len(results['ids'][0]) > 0:
                for i, doc_id in enumerate(results['ids'][0]):
                    distance = results['distances'][0][i]
                    similarity = 1 - distance  # Convert distance to similarity

                    if similarity >= threshold:
                        metadata = results['metadatas'][0][i]
                        kb_articles.append({
                            "title": metadata.get("title", "Internal Runbook"),
                            "url": metadata.get("url", f"file://{metadata.get('file_path', 'unknown')}"),
                            "description": results['documents'][0][i][:200],
                            "similarity": round(similarity, 3),
                            "source": "internal_rag"
                        })

            logger.info(
                f"RAG search completed: {len(kb_articles)} results",
                query=query[:100],
                top_k=top_k,
                threshold=threshold,
                results_count=len(kb_articles)
            )

            return kb_articles

        except Exception as e:
            logger.error(f"RAG search failed: {e}", exc_info=True)
            return []

    async def index_documents(self, force_reindex: bool = False) -> int:
        """
        Index markdown documents from docs_path.

        Args:
            force_reindex: Force re-indexing even if already indexed

        Returns:
            Number of documents indexed
        """
        if not self.enabled:
            logger.warning("RAG indexing skipped - disabled")
            return 0

        try:
            # Check if already indexed
            current_count = self.collection.count()
            if current_count > 0 and not force_reindex:
                logger.info(f"RAG collection already has {current_count} documents, skipping indexing")
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

            # Load embedding model
            model = self._get_model()

            # Process each file
            documents = []
            metadatas = []
            ids = []

            for md_file in md_files:
                try:
                    content = md_file.read_text(encoding='utf-8')

                    # Split into chunks (simple paragraph split)
                    chunks = self._split_document(content)

                    for i, chunk in enumerate(chunks):
                        doc_id = f"{md_file.stem}_{i}"
                        documents.append(chunk)
                        metadatas.append({
                            "title": md_file.stem.replace("-", " ").title(),
                            "file_path": str(md_file),
                            "url": f"file://{md_file}",
                            "chunk_index": i,
                            "indexed_at": datetime.utcnow().isoformat()
                        })
                        ids.append(doc_id)

                except Exception as e:
                    logger.error(f"Failed to process {md_file}: {e}")
                    continue

            if not documents:
                logger.warning("No documents to index")
                return 0

            # Generate embeddings
            logger.info(f"Generating embeddings for {len(documents)} chunks")
            embeddings = model.encode(documents, show_progress_bar=False).tolist()

            # Add to ChromaDB
            self.collection.add(
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )

            logger.info(
                f"Successfully indexed {len(documents)} chunks from {len(md_files)} files",
                file_count=len(md_files),
                chunk_count=len(documents)
            )

            return len(documents)

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
_rag_engine: Optional[RAGEngine] = None


def get_rag_engine() -> RAGEngine:
    """Get or create global RAG engine instance."""
    global _rag_engine
    if _rag_engine is None:
        enabled = os.getenv("RAG_ENABLED", "false").lower() == "true"
        _rag_engine = RAGEngine(enabled=enabled)
    return _rag_engine
