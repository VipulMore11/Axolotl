"""
Round-trip check for the Neo4j knowledge base.

Connects with the NEO4J_* settings from backend/.env, provisions the schema,
writes a throwaway fix, reads it back through the grounding query, then removes
the test nodes again.

    cd backend
    python -m scripts.verify_kb            # write, read back, clean up
    python -m scripts.verify_kb --keep     # leave the test nodes in the graph
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from agents.knowledge_store import KnowledgeStore  # noqa: E402
from db.neo4j_service import get_neo4j_service  # noqa: E402

PROJECT_ID = "kb-verify-project"
PIPELINE_ID = "kb-verify-pipeline"
ROOT_CAUSE = "ModuleNotFoundError: No module named 'requests' during pytest collection"


async def main(keep: bool) -> int:
    neo4j = get_neo4j_service()

    print(f"URI      : {neo4j.uri or '(not set)'}")
    print(f"Username : {neo4j.username}")
    print(f"Database : {neo4j.database}")
    print(f"Password : {'set' if neo4j.password else '(not set)'}")

    if not await neo4j.connect():
        print("\nFAILED: could not connect. Set NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD in backend/.env")
        return 1

    store = KnowledgeStore(neo4j)

    ids = await store.record_successful_fix(
        project_id=PROJECT_ID,
        pipeline_id=PIPELINE_ID,
        root_cause=ROOT_CAUSE,
        commit_message="fix: add requests to requirements.txt",
        file_patches=[
            {"file_path": "requirements.txt", "updated_content": "requests==2.34.2\n"},
            {"file_path": "tests/test_api.py", "updated_content": "import requests\n"},
        ],
        architecture_plan={
            "strategy_type": "deps",
            "affected_files": ["requirements.txt", "tests/test_api.py"],
            "proposed_solution": "Pin the missing dependency",
        },
        logs_excerpt="E   ModuleNotFoundError: No module named 'requests'",
    )
    print(f"\nWrote nodes: {ids}")

    hits = await store.find_historical_fixes(
        project_id=PROJECT_ID,
        error_text="ERROR ModuleNotFoundError: No module named 'requests'",
        limit=3,
    )
    print(f"Grounding hits: {len(hits)}")
    for hit in hits:
        print(f"  claim   : {hit.get('claim_label')}")
        print(f"  fix     : {hit.get('commit_message')}")
        print(f"  patches : {[p.get('file_path') for p in hit.get('artifact_patches') or []]}")

    counts = await neo4j.run(
        """
        MATCH (n:KBNode {project_id: $project_id})
        OPTIONAL MATCH (n)-[r]->(:KBNode)
        RETURN n.type AS type, count(DISTINCT n) AS nodes, count(r) AS edges
        ORDER BY type
        """,
        {"project_id": PROJECT_ID},
        write=False,
    )
    print("\nGraph contents for the test project:")
    for row in counts:
        print(f"  {row['type']:<9} nodes={row['nodes']} outgoing_edges={row['edges']}")

    if keep:
        print(f"\nLeaving test nodes in place (project_id={PROJECT_ID}).")
    else:
        await neo4j.run(
            "MATCH (n:KBNode {project_id: $project_id}) DETACH DELETE n",
            {"project_id": PROJECT_ID},
        )
        print("\nCleaned up test nodes.")

    await neo4j.disconnect()

    if not hits:
        print("WARNING: write succeeded but grounding returned no hits.")
        return 1

    print("Knowledge base OK.")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    raise SystemExit(asyncio.run(main(keep="--keep" in sys.argv)))
