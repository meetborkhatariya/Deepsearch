"""Fixed Qdrant database with correct filter syntax and text-embedding-3-small only"""

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue, PointIdsList
from openai import OpenAI
import uuid
from datetime import datetime
from typing import List, Dict, Optional
import json
import os
from dotenv import load_dotenv

load_dotenv()

# Lazy OpenAI client — created on first use so import never fails if key not yet set
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


client = QdrantClient(host="localhost", port=6333)

COLLECTION_NAME = "user_summaries_v2"

# Use ONLY text-embedding-3-small (most cost-effective)
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536

# Auto-initialize collection on module import (will create if doesn't exist)
try:
    collections = client.get_collections().collections
    if not any(col.name == COLLECTION_NAME for col in collections):
        print(f"⚠️  Collection '{COLLECTION_NAME}' not found. It will be created on first save.")
except Exception as e:
    print(f"Note: Qdrant collection will be initialized on first use")


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


def migrate_from_old_collection():
    """
    Migrate data from old collection (sentence-transformers) to new collection (OpenAI).
    """
    OLD_COLLECTION = "user_summaries"
    NEW_COLLECTION = COLLECTION_NAME
    
    try:
        # Check if old collection exists
        collections = client.get_collections().collections
        old_exists = any(col.name == OLD_COLLECTION for col in collections)
        new_exists = any(col.name == NEW_COLLECTION for col in collections)
        
        if not old_exists:
            print("No old collection found. Starting fresh with OpenAI embeddings.")
            return
        
        if new_exists:
            print(f"New collection '{NEW_COLLECTION}' already exists. Skipping migration.")
            return
        
        print(f"Migrating from '{OLD_COLLECTION}' to '{NEW_COLLECTION}'...")
        
        # Create new collection with OpenAI dimensions
        client.create_collection(
            collection_name=NEW_COLLECTION,
            vectors_config=VectorParams(
                size=EMBEDDING_DIMENSIONS, 
                distance=Distance.COSINE
            )
        )
        print(f"Created new collection: {NEW_COLLECTION}")
        
        # Get all points from old collection
        scroll_result = client.scroll(
            collection_name=OLD_COLLECTION,
            limit=10000,
            with_payload=True,
            with_vectors=False
        )
        
        old_points = scroll_result[0]
        
        if not old_points:
            print("Old collection is empty. Nothing to migrate.")
            return
        
        print(f"Found {len(old_points)} records to migrate...")
        
        # Migrate each point
        migrated_count = 0
        failed_count = 0
        
        for point in old_points:
            try:
                payload = point.payload
                
                # Extract text for re-embedding
                summary_data = payload.get('summary', {})
                if isinstance(summary_data, dict):
                    text = summary_data.get('narrative_summary', '') or summary_data.get('summary_text', '')
                else:
                    text = str(summary_data)
                
                if not text or len(text.strip()) == 0:
                    print(f"Skipping empty summary for user {payload.get('user_id')}")
                    failed_count += 1
                    continue
                
                # Generate new OpenAI embedding
                new_embedding = get_embedding(text)
                
                # Update payload
                payload['migrated_from'] = OLD_COLLECTION
                payload['migration_date'] = datetime.now().isoformat()
                payload['embedding_model'] = EMBEDDING_MODEL
                
                # Insert into new collection
                client.upsert(
                    collection_name=NEW_COLLECTION,
                    points=[
                        PointStruct(
                            id=str(uuid.uuid4()),
                            vector=new_embedding,
                            payload=payload
                        )
                    ]
                )
                
                migrated_count += 1
                
                if migrated_count % 10 == 0:
                    print(f"Migrated {migrated_count}/{len(old_points)} records...")
                
            except Exception as e:
                print(f"Error migrating point {point.id}: {e}")
                failed_count += 1
                continue
        
        print(f"\n✅ Migration complete!")
        print(f"   - Successfully migrated: {migrated_count}")
        print(f"   - Failed: {failed_count}")
        
    except Exception as e:
        print(f"Migration error: {e}")


def init_db(auto_migrate: bool = True):
    """
    Initialize Qdrant collection with OpenAI embeddings (text-embedding-3-small only).
    
    Args:
        auto_migrate: If True, automatically migrate from old collection
    """
    try:
        collections = client.get_collections().collections
        collection_exists = any(col.name == COLLECTION_NAME for col in collections)
        
        if not collection_exists:
            print(f"Creating new collection: {COLLECTION_NAME}")
            # Create new collection
            client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=EMBEDDING_DIMENSIONS, distance=Distance.COSINE)
            )
            print(f"✅ Created collection '{COLLECTION_NAME}' successfully")
            # Attempt migration if old collection exists
            if auto_migrate:
                migrate_from_old_collection()
        else:
            print(f"Collection '{COLLECTION_NAME}' already exists")
    except Exception as e:
        print(f"Error initializing database: {e}")
        # Non-fatal — server starts without Qdrant; will fail on actual DB calls

