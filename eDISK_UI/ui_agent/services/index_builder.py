"""
_*_CODING:UTF-8_*_
@Author: Yu Hou
@File: index_builder.py
@Time: 10/16/25; 11:02 AM
"""
import sqlite3, numpy as np, faiss, pickle
from django.conf import settings


def build_faiss():
    con = sqlite3.connect(settings.EMB_SQLITE_PATH)
    cur = con.cursor()
    cur.execute("SELECT name, edisk_id, node_type, is_primary, embedding FROM entity_embeddings")
    rows = cur.fetchall()
    con.close()

    names, ids, types, prim, vecs = [], [], [], [], []
    for name, eid, ntype, is_primary, blob in rows:
        emb = np.frombuffer(blob, dtype=np.float32)
        names.append(name)
        ids.append(eid)
        types.append(ntype)
        prim.append(1 if (str(is_primary).lower().startswith("y")) else 0)
        vecs.append(emb)

    X = np.vstack(vecs).astype(np.float32)
    # 归一化用于内积当作 cos 相似
    faiss.normalize_L2(X)
    index = faiss.IndexFlatIP(X.shape[1])
    index.add(X)

    faiss.write_index(index, settings.FAISS_INDEX_PATH)
    with open(settings.FAISS_META_PATH, "wb") as f:
        pickle.dump({
            "ids": list(range(len(names))),
            "names": names, "edisk_ids": ids, "node_types": types, "is_primary": prim
        }, f)
    return len(names), X.shape[1]
