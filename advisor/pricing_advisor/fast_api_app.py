# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import contextlib
import os
from collections.abc import AsyncIterator

from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentSkill
from dotenv import load_dotenv
from fastapi import FastAPI
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import Runner

from pricing_advisor.app_utils import services
from pricing_advisor.app_utils.a2a import attach_a2a_routes, only_node_artifacts

load_dotenv()
allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)
otel_to_cloud = False

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A2A agent card 上的 skill：外部 Agent 可以請議價顧問做的事
ADVISOR_SKILLS = [
    AgentSkill(
        id="policy_question",
        name="回答報價規則",
        description="依 OKF 知識庫回答改價核准、報價因子下限、轉訂單規則與報價公式，附來源與信任等級。",
        tags=["ezstore", "policy", "okf"],
        examples=["報價因子最低可以到多少？", "毛利率要多少以上業務才能自己改價？"],
    ),
    AgentSkill(
        id="price_check",
        name="試算改價",
        description="用知識庫的 Attested Computation 試算改價後的報價因子與毛利率，驗證通過後依規則判斷核准層級。",
        tags=["ezstore", "pricing", "attested-computation"],
        examples=["神盾局科技想把 QT-20260325-001 壓到 180000，可以嗎？"],
    ),
    AgentSkill(
        id="apply_price",
        name="改價（經 A2A 交給報價單 Agent）",
        description="不需要核准的改價才經 A2A 請報價單 Agent 修改總價（先複製再改）；需要核准時只產生核准申請。",
        tags=["ezstore", "pricing", "a2a"],
        examples=["幫我把 QT-20260325-001 的總價改成 200000"],
    ),
    AgentSkill(
        id="order_check",
        name="轉訂單檢查",
        description="檢查報價單是否已發佈、是否已有訂單，通過才經 A2A 請報價單 Agent 轉訂單。",
        tags=["ezstore", "order", "a2a"],
        examples=["QT-20260301-001 可以轉訂單嗎？", "幫我把 QT-20260301-001 轉成訂單"],
    ),
]


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from pricing_advisor.agent import app as adk_app
    from pricing_advisor.agent import root_agent

    runner = Runner(
        app=adk_app,
        session_service=services.get_session_service(),
        artifact_service=services.get_artifact_service(),
        auto_create_session=True,
    )
    app.state.runner = runner
    app.state.agent_app_name = adk_app.name
    await attach_a2a_routes(
        app,
        agent=root_agent,
        runner=runner,
        task_store=InMemoryTaskStore(),
        rpc_path=f"/a2a/{adk_app.name}",
        skills=ADVISOR_SKILLS,
        # A2A 回覆只給 respond 節點的文字
        execute_interceptors=[only_node_artifacts("respond")],
    )
    yield


app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=services.ARTIFACT_SERVICE_URI,
    allow_origins=allow_origins,
    session_service_uri=services.SESSION_SERVICE_URI,
    otel_to_cloud=otel_to_cloud,
    lifespan=lifespan,
)
app.title = "ezstore-advisor"
app.description = "API for interacting with the Agent ezstore-advisor"


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
