"""
MongoDB Service for Axolotl
Handles connection to MongoDB and CRUD operations for project configurations.
"""

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from typing import Optional, Dict, Any, List
import os
from contextlib import asynccontextmanager
from datetime import datetime, UTC
from pymongo import ReturnDocument


class MongoDBService:
    """Service for managing MongoDB operations."""

    def __init__(self, connection_string: str = "mongodb://localhost:27017", db_name: str = "Axolotl"):
        """
        Initialize MongoDB service.

        Args:
            connection_string: MongoDB connection string
            db_name: Database name
        """
        self.connection_string = connection_string
        self.db_name = db_name
        self.client: Optional[AsyncIOMotorClient] = None
        self.db: Optional[AsyncIOMotorDatabase] = None

    async def connect(self):
        """Connect to MongoDB."""
        self.client = AsyncIOMotorClient(self.connection_string)
        self.db = self.client[self.db_name]

        # Create necessary indexes
        await self._create_indexes()

        print(f"Connected to MongoDB at {self.connection_string}, database: {self.db_name}")

    async def disconnect(self):
        """Disconnect from MongoDB."""
        if self.client:
            self.client.close()
            print("Disconnected from MongoDB")

    async def _create_indexes(self):
        """Create necessary indexes in MongoDB."""
        projects_collection = self.db["projects"]

        # Create unique index on project_id
        await projects_collection.create_index("project_id", unique=True)
        print("Created indexes for projects collection")

        users_collection = self.db["users"]
        await users_collection.create_index("gitlab_user_id", unique=True)
        print("Created indexes for users collection")

    # ============ Projects Collection Operations ============

    async def add_project(self, project_data: Dict[str, Any]) -> str:
        """
        Add a new GitLab project configuration.

        Args:
            project_data: Dictionary with keys:
                - project_id (required): GitLab project ID
                - gitlab_url (required): GitLab base URL (e.g., https://gitlab.com)
                - access_token (required): GitLab personal access token
                - author_name (optional): Name for automated commits (default: "Axolotl Agent")
                - author_email (optional): Email for automated commits (default: "agent@axolotl.local")

        Returns:
            Inserted document ID
        """
        projects_collection = self.db["projects"]

        # Set defaults
        if "author_name" not in project_data:
            project_data["author_name"] = "Axolotl Agent"
        if "author_email" not in project_data:
            project_data["author_email"] = "agent@axolotl.local"

        result = await projects_collection.insert_one(project_data)
        return str(result.inserted_id)

    async def get_project_by_id(self, project_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a project configuration by GitLab project ID.

        Args:
            project_id: GitLab project ID

        Returns:
            Project configuration dictionary or None if not found
        """
        projects_collection = self.db["projects"]
        project = await projects_collection.find_one({"project_id": project_id})
        return project

    async def get_project_by_mongo_id(self, mongo_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a project configuration by MongoDB ID.

        Args:
            mongo_id: MongoDB ObjectId as string

        Returns:
            Project configuration dictionary or None if not found
        """
        from bson import ObjectId
        projects_collection = self.db["projects"]

        try:
            project = await projects_collection.find_one({"_id": ObjectId(mongo_id)})
            return project
        except Exception as e:
            print(f"Error retrieving project by MongoDB ID: {e}")
            return None

    async def update_project(self, project_id: str, update_data: Dict[str, Any]) -> bool:
        """
        Update a project configuration.

        Args:
            project_id: GitLab project ID
            update_data: Dictionary with fields to update

        Returns:
            True if update was successful, False otherwise
        """
        projects_collection = self.db["projects"]
        result = await projects_collection.update_one(
            {"project_id": project_id},
            {"$set": update_data}
        )
        return result.modified_count > 0

    async def delete_project(self, project_id: str) -> bool:
        """
        Delete a project configuration.

        Args:
            project_id: GitLab project ID

        Returns:
            True if deletion was successful, False otherwise
        """
        projects_collection = self.db["projects"]
        result = await projects_collection.delete_one({"project_id": project_id})
        return result.deleted_count > 0

    async def list_all_projects(self) -> List[Dict[str, Any]]:
        """
        List all project configurations.

        Returns:
            List of project configuration dictionaries
        """
        projects_collection = self.db["projects"]
        projects = []
        async for project in projects_collection.find():
            projects.append(project)
        return projects

    async def project_exists(self, project_id: str) -> bool:
        """
        Check if a project configuration exists.

        Args:
            project_id: GitLab project ID

        Returns:
            True if project exists, False otherwise
        """
        projects_collection = self.db["projects"]
        count = await projects_collection.count_documents({"project_id": project_id})
        return count > 0

    async def link_project_to_user(self, project_id: str, user_id: str) -> bool:
        """Associate a project with an authenticated user."""
        result = await self.db["projects"].update_one(
            {"project_id": project_id},
            {"$set": {"user_id": user_id}}
        )
        return result.modified_count > 0

    # ============ Users Collection Operations ============

    async def upsert_user(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Upsert a user by gitlab_user_id. Returns the full document."""
        users = self.db["users"]
        now = datetime.now(UTC)
        result = await users.find_one_and_update(
            {"gitlab_user_id": user_data["gitlab_user_id"]},
            {
                "$set": {**user_data, "updated_at": now},
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return result

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Lookup user by MongoDB _id."""
        from bson import ObjectId
        try:
            return await self.db["users"].find_one({"_id": ObjectId(user_id)})
        except Exception:
            return None

    async def get_user_by_gitlab_id(self, gitlab_user_id: int) -> Optional[Dict[str, Any]]:
        """Lookup user by GitLab user ID."""
        return await self.db["users"].find_one({"gitlab_user_id": gitlab_user_id})

    # ============ Events Collection Operations ============

    async def log_event(self, event_data: Dict[str, Any]) -> str:
        """Persist an orchestration event to the events collection."""
        events = self.db["events"]
        result = await events.insert_one(event_data)
        return str(result.inserted_id)

    async def get_events(
        self,
        user_id: Optional[str] = None,
        limit: int = 50,
        event_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query events, optionally filtered by user or type, newest first."""
        events = self.db["events"]
        query: Dict[str, Any] = {}
        if user_id:
            query["user_id"] = user_id
        if event_type:
            query["event_type"] = event_type

        cursor = events.find(query).sort("timestamp", -1).limit(limit)
        return await cursor.to_list(length=limit)

    async def get_agent_metrics(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Compute aggregate agent metrics from the events collection."""
        events = self.db["events"]
        match_stage: Dict[str, Any] = {}
        if user_id:
            match_stage["user_id"] = user_id

        pipeline_stages = []
        if match_stage:
            pipeline_stages.append({"$match": match_stage})
        pipeline_stages.append({
            "$group": {
                "_id": None,
                "total_events": {"$sum": 1},
                "failures_detected": {
                    "$sum": {"$cond": [{"$eq": ["$event_type", "pipeline_failed"]}, 1, 0]}
                },
                "fixes_generated": {
                    "$sum": {"$cond": [{"$eq": ["$event_type", "generating_fix"]}, 1, 0]}
                },
                "mrs_created": {
                    "$sum": {"$cond": [{"$eq": ["$event_type", "creating_mr"]}, 1, 0]}
                },
                "fixes_succeeded": {
                    "$sum": {"$cond": [{"$eq": ["$event_type", "fix_succeeded"]}, 1, 0]}
                },
                "fixes_failed": {
                    "$sum": {"$cond": [{"$eq": ["$event_type", "fix_failed"]}, 1, 0]}
                },
            }
        })

        results = await events.aggregate(pipeline_stages).to_list(length=1)
        if results:
            r = results[0]
            total_fixes = r.get("fixes_succeeded", 0) + r.get("fixes_failed", 0)
            success_rate = (
                round(r["fixes_succeeded"] / total_fixes * 100, 1)
                if total_fixes > 0
                else 0
            )
            return {
                "failures_detected": r.get("failures_detected", 0),
                "fixes_generated": r.get("fixes_generated", 0),
                "merge_requests_raised": r.get("mrs_created", 0),
                "success_rate": success_rate,
                "human_approved": r.get("fixes_succeeded", 0),
                "auto_merged": 0,
            }
        return {
            "failures_detected": 0,
            "fixes_generated": 0,
            "merge_requests_raised": 0,
            "success_rate": 0,
            "human_approved": 0,
            "auto_merged": 0,
        }

    # ============ Settings Operations ============

    async def get_user_settings(self, user_id: str) -> Dict[str, Any]:
        """Get agent settings for a user. Returns defaults if not set."""
        from bson import ObjectId
        user = await self.db["users"].find_one({"_id": ObjectId(user_id)})
        if not user:
            return {}
        return user.get("settings", {
            "confidence_threshold": 85,
            "require_approval": True,
            "auto_branch": True,
            "notify_failures": True,
        })

    async def update_user_settings(self, user_id: str, settings: Dict[str, Any]) -> bool:
        """Update agent settings for a user."""
        from bson import ObjectId
        result = await self.db["users"].update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"settings": settings}}
        )
        return result.modified_count > 0

    async def get_projects_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        """List all projects owned by / linked to a user."""
        projects = self.db["projects"]
        cursor = projects.find({"user_id": user_id})
        results = []
        async for project in cursor:
            project["_id"] = str(project["_id"])
            results.append(project)
        return results

    @asynccontextmanager
    async def get_connection(self):
        """Context manager for database connection."""
        try:
            await self.connect()
            yield self
        finally:
            await self.disconnect()


# Singleton instance
_mongo_service: Optional[MongoDBService] = None


def get_mongo_service(connection_string: str = None, db_name: str = None) -> MongoDBService:
    """
    Get or create MongoDB service singleton.

    Args:
        connection_string: MongoDB connection string (used only on first call)
        db_name: Database name (used only on first call)

    Returns:
        MongoDBService instance
    """
    global _mongo_service

    if _mongo_service is None:
        conn_str = connection_string or os.getenv("MONGODB_CONNECTION_STRING", "mongodb://localhost:27017")
        db = db_name or os.getenv("MONGODB_DB_NAME", "Axolotl")
        _mongo_service = MongoDBService(conn_str, db)

    return _mongo_service
