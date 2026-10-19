"""本機評審版 custom_response_quality（1–5）：提示與 scripts/grading/response_quality.py 相同。"""

import json
import os
import re
import urllib.request

from pydantic import BaseModel


class _Verdict(BaseModel):
    explanation: str  # 先寫理由再給分，分數才會跟理由一致
    score: int  # 1-5


def _judge_model():
    return os.environ.get("JUDGE_MODEL") or os.environ.get("AGENT_MODEL") or "gemini-3.8-flash"


def _ask(prompt, schema_hint, schema):
    """回傳評審的 JSON dict。openai/<模型> 走 OpenAI 相容 API，其餘用 google-genai。"""
    model = _judge_model()
    if model.startswith("openai/"):
        base = os.environ.get("LOCAL_LLM_BASE", "http://127.0.0.1:18081/v1").rstrip("/")
        body = {
            "model": model.split("/", 1)[1],
            "temperature": 0,
            "messages": [{"role": "system", "content": schema_hint}, {"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(f"{base}/chat/completions", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer local"})
        with urllib.request.urlopen(req, timeout=240) as resp:
            text = json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"]
    else:
        from google import genai
        from google.genai import types
        # client 要先存成變數，臨時物件被回收時連線會關掉（Cannot send a request, as the client has been closed）
        client = genai.Client()
        # 一定要給 schema：只寫 application/json 時模型會自己取欄位名稱（例如 feedback、rating），
        # 找不到 score 就會被當成預設值。和 scripts/grading/response_quality.py 一樣用 schema 固定格式。
        text = client.models.generate_content(
            model=model, contents=prompt,
            config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                               response_schema=schema),
        ).text
    match = re.search(r"\{.*\}", text or "", re.S)
    verdict = json.loads(match.group(0)) if match else None
    if not isinstance(verdict, dict) or "score" not in verdict:
        # 不可以用預設分數代替：之前缺 score 時被當成 1 分，評審明明寫「成功完成」
        raise ValueError(f"評審回傳沒有 score 欄位，不能當成有效分數：{(text or '')[:300]}")
    return verdict


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
    prompt += 'Return JSON: {"explanation": "one sentence", "score": integer 1-5}\n'
    verdict = _ask(prompt, '只回傳 JSON：{"explanation": "一句話", "score": 1 到 5 的整數}', _Verdict)
    if not verdict:
        raise ValueError('評審沒有回傳可解析的結果；不能當成有效 0 分')
    return {"score": max(1, min(5, int(verdict["score"]))), "explanation": str(verdict.get("explanation", ""))}
