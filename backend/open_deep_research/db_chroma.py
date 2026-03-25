"""ChromaDB database implementation - replaces Qdrant (no separate server needed)"""

import chromadb
from chromadb.config import Settings
from openai import OpenAI
import uuid
from datetime import datetime
from typing import List, Dict, Optional
import json
import os
from dotenv import load_dotenv

load_dotenv()

# Lazy OpenAI client — created on first use
_openai_client: Optional[OpenAI] = None


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to your .env file."
            )
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


# ChromaDB persistent client (embedded - no separate server needed)
client = chromadb.PersistentClient(path="./chroma_db")

COLLECTION_NAME = "user_summaries_v2"

# Use text-embedding-3-small (most cost-effective)
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536

# Auto-initialize collection
try:
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )
    print(f"✓ ChromaDB collection '{COLLECTION_NAME}' ready")
except Exception as e:
    print(f"Note: ChromaDB collection will be created on first use: {e}")


def get_embedding(text: str) -> List[float]:
    """
    Generate embedding using OpenAI's text-embedding-3-small model.
    
    Args:
        text: Text to embed
        
    Returns:
        List of floats representing the embedding vector (1536 dimensions)
    """
    try:
        # Clean the text
        text = text.replace("\n", " ").strip()
        
        # Truncate if too long (max 8191 tokens)
        if len(text) > 8000:
            text = text[:8000]
        
        # Handle empty text
        if not text or len(text.strip()) == 0:
            text = "Empty medical report"
        
        # Generate embedding using text-embedding-3-small
        response = _get_openai_client().embeddings.create(
            input=text,
            model=EMBEDDING_MODEL
        )
        
        return response.data[0].embedding
        
    except Exception as e:
        print(f"Error generating embedding: {e}")
        raise


def init_db():
    """Initialize ChromaDB (no-op since collection is auto-created)"""
    try:
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
        count = collection.count()
        print(f"✓ ChromaDB initialized: {count} documents in {COLLECTION_NAME}")
    except Exception as e:
        print(f"ChromaDB initialization note: {e}")


def save_summary(
    user_id: str, 
    summary: any, 
    date: str = None, 
    metadata: dict = None
):
    """
    Save ONLY the summary_text to ChromaDB with OpenAI embeddings.
    
    Args:
        user_id: User identifier
        summary: Can be dict (structured) or str (plain text)
        date: Report date (YYYY-MM-DD format)
        metadata: Additional metadata
    """
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    # Extract ONLY the summary text
    if isinstance(summary, dict):
        summary_text = (
            summary.get('narrative_summary', '')
            or summary.get('summary_text', '')
        )
    else:
        summary_text = str(summary)
    
    # Validate text
    if not summary_text or len(summary_text.strip()) == 0:
        print(f"Warning: Empty summary text for user {user_id}, using default")
        summary_text = f"Medical report for user {user_id} on {date}"
    
    try:
        # Generate embedding using OpenAI
        embedding = get_embedding(summary_text)
        
        # Prepare metadata
        doc_metadata = {
            "user_id": user_id,
            "date": date,
            "timestamp": datetime.now().isoformat(),
            "embedding_model": EMBEDDING_MODEL,
            "summary_text": summary_text[:1000]  # ChromaDB metadata size limit
        }
        
        if metadata:
            doc_metadata.update(metadata)
        
        # Generate unique ID
        doc_id = str(uuid.uuid4())
        
        # Get collection
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
        
        # Store in ChromaDB
        collection.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[summary_text],
            metadatas=[doc_metadata]
        )
        
        print(f"✓ Saved summary to ChromaDB for user {user_id} (date: {date})")
        
    except Exception as e:
        print(f"✗ Error saving summary to ChromaDB: {e}")
        raise


def get_user_summaries(user_id: str, limit: int = 10) -> List[Dict]:
    """
    Retrieve user's historical summary texts from ChromaDB.
    
    Args:
        user_id: User identifier
        limit: Maximum number of summaries to retrieve
        
    Returns:
        List of dicts with 'id', 'user_id', 'date', 'summary', 'timestamp', 'metadata'
    """
    try:
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
        
        # Query by user_id
        results = collection.get(
            where={"user_id": user_id},
            limit=limit,
            include=["documents", "metadatas"]
        )
        
        if not results or not results["ids"]:
            return []
        
        summaries = []
        for i, doc_id in enumerate(results["ids"]):
            meta = results["metadatas"][i]
            doc = results["documents"][i]
            
            summaries.append({
                "id": doc_id,
                "user_id": meta.get("user_id"),
                "date": meta.get("date"),
                "summary": {
                    "summary_text": doc,
                    "report_date": meta.get("date")
                },
                "timestamp": meta.get("timestamp"),
                "metadata": {k: v for k, v in meta.items() 
                           if k not in ["user_id", "date", "timestamp", "summary_text"]}
            })
        
        # Sort by date (newest first)
        summaries.sort(key=lambda x: x.get("date", ""), reverse=True)
        
        return summaries[:limit]
        
    except Exception as e:
        print(f"Error retrieving summaries from ChromaDB: {e}")
        return []


