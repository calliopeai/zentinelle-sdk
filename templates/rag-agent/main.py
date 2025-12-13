#!/usr/bin/env python3
"""
RAG Agent Template - Zentinelle Integration

A Retrieval-Augmented Generation agent with governance:
- Document retrieval policy checks
- PII detection in retrieved context
- Source attribution tracking
- Cost control for embeddings and completions

Usage:
    pip install zentinelle openai chromadb
    export ZENTINELLE_API_KEY=sk_agent_...
    export OPENAI_API_KEY=sk-...
    python main.py
"""
import os
from typing import List, Optional, Dict, Any

from openai import OpenAI
from zentinelle import ZentinelleClient, ModelUsage, EvaluateResult


class GovernedRAGAgent:
    """RAG agent with Zentinelle governance."""

    def __init__(
        self,
        zentinelle_api_key: str,
        openai_api_key: Optional[str] = None,
        embedding_model: str = "text-embedding-3-small",
        completion_model: str = "gpt-4o-mini",
    ):
        # Initialize OpenAI
        self.openai = OpenAI(api_key=openai_api_key)
        self.embedding_model = embedding_model
        self.completion_model = completion_model

        # Initialize Zentinelle
        self.zentinelle = ZentinelleClient(
            api_key=zentinelle_api_key,
            agent_type="rag-agent",
            fail_open=True,
        )

        # Register agent
        self.zentinelle.register(
            capabilities=["chat", "rag", "embeddings"],
            metadata={
                "template": "rag-agent",
                "embedding_model": embedding_model,
                "completion_model": completion_model,
            },
        )

        # Simple in-memory vector store (use ChromaDB/Pinecone in production)
        self.documents: List[Dict[str, Any]] = []
        self.embeddings: List[List[float]] = []

    def add_document(
        self,
        content: str,
        metadata: Optional[Dict] = None,
        user_id: Optional[str] = None,
    ) -> bool:
        """
        Add a document with governance checks.

        Args:
            content: Document content
            metadata: Document metadata
            user_id: User adding the document

        Returns:
            True if added successfully
        """
        # Check document ingestion policy
        result = self.zentinelle.evaluate(
            action="document_ingest",
            user_id=user_id,
            context={
                "content_length": len(content),
                "metadata": metadata or {},
            },
        )

        if not result.allowed:
            print(f"Document blocked: {result.reason}")
            return False

        # Check for PII before ingestion
        pii_result = self.zentinelle.evaluate(
            action="pii_check",
            user_id=user_id,
            context={"content": content[:2000]},
        )

        if not pii_result.allowed:
            print(f"PII detected: {pii_result.reason}")
            # Could redact here instead of blocking
            return False

        # Generate embedding
        response = self.openai.embeddings.create(
            model=self.embedding_model,
            input=content,
        )

        # Track embedding usage
        self.zentinelle.emit("embedding_created", {
            "model": self.embedding_model,
            "tokens": response.usage.total_tokens,
        }, category="telemetry", user_id=user_id)

        # Store document
        self.documents.append({
            "content": content,
            "metadata": metadata or {},
        })
        self.embeddings.append(response.data[0].embedding)

        self.zentinelle.emit("document_added", {
            "content_length": len(content),
            "total_documents": len(self.documents),
        }, category="audit", user_id=user_id)

        return True

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve relevant documents with governance.

        Args:
            query: Search query
            top_k: Number of results
            user_id: User making the query

        Returns:
            List of relevant documents
        """
        if not self.documents:
            return []

        # Check retrieval policy
        result = self.zentinelle.evaluate(
            action="document_retrieval",
            user_id=user_id,
            context={
                "query_length": len(query),
                "top_k": top_k,
            },
        )

        if not result.allowed:
            print(f"Retrieval blocked: {result.reason}")
            return []

        # Generate query embedding
        response = self.openai.embeddings.create(
            model=self.embedding_model,
            input=query,
        )
        query_embedding = response.data[0].embedding

        # Simple cosine similarity search
        scores = []
        for i, doc_embedding in enumerate(self.embeddings):
            score = self._cosine_similarity(query_embedding, doc_embedding)
            scores.append((i, score))

        # Sort by score and get top_k
        scores.sort(key=lambda x: x[1], reverse=True)
        results = []
        for idx, score in scores[:top_k]:
            results.append({
                **self.documents[idx],
                "score": score,
            })

        self.zentinelle.emit("retrieval_completed", {
            "query_length": len(query),
            "results_count": len(results),
            "top_score": results[0]["score"] if results else 0,
        }, category="telemetry", user_id=user_id)

        return results

    def query(
        self,
        question: str,
        user_id: Optional[str] = None,
    ) -> str:
        """
        Answer a question using RAG with governance.

        Args:
            question: User's question
            user_id: User identifier

        Returns:
            Generated answer
        """
        # Evaluate RAG query policy
        result = self.zentinelle.evaluate(
            action="rag_query",
            user_id=user_id,
            context={"question_length": len(question)},
        )

        if not result.allowed:
            return f"[Query blocked: {result.reason}]"

        # Retrieve relevant documents
        docs = self.retrieve(question, top_k=3, user_id=user_id)

        if not docs:
            context = "No relevant documents found."
        else:
            context = "\n\n".join([
                f"[Source {i+1}]: {doc['content']}"
                for i, doc in enumerate(docs)
            ])

        # Generate response
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant. Answer questions based on the "
                    "provided context. Always cite your sources using [Source N] "
                    "notation. If the context doesn't contain relevant information, "
                    "say so."
                ),
            },
            {
                "role": "user",
                "content": f"Context:\n{context}\n\nQuestion: {question}",
            },
        ]

        response = self.openai.chat.completions.create(
            model=self.completion_model,
            messages=messages,
        )

        # Track completion usage
        if response.usage:
            self.zentinelle.track_usage(ModelUsage(
                provider="openai",
                model=self.completion_model,
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
            ))

        answer = response.choices[0].message.content

        self.zentinelle.emit("rag_query_completed", {
            "question_length": len(question),
            "context_docs": len(docs),
            "answer_length": len(answer),
        }, category="audit", user_id=user_id)

        return answer

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        import math
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        return dot / (norm_a * norm_b) if norm_a and norm_b else 0

    def shutdown(self):
        """Clean shutdown."""
        self.zentinelle.shutdown()


def main():
    """Demo the RAG agent."""
    agent = GovernedRAGAgent(
        zentinelle_api_key=os.environ.get("ZENTINELLE_API_KEY", ""),
    )

    user_id = "demo-user"

    # Add some sample documents
    sample_docs = [
        "Zentinelle is an AI agent governance platform that provides policy "
        "enforcement, secrets management, and observability for AI agents.",

        "Rate limiting policies in Zentinelle can be configured per agent, "
        "per user, or per organization. They support requests per minute and "
        "burst limits.",

        "PII detection in Zentinelle identifies names, emails, phone numbers, "
        "SSNs, and other sensitive data. Detected PII can be redacted, blocked, "
        "or logged for compliance.",
    ]

    print("Adding sample documents...")
    for doc in sample_docs:
        agent.add_document(doc, user_id=user_id)

    print(f"\nRAG Agent ready with {len(agent.documents)} documents")
    print("=" * 40)
    print("Type 'quit' to exit\n")

    try:
        while True:
            question = input("Question: ").strip()
            if question.lower() in ['quit', 'exit', 'q']:
                break
            if not question:
                continue

            answer = agent.query(question, user_id=user_id)
            print(f"\nAnswer: {answer}\n")

    except KeyboardInterrupt:
        print("\nGoodbye!")
    finally:
        agent.shutdown()


if __name__ == "__main__":
    main()
