"""
_*_CODING:UTF-8_*_
@Author: Yu Hou
@File: orchestrator.py
@Time: 10/16/25; 11:27 AM
"""
import json
from typing import List, Dict, Any, Optional, Set
from ui_agent.services.neo4j_client import run_cypher
from ui_agent.services.progress import set_progress
from ui_agent.services import (
    llm_parser,
    entity_linker,
    neo4j_client,
    context_graph,
    reasoner,
    verifier,
    summarizer,
    run_logger,
)


def _pick_top(candidates):
    if not candidates:
        return None

    if isinstance(candidates, str):
        return {"id": candidates, "name": candidates, "type": "", "score": 1.0}

    if isinstance(candidates, dict):
        return candidates

    if isinstance(candidates[0], str):
        return {"id": candidates[0], "name": candidates[0], "type": "", "score": 1.0}

    return sorted(candidates, key=lambda x: -x.get("score", 0.0))[0]


def _etype_norm(t: str) -> str:
    if not t:
        return ""
    m = {
        "DSI": "DSI",
        "DSP": "DSP",
        "Drug": "Drug",
        "Dis": "Disease",
        "Symptom": "Symptom",
        "SS": "Symptom",
        "Gene": "Gene",
    }
    return m.get(t, t)


# --- helpers for connectivity-aware disambiguation ---

def _dedup_by_id(cands):
    best = {}
    for c in cands or []:
        cid = c.get("id")
        if not cid:
            continue
        if cid not in best or c.get("score", 0.0) > best[cid].get("score", 0.0):
            best[cid] = c
    return list(best.values())


def _connected_hops(a_id: str, b_id: str, max_hops: int = 2) -> int:
    query = f"""
    MATCH p = shortestPath(
        (a {{eDISK_ID:'{a_id}'}})-[*..{max_hops}]-(b {{eDISK_ID:'{b_id}'}})
    )
    RETURN CASE WHEN p IS NULL THEN 0 ELSE length(p) END AS hops
    """

    try:
        res = neo4j_client.run_cypher(query)
        if res and "hops" in res[0]:
            return int(res[0]["hops"])
    except Exception as e:
        print(f"[WARN] _connected_hops failed for {a_id} ↔ {b_id}: {e}")
    return 0


def _pick_connected_candidate(candidates, target_id: str, max_hops: int = 2):
    if not candidates:
        return None
    for hops in range(1, max_hops + 1):
        for cand in candidates:
            cand_id = cand["id"]
            query = f"""
            MATCH (a {{eDISK_ID: '{cand_id}'}})-[r*1..{hops}]-(b {{eDISK_ID: '{target_id}'}})
            RETURN COUNT(r) AS rels
            """
            try:
                result = run_cypher(query)
                if result and result[0].get("rels", 0) > 0:
                    print(f"[DEBUG] Connectivity pick: {cand_id} ↔ {target_id} within {hops} hops")
                    return cand
            except Exception as e:
                print(f"[WARN] Neo4j connectivity check failed for {cand_id} → {target_id}: {e}")
                continue
    return candidates[0]


REL_TYPE_MAP = {
    ("DSI", "DSI"): ["interacts_with", "stimulates", "inhibits"],
    ("DSI", "Disease"): ["is_effective_for", "associated_with", "Causes"],
    ("DSI", "Drug"): ["interacts_with", "stimulates", "inhibits"],
    ("DSI", "Gene"): ["stimulates", "interacts_with", "inhibits"],
    ("DSI", "Symptom"): ["is_effective_for", "associated_with", "has_adverse_reaction"],
    ("DSP", "DSI"): ["has_ingredient"],
    ("Disease", "Gene"): ["associated_with"],
    ("Drug", "Disease"): ["is_effective_for", "associated_with", "Causes", "inhibits", "interacts_with"],
    ("Drug", "Gene"): ["interacts_with", "stimulates", "inhibits"]
}


