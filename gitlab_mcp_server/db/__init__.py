"""Database module for Axolotl."""

from .mongo_service import MongoDBService, get_mongo_service

__all__ = ["MongoDBService", "get_mongo_service"]
