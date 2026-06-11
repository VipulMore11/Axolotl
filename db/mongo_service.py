"""
MongoDB Service for Axolotl
Handles connection to MongoDB and CRUD operations for project configurations.
"""

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from typing import Optional, Dict, Any, List
import os
from contextlib import asynccontextmanager


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
