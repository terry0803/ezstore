"""A2A 回覆只保留 respond 節點的 artifact，狀態更新照常送出。"""

from types import SimpleNamespace

import pytest
from a2a.types import Artifact, Part, TaskArtifactUpdateEvent, TaskStatus, TaskStatusUpdateEvent

from quotation_agent.app_utils.a2a import only_node_artifacts


def adk_event(path):
    return SimpleNamespace(node_info=SimpleNamespace(path=path))


def artifact_event(text):
    return TaskArtifactUpdateEvent(
        task_id="t", context_id="c", artifact=Artifact(artifact_id="a", parts=[Part(text=text)])
    )


@pytest.mark.asyncio
async def test_only_respond_artifacts_pass():
    after_event = only_node_artifacts("respond").after_event
    respond = artifact_event("報價單編號: QT-20260330-001")
    assert await after_event(None, respond, adk_event("quotation_agent/respond@1")) is respond
    classifier = artifact_event('{"intent": "get_quotation"}')
    assert await after_event(None, classifier, adk_event("quotation_agent/classify_intent@1")) is None
    status = TaskStatusUpdateEvent(task_id="t", context_id="c", status=TaskStatus())
    assert await after_event(None, status, adk_event("quotation_agent/classify_intent@1")) is status
