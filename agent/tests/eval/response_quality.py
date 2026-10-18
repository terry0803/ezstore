"""LLM 評審 custom_response_quality（1–5 分），見 eval_config.yaml。

評審模型由 JUDGE_MODEL 指定，沒設定時用 AGENT_MODEL，再沒有就用 gemini-3.8-flash：
- Gemini：google-genai（GEMINI_API_KEY 或 Vertex AI 的 ADC）
- openai/<模型>：OpenAI 相容 API（例如本機 llama.cpp），位址 LOCAL_LLM_BASE
"""

import json
import os
import re
import threading
import urllib.request

from pydantic import BaseModel

_local = threading.local()


class _Verdict(BaseModel):
    score: int  # 1-5
    explanation: str


def _judge_model() -> str:
    return os.environ.get("JUDGE_MODEL") or os.environ.get("AGENT_MODEL") or "gemini-3.8-flash"


def _ask_openai_compatible(model: str, prompt: str) -> _Verdict | None:
    base = os.environ.get("LOCAL_LLM_BASE", "http://127.0.0.1:18081/v1").rstrip("/")
    body = {
        "model": model.split("/", 1)[1],
        "temperature": 0,
        "messages": [
            {"role": "system", "content": "只回傳 JSON：{\"score\": 1 到 5 的整數, \"explanation\": \"一句話\"}"},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        text = json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"]
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    return _Verdict.model_validate_json(match.group(0))


def _ask_gemini(model: str, prompt: str) -> _Verdict | None:
    from google import genai
    from google.genai import types

    client = getattr(_local, "client", None)
    if client is None:
        # 每個評分執行緒一個 client（AI Studio 的 GEMINI_API_KEY 或 ADC）
        client = _local.client = genai.Client()
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=_Verdict,
        ),
    )
    return response.parsed


def evaluate(instance):
    reference = instance.get("reference")
    rubric = (
        "Grade the agent's final response on a 1-5 scale (1 poor, 5 excellent) for "
        "accuracy, relevance, and clarity."
    )
    if reference:
        rubric += (
            " The response should agree with the expected answer below; penalize "
            "factual disagreement with it."
        )
    prompt = (
        f"You are an expert QA evaluator for an enterprise AI assistant. {rubric}\n"
        f"User Prompt: {instance.get('prompt', '')}\n"
        f"Final Response: {instance.get('response', '')}\n"
    )
    if reference:
        prompt += f"Expected Answer (ground truth): {reference}\n"
    prompt += f"Full Agent Trace: {instance.get('agent_data', '')}\n"

    model = _judge_model()
    if model.startswith("openai/"):
        verdict = _ask_openai_compatible(model, prompt)
    else:
        verdict = _ask_gemini(model, prompt)
    if verdict is None:
        return {"score": 0, "explanation": "評審沒有回傳可解析的結果"}
    return {"score": max(1, min(5, verdict.score)), "explanation": verdict.explanation}
