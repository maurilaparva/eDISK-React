"""
_*_CODING:UTF-8_*_
@Author: Yu Hou
@File: context_graph.py
@Time: 10/16/25; 11:25 AM
"""

from collections import defaultdict
from typing import Dict, List, Any, Sequence, Optional
from .neo4j_client import run_cypher


def _safe_name(node_props: Dict[str, Any]) -> str:
    """Return the most informative display name for a node."""
    if not node_props:
        return ""
    for key in (
        "Name",
        "name",
        "Preferred_name",
        "Symbol",
        "preferredTerm",
        "Label",
        "label",
    ):
        if node_props.get(key):
            return str(node_props[key])
    if node_props.get("eDISK_ID"):
        return str(node_props["eDISK_ID"])
    if node_props.get("id"):
        return str(node_props["id"])
    return ""


def _collect_evidence(props: Dict[str, Any]) -> List[str]:
    evid_keys = ("Sentence", "sentence", "Evidence", "evidence", "Source", "source", "PMID", "PubMed_ID")
    evid = []
    for key in evid_keys:
        val = props.get(key) if props else None
        if isinstance(val, (str, int)) and str(val).strip():
            evid.append(f"{key}: {val}")
    return evid


def _first_label(labels: List[str]) -> str:
    if not labels:
        return ""
    if isinstance(labels, (list, tuple)):
        return labels[0] if labels else ""
    return str(labels)


def one_two_hop_subgraph(eid: str, etype: str, max_nodes: int = 80) -> Dict[str, Any]:
    """
    Retrieve 1-hop and 2-hop context around a node and convert it into
    lightweight summaries that can be surfaced to the LLM.
    """

    params = {"eid": eid, "limit1": max_nodes, "limit2": max_nodes * 2}

    one_hop_query = f"""
            MATCH (e:{etype} {{eDISK_ID:$eid}})-[r]-(n)
            WITH e, r, n
            RETURN {{
                neighbor_id: coalesce(n.eDISK_ID, n.id, n.ID),
                neighbor_name: coalesce(n.Name, n.name, n.Symbol, n.Label, n.eDISK_ID, n.id),
                neighbor_labels: labels(n),
                relation: type(r),
                direction: CASE WHEN startNode(r)=e THEN 'outbound' ELSE 'inbound' END,
                relation_props: properties(r)
            }} AS hop
            LIMIT $limit1
        """
    one_hop_rows = run_cypher(one_hop_query, params)

    two_hop_query = f"""
            MATCH (e:{etype} {{eDISK_ID:$eid}})-[r1]-(m)-[r2]-(n)
            WHERE n <> e
            RETURN {{
                mid_id: coalesce(m.eDISK_ID, m.id, m.ID),
                mid_name: coalesce(m.Name, m.name, m.Symbol, m.Label, m.eDISK_ID, m.id),
                mid_labels: labels(m),
                end_id: coalesce(n.eDISK_ID, n.id, n.ID),
                end_name: coalesce(n.Name, n.name, n.Symbol, n.Label, n.eDISK_ID, n.id),
                end_labels: labels(n),
                rel1: type(r1),
                rel2: type(r2),
                rel1_props: properties(r1),
                rel2_props: properties(r2)
            }} AS path
            LIMIT $limit2
        """
    two_hop_rows = run_cypher(two_hop_query, params)

    one_hop: List[Dict[str, Any]] = []
    type_buckets: Dict[str, List[str]] = defaultdict(list)
    for row in one_hop_rows:
        hop = row.get("hop", {}) if isinstance(row, dict) else {}
        hop_props = hop.get("relation_props") or {}
        hop["neighbor_type"] = _first_label(hop.get("neighbor_labels", []))
        hop["evidence"] = _collect_evidence(hop_props)
        hop["neighbor_display_name"] = hop.get("neighbor_name") or _safe_name({
            "Name": hop.get("neighbor_name"),
            "eDISK_ID": hop.get("neighbor_id"),
        }) or hop.get("neighbor_id") or "Unknown"
        one_hop.append(hop)
        if hop.get("neighbor_type") and hop.get("neighbor_display_name"):
            type_buckets[hop["neighbor_type"]].append(hop["neighbor_display_name"])

    two_hop: List[Dict[str, Any]] = []
    bridge_highlights: List[str] = []
    for row in two_hop_rows:
        path = row.get("path", {}) if isinstance(row, dict) else {}
        path["mid_type"] = _first_label(path.get("mid_labels", []))
        path["end_type"] = _first_label(path.get("end_labels", []))
        path["rel1_evidence"] = _collect_evidence(path.get("rel1_props") or {})
        path["rel2_evidence"] = _collect_evidence(path.get("rel2_props") or {})
        two_hop.append(path)
        mid_name = path.get("mid_name") or path.get("mid_id")
        end_name = path.get("end_name") or path.get("end_id")
        if mid_name and end_name:
            bridge_highlights.append(
                f"via {mid_name} ({path.get('mid_type', '?')}) to {end_name} ({path.get('end_type', '?')})"
            )

    highlights: List[str] = []
    for ntype, names in type_buckets.items():
        if not names:
            continue
        uniq = []
        for name in names:
            if name not in uniq:
                uniq.append(name)
        highlights.append(f"{ntype or 'Entity'} neighbors include {', '.join(uniq[:3])}")

    if bridge_highlights:
        highlights.append(
            "Two-hop bridges worth exploring: " + "; ".join(bridge_highlights[:3])
        )

    tips = []
    if highlights:
        tips = highlights[:]
    else:
        tips = [
            "Explore connected genes or pathways for mechanistic insights.",
            "Review adverse events or interaction edges around the mapped entities.",
            "Check co-morbid diseases appearing within two hops for broader context.",
        ]

    return {
        "one_hop": one_hop,
        "two_hop": two_hop,
        "highlights": highlights,
        "tips": tips,
        "queries": {
            "one_hop": {"cypher": one_hop_query.strip(), "params": params},
            "two_hop": {"cypher": two_hop_query.strip(), "params": params},
        },
    }


