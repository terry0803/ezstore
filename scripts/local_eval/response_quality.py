"""本機評審版 custom_response_quality（1–5）：提示與 scripts/grading/response_quality.py 相同。"""

import json
import os
import re
import urllib.request


def _judge_model():
    return os.environ.get("JUDGE_MODEL") or os.environ.get("AGENT_MODEL") or "gemini-3.8-flash"


def _ask(prompt, schema_hint):
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
        text = client.models.generate_content(
            model=model, contents=prompt,
            config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json"),
        ).text
    match = re.search(r"\{.*\}", text or "", re.S)
    return json.loads(match.group(0)) if match else None


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
    verdict = _ask(prompt, '只回傳 JSON：{"score": 1 到 5 的整數, "explanation": "一句話"}')
    if not verdict:
        raise ValueError('評審沒有回傳可解析的結果；不能當成有效 0 分')
    return {"score": max(1, min(5, int(verdict.get("score", 1)))), "explanation": str(verdict.get("explanation", ""))}
