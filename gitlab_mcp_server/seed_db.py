"""
Database Seeding Script
Populates MongoDB with project configurations for testing.
"""

import asyncio
from db.mongo_service import get_mongo_service


async def seed_database():
    """Seed the MongoDB database with test projects."""
    
    mongo_service = get_mongo_service()
    await mongo_service.connect()
    
    try:
        # Check if test project already exists
        existing_project = await mongo_service.get_project_by_id("82917278")
        
        if existing_project:
            print("Test project already exists in database")
            print(f"Project: {existing_project}")
            return
        
        # Add test project
        project_data = {
            "project_id": "82917278",
            "gitlab_url": "https://gitlab.com",
            "access_token": "glpat-retLzpamlW1D_u4deVZe02M6MQpvOjEKdTpuNTU5YQ8.01.171egtu06",
            "author_name": "Axolotl Agent",
            "author_email": "agent@axolotl.local",
            "project_name": "axolotl-test",
        }
        
        inserted_id = await mongo_service.add_project(project_data)
        print(f"Successfully seeded test project: {inserted_id}")
        
        # List all projects
        all_projects = await mongo_service.list_all_projects()
        print(f"\nAll projects in database:")
        for project in all_projects:
            print(f"  - Project ID: {project['project_id']}, Name: {project.get('project_name', 'N/A')}")
    
    except Exception as e:
        print(f"Error seeding database: {e}")
    
    finally:
        await mongo_service.disconnect()


if __name__ == "__main__":
    print("Starting database seeding...")
    asyncio.run(seed_database())
    print("Database seeding complete!")