def save_summary(
    user_id: str, 
    summary: any, 
    date: str = None, 
    metadata: dict = None
):
    """
    Save ONLY the summary_text to Qdrant with OpenAI embeddings (text-embedding-3-small).
    
    This stores only contextual narrative text — not parameter-level structured data.
    The stored summary_text is used exclusively to provide the model with contextual
    awareness of what was previously covered (past recommendations, health focus, etc.).
    
    Args:
        user_id: User identifier
        summary: Can be dict (structured) or str (plain text).
                 If dict, only 'narrative_summary' or 'summary_text' fields are stored.
        date: Report date (YYYY-MM-DD format)
        metadata: Additional metadata
    """
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    # Extract ONLY the summary text — never store full structured data
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
        # Generate embedding using OpenAI (text-embedding-3-small)
        embedding = get_embedding(summary_text)
        
        # Prepare payload — store ONLY summary_text, no parameter-level data
        payload = {
            "user_id": user_id,
            "date": date,
            "summary": {
                "summary_text": summary_text,
                "report_date": date
            },
            "timestamp": datetime.now().isoformat(),
            "embedding_model": EMBEDDING_MODEL
        }
        
        if metadata:
            payload["metadata"] = metadata
        
        point_id = str(uuid.uuid4())
        
        # Store in Qdrant
        client.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload=payload
                )
            ]
        )
        
        print(f"✅ Saved summary_text to Qdrant for user {user_id} (date: {date})")
        
    except Exception as e:
        print(f"❌ Error saving summary: {e}")
        raise


def get_user_summaries(user_id: str, limit: int = 10) -> List[Dict]:
    """
    Retrieve user's historical summary texts from Qdrant.
    
    Returns only summary_text for contextual awareness — no parameter-level data.
    Callers must NOT use this data for trend/comparison analysis; use previousValues
    from the incoming request payload for that purpose.
    
    Args:
        user_id: User identifier
        limit: Maximum number of summaries to retrieve
        
    Returns:
        List of dicts with 'id', 'user_id', 'date', 'summary' (summary_text only),
        'timestamp', 'metadata' — sorted newest first.
    """
    try:
        # Correct filter syntax for Qdrant
        search_result = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="user_id",
                        match=MatchValue(value=user_id)
                    )
                ]
            ),
            limit=limit * 2,
            with_payload=True,
            with_vectors=False
        )
        
        points = search_result[0]
        
        if not points:
            return []
        
        summaries = []
        for point in points:
            payload = point.payload
            raw_summary = payload.get("summary", {})
            
            # Normalise to always return only summary_text
            if isinstance(raw_summary, dict):
                summary_text = (
                    raw_summary.get("summary_text", "")
                    or raw_summary.get("narrative_summary", "")
                )
                report_date = raw_summary.get("report_date", payload.get("date", ""))
            else:
                summary_text = str(raw_summary)
                report_date = payload.get("date", "")
            
            summaries.append({
                "id": point.id,
                "user_id": payload.get("user_id"),
                "date": payload.get("date"),
                "summary": {
                    "summary_text": summary_text,
                    "report_date": report_date
                },
                "timestamp": payload.get("timestamp"),
                "metadata": payload.get("metadata", {}),
                "embedding_model": payload.get("embedding_model", EMBEDDING_MODEL)
            })
        
        # Sort by date (newest first)
        summaries.sort(key=lambda x: x.get("date", ""), reverse=True)
        return summaries[:limit]
        
    except Exception as e:
        print(f"Error retrieving summaries: {e}")
        import traceback
        traceback.print_exc()
        return []


def semantic_search_summaries(user_id: str, query: str, limit: int = 5) -> List[Dict]:
    """
    Perform semantic search across user's summaries using OpenAI embeddings.
    
    Args:
        user_id: User identifier
        query: Natural language search query
        limit: Maximum number of results
        
    Returns:
        List of relevant summaries with similarity scores
    """
    try:
        # Generate embedding for query
        query_embedding = get_embedding(query)
        
        # Search with user filter
        search_result = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_embedding,
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="user_id",
                        match=MatchValue(value=user_id)
                    )
                ]
            ),
            limit=limit,
            with_payload=True
        )
        
        results = []
        for scored_point in search_result:
            raw_summary = scored_point.payload.get("summary", {})
            if isinstance(raw_summary, dict):
                summary_text = (
                    raw_summary.get("summary_text", "")
                    or raw_summary.get("narrative_summary", "")
                )
                report_date = raw_summary.get("report_date", scored_point.payload.get("date", ""))
            else:
                summary_text = str(raw_summary)
                report_date = scored_point.payload.get("date", "")
            
            results.append({
                "id": scored_point.id,
                "score": scored_point.score,
                "user_id": scored_point.payload.get("user_id"),
                "date": scored_point.payload.get("date"),
                "summary": {
                    "summary_text": summary_text,
                    "report_date": report_date
                },
                "timestamp": scored_point.payload.get("timestamp"),
                "metadata": scored_point.payload.get("metadata", {})
            })
        
        return results
        
    except Exception as e:
        print(f"Error performing semantic search: {e}")
        import traceback
        traceback.print_exc()
        return []


