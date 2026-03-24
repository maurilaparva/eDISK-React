"""
_*_CODING:UTF-8_*_
@Author: Yu Hou
@File: faiss_index.py
@Time: 10/16/25; 1:40 PM
"""
import os
import faiss
import pickle
import numpy as np
from django.conf import settings

_index = None
_meta = None


def load_index():
    """加载 FAISS 索引与元数据"""
    global _index, _meta
    if _index is not None:
        return _index, _meta

    index_path = settings.FAISS_INDEX_PATH
    meta_path = settings.FAISS_META_PATH

    if not os.path.exists(index_path):
        raise FileNotFoundError(f"FAISS index not found: {index_path}")
    if not os.path.exists(meta_path):
        raise FileNotFoundError(f"FAISS meta not found: {meta_path}")

    _index = faiss.read_index(index_path)
    with open(meta_path, "rb") as f:
        _meta = pickle.load(f)

    print(f"[FAISS] Loaded index with {_index.ntotal} vectors, dim={_index.d}")
    return _index, _meta


def search(vec, topk=10):
    """在 FAISS 索引中搜索最相似的向量"""
    if isinstance(vec, list):
        vec = np.array(vec, dtype="float32").reshape(1, -1)
    elif isinstance(vec, np.ndarray):
        if vec.ndim == 1:
            vec = vec.reshape(1, -1)
    else:
        raise ValueError("Input vector must be numpy array or list")

    index, meta = load_index()
    scores, idxs = index.search(vec, topk)

    results = []
    for score, idx in zip(scores[0], idxs[0]):
        if idx < 0 or idx >= len(meta):
            continue
        results.append({
            "id": meta[idx]["entity_id"],
            "name": meta[idx]["entity_name"],
            "type": meta[idx].get("entity_type", ""),
            "score": float(score),
        })
    return results