CATEGORY_SYNONYMS = {
    "DSI": {
        "dietary supplement",
        "dietary supplements",
        "supplement",
        "supplements",
        "dietary supplement ingredient",
        "dietary supplement ingredients",
        "supplement ingredient",
        "supplement ingredients",
        "dsi",
        "dsis",
    },
    "Drug": {
        "drug",
        "drugs",
        "medication",
        "medications",
        "medicine",
        "medicines",
        "pharmaceutical",
        "pharmaceuticals",
        "therapeutic agent",
        "therapeutic agents",
    },
    "Disease": {
        "disease",
        "diseases",
        "illness",
        "illnesses",
        "disorder",
        "disorders",
        "condition",
        "conditions",
        "syndrome",
        "syndromes",
    },
    "Gene": {
        "gene",
        "genes",
        "genetic marker",
        "genetic markers",
        "genetic target",
        "genetic targets",
    },
    "Symptom": {
        "symptom",
        "symptoms",
        "clinical symptom",
        "clinical symptoms",
        "adverse reaction",
        "adverse reactions",
        "side effect",
        "side effects",
        "reaction",
        "reactions",
        "adverse event",
        "adverse events",
    },
}


CATEGORY_DISPLAY_NAMES = {
    "DSI": "dietary supplement ingredients",
    "Drug": "drugs",
    "Disease": "diseases",
    "Gene": "genes",
    "Symptom": "symptoms",
}


def _detect_category_placeholders_from_query(
    query: str, existing_texts: Set[str]
) -> List[Dict[str, str]]:
    if not query:
        return []

    lowered_query = query.lower()
    inferred: List[Dict[str, str]] = []

    for label, synonyms in CATEGORY_SYNONYMS.items():
        best_match = None
        best_len = 0
        for phrase in synonyms:
            normalized = phrase.lower()
            if not normalized:
                continue
            if normalized in existing_texts:
                continue
            if normalized in lowered_query and len(normalized) > best_len:
                best_match = phrase
                best_len = len(normalized)

        if best_match:
            inferred.append({"text": best_match, "type": label})

    return inferred


def _normalize_placeholder_candidate(text: str) -> str:
    if not text:
        return ""
    lowered = text.strip().lower()
    if not lowered:
        return ""
    cleaned = lowered.replace("?", " ").replace(",", " ").replace(".", " ")
    tokens = [
        tok
        for tok in cleaned.split()
        if tok
        and tok not in {"a", "an", "the", "any", "type", "types", "kind", "kinds", "of"}
    ]
    return " ".join(tokens)


def _resolve_category_placeholder(text: str, etype: Optional[str]) -> Optional[str]:
    candidate = _normalize_placeholder_candidate(text)
    if not candidate:
        return None

    def _match_candidate(norm_type: str) -> bool:
        synonyms = CATEGORY_SYNONYMS.get(norm_type) or set()
        if not synonyms:
            return False
        if candidate in synonyms:
            return True
        if candidate.endswith("s") and candidate[:-1] in synonyms:
            return True
        if candidate.endswith("es") and candidate[:-2] in synonyms:
            return True
        return False

    normalized_type = _etype_norm(etype or "")
    if normalized_type and _match_candidate(normalized_type):
        return normalized_type

    for norm_type in CATEGORY_SYNONYMS.keys():
        if _match_candidate(norm_type):
            return norm_type

    return None


def _is_category_placeholder(text: str, etype: Optional[str]) -> bool:
    return _resolve_category_placeholder(text, etype) is not None


def _category_display_name(label: Optional[str]) -> str:
    if not label:
        return "category entities"
    return CATEGORY_DISPLAY_NAMES.get(label, label)


