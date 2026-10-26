"""One DeepSeek connection shared by every live agent. No cross-project secrets."""
import json
import os
from pathlib import Path

import httpx
from dotenv import dotenv_values

from schemas import AgentError

ROOT = Path(__file__).resolve().parent
MODEL_ID = "deepseek-flash"
MODEL_LABEL = "DeepSeek-V4.1-Flash"
API_BASE = "https://api.deepseek.com"


def config():
    # Explicit project key only. Never read legacy OPENAI_* or sibling .env files.
    values = dotenv_values(ROOT / ".env", interpolate=False)
    key = os.getenv("DEEPSEEK_API_KEY", values.get("DEEPSEEK_API_KEY") or "").strip()
    return {"key": key, "base": API_BASE, "model": MODEL_ID, "label": MODEL_LABEL,
            "source": "DEEPSEEK_API_KEY 环境变量" if "DEEPSEEK_API_KEY" in os.environ else "本项目 .env"}


async def completion(system, messages, schema=None):
    settings = config()
    if not settings["key"]:
        raise AgentError("请先在本项目 .env 中填写 DEEPSEEK_API_KEY，或新建离线演示练习。")
    if schema:
        system += "\n只输出 JSON，遵循结构：" + json.dumps(schema.model_json_schema(), ensure_ascii=False)
    payload = {"model": MODEL_ID, "messages": [{"role": "system", "content": system}] + messages,
               "max_tokens": 6500 if schema else 1400, "thinking": {"type": "disabled"}, "stream": False}
    if schema:
        payload["response_format"] = {"type": "json_object"}
    try:
        async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
            response = await client.post(API_BASE + "/chat/completions",
                                         headers={"Authorization": "Bearer " + settings["key"]}, json=payload)
        if response.status_code != 200:
            raise AgentError(f"DeepSeek 返回 HTTP {response.status_code}。请检查本项目 DEEPSEEK_API_KEY、账户权限或额度。")
        choice = response.json()["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise AgentError("模型未正常完成回复（可能被截断），本次结果未保存，请重试。")
        content = choice["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise AgentError("模型返回了空内容，请重试。")
        return schema.model_validate_json(content) if schema else content.strip()
    except httpx.TimeoutException:
        raise AgentError("模型响应超时，本次操作未保存，可以重试。") from None
    except httpx.HTTPError:
        raise AgentError("无法连接 DeepSeek，请检查网络后重试。") from None
    except (KeyError, IndexError, TypeError, ValueError):
        raise AgentError("模型返回格式不符合要求，本次结果未保存，请重试。") from None
