"""
_*_CODING:UTF-8_*_
@Author: Yu Hou
@File: neo4j_client.py
@Time: 10/16/25; 11:25 AM
"""
from neo4j import GraphDatabase
from django.conf import settings

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
        )
    return _driver


def run_cypher(cypher: str, params: dict = None) -> list:
    with get_driver().session() as s:
        rs = s.run(cypher, params or {})
        return [r.data() for r in rs]


def edge_label_for(relation: str, e1_type: str, e2_type: str) -> str:
    # 简单映射；你可在此扩展自定义映射表
    m = {
        "treats": "DSI_Disease",
        "prevents": "DSI_Disease",
        "associated_with": "ASSOCIATED_WITH",
        "interacts_with": "INTERACTS_WITH",
        "contraindicated_for": "CONTRAINDICATED_FOR",
        "biomarker_of": "BIOMARKER",
        "causes": "CAUSES",
    }
    return m.get(relation, "ASSOCIATED_WITH")


def match_direct(e1_id: str, e1_type: str, e2_id: str, e2_type: str, relation: str) -> list:
    rel = edge_label_for(relation, e1_type, e2_type)
    cypher = f"""
    MATCH p=(e1:{e1_type} {{eDISK_ID:$e1}})-[r:{rel}]->(e2:{e2_type} {{eDISK_ID:$e2}})
    RETURN p LIMIT 50
    """
    return run_cypher(cypher, {"e1": e1_id, "e2": e2_id})


def match_direct_any_relation(e1_id: str, e2_id: str, max_hops: int = 1) -> list:
    """
    查询两个实体之间所有直接关系（不限制relation type）。
    返回每条关系的类型和属性。
    """
    cypher = build_match_direct_any_relation_query(max_hops=max_hops)
    try:
        return run_cypher(cypher, {"e1": e1_id, "e2": e2_id})
    except Exception as e:
        print(f"[ERROR] match_direct_any_relation failed: {e}")
        return []


def build_match_direct_any_relation_query(max_hops: int = 1) -> str:
    return f"""
    MATCH p = (a {{eDISK_ID:$e1}})-[*1..{max_hops}]-(b {{eDISK_ID:$e2}})
    WITH relationships(p) AS rels, p
    RETURN
        p,
        [rel IN rels |
            {{
                edge_type: type(rel),
                properties: properties(rel)
            }}
        ] AS rel_info
    LIMIT 50
    """


def build_top_connected_entities_query(neighbor_label: str) -> str:
    return f"""
    MATCH (target {{eDISK_ID:$target_id}})
    MATCH (neighbor:{neighbor_label})-[r]-(target)
    WITH target, neighbor, r
    WITH
        target,
        neighbor,
        collect({{
            edge_type: type(r),
            direction: CASE WHEN startNode(r)=target THEN 'outbound' ELSE 'inbound' END,
            properties: properties(r)
        }}) AS rels,
        count(r) AS rel_count,
        max(coalesce(r.Score, r.score, r.Confidence, r.confidence, r.Weight, r.weight, 0.0)) AS best_score,
        coalesce(neighbor.Name, neighbor.name, neighbor.Symbol, neighbor.Label, neighbor.eDISK_ID, neighbor.id, neighbor.ID) AS neighbor_name
    RETURN {{
        id: coalesce(neighbor.eDISK_ID, neighbor.id, neighbor.ID),
        name: neighbor_name,
        labels: labels(neighbor)
    }} AS neighbor,
    rels AS relations,
    rel_count AS relation_count,
    best_score AS best_score,
    neighbor_name AS neighbor_name
    ORDER BY relation_count DESC, best_score DESC, neighbor_name
    LIMIT $limit
    """


def top_connected_entities(target_id: str, neighbor_label: str, topk: int = 5) -> list:
    if not target_id:
        return []
    query = build_top_connected_entities_query(neighbor_label)
    params = {"target_id": target_id, "limit": topk}
    rows = run_cypher(query, params)
    results = []
    for row in rows or []:
        neighbor = row.get("neighbor") or {}
        relations = row.get("relations") or []
        relation_count = row.get("relation_count")
        best_score = row.get("best_score")
        if relation_count is not None:
            try:
                relation_count = int(relation_count)
            except Exception:
                pass
        if best_score is not None:
            try:
                best_score = float(best_score)
            except Exception:
                pass
        if neighbor_label and neighbor and "type" not in neighbor:
            neighbor["type"] = neighbor_label
        results.append(
            {
                "neighbor": neighbor,
                "relations": relations,
                "relation_count": relation_count,
                "best_score": best_score,
            }
        )
    return results


def fetch_node_with_properties(eid: str) -> dict:
    """Return a node's labels and properties for a given eDISK identifier."""

    if not eid:
        return {}

    query = """
        MATCH (n)
        WHERE n.eDISK_ID = $eid OR n.id = $eid OR n.ID = $eid
        RETURN
            coalesce(n.eDISK_ID, n.id, n.ID) AS id,
            labels(n) AS labels,
            properties(n) AS props
        LIMIT 1
    """

    rows = run_cypher(query, {"eid": eid})
    if not rows:
        return {}

    row = rows[0] or {}
    return {
        "id": row.get("id") or eid,
        "labels": row.get("labels", []),
        "properties": row.get("props", {}),
    }