def single_entity_one_hop_context(
    eid: str,
    allowed_types: Sequence[str] = ("DSI", "DSP", "Disease", "Drug", "Symptom", "Gene"),
    *,
    allowed_relations: Optional[Sequence[str]] = None,
    max_neighbors: int = 60,
) -> Dict[str, Any]:
    """Return a concise one-hop view of the entity filtered by neighbour types."""

    allowed = list(allowed_types or [])
    relation_filter = list(allowed_relations or [])
    params = {
        "eid": eid,
        "types": allowed,
        "rels": relation_filter,
        "limit": max_neighbors,
    }

    query = """
        MATCH (e {eDISK_ID:$eid})-[r]-(n)
        WHERE ($types = [] OR ANY(lbl IN labels(n) WHERE lbl IN $types))
          AND ($rels = [] OR type(r) IN $rels)
        RETURN {
            neighbor_id: coalesce(n.eDISK_ID, n.id, n.ID),
            neighbor_name: coalesce(n.Name, n.name, n.Symbol, n.Label, n.eDISK_ID, n.id),
            neighbor_labels: labels(n),
            relation: type(r),
            direction: CASE WHEN startNode(r)=e THEN 'outbound' ELSE 'inbound' END,
            relation_props: properties(r)
        } AS hop
        LIMIT $limit
    """

    rows = run_cypher(query, params)

    neighbors: List[Dict[str, Any]] = []
    type_buckets: Dict[str, List[str]] = defaultdict(list)
    relation_buckets: Dict[str, List[str]] = defaultdict(list)

    for row in rows or []:
        hop = row.get("hop", {}) if isinstance(row, dict) else {}
        rel_props = hop.get("relation_props") or {}
        hop["neighbor_type"] = _first_label(hop.get("neighbor_labels", []))
        hop["neighbor_display_name"] = hop.get("neighbor_name") or _safe_name({
            "Name": hop.get("neighbor_name"),
            "eDISK_ID": hop.get("neighbor_id"),
        }) or hop.get("neighbor_id") or "Unknown"
        hop["evidence"] = _collect_evidence(rel_props)
        neighbors.append(hop)

        ntype = hop.get("neighbor_type") or "Entity"
        display = hop.get("neighbor_display_name")
        if display:
            if ntype not in type_buckets or display not in type_buckets[ntype]:
                type_buckets[ntype].append(display)
        rel_key = f"{ntype} via {hop.get('relation') or 'related_to'}"
        if display:
            relation_buckets.setdefault(rel_key, [])
            if display not in relation_buckets[rel_key]:
                relation_buckets[rel_key].append(display)

    highlights: List[str] = []
    for ntype, names in type_buckets.items():
        if names:
            highlights.append(f"{ntype} neighbors include {', '.join(names[:3])}")

    for rel_key, names in relation_buckets.items():
        if names and len(highlights) < 5:
            highlights.append(f"{rel_key} such as {', '.join(names[:3])}")

    tips = []
    if not highlights:
        tips = [
            "Review related diseases, drugs, or genes connected to this entity for broader insight.",
            "Consider exploring supporting literature from relation evidence fields.",
        ]

    return {
        "neighbors": neighbors,
        "highlights": highlights,
        "tips": tips,
        "queries": {"one_hop": {"cypher": query.strip(), "params": params}},
    }