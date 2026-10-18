# Coding Agent Guide

## Prerequisites

Install the CLI (one-time):
```bash
uv tool install google-agents-cli
```

---

## Development Phases

### Phase 1: Understand Requirements
Before writing any code, understand the project's requirements, constraints, and success criteria.

### Phase 2: Build and Implement
Implement agent logic in `quotation_agent/`. Use `agents-cli playground` for interactive testing. Iterate based on user feedback.

### Phase 3: The Evaluation Loop (Main Iteration Phase)
Start with 1-2 eval cases, run `agents-cli eval run`, iterate by making changes and rerunning it until satisfied. Expect 5-10+ iterations. Once you have a baseline, reach for `agents-cli eval compare` (regression diffs), `agents-cli eval analyze` (cluster failure modes), and `agents-cli eval optimize` (auto-tune prompts). See the **Evaluation Guide** for metrics, dataset schema, LLM-as-judge config, and common gotchas.

### Phase 4: Pre-Deployment Tests
Run `uv run pytest tests/unit tests/integration`. Fix issues until all tests pass.

### Phase 5: Deploy to Dev
**Requires explicit human approval.** Run `agents-cli deploy` only after user confirms. See the **Deployment Guide** for details.

### Phase 6: Production Deployment
Ask the user: Option A (simple single-project) or Option B (full CI/CD pipeline with `agents-cli infra cicd`).

## Development Commands

| Command | Purpose |
|---------|---------|
| `agents-cli playground` | Interactive local testing |
| `uv run pytest tests/unit tests/integration` | Run unit and integration tests |
| `agents-cli eval dataset synthesize` | Synthesize multi-turn eval scenarios for your agent |
| `agents-cli eval run` | Run the agent over the eval dataset and grade the traces |
| `agents-cli eval generate` / `agents-cli eval grade` | Decoupled form: produce traces, then grade them |
| `agents-cli eval compare` | Compare two grade-results files (regression check) |
| `agents-cli eval analyze` | Cluster failure modes from grade results |
| `agents-cli eval metric list` | List built-in metrics available in the SDK |
| `agents-cli eval optimize` | Auto-tune agent prompts using eval data |
| `agents-cli lint` | Check code quality |
| `agents-cli infra single-project` | Set up project infrastructure (Terraform) |
| `agents-cli deploy` | Deploy to dev |
| `agents-cli scaffold enhance` | Add deployment target or CI/CD to project |
| `agents-cli scaffold upgrade` | Upgrade project to latest version |

---

## Operational Guidelines for Coding Agents

- **Code preservation**: Only modify code directly targeted by the user's request. Preserve all surrounding code, config values (e.g., `model`), comments, and formatting.
- **NEVER change the model** unless explicitly asked.
- **Model 404 errors**: Fix `GOOGLE_CLOUD_LOCATION` (e.g., `global` instead of `us-east1`), not the model name.
- **ADK tool imports**: Import the tool instance, not the module: `from google.adk.tools.load_web_page import load_web_page`
- **Run Python with `uv`**: `uv run python script.py`. Run `agents-cli install` first.
- **Stop on repeated errors**: If the same error appears 3+ times, fix the root cause instead of retrying.
- **Terraform conflicts** (Error 409): Use `terraform import` instead of retrying creation.

---

## EZStore 專屬注意事項

- ADK app 名稱必須是 `quotation_agent`，最終回覆只能從 `respond` 節點輸出（Chat UI 與評分都靠 `nodeInfo.path` 找它）。
- 只有 `classify_intent` 呼叫 LLM。工具、參數、追問、拒答都在 `route` 用程式決定，不要改成讓 LLM 自己挑工具。
- ADK 2.11 的 `edges`：tuple 是一條鏈，分支用 `(node, {route: target})`。
- `CLASSIFIER_INSTRUCTION` 裡不要寫大括號或 JSON，ADK 會當成 state 變數替換。
- 拒答文字要含「只能協助」，追問要以「請提供」開頭；`scripts/grading/link_presence.py` 靠這兩個慣例辨認拒答與追問。
- 不要改 `mcp_server/`、`frontend/`、`backend/`。
- 本機模型（`AGENT_MODEL=openai/...`）只有一個推論槽時，eval 要加 `--concurrency 1`。
- A2A：`fast_api_app.py` 的 agent card 每個操作一個 skill（例句同 spec 1.1–1.6），`only_node_artifacts("respond")` 讓 A2A 回覆只帶 respond 的文字。議價顧問（`../advisor`）會讀這張 card 確認 skill，改 skill id 要一起改 `advisor/pricing_advisor/a2a_client.py` 的 `REQUIRED_SKILLS`。
