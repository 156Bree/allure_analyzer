"""store.py —— AI 分析结果的全局指纹缓存（跨日期复用）。

存储位置默认 ``trend_data/ai_analysis/store.json``，结构为 ``{fp: entry}``：

    {
      "<fp>": {
        "case_key": "LIP-690", "host": "...", "scenario": "...",
        "status_message": "...",               # 原始报错（供 serve/吸收展示）
        "conclusion": "结论(全文)",
        "cause": "原因(全文)",
        "suggestion": "建议(全文)",
        "evidence": "分析依据(关键断言/log片段/匹配规则)",
        "source": "llm" | "manual",
        "locked": false,                        # 人工修正后 true，自动分析永不覆盖
        "model": "gpt-4o-mini",
        "updated_at": "ISO8601"
      }
    }

指纹 fp = sha1(case_key | host | scenario | status_message)，status_message 变化即换新 fp，
天然实现“失败内容变化才重新分析”。``source=manual`` / ``locked=true`` 永不被自动覆盖。
"""
import datetime
import hashlib
import json
import os
import tempfile


def fingerprint(case_key, host, scenario, status_message):
    """对失败项的稳定四元组求 sha1，作为缓存键。"""
    raw = "|".join([
        str(case_key or ""),
        str(host or ""),
        str(scenario or ""),
        str(status_message or ""),
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def now_iso():
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


class Store(object):
    """store.json 的薄封装：内存 dict + 原子写盘，记录是否 dirty。"""

    def __init__(self, path):
        self.path = path
        self.data = {}
        self.dirty = False
        self._load()

    def _load(self):
        if not self.path or not os.path.isfile(self.path):
            self.data = {}
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            if isinstance(obj, dict):
                # 兼容未来可能的 {"version":..,"entries":{...}} 结构
                self.data = obj.get("entries", obj) if "entries" in obj else obj
                if not isinstance(self.data, dict):
                    self.data = {}
        except Exception as e:  # noqa: BLE001
            print("[ai.store] 读取 %s 失败(%s)，按空缓存处理。" % (self.path, e))
            self.data = {}

    # -- 查询 ----------------------------------------------------------------
    def get(self, fp):
        return self.data.get(fp)

    def has(self, fp):
        return fp in self.data

    def is_locked(self, fp):
        e = self.data.get(fp)
        return bool(e and (e.get("locked") or e.get("source") == "manual"))

    # -- 写入 ----------------------------------------------------------------
    def upsert_llm(self, fp, fields, model):
        """写入/更新一条 LLM 结果；若该 fp 已被人工锁定则跳过（永不覆盖）。返回是否写入。"""
        if self.is_locked(fp):
            return False
        entry = dict(self.data.get(fp) or {})
        entry.update(fields)
        entry["source"] = "llm"
        entry["locked"] = False
        entry["model"] = model
        entry["updated_at"] = now_iso()
        self.data[fp] = entry
        self.dirty = True
        return True

    def upsert_manual(self, fp, fields):
        """人工保存：置 source=manual / locked=true（自动分析永不覆盖）。"""
        entry = dict(self.data.get(fp) or {})
        entry.update(fields)
        entry["source"] = "manual"
        entry["locked"] = True
        entry["updated_at"] = now_iso()
        self.data[fp] = entry
        self.dirty = True
        return entry

    def delete(self, fp):
        if fp in self.data:
            del self.data[fp]
            self.dirty = True
            return True
        return False

    def save(self, force=False):
        if not self.path:
            return False
        if not (self.dirty or force):
            return False
        d = os.path.dirname(self.path)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        # 原子写：先写临时文件再 replace
        fd, tmp = tempfile.mkstemp(dir=d or ".", prefix=".store_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception as e:  # noqa: BLE001
            print("[ai.store] 写入 %s 失败(%s)。" % (self.path, e))
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return False
        self.dirty = False
        return True
