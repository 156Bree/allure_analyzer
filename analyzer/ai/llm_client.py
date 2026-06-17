"""llm_client.py —— OpenAI 兼容 /chat/completions 客户端（纯标准库 urllib）。

特性：
- 不引入 openai/requests 强依赖；用 ``urllib.request`` POST。
- 超时 + 轻量重试；失败抛 ``LLMError``（由编排层捕获并降级，不打印密钥/完整 payload）。
- 解析返回的 message.content，鲁棒提取严格 JSON（容忍代码围栏 / 前后多余文本）。
"""
import json
import re
import time
import urllib.request
import urllib.error


class LLMError(Exception):
    pass


def _endpoint(base_url):
    base = (base_url or "").rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def _extract_json_object(text):
    """从模型输出里鲁棒提取一个 JSON 对象。失败抛 LLMError。"""
    if not text:
        raise LLMError("empty content")
    s = text.strip()
    # 去掉 ```json ... ``` 围栏
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        pass
    # 退而求其次：截取第一个 { 到最后一个 }
    i, j = s.find("{"), s.rfind("}")
    if i != -1 and j != -1 and j > i:
        try:
            return json.loads(s[i:j + 1])
        except Exception:  # noqa: BLE001
            pass
    raise LLMError("cannot parse JSON from content")


def chat_json(base_url, api_key, model, system_prompt, user_prompt,
              timeout=30, max_retries=1, log=print):
    """调用一次对话补全并返回解析后的 dict。

    失败（网络/HTTP/解析）在重试用尽后抛 ``LLMError``。绝不打印 api_key 或完整 payload。
    """
    if not api_key:
        raise LLMError("no api key")
    url = _endpoint(base_url)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer %s" % api_key,
    }

    last_err = None
    attempts = max(1, int(max_retries) + 1)
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
            obj = json.loads(raw)
            content = (((obj.get("choices") or [{}])[0]).get("message") or {}).get("content", "")
            return _extract_json_object(content)
        except urllib.error.HTTPError as e:  # noqa: PERF203
            # 不打印响应体（可能含敏感信息），只记状态码
            last_err = LLMError("HTTP %s" % getattr(e, "code", "?"))
        except urllib.error.URLError as e:
            last_err = LLMError("URL error: %s" % getattr(e, "reason", e))
        except LLMError as e:
            last_err = e
        except Exception as e:  # noqa: BLE001
            last_err = LLMError("unexpected: %s" % e)
        if attempt < attempts - 1:
            log("[ai.llm] 第 %d 次调用失败(%s)，重试…" % (attempt + 1, last_err))
            time.sleep(min(2 ** attempt, 5))
    raise last_err or LLMError("unknown error")
