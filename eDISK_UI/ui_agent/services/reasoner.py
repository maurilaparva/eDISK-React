"""
_*_CODING:UTF-8_*_
@Author: Yu Hou
@File: reasoner.py
@Time: 10/16/25; 11:26 AM
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from django.conf import settings
from .neo4j_client import run_cypher

try:  # Optional heavy dependencies (torch/pykeen)
    import torch  # type: ignore
    from pykeen.triples import TriplesFactory  # type: ignore

    _TORCH_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    torch = None  # type: ignore
    TriplesFactory = None  # type: ignore
    _TORCH_AVAILABLE = False


TYPE_LABEL_MAP = {
    "DSI": "DSI",
    "DSP": "DSP",
    "Drug": "Drug",
    "Dis": "Disease",
    "Disease": "Disease",
    "SS": "Symptom",
    "Symptom": "Symptom",
    "Gene": "Gene",
}


CANONICAL_TYPE = {
    "DSI": "DSI",
    "DSP": "DSP",
    "Drug": "Drug",
    "DRUG": "Drug",
    "Dis": "Disease",
    "Disease": "Disease",
    "DISEASE": "Disease",
    "SS": "Symptom",
    "Symptom": "Symptom",
    "SYMPTOM": "Symptom",
    "Gene": "Gene",
    "GENE": "Gene",
}


# Relations that typically connect entity type pairs in eDISK. The order conveys
# preference when scoring via TransE – earlier relations are tried first.
LP_RELATIONS: Dict[tuple[str, str], Sequence[str]] = {
    ("DSI", "Disease"): ("is_effective_for", "associated_with", "has_adverse_reaction"),
    ("DSI", "Drug"): ("interacts_with", "stimulates", "inhibits"),
    ("DSI", "Symptom"): ("is_effective_for", "associated_with", "has_adverse_reaction"),
    ("DSI", "Gene"): ("interacts_with", "stimulates", "inhibits"),
    ("Disease", "DSI"): ("is_effective_for", "associated_with"),
    ("Disease", "Drug"): ("is_effective_for", "associated_with", "Causes"),
    ("Disease", "Symptom"): ("associated_with", "presents_with"),
    ("Disease", "Gene"): ("associated_with", "Causes"),
    ("Drug", "DSI"): ("interacts_with", "inhibits", "stimulates"),
    ("Drug", "Disease"): ("is_effective_for", "associated_with", "Causes", "inhibits"),
    ("Drug", "Symptom"): ("has_adverse_reaction", "associated_with"),
    ("Drug", "Gene"): ("interacts_with", "inhibits", "stimulates"),
    ("Symptom", "DSI"): ("is_effective_for", "associated_with"),
    ("Symptom", "Disease"): ("associated_with", "Causes"),
    ("Symptom", "Drug"): ("has_adverse_reaction", "associated_with"),
    ("Symptom", "Gene"): ("associated_with",),
    ("Gene", "DSI"): ("interacts_with", "stimulates", "inhibits"),
    ("Gene", "Disease"): ("associated_with", "Causes"),
    ("Gene", "Drug"): ("interacts_with", "inhibits", "stimulates"),
    ("Gene", "Symptom"): ("associated_with",),
}


DEFAULT_TARGET_TYPES: Dict[str, Sequence[str]] = {
    "DSI": ("Disease", "Drug", "Symptom", "Gene"),
    "Disease": ("DSI", "Drug", "Symptom", "Gene"),
    "Drug": ("DSI", "Disease", "Symptom", "Gene"),
    "Symptom": ("DSI", "Disease", "Drug", "Gene"),
    "Gene": ("DSI", "Disease", "Drug", "Symptom"),
}


@dataclass
class LPBackend:
    mode: str
    details: str = ""


_backend: Optional[LPBackend] = None
_model = None
_tf: Optional[TriplesFactory] = None


def _load_transe_model() -> LPBackend:
    """Attempt to load the trained TransE model from disk."""

    global _model, _tf, _backend
    if _backend is not None:
        return _backend

    if not _TORCH_AVAILABLE:
        _backend = LPBackend(mode="fallback", details="torch/pykeen unavailable")
        return _backend

    model_path = settings.PYKEEN_MODEL_DIR + "/model.pkl"
    triples_path = settings.PYKEEN_MODEL_DIR + "/training_triples.tsv"

    try:
        _tf = TriplesFactory.from_path(triples_path)
        _model = torch.load(model_path, map_location="cpu")
        _model.eval()
        _backend = LPBackend(mode="transe", details="pykeen model loaded")
    except Exception as exc:  # pragma: no cover - depends on runtime files
        _model = None
        _tf = None
        _backend = LPBackend(mode="fallback", details=str(exc))

    return _backend


def _normalize_label(node_type: Optional[str]) -> Optional[str]:
    if not node_type:
        return None
    return TYPE_LABEL_MAP.get(node_type, node_type)


def canonical_type(node_type: Optional[str]) -> Optional[str]:
    if not node_type:
        return None
    return CANONICAL_TYPE.get(node_type, node_type)


def default_target_types(node_type: Optional[str]) -> List[str]:
    canon = canonical_type(node_type)
    if not canon:
        return []
    return list(DEFAULT_TARGET_TYPES.get(canon, []))


def _relation_preferences(head_type: Optional[str], tail_type: Optional[str]) -> List[str]:
    h = canonical_type(head_type)
    t = canonical_type(tail_type)
    if not h or not t:
        return []
    prefs = LP_RELATIONS.get((h, t))
    if prefs:
        return list(prefs)
    # Try symmetric lookup to avoid hand-maintaining every direction.
    prefs = LP_RELATIONS.get((t, h))
    return list(prefs) if prefs else []


def _format_candidate(row: Dict[str, any], method: str) -> Dict[str, any]:
    connectors = row.get("connector_names") or []
    conn_types = row.get("connector_types") or []
    connector_text = ""
    if connectors:
        joined = ", ".join(connectors[:3])
        connector_text = f"connectors: {joined}"
    elif conn_types:
        joined = ", ".join(conn_types[:3])
        connector_text = f"connector types: {joined}"

    tail_type_raw = row.get("tail_type")
    tail_type = canonical_type(tail_type_raw) or tail_type_raw

    return {
        "tail_id": row.get("tail_id"),
        "tail_name": row.get("tail_name"),
        "tail_type": tail_type,
        "score": float(row.get("score", 0.0)),
        "method": method,
        "explanation": connector_text,
        "relations": row.get("via_relations", []),
    }


def _graph_based_rank(head_id: str, tail_label: str, topk: int) -> Dict[str, any]:
    """Rank candidates using two-hop connector counts as a heuristic."""

    query = f"""
        MATCH (h {{eDISK_ID:$head}})
        MATCH (h)-[r1]-(mid)-[r2]-(cand:{tail_label})
        WHERE cand.eDISK_ID IS NOT NULL AND cand.eDISK_ID <> $head
          AND NOT (h)--(cand)
        RETURN
            cand.eDISK_ID AS tail_id,
            coalesce(cand.Name, cand.name, cand.Symbol, cand.Label, cand.eDISK_ID) AS tail_name,
            head(labels(cand)) AS tail_type,
            COUNT(*) AS score,
            collect(DISTINCT head(labels(mid))) AS connector_types,
            [x IN collect(DISTINCT coalesce(mid.Name, mid.name, mid.Symbol, mid.Label, mid.eDISK_ID)) WHERE x IS NOT NULL][0..3] AS connector_names,
            collect(DISTINCT type(r1)) + collect(DISTINCT type(r2)) AS via_relations
        ORDER BY score DESC, tail_name
        LIMIT $limit
    """

    rows = run_cypher(query, {"head": head_id, "limit": topk})

    # If nothing is returned, fall back to direct neighbours (still useful)
    if not rows:
        direct_query = f"""
            MATCH (h {{eDISK_ID:$head}})-[r]-(cand:{tail_label})
            RETURN
                cand.eDISK_ID AS tail_id,
                coalesce(cand.Name, cand.name, cand.Symbol, cand.Label, cand.eDISK_ID) AS tail_name,
                head(labels(cand)) AS tail_type,
                COUNT(*) AS score,
                collect(DISTINCT type(r)) AS via_relations,
                [] AS connector_names,
                [] AS connector_types
            ORDER BY score DESC, tail_name
            LIMIT $limit
        """
        rows = run_cypher(direct_query, {"head": head_id, "limit": topk})

    candidates = [_format_candidate(r, "graph-heuristic") for r in rows or []]
    return {
        "candidates": candidates,
        "method": "graph-heuristic",
        "notes": "Ranked by shared two-hop connectors" if rows else "Ranked by direct degree",
        "uses_transe": False,
    }


def _fetch_node_metadata(ids: Iterable[str]) -> Dict[str, Dict[str, any]]:
    """Return label/name metadata for the supplied eDISK identifiers."""

    unique_ids = [i for i in dict.fromkeys([i for i in ids if i])]
    if not unique_ids:
        return {}

    rows = run_cypher(
        """
        MATCH (n)
        WHERE n.eDISK_ID IN $ids
        RETURN
            n.eDISK_ID AS id,
            labels(n) AS labels,
            coalesce(n.Name, n.name, n.Symbol, n.Label, n.eDISK_ID) AS name
        """,
        {"ids": unique_ids},
    )

    meta: Dict[str, Dict[str, any]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        node_id = row.get("id")
        if not node_id:
            continue
        meta[node_id] = {
            "labels": row.get("labels", []),
            "name": row.get("name"),
        }
    return meta


def _transe_rank(head_id: str, relation: str, tail_type: str, topk: int) -> Optional[Dict[str, any]]:
    backend = _load_transe_model()
    if backend.mode != "transe" or _model is None or _tf is None:
        return None

    try:  # pragma: no cover - depends on training artefacts
        h_idx = _tf.entity_label_to_id[head_id]
        if relation not in _tf.relation_label_to_id:
            return None
        r_idx = _tf.relation_label_to_id[relation]
        scores = _model.score_t(h=h_idx, r=r_idx)
        fetch_k = min(len(scores), max(topk * 10, topk))
        vals, idx = torch.topk(scores, k=fetch_k)
        raw_candidates: List[tuple[str, float]] = []
        for value, entity_idx in zip(vals.tolist(), idx.tolist()):
            label = _tf.entity_id_to_label[int(entity_idx)]
            if label == head_id:
                continue
            raw_candidates.append((label, float(value)))

        metadata = _fetch_node_metadata([label for label, _ in raw_candidates])
        filtered: List[Dict[str, any]] = []
        target_canon = canonical_type(tail_type) or tail_type

        for label, score in raw_candidates:
            meta = metadata.get(label, {})
            labels = meta.get("labels", []) if isinstance(meta, dict) else []
            label_matches = False
            if target_canon:
                for node_label in labels or []:
                    if canonical_type(node_label) == target_canon:
                        label_matches = True
                        break
            else:
                label_matches = True
            if not label_matches:
                continue
            filtered.append(
                {
                    "tail_id": label,
                    "tail_name": meta.get("name") or label,
                    "tail_type": target_canon,
                    "score": score,
                    "method": "transe",
                    "explanation": "TransE score",
                    "relations": [relation],
                }
            )
            if len(filtered) >= topk:
                break

        notes = backend.details
        if filtered and len(filtered) < topk:
            notes = f"{backend.details} (insufficient type-matched hits; showing top {len(filtered)})"

        return {
            "candidates": filtered,
            "method": "transe",
            "notes": notes,
            "uses_transe": True,
        }
    except Exception as exc:
        # If the trained model cannot score, fall back gracefully.
        _backend.mode = "fallback"
        _backend.details = str(exc)
        return None


def lp_rank(head_id: str, relation: Optional[str], tail_type: str, topk: int = 10) -> Dict[str, any]:
    """
    Return ranked candidates for the tail entity.

    The dictionary includes the candidate list and metadata about the method
    that produced them.
    """

    tail_label = _normalize_label(tail_type)
    if not tail_label:
        return {
            "candidates": [],
            "method": None,
            "notes": "Unknown tail type",
            "uses_transe": False,
            "relation": relation,
        }

    relation_to_use = relation or "associated_with"
    transe_result = None
    if relation:
        transe_result = _transe_rank(head_id, relation_to_use, tail_label, topk)
        if transe_result and transe_result.get("candidates"):
            if len(transe_result["candidates"]) < topk:
                graph_result = _graph_based_rank(head_id, tail_label, topk)
                existing_ids = {c.get("tail_id") for c in transe_result["candidates"]}
                for cand in graph_result.get("candidates", []):
                    if cand.get("tail_id") in existing_ids:
                        continue
                    transe_result["candidates"].append(cand)
                    if len(transe_result["candidates"]) >= topk:
                        break
                if graph_result.get("candidates"):
                    existing_note = (transe_result.get("notes") or "").strip()
                    extra = "supplemented with graph heuristic for coverage"
                    if existing_note:
                        transe_result["notes"] = existing_note + "; " + extra
                    else:
                        transe_result["notes"] = extra
            transe_result["relation"] = relation_to_use
            return transe_result

    graph_result = _graph_based_rank(head_id, tail_label, topk)
    graph_result["relation"] = relation_to_use
    return graph_result


def describe_backend() -> LPBackend:
    backend = _load_transe_model()
    return backend


def predict_for_entity(
    head_id: str,
    head_type: Optional[str],
    target_types: Sequence[str],
    topk: int = 3,
) -> Dict[str, any]:
    """Predict top-k entities for each target type around the given head."""

    backend = _load_transe_model()
    head_canon = canonical_type(head_type)
    predictions: List[Dict[str, any]] = []

    for tail_type in target_types:
        relation_options = _relation_preferences(head_canon, tail_type)
        result = None
        used_relation = None
        for rel in relation_options:
            result = lp_rank(head_id, rel, tail_type, topk=topk)
            if result.get("candidates"):
                used_relation = rel
                break
        if result is None:
            result = lp_rank(head_id, None, tail_type, topk=topk)
        elif not result.get("candidates"):
            # try heuristic fallback even if we attempted TransE with relations
            graph = lp_rank(head_id, None, tail_type, topk=topk)
            if graph.get("candidates"):
                result = graph
        if result.get("relation") is None:
            result["relation"] = used_relation or (relation_options[0] if relation_options else None)
        result["target_type"] = canonical_type(tail_type)
        predictions.append(result)

    return {
        "backend": backend,
        "head_type": head_canon,
        "predictions": predictions,
    }