def get_summary_by_date(user_id: str, date: str) -> Optional[Dict]:
    """
    Retrieve a specific summary by user_id and date.
    
    Args:
        user_id: User identifier
        date: Report date (YYYY-MM-DD)
        
    Returns:
        Summary dict or None
    """
    try:
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
        
        results = collection.get(
            where={"$and": [
                {"user_id": user_id},
                {"date": date}
            ]},
            limit=1,
            include=["documents", "metadatas"]
        )
        
        if not results or not results["ids"]:
            return None
        
        meta = results["metadatas"][0]
        doc = results["documents"][0]
        
        return {
            "id": results["ids"][0],
            "user_id": meta.get("user_id"),
            "date": meta.get("date"),
            "summary": {
                "summary_text": doc,
                "report_date": meta.get("date")
            },
            "timestamp": meta.get("timestamp"),
            "metadata": {k: v for k, v in meta.items() 
                       if k not in ["user_id", "date", "timestamp", "summary_text"]}
        }
        
    except Exception as e:
        print(f"Error getting summary by date from ChromaDB: {e}")
        return None


def get_parameter_history(user_id: str, parameter_name: str, limit: int = 10) -> List[Dict]:
    """
    Retrieve parameter history (returns empty - use previousValues from payload instead).
    
    Args:
        user_id: User identifier
        parameter_name: Parameter name
        limit: Maximum results
        
    Returns:
        Empty list (parameter history should come from request payload)
    """
    # ChromaDB stores only summary text, not structured parameter data
    # Parameter history should come from the request payload's previousValues
    return []


def get_summaries_by_date_range(
    user_id: str, 
    start_date: str, 
    end_date: str
) -> List[Dict]:
    """
    Retrieve summaries within a date range.
    
    Args:
        user_id: User identifier
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        
    Returns:
        List of summary dicts
    """
    try:
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
        
        # Get all summaries for user and filter by date
        results = collection.get(
            where={"user_id": user_id},
            include=["documents", "metadatas"]
        )
        
        if not results or not results["ids"]:
            return []
        
        summaries = []
        for i, doc_id in enumerate(results["ids"]):
            meta = results["metadatas"][i]
            doc_date = meta.get("date", "")
            
            # Filter by date range
            if start_date <= doc_date <= end_date:
                summaries.append({
                    "id": doc_id,
                    "user_id": meta.get("user_id"),
                    "date": doc_date,
                    "summary": {
                        "summary_text": results["documents"][i],
                        "report_date": doc_date
                    },
                    "timestamp": meta.get("timestamp"),
                    "metadata": {k: v for k, v in meta.items() 
                               if k not in ["user_id", "date", "timestamp", "summary_text"]}
                })
        
        # Sort by date (newest first)
        summaries.sort(key=lambda x: x.get("date", ""), reverse=True)
        
        return summaries
        
    except Exception as e:
        print(f"Error getting summaries by date range from ChromaDB: {e}")
        return []


def delete_summary_by_date(user_id: str, date: str):
    """
    Delete a summary by user_id and date.
    
    Args:
        user_id: User identifier
        date: Report date (YYYY-MM-DD)
    """
    try:
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
        
        # Find matching documents
        results = collection.get(
            where={"$and": [
                {"user_id": user_id},
                {"date": date}
            ]},
            include=["metadatas"]
        )
        
        if results and results["ids"]:
            collection.delete(ids=results["ids"])
            print(f"✓ Deleted {len(results['ids'])} summary/summaries for user {user_id} on {date}")
        else:
            print(f"No summaries found for user {user_id} on {date}")
            
    except Exception as e:
        print(f"Error deleting summary from ChromaDB: {e}")
        raise


# Initialize on import
try:
    init_db()
except Exception as e:
    print(f"ChromaDB will initialize on first use: {e}")