def get_summaries_by_date_range(user_id: str, start_date: str, end_date: str) -> List[Dict]:
    """Get summaries within a date range."""
    all_summaries = get_user_summaries(user_id, limit=100)
    return [s for s in all_summaries if start_date <= s.get("date", "") <= end_date]


def get_summary_by_date(user_id: str, date: str) -> Optional[Dict]:
    """
    Get a specific summary by exact date.
    
    Args:
        user_id: User identifier
        date: Report date (YYYY-MM-DD)
        
    Returns:
        Summary dict if found, None otherwise
    """
    try:
        search_result = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=Filter(
                must=[
                    FieldCondition(key="user_id", match=MatchValue(value=user_id)),
                    FieldCondition(key="date", match=MatchValue(value=date))
                ]
            ),
            limit=1,
            with_payload=True,
            with_vectors=False
        )
        
        points = search_result[0]
        if not points:
            return None
        
        payload = points[0].payload
        return {
            "id": points[0].id,
            "user_id": payload.get("user_id"),
            "date": payload.get("date"),
            "summary": payload.get("summary"),
            "timestamp": payload.get("timestamp"),
            "metadata": payload.get("metadata", {}),
            "embedding_model": payload.get("embedding_model", EMBEDDING_MODEL)
        }
        
    except Exception as e:
        print(f"Error retrieving summary by date: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_parameter_history(user_id: str, parameter_name: str) -> List[Dict]:
    """
    DEPRECATED: Parameter-level historical data is no longer stored in Qdrant.
    
    Qdrant now stores only summary_text for contextual awareness.  All trend
    analysis and comparison must be performed using the previousValues supplied
    in the incoming request payload.
    
    Returns an empty list unconditionally.
    """
    print(
        f"[get_parameter_history] WARNING: parameter history is not stored in Qdrant. "
        f"Use previousValues from the request payload for trend analysis."
    )
    return []


def delete_user_summaries(user_id: str) -> int:
    """
    Delete all summaries for a specific user.
    
    Args:
        user_id: User identifier
        
    Returns:
        Number of deleted summaries
    """
    try:
        summaries = get_user_summaries(user_id, limit=1000)
        if not summaries:
            return 0
        
        point_ids = [s['id'] for s in summaries]
        client.delete(collection_name=COLLECTION_NAME, points_selector=PointIdsList(points=point_ids))
        
        print(f"Deleted {len(point_ids)} summaries for user {user_id}")
        return len(point_ids)
        
    except Exception as e:
        print(f"Error deleting summaries: {e}")
        return 0


def get_embedding_stats(user_id: str) -> Dict:
    """
    Get statistics about embeddings used for a user.
    
    Args:
        user_id: User identifier
        
    Returns:
        Dict with embedding statistics
    """
    summaries = get_user_summaries(user_id, limit=1000)
    
    if not summaries:
        return {
            "total_summaries": 0,
            "embedding_model": EMBEDDING_MODEL,
            "embedding_dimensions": EMBEDDING_DIMENSIONS
        }
    
    return {
        "total_summaries": len(summaries),
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimensions": EMBEDDING_DIMENSIONS,
        "oldest_summary": summaries[-1].get('date') if summaries else None,
        "newest_summary": summaries[0].get('date') if summaries else None
    }


def delete_old_collection():
    """
    Delete the old sentence-transformers collection after successful migration.
    
    WARNING: Only run this after verifying migration was successful!
    """
    OLD_COLLECTION = "user_summaries"
    
    try:
        collections = client.get_collections().collections
        old_exists = any(col.name == OLD_COLLECTION for col in collections)
        
        if not old_exists:
            print(f"Old collection '{OLD_COLLECTION}' not found.")
            return
        
        # Safety check: make sure new collection has data
        new_count = client.count(collection_name=COLLECTION_NAME).count
        
        if new_count == 0:
            print("⚠️ Warning: New collection is empty. Not deleting old collection.")
            return
        
        client.delete_collection(collection_name=OLD_COLLECTION)
        print(f"✅ Deleted old collection: {OLD_COLLECTION}")
        print(f"   New collection has {new_count} records")
        
    except Exception as e:
        print(f"Error deleting old collection: {e}")

def delete_summary_by_date(user_id: str, report_date: str) -> Optional[dict]:
    """
    Delete a specific summary for a user by report date from Qdrant.
    
    Args:
        user_id: The user ID
        report_date: The report date in YYYY-MM-DD format
        
    Returns:
        The deleted summary data, or None if no summary found
    """
    try:        
        # Get the specific summary by date
        summary = get_summary_by_date(user_id, report_date)
        
        if not summary:
            return None
        
        point_id = summary.get('id')
        
        if not point_id:
            return None
        
        # Delete this specific point
        client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=PointIdsList(points=[point_id])
        )
        
        print(f"Deleted Qdrant point {point_id} for user {user_id}, date {report_date}")
        
        return summary
        
    except Exception as e:
        print(f"Error deleting summary for user {user_id}, date {report_date}: {e}")
        return None