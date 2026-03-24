"""
_*_CODING:UTF-8_*_
@Author: Yu Hou
@File: llm_parser.py
@Time: 10/16/25; 10:54 AM
"""
from .openai_client import chat

SYSTEM = (
    "You are an expert biomedical information extraction agent. "
    "Parse user question into JSON with keys: query_type, entities(list of {text,type}), relation, confidence(0-1). "
    "Entity types: DSI (dietary supplement ingredient), Disease, Gene, Drug, Symptom. "
    "Relation is one of: treats, prevents, associated_with, causes, interacts_with, contraindicated_for, biomarker_of."
    "Return ONLY valid JSON."
)


def parse_query(q: str) -> dict:
    user = f"Question: {q}\nReturn JSON only."
    raw = chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}])
    # 为健壮性做一层解析
    import json, re
    jtxt = raw.strip().strip("`")
    jtxt = re.sub(r'^[^{]*({.*})[^}]*$', r'\1', jtxt, flags=re.S)
    try:
        return json.loads(jtxt)
    except Exception:
        # 兜底：给个最小结构
        return {"query_type": "fact", "entities": [], "relation": None, "confidence": 0.5}
