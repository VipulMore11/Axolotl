"""
Verification & Health Check Script
Tests all components to ensure they are working correctly.
"""

import asyncio
import sys
from db.mongo_service import get_mongo_service


async def test_mongodb_connection():
    """Test MongoDB connection."""
    print("\n" + "="*60)
    print("Testing MongoDB Connection...")
    print("="*60)
    
    try:
        mongo_service = get_mongo_service()
        await mongo_service.connect()
        
        # Try to list projects
        projects = await mongo_service.list_all_projects()
        print(f"✓ MongoDB connection successful")
        print(f"✓ Found {len(projects)} projects in database")
        
        for project in projects:
            print(f"  - Project ID: {project['project_id']}, Name: {project.get('project_name', 'N/A')}")
        
        await mongo_service.disconnect()
        return True
    
    except Exception as e:
        print(f"✗ MongoDB connection failed: {e}")
        return False


async def test_project_operations():
    """Test MongoDB project operations."""
    print("\n" + "="*60)
    print("Testing MongoDB Project Operations...")
    print("="*60)
    
    try:
        mongo_service = get_mongo_service()
        await mongo_service.connect()
        
        # Test: Check if test project exists
        exists = await mongo_service.project_exists("82917278")
        print(f"✓ Test project exists: {exists}")
        
        # Test: Get project
        project = await mongo_service.get_project_by_id("82917278")
        if project:
            print(f"✓ Successfully retrieved project: {project.get('project_name')}")
        else:
            print(f"✓ Project not in database (needs seeding)")
        
        # Test: List all projects
        projects = await mongo_service.list_all_projects()
        print(f"✓ Total projects in database: {len(projects)}")
        
        await mongo_service.disconnect()
        return True
    
    except Exception as e:
        print(f"✗ Project operations failed: {e}")
        return False


async def test_gitlab_client_import():
    """Test GitLab client can be imported."""
    print("\n" + "="*60)
    print("Testing GitLab Client Import...")
    print("="*60)
    
    try:
        from gitlabmcp.gitlab_mcp_client import GitLabMCPClient
        from db.mongo_service import get_mongo_service
        
        print(f"✓ GitLab client imported successfully")
        
        mongo_service = get_mongo_service()
        await mongo_service.connect()
        
        gitlab_client = GitLabMCPClient(mongo_service)
        print(f"✓ GitLab client instantiated successfully")
        
        await mongo_service.disconnect()
        return True
    
    except Exception as e:
        print(f"✗ GitLab client import failed: {e}")
        return False


async def test_mcp_server_import():
    """Test MCP server can be imported."""
    print("\n" + "="*60)
    print("Testing MCP Server Import...")
    print("="*60)
    
    try:
        from gitlabmcp.mcp_server import server, list_tools
        
        print(f"✓ MCP server imported successfully")
        print(f"✓ MCP server instance created")
        
        return True
    
    except Exception as e:
        print(f"✗ MCP server import failed: {e}")
        return False


async def test_webhook_import():
    """Test webhook routes can be imported."""
    print("\n" + "="*60)
    print("Testing Webhook Routes Import...")
    print("="*60)
    
    try:
        from api.webhook_routes import app
        
        print(f"✓ Webhook routes imported successfully")
        print(f"✓ FastAPI app instance created")
        
        return True
    
    except Exception as e:
        print(f"✗ Webhook import failed: {e}")
        return False


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("AXOLOTL - SYSTEM HEALTH CHECK")
    print("="*60)
    
    results = {}
    
    # Run tests
    results["MongoDB Connection"] = await test_mongodb_connection()
    results["Project Operations"] = await test_project_operations()
    results["GitLab Client"] = await test_gitlab_client_import()
    results["MCP Server"] = await test_mcp_server_import()
    results["Webhook Routes"] = await test_webhook_import()
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✓" if result else "✗"
        print(f"{status} {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✓ All tests passed! System is ready.")
        return 0
    else:
        print(f"\n✗ {total - passed} test(s) failed. Please check the errors above.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
