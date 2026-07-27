"""
Post-HITL knowledge extraction.

Called asynchronously after a human approves/merges an Axolotl fix MR.
Writes Claim / Artifact / Run / Source nodes and provenance edges.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from agents.knowledge_store import get_knowledge_store
from db.mongo_service import get_mongo_service


async def extract_fix_to_knowledge_base(
    *,
    project_id: str,
    mr_iid: str,
) -> Optional[dict[str, str]]:
    """Load pending fix for this MR and write it into the KB (additive)."""
    mongo = get_mongo_service()
    pending = await mongo.get_pending_fix(project_id, mr_iid=str(mr_iid))
    if not pending:
        print(f"[KB] No pending fix for project={project_id} mr={mr_iid}")
        return None

    store = get_knowledge_store()
    ids = await store.record_successful_fix(
        project_id=str(pending.get("project_id") or project_id),
        pipeline_id=str(pending.get("pipeline_id") or ""),
        root_cause=str(pending.get("root_cause") or ""),
        commit_message=str(pending.get("commit_message") or ""),
        file_patches=list(pending.get("file_patches") or []),
        architecture_plan=pending.get("architecture_plan") or {},
        logs_excerpt=str(pending.get("logs_excerpt") or ""),
        run_metadata={
            "mr_iid": str(mr_iid),
            "fix_branch": pending.get("fix_branch"),
            "kb_grounding": pending.get("kb_grounding"),
        },
    )
    await mongo.mark_pending_fix_status(project_id, str(mr_iid), "kb_recorded")
    print(f"[KB] Recorded successful fix → {ids}")
    return ids


def schedule_kb_extraction(project_id: str, mr_iid: str | int) -> None:
    """Fire-and-forget extraction so API latency stays low."""

    async def _run() -> None:
        try:
            await extract_fix_to_knowledge_base(
                project_id=str(project_id),
                mr_iid=str(mr_iid),
            )
        except Exception as exc:
            print(f"[KB] Extraction failed: {exc}")

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())
    except RuntimeError:
        asyncio.run(_run())
