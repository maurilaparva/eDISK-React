"""
_*_CODING:UTF-8_*_
@Author: Yu Hou
@File: entity_linker.py
@Time: 10/16/25; 11:01 AM
"""
import sqlite3
from django.conf import settings
import numpy as np
from ui_agent.services import faiss_index, openai_client


def link_entities(entity_name: str, entity_type: str = None, threshold: float = 0.8, topk: int = 10):
    """
    从 eDISK 向量库中查找最相似的实体。
    支持类型优先匹配和 Disease/Symptom 互查。
    """
    print(f"\n[DEBUG] 🔍 Linking entity: '{entity_name}' (type={entity_type})")
    if not entity_name:
        return None

    # 生成 embedding
    try:
        vec = openai_client.embed([entity_name])[0]
    except Exception as e:
        print(f"[ERROR] embedding failed for {entity_name}: {e}")
        return None

    if vec is None:
        print(f"[WARN] No embedding returned for {entity_name}")
        return None

    # 加载索引和元数据
    index, meta = faiss_index.load_index()
    n = len(meta["names"])
    print(f"[DEBUG] FAISS index loaded: {n} vectors")

    # === Helper: 执行带类型过滤的搜索 ===
    def _search_by_types(allowed_types, th=threshold):
        scores, idxs = index.search(np.array(vec, dtype="float32").reshape(1, -1), topk)
        results = []
        for score, idx in zip(scores[0], idxs[0]):
            if idx < 0 or idx >= len(meta["names"]):
                continue
            node_type = meta["node_types"][idx]
            if node_type in allowed_types:
                results.append({
                    "id": meta["edisk_ids"][idx],
                    "name": meta["names"][idx],
                    "type": node_type,
                    "score": float(score),
                })
        results = sorted(results, key=lambda x: -x["score"])
        if results:
            print(f"[DEBUG] Top results ({allowed_types}): {[(r['name'], round(r['score'], 3)) for r in results[:3]]}")
        return results

    # === Step 1: 类型约束匹配 ===
    if entity_type == "DSI":
        results = search_dsi_only(entity_name, topk=20)
    elif entity_type in ["Disease", "Dis"]:
        results = _search_by_types(["Dis"])
        if not results or results[0]["score"] < threshold:
            print("[DEBUG] Cross-type fallback: try Symptom (SS)")
            results = _search_by_types(["SS"], th=threshold * 0.95)
    elif entity_type in ["Symptom", "SS"]:
        results = _search_by_types(["SS"])
        if not results or results[0]["score"] < threshold:
            print("[DEBUG] Cross-type fallback: try Disease (Dis)")
            results = _search_by_types(["Dis"], th=threshold * 0.95)
    elif entity_type in ["Gene"]:
        results = _search_by_types(["Gene"])
    else:
        print("[DEBUG] No type constraint applied (unknown or None)")
        results = _search_by_types(set(meta["node_types"]))

    # === Step 2: 回退到全局搜索 ===
    if not results or results[0]["score"] < threshold * 0.8:
        print(f"[DEBUG] Global fallback: threshold relaxed to {threshold * 0.8:.2f}")
        results = _search_by_types(set(meta["node_types"]), th=threshold * 0.8)

    # === Step 3: 输出最终结果 ===
    if results:
        best = results[0]
        print(f"[DEBUG] ✅ Matched: {entity_name} → {best}")
        return best
    else:
        print(f"[WARN] ❌ No confident match for {entity_name}")
        return None


def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


def search_dsi_only(entity_name, topk=10):
    """仅在 DSI 类型实体中进行向量相似度匹配"""
    print(f"[DEBUG] DSI-only search for '{entity_name}'")

    # 生成查询实体的 embedding
    vec_query = np.array(openai_client.embed([entity_name])[0], dtype=np.float32)

    # 连接数据库
    con = sqlite3.connect(settings.EMB_SQLITE_PATH)
    cur = con.cursor()
    cur.execute("""
        SELECT edisk_id, name, embedding 
        FROM entity_embeddings 
        WHERE node_type='DSI'
    """)
    candidates = cur.fetchall()
    con.close()

    scores = []
    for eid, ename, emb_blob in candidates:
        emb = np.frombuffer(emb_blob, dtype=np.float32)
        score = cosine_similarity(vec_query, emb)
        scores.append((eid, ename, score))

    # 按相似度排序
    scores = sorted(scores, key=lambda x: -x[2])[:topk]
    results = [
        {"id": eid, "name": ename, "type": "DSI", "score": float(score)}
        for eid, ename, score in scores
    ]
    print(f"[DEBUG] Top {topk} DSI results: {[(r['name'], round(r['score'], 3)) for r in results]}")
    return results


def link_entities_candidates(entity_name: str, entity_type: str = None, threshold: float = 0.8, topk: int = 10):
    """
    在不影响现有 link_entities() 的情况下，返回 Top-K 候选列表。
    结构：[{id, name, type, score}, ...] （已按score降序，最多 topk 个）
    """
    print(f"\n[DEBUG] 🔍 Linking (candidates): '{entity_name}' (type={entity_type}, topk={topk})")
    if not entity_name:
        return []

    # 生成 embedding
    try:
        vec = openai_client.embed([entity_name])[0]
    except Exception as e:
        print(f"[ERROR] embedding failed for {entity_name}: {e}")
        return []

    if vec is None:
        print(f"[WARN] No embedding returned for {entity_name}")
        return []

    # 加载索引和元数据
    index, meta = faiss_index.load_index()
    n = len(meta["names"])
    print(f"[DEBUG] FAISS index loaded: {n} vectors")

    # 与 link_entities 中一致的内部搜索逻辑
    def _search_by_types(allowed_types, th=threshold):
        scores, idxs = index.search(np.array(vec, dtype="float32").reshape(1, -1), topk)
        results = []
        for score, idx in zip(scores[0], idxs[0]):
            if idx < 0 or idx >= len(meta["names"]):
                continue
            node_type = meta["node_types"][idx]
            if node_type in allowed_types:
                results.append({
                    "id": meta["edisk_ids"][idx],
                    "name": meta["names"][idx],
                    "type": node_type,
                    "score": float(score),
                })
        results = sorted(results, key=lambda x: -x["score"])
        if results:
            print(f"[DEBUG] Top results ({allowed_types}): {[(r['name'], round(r['score'], 3)) for r in results[:3]]}")
        return results

    # 类型约束与互查逻辑，完全沿用你现有的分支
    if entity_type == "DSI":
        # 你现有代码里调用了 search_dsi_only，这里保持一致
        results = search_dsi_only(entity_name, topk=topk)
    elif entity_type in ["Disease", "Dis"]:
        results = _search_by_types(["Dis"])
        if not results or results[0]["score"] < threshold:
            print("[DEBUG] Cross-type fallback: try Symptom (SS)")
            results = _search_by_types(["SS"], th=threshold * 0.95)
    elif entity_type in ["Symptom", "SS"]:
        results = _search_by_types(["SS"])
        if not results or results[0]["score"] < threshold:
            print("[DEBUG] Cross-type fallback: try Disease (Dis)")
            results = _search_by_types(["Dis"], th=threshold * 0.95)
    elif entity_type in ["Gene"]:
        results = _search_by_types(["Gene"])
    else:
        print("[DEBUG] No type constraint applied (unknown or None)")
        results = _search_by_types(set(meta["node_types"]))

    # 回退全局搜索（放宽阈值）
    if not results or results[0]["score"] < threshold * 0.8:
        print(f"[DEBUG] Global fallback (candidates): threshold relaxed to {threshold * 0.8:.2f}")
        results = _search_by_types(set(meta["node_types"]), th=threshold * 0.8)

    # 返回候选列表（最多 topk 个）
    return results[:topk] if results else []