def _first_mapped_entity_with_id(linked_entities: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for item in linked_entities or []:
        mapped = item.get("mapped") or {}
        if mapped.get("id") and not mapped.get("is_category"):
            return mapped
    return None


def _build_graph_data(linked, context, direct_result, mode):
    """
    Serialise entity + neighbour data into a compact structure
    that GraphPanel can use directly without regex-parsing the prose.
    """
    entities = []
    for item in linked or []:
        mapped = item.get("mapped") or {}
        if mapped.get("is_category"):
            continue
        entities.append({
            "id":    mapped.get("id"),
            "name":  mapped.get("name") or mapped.get("id"),
            "type":  mapped.get("type"),
            "score": mapped.get("score"),
        })

    neighbors = []

    if mode == "pair":
        for ent_ctx in (context or {}).get("entities", []):
            entity  = ent_ctx.get("entity") or {}
            ctx     = ent_ctx.get("context") or {}
            for hop in (ctx.get("one_hop") or []):
                neighbors.append({
                    "source_id":   entity.get("id"),
                    "neighbor_id": hop.get("neighbor_id"),
                    "neighbor_name": hop.get("neighbor_display_name") or hop.get("neighbor_name"),
                    "neighbor_type": hop.get("neighbor_type"),
                    "relation":    hop.get("relation"),
                    "direction":   hop.get("direction"),
                    "evidence":    (hop.get("evidence") or [])[:2],
                })
    else:
        single = (context or {}).get("single_entity") or {}
        entity = single.get("entity") or {}
        ctx    = single.get("context") or {}
        for hop in (ctx.get("neighbors") or []):
            neighbors.append({
                "source_id":   entity.get("id"),
                "neighbor_id": hop.get("neighbor_id"),
                "neighbor_name": hop.get("neighbor_display_name") or hop.get("neighbor_name"),
                "neighbor_type": hop.get("neighbor_type"),
                "relation":    hop.get("relation"),
                "direction":   hop.get("direction"),
                "evidence":    (hop.get("evidence") or [])[:2],
            })

    direct_edges = []
    if mode == "pair" and direct_result:
        for item in direct_result:
            for rel in (item.get("rel_info") or []):
                direct_edges.append({
                    "edge_type":  rel.get("edge_type"),
                    "properties": rel.get("properties") or {},
                })

    return {
        "entities":     entities,
        "neighbors":    neighbors[:40],
        "direct_edges": direct_edges,
        "mode":         mode,
    }


def run_pipeline(run_id: str, user_query: str):
    """End-to-end pipeline with progress updates."""
    try:
        log_details = {
            "question": user_query,
            "relation": None,
            "parsed_entities": [],
            "entity_linking": {},
            "direct_query": {},
            "direct_result": [],
            "context": [],
            "link_prediction": {},
            "verification": [],
        }
        # 1) Parse
        set_progress(run_id, "[1/7] Parsing query...")
        parsed = llm_parser.parse_query(user_query) or {}
        rel = parsed.get("relation") or "associated_with"
        ents = parsed.get("entities") or []
        log_details["relation"] = rel
        # sanitize
        norm_ents = []
        for e in ents:
            norm_ents.append({"text": e.get("text", "").strip(), "type": e.get("type")})
        ents = [e for e in norm_ents if e["text"]]

        if len(ents) <= 1:
            existing_texts = {e["text"].lower() for e in ents if e.get("text")}
            inferred = _detect_category_placeholders_from_query(user_query, existing_texts)
            if inferred:
                print(f"[DEBUG] Fallback placeholders inferred from query: {inferred}")
                ents.extend(inferred)

        log_details["parsed_entities"] = ents

        # 2) Entity linking with connectivity-aware disambiguation
        set_progress(run_id, "[2/7] Mapping entities to eDISK IDs...")
        linked: List[Dict[str, Any]] = []

        # Step 2.1
        candidates_all = []
        for e in ents:
            et = e.get("type")
            name = e["text"]
            cands = entity_linker.link_entities_candidates(name, et, threshold=0.8, topk=10)
            cands = _dedup_by_id(cands)
            print(f"[DEBUG] link_entities_candidates({name}, {et}) → {len(cands)} unique results")
            candidates_all.append({"input": e, "candidates": cands})

        if len(candidates_all) < 1 or not candidates_all[0]["candidates"]:
            set_progress(run_id, "[FINAL] Sorry, I could not confidently map entities. Please rephrase.")
            set_progress(run_id, "[DONE]")
            log_details["entity_linking"] = {"candidates": candidates_all, "selected": []}
            run_logger.log_pipeline_run(run_id, log_details)
            return

        # Step 2.2
        placeholders: List[Dict[str, Any]] = []
        real_items: List[Dict[str, Any]] = []
        category_label: Optional[str] = None
        category_inputs: List[str] = []
        for item in candidates_all:
            raw_input = item.get("input", {})
            text = raw_input.get("text", "")
            etype = raw_input.get("type")
            placeholder_type = _resolve_category_placeholder(text, etype)
            if placeholder_type:
                placeholders.append({"item": item, "category_type": placeholder_type})
                if not category_label:
                    category_label = placeholder_type
                category_inputs.append(text)
            else:
                real_items.append(item)

        mode = None
        category_info: Optional[Dict[str, Any]] = None

        if placeholders and len(real_items) == 1:
            target_item = real_items[0]
            if not target_item.get("candidates"):
                set_progress(run_id, "[FINAL] Sorry, I could not confidently map entities. Please rephrase.")
                set_progress(run_id, "[DONE]")
                log_details["entity_linking"] = {"candidates": candidates_all, "selected": []}
                run_logger.log_pipeline_run(run_id, log_details)
                return

            for placeholder in placeholders:
                placeholder_item = placeholder.get("item") or {}
                placeholder_input = placeholder_item.get("input") or {}
                placeholder_type = placeholder.get("category_type")
                if not placeholder_type:
                    placeholder_type = _etype_norm(placeholder_input.get("type")) or (placeholder_input.get("type") or "")
                linked.append(
                    {
                        "input": placeholder_input,
                        "mapped": {
                            "id": f"Category:{placeholder_type or 'Entity'}",
                            "name": placeholder_input.get("text"),
                            "type": placeholder_type or placeholder_input.get("type"),
                            "score": 1.0,
                            "is_category": True,
                        },
                    }
                )

            selected_target = _pick_top(target_item.get("candidates"))
            if not selected_target:
                set_progress(run_id, "[FINAL] Sorry, I could not confidently map entities. Please rephrase.")
                set_progress(run_id, "[DONE]")
                log_details["entity_linking"] = {"candidates": candidates_all, "selected": linked}
                run_logger.log_pipeline_run(run_id, log_details)
                return
            linked.append({"input": target_item.get("input"), "mapped": selected_target})
            mode = "category_single"
            resolved_label = category_label
            if not resolved_label and placeholders:
                resolved_label = _etype_norm(
                    (placeholders[0].get("item") or {}).get("input", {}).get("type")
                )
            category_info = {
                "label": resolved_label,
                "inputs": category_inputs,
                "display": _category_display_name(resolved_label),
            }

        elif len(candidates_all) >= 2:
            e1_cands = candidates_all[0]["candidates"]
            e2_cands = candidates_all[1]["candidates"]

            best_pair = None
            best_key = None
            for c1 in e1_cands:
                for c2 in e2_cands:
                    hops = _connected_hops(c1["id"], c2["id"], max_hops=2)
                    if hops > 0:
                        key = (hops, -c1.get("score", 0.0), -c2.get("score", 0.0))
                        if best_key is None or key < best_key:
                            best_key = key
                            best_pair = (c1, c2)

            if best_pair:
                c1, c2 = best_pair
                print(f"[DEBUG] ✅ Best connected pair: {c1['id']} ({c1.get('name')}) "
                      f"↔ {c2['id']} ({c2.get('name')}), key={best_key}")
                linked.append({"input": candidates_all[0]["input"], "mapped": c1})
                linked.append({"input": candidates_all[1]["input"], "mapped": c2})
            else:
                print("[DEBUG] No connected pair found; using top-1 by similarity for each.")
                linked.append({"input": candidates_all[0]["input"], "mapped": e1_cands[0]})
                linked.append({"input": candidates_all[1]["input"], "mapped": e2_cands[0]})

        else:
            linked.append({"input": candidates_all[0]["input"], "mapped": candidates_all[0]["candidates"][0]})

        if mode is None:
            mode = "pair" if len(linked) >= 2 else "single"

        main_entity = _first_mapped_entity_with_id(linked)

        if mode == "pair" and len(linked) >= 2:
            set_progress(
                run_id,
                "[Entity Mapping] Selected: "
                f"{linked[0]['mapped']['name']} ({linked[0]['mapped']['id']}) ↔ "
                f"{linked[1]['mapped']['name']} ({linked[1]['mapped']['id']})",
            )
        elif mode == "category_single" and main_entity:
            display_label = _category_display_name((category_info or {}).get("label"))
            set_progress(
                run_id,
                "[Entity Mapping] Category request mapped: "
                f"{main_entity.get('name')} ({main_entity.get('id')}) with {display_label}",
            )
        elif len(linked) == 1:
            set_progress(
                run_id,
                "[Entity Mapping] Selected: "
                f"{linked[0]['mapped']['name']} ({linked[0]['mapped']['id']})",
            )

        log_details["entity_linking"] = {
            "candidates": candidates_all,
            "selected": linked,
            "mode": mode,
            "category": category_info,
        }

        if not main_entity and mode != "pair":
            set_progress(run_id, "[FINAL] Sorry, I could not confidently map entities. Please rephrase.")
            set_progress(run_id, "[DONE]")
            run_logger.log_pipeline_run(run_id, log_details)
            return

        # 3) Direct KG query
        if mode == "pair":
            set_progress(run_id, "[3/7] Querying eDISK graph for direct relations...")
        elif mode == "category_single":
            display_label = _category_display_name((category_info or {}).get("label"))
            set_progress(run_id, f"[3/7] Retrieving {display_label} linked in eDISK...")
        else:
            set_progress(run_id, "[3/7] Single-entity query: skipping direct relation lookup.")
        direct_result = []
        direct_query = {}
        if mode == "pair":
            e1 = linked[0]["mapped"]
            e2 = linked[1]["mapped"]
            t1 = _etype_norm(e1.get("type"))
            t2 = _etype_norm(e2.get("type"))

            rel_candidates = (
                    REL_TYPE_MAP.get((t1, t2))
                    or REL_TYPE_MAP.get((t2, t1))
                    or []
            )
            print(f"[DEBUG] Trying relation types for ({t1}, {t2}): {rel_candidates}")

            direct_query = {
                "cypher": neo4j_client.build_match_direct_any_relation_query(max_hops=1).strip(),
                "params": {"e1": e1.get("id"), "e2": e2.get("id")},
            }
            for rel_try in rel_candidates:
                try:
                    res = neo4j_client.match_direct_any_relation(e1.get("id"), e2.get("id"), max_hops=1)
                    if res:
                        print(f"[DEBUG] ✅ Found relation: {rel_try} ({len(res)} matches)")
                        direct_result = res
                        rel = rel_try
                        break
                except Exception as e:
                    print(f"[WARN] match_direct failed for {rel_try}: {e}")

        elif mode == "category_single" and main_entity:
            neighbor_label = (category_info or {}).get("label") or "DSI"
            direct_query = {
                "cypher": neo4j_client.build_top_connected_entities_query(neighbor_label).strip(),
                "params": {"target_id": main_entity.get("id"), "limit": 5},
                "neighbor_label": neighbor_label,
            }
            try:
                neighbors = neo4j_client.top_connected_entities(main_entity.get("id"), neighbor_label, topk=5)
                for entry in neighbors:
                    neighbor = entry.get("neighbor") or {}
                    if neighbor and "type" not in neighbor:
                        neighbor["type"] = neighbor_label
                    direct_result.append(
                        {
                            "target": main_entity,
                            "neighbor": neighbor,
                            "rel_info": entry.get("relations") or [],
                            "metrics": {
                                "relation_count": entry.get("relation_count"),
                                "best_score": entry.get("best_score"),
                            },
                            "category_label": neighbor_label,
                        }
                    )
            except Exception as e:
                print(f"[WARN] Failed to retrieve top {neighbor_label} neighbors: {e}")

        log_details["direct_query"] = direct_query
        log_details["direct_result"] = direct_result

        # 4) Context subgraphs
        set_progress(run_id, "[4/7] Extracting context subgraph...")
        context = {"mode": mode, "entities": []}
        context_logs = []
        try:
            if mode == "pair":
                for item in linked[:2]:
                    m = item["mapped"]
                    et = _etype_norm(m.get("type"))
                    sub = context_graph.one_two_hop_subgraph(m.get("id"), et)
                    if sub:
                        context["entities"].append({
                            "entity": m,
                            "context": sub,
                        })
                        context_logs.append({
                            "entity": m,
                            "queries": sub.get("queries"),
                            "one_hop": sub.get("one_hop"),
                            "two_hop": sub.get("two_hop"),
                        })
            else:
                if main_entity:
                    allowed_types = None
                    neighbor_label = None
                    normalized_neighbor_label = None
                    if mode == "category_single":
                        neighbor_label = (category_info or {}).get("label")
                        if neighbor_label:
                            normalized_neighbor_label = _etype_norm(neighbor_label)
                            allowed_types = [
                                normalized_neighbor_label or neighbor_label
                            ]
                    allowed_relations = None
                    if mode == "category_single":
                        head_type = _etype_norm(main_entity.get("type"))
                        if neighbor_label:
                            rel_candidates = []
                            rel_key_forward = (
                                (normalized_neighbor_label, head_type)
                                if normalized_neighbor_label
                                else None
                            )
                            rel_key_reverse = (
                                (head_type, normalized_neighbor_label)
                                if normalized_neighbor_label
                                else None
                            )
                            if rel_key_forward and all(rel_key_forward):
                                rel_candidates.extend(
                                    REL_TYPE_MAP.get(rel_key_forward) or []
                                )
                            if rel_key_reverse and all(rel_key_reverse):
                                rel_candidates.extend(
                                    REL_TYPE_MAP.get(rel_key_reverse) or []
                                )
                            if not rel_candidates and head_type and neighbor_label:
                                rel_candidates.extend(
                                    REL_TYPE_MAP.get((neighbor_label, head_type)) or []
                                )
                                rel_candidates.extend(
                                    REL_TYPE_MAP.get((head_type, neighbor_label)) or []
                                )
                            if rel_candidates:
                                seen = set()
                                ordered = []
                                for rel in rel_candidates:
                                    if rel and rel not in seen:
                                        seen.add(rel)
                                        ordered.append(rel)
                                if ordered:
                                    allowed_relations = ordered
                    if allowed_types is not None:
                        single_ctx = context_graph.single_entity_one_hop_context(
                            main_entity.get("id"),
                            allowed_types=allowed_types,
                            allowed_relations=allowed_relations,
                        )
                    else:
                        single_ctx = context_graph.single_entity_one_hop_context(
                            main_entity.get("id")
                        )
                    context["single_entity"] = {
                        "entity": main_entity,
                        "context": single_ctx,
                    }
                    context_logs.append({
                        "entity": main_entity,
                        "queries": single_ctx.get("queries"),
                        "neighbors": single_ctx.get("neighbors"),
                    })
        except Exception as exc:
            print(f"[WARN] Context extraction failed: {exc}")

        # Flatten highlights for the summariser
        highlights = []
        tips = []
        category_highlights = None
        if mode == "category_single" and main_entity:
            neighbor_label = (category_info or {}).get("label")
            if neighbor_label:
                display_label = _category_display_name(neighbor_label)
                focus_name = main_entity.get("name") or main_entity.get("id") or "the target"
                snippets = []
                for entry in direct_result:
                    if entry.get("category_label") != neighbor_label:
                        continue
                    neighbor = entry.get("neighbor") or {}
                    neighbor_name = neighbor.get("name") or neighbor.get("id")
                    if not neighbor_name:
                        continue
                    rel_types = []
                    for rel in entry.get("rel_info") or []:
                        rtype = rel.get("edge_type") or rel.get("type") or rel.get("relation")
                        if rtype and rtype not in rel_types:
                            rel_types.append(rtype)
                    metrics = entry.get("metrics") or {}
                    rel_count = metrics.get("relation_count")
                    detail_bits = []
                    if rel_types:
                        detail_bits.append(
                            " via " + ", ".join(rel_types[:2]) + ("…" if len(rel_types) > 2 else "")
                        )
                    if rel_count:
                        detail_bits.append(f" ({rel_count} edge{'s' if rel_count != 1 else ''})")
                    snippets.append(neighbor_name + "".join(detail_bits))
                if snippets:
                    category_highlights = [
                        f"Top {display_label} linked to {focus_name}: {', '.join(snippets[:3])}"
                    ]

        if mode == "pair":
            for ent in context.get("entities", []):
                ctx = ent.get("context", {})
                highlights.extend(ctx.get("highlights", []))
                tips.extend(ctx.get("tips", []))
        else:
            single_ctx = (context.get("single_entity") or {}).get("context", {})
            highlights.extend(single_ctx.get("highlights", []))
            tips.extend(single_ctx.get("tips", []))
        if category_highlights:
            highlights = category_highlights
            tips = []
        context["highlights"] = highlights[:5]
        context["tips"] = tips[:5]
        log_details["context"] = context_logs

        # 4.1) Node attribute lookup (background / descriptions)
        node_attributes = []
        try:
            for item in linked:
                mapped = item.get("mapped", {})
                if mapped.get("is_category"):
                    continue
                node_meta = neo4j_client.fetch_node_with_properties(mapped.get("id"))
                if node_meta and node_meta.get("properties"):
                    node_attributes.append({
                        "entity": mapped,
                        "labels": node_meta.get("labels", []),
                        "properties": node_meta.get("properties", {}),
                    })
        except Exception as exc:
            print(f"[WARN] Node attribute lookup failed: {exc}")

        log_details["node_attributes"] = node_attributes

        # 5) Reasoning (TransE LP)
        set_progress(run_id, "[5/7] Running TransE reasoning...")
        lp = {"per_entity": [], "backend": None}
        try:
            backend = reasoner.describe_backend()
            if backend:
                lp["backend"] = {"mode": backend.mode, "details": backend.details}

            for item in linked:
                mapped = item.get("mapped", {})
                head_id = mapped.get("id")
                head_type = mapped.get("type")
                if not head_id or mapped.get("is_category"):
                    continue
                target_types = reasoner.default_target_types(head_type)
                if mode == "category_single":
                    category_label = (category_info or {}).get("label")
                    if category_label:
                        normalized_label = reasoner.canonical_type(category_label) or category_label
                        target_types = [normalized_label]
                if not target_types:
                    continue

                preds = reasoner.predict_for_entity(head_id, head_type, target_types, topk=3)
                entry_backend = preds.get("backend")
                lp_entry = {
                    "entity": mapped,
                    "head_type": preds.get("head_type"),
                    "target_blocks": preds.get("predictions", []),
                    "backend": {
                        "mode": entry_backend.mode,
                        "details": entry_backend.details,
                    }
                    if entry_backend
                    else None,
                }
                lp["per_entity"].append(lp_entry)
        except Exception as exc:
            print(f"[WARN] Reasoning step failed: {exc}")

        log_details["link_prediction"] = lp

        # 6) Verification (find support paths for top predictions)
        set_progress(run_id, "[6/7] Validating inferred links...")
        verify = []
        try:
            pairs = []
            for block in lp.get("per_entity", []):
                entity = block.get("entity", {})
                head_id = entity.get("id")
                head_name = entity.get("name") or entity.get("text")
                for pred in block.get("target_blocks", []):
                    candidates = pred.get("candidates") or []
                    if not head_id or not candidates:
                        continue
                    top = candidates[0]
                    pairs.append(
                        {
                            "h_id": head_id,
                            "h_name": head_name,
                            "t_id": top.get("tail_id"),
                            "t_name": top.get("tail_name"),
                            "relation": pred.get("relation"),
                            "target_type": pred.get("target_type"),
                            "method": pred.get("method") or top.get("method"),
                            "notes": pred.get("notes"),
                        }
                    )

            for pair in pairs[:6]:
                if not pair.get("h_id") or not pair.get("t_id"):
                    continue
                head = {"id": pair.get("h_id"), "name": pair.get("h_name")}
                tail = {"id": pair.get("t_id"), "name": pair.get("t_name")}
                paths = verifier.find_support_paths(pair["h_id"], pair["t_id"], max_hops=3, k=3)
                direct_edges = verifier.find_direct_relations(pair["h_id"], pair["t_id"])
                combined_citations = []
                for collection in [paths, direct_edges]:
                    for item in collection or []:
                        for citation in item.get("citations", []) or []:
                            combined_citations.append(citation)
                external_refs = verifier.external_literature_lookup(
                    head,
                    tail,
                    pair.get("relation"),
                    combined_citations,
                )
                verify.append(
                    {
                        "predicted": {
                            "h_id": pair.get("h_id"),
                            "h_name": pair.get("h_name"),
                            "t_id": pair.get("t_id"),
                            "t_name": pair.get("t_name"),
                            "relation": pair.get("relation"),
                            "target_type": pair.get("target_type"),
                            "method": pair.get("method"),
                            "notes": pair.get("notes"),
                        },
                        "support_paths": paths,
                        "direct_relations": direct_edges,
                        "external_citations": external_refs,
                    }
                )
        except Exception as exc:
            print(f"[WARN] Verification step failed: {exc}")

        log_details["verification"] = verify

        # 7) Summarize
        set_progress(run_id, "[7/7] Generating final summary...")
        payload = {
            "question": user_query,
            "parsed": parsed,
            "linked": linked,
            "direct_result": direct_result,
            "context": context,
            "lp": lp,
            "verify": verify,
            "mode": mode,
            "node_attributes": node_attributes,
            "category_info": category_info,
        }
        answer = summarizer.summarize(payload)

        # The summarizer now stores parsed entity annotations on the payload
        entity_annotations = payload.get("_entity_annotations", [])

        try:
            run_logger.log_pipeline_run(run_id, log_details)
        except Exception as log_exc:
            print(f"[WARN] Failed to persist pipeline log: {log_exc}")

        # Build and emit graph data
        graph_data = _build_graph_data(linked, context, direct_result, mode)
        graph_data_json = json.dumps(graph_data, ensure_ascii=False, separators=(",", ":"))
        print(f"[DEBUG] graph_data entities: {graph_data['entities']}")
        print(f"[DEBUG] graph_data neighbors sample: {graph_data['neighbors'][:5]}")
        set_progress(run_id, f"[DATA]{graph_data_json}")

        # Emit entity annotations from the LLM's tagged output
        if entity_annotations:
            tags_json = json.dumps(entity_annotations, ensure_ascii=False, separators=(",", ":"))
            print(f"[DEBUG] entity_annotations: {len(entity_annotations)} tags")
            set_progress(run_id, f"[TAGS]{tags_json}")

        set_progress(run_id, f"[FINAL] {answer}")
        set_progress(run_id, "[DONE]")

    except Exception as e:
        import traceback
        set_progress(run_id, f"[ERROR] {e}")
        set_progress(run_id, "[DONE]")
        traceback.print_exc()
        try:
            run_logger.log_pipeline_run(run_id, log_details)
        except Exception:
            pass