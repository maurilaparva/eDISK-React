"""
_*_CODING:UTF-8_*_
@Author: Yu Hou
@File: summarizer.py
@Time: 10/16/25; 11:26 AM
"""
import json
import re
from .openai_client import chat

CATEGORY_DISPLAY_NAMES = {
    "DSI": "dietary supplement ingredients",
    "Drug": "drugs",
    "Disease": "diseases",
    "Gene": "genes",
    "Symptom": "symptoms",
}

# ─────────────────────────────────────────────
# Model override: use GPT-4o for the summarizer
# to get better instruction-following on entity tagging
# ─────────────────────────────────────────────

SUMMARIZER_MODEL = "gpt-4o"

# ─────────────────────────────────────────────
# System prompt: answer-first + separate JSON annotations
# ─────────────────────────────────────────────

SUMMARY_SYS = (
    "You are a biomedical knowledge graph assistant. "
    "Write a concise and fluent English summary integrating the eDISK AI Agent results.\n\n"
    "STRUCTURE YOUR ANSWER:\n"
    "1. State the mapped entities and IMMEDIATELY answer the user's question by reporting "
    "the direct relationship between them (if found) — include relation type and source.\n"
    "2. Optionally include 1 sentence of background ONLY if background data was provided.\n"
    "3. Briefly mention relevant context associations (1 sentence). NAME the specific entities.\n"
    "4. Briefly mention link prediction findings (1 sentence). NAME the specific predicted entities.\n"
    "5. Mention verification findings with PMID references (1 sentence).\n\n"
    "Keep it to 5–7 sentences. Avoid long paragraphs. "
    "Cite verification references (PMID, DOI) verbatim. "
    "If no background information exists, omit it — do not say it is unavailable.\n\n"
    "CRITICAL — ENTITY TAGGING INSTRUCTIONS:\n"
    "After your prose answer, on a new line, write exactly:\n"
    "---ENTITIES---\n"
    "Then output a JSON array listing EVERY biomedical entity you mentioned in your answer. "
    "Each entry must have: {\"text\": \"exact words used in your answer\", \"kg_id\": \"eDISK_ID from the data\", \"type\": \"DSI|Disease|Drug|Gene|Symptom\"}\n\n"
    "TAGGING RULES (follow these strictly):\n"
    "- You MUST tag EVERY biomedical entity you mention — not just the primary two.\n"
    "- This includes: primary mapped entities, context neighbors (diseases, genes, drugs mentioned "
    "in context associations), link prediction candidates, and any other biomedical entities in your prose.\n"
    "- \"text\" must match EXACTLY how you wrote the entity in your prose (same casing, same words).\n"
    "- Use the eDISK_ID from the Entity Reference list. Use \"NONE\" if no ID was provided.\n"
    "- Do NOT skip entities just because you don't have their eDISK_ID — use \"NONE\" instead.\n"
    "- Do NOT include generic category words (\"diseases\", \"drugs\") or sources (\"MSKCC\", PMIDs).\n"
    "- Do NOT include entities you did not actually mention in the prose.\n"
    "- If you mention \"Alzheimer's disease\", \"inflammation\", \"insomnia\", drug names, gene names, "
    "etc. in your prose, they MUST appear in the JSON array.\n\n"
    "COMPLETE EXAMPLE:\n"
    "The mapped entities are Ginkgo and memory loss. In eDISK, Ginkgo is effective for memory loss "
    "(Source: MSKCC). Ginkgo biloba is known for its medicinal properties in traditional Chinese medicine. "
    "Contextually, Ginkgo is associated with inflammation, Alzheimer's disease, and hypertension. "
    "Link prediction indicates Ginkgo may also be effective for insomnia and interacts with warfarin. "
    "Verification supports the Ginkgo–memory loss relationship (PMID: 17110111, 24054487).\n"
    "---ENTITIES---\n"
    "["
    '{\"text\": \"Ginkgo\", \"kg_id\": \"DSI000108\", \"type\": \"DSI\"}, '
    '{\"text\": \"memory loss\", \"kg_id\": \"DIS000134\", \"type\": \"Disease\"}, '
    '{\"text\": \"Ginkgo biloba\", \"kg_id\": \"DSI000108\", \"type\": \"DSI\"}, '
    '{\"text\": \"inflammation\", \"kg_id\": \"DIS000045\", \"type\": \"Disease\"}, '
    '{\"text\": \"Alzheimer\\\'s disease\", \"kg_id\": \"DIS000012\", \"type\": \"Disease\"}, '
    '{\"text\": \"hypertension\", \"kg_id\": \"DIS000078\", \"type\": \"Disease\"}, '
    '{\"text\": \"insomnia\", \"kg_id\": \"NONE\", \"type\": \"Disease\"}, '
    '{\"text\": \"warfarin\", \"kg_id\": \"NONE\", \"type\": \"Drug\"}'
    "]\n\n"
    "Notice: EVERY disease, drug, gene, supplement mentioned in the prose is tagged — "
    "not just the two primary entities. This is mandatory."
)


def _truncate(txt: str, limit: int = 180) -> str:
    if not txt:
        return ""
    if len(txt) <= limit:
        return txt.strip()
    return (txt[:limit].rstrip() + "…").strip()


def _walk_find_backgrounds(obj):
    results = []

    def _search(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if isinstance(k, str) and k.lower() == "background" and isinstance(v, str) and v.strip():
                    results.append(v.strip())
                else:
                    _search(v)
        elif isinstance(x, list):
            for item in x:
                _search(item)

    _search(obj)
    return results


def _is_textual(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and value.strip():
        return True
    if isinstance(value, (int, float)):
        return True
    return False


def _format_node_attributes(node_attrs) -> str:
    if not node_attrs:
        return ""

    priority_keys = [
        "background",
        "mechanism_of_action",
        "mechanism",
        "source_material",
        "function",
        "indications",
        "uses",
        "description",
        "summary",
    ]

    lines = []
    for entry in node_attrs:
        entity = entry.get("entity", {}) if isinstance(entry, dict) else {}
        props = entry.get("properties", {}) if isinstance(entry, dict) else {}
        if not isinstance(props, dict) or not props:
            continue
        ent_name = (
                entity.get("name")
                or entity.get("text")
                or entity.get("id")
                or "Entity"
        )
        used_keys = set()
        details = []

        for key in priority_keys:
            for actual_key, value in props.items():
                if actual_key in used_keys:
                    continue
                if isinstance(actual_key, str) and actual_key.lower() == key and _is_textual(value):
                    label = actual_key.replace("_", " ").capitalize()
                    details.append(f"{label}: {_truncate(str(value), 220)}")
                    used_keys.add(actual_key)
                    break

        if len(details) < 2:
            for actual_key, value in props.items():
                if len(details) >= 3:
                    break
                if actual_key in used_keys:
                    continue
                if not isinstance(actual_key, str) or not _is_textual(value):
                    continue
                label = actual_key.replace("_", " ").capitalize()
                details.append(f"{label}: {_truncate(str(value), 160)}")
                used_keys.add(actual_key)

        if details:
            lines.append(f"{ent_name}: {'; '.join(details[:3])}")

    return "\n".join(lines) if lines else ""


def _format_citation_snippet(citations) -> str:
    if not citations:
        return ""

    grouped = {}
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        ctype = str(citation.get("type") or "Reference").strip() or "Reference"
        value = str(citation.get("value") or "").strip()
        if not value:
            continue
        meta_bits = []
        title = citation.get("title")
        journal = citation.get("journal")
        year = citation.get("year")
        url = citation.get("url")
        if isinstance(title, str) and title.strip():
            meta_bits.append(_truncate(title.strip(), 80))
        if isinstance(journal, str) and journal.strip():
            meta_bits.append(journal.strip())
        if year:
            meta_bits.append(str(year))
        if isinstance(url, str) and url.strip():
            meta_bits.append(url.strip())
        entry = value
        if meta_bits:
            entry = f"{entry} ({'; '.join(meta_bits[:3])})"
        bucket = grouped.setdefault(ctype.upper(), [])
        if entry not in bucket:
            bucket.append(entry)

    if not grouped:
        return ""

    parts = []
    for ctype, values in grouped.items():
        limited = values[:5]
        parts.append(f"{ctype}: {', '.join(limited)}")

    return "; ".join(parts)


# ─────────────────────────────────────────────
# Parse the LLM output: split prose from JSON annotations
# ─────────────────────────────────────────────

_ENTITY_SEPARATOR = "---ENTITIES---"


def _parse_response_with_annotations(raw_text: str):
    """
    Split the LLM response into clean prose and a JSON entity list.

    Expected format:
        <prose text>
        ---ENTITIES---
        [{"text": "...", "kg_id": "...", "type": "..."}, ...]

    Returns:
        clean_text: str — just the prose
        annotations: list[dict] — parsed entity annotations
    """
    if not raw_text:
        return "", []

    # Split on the separator
    if _ENTITY_SEPARATOR in raw_text:
        parts = raw_text.split(_ENTITY_SEPARATOR, 1)
        prose = parts[0].strip()
        json_part = parts[1].strip() if len(parts) > 1 else ""
    else:
        # No separator found — the model didn't follow instructions
        # Try to find a JSON array at the end
        prose = raw_text.strip()
        json_part = ""
        # Look for trailing JSON array
        match = re.search(r'\[\s*\{.*\}\s*\]\s*$', prose, re.DOTALL)
        if match:
            json_part = match.group(0)
            prose = prose[:match.start()].strip()

    # Parse the JSON annotations
    annotations = []
    if json_part:
        # Clean up common issues
        json_part = json_part.strip()
        # Remove markdown code fences if present
        json_part = re.sub(r'^```json\s*', '', json_part)
        json_part = re.sub(r'^```\s*', '', json_part)
        json_part = re.sub(r'\s*```$', '', json_part)
        json_part = json_part.strip()

        try:
            parsed = json.loads(json_part)
            if isinstance(parsed, list):
                for item in parsed:
                    if not isinstance(item, dict):
                        continue
                    text = (item.get("text") or "").strip()
                    kg_id = (item.get("kg_id") or "NONE").strip()
                    etype = (item.get("type") or "Entity").strip()
                    if text and len(text) >= 2:
                        annotations.append({
                            "text": text,
                            "kg_id": kg_id,
                            "type": etype,
                        })
        except (json.JSONDecodeError, TypeError) as e:
            print(f"[WARN] Failed to parse entity annotations JSON: {e}")
            print(f"[WARN] JSON part was: {json_part[:200]}")

    # Deduplicate annotations (keep first occurrence)
    seen = set()
    unique = []
    for a in annotations:
        key = a["text"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(a)
    annotations = unique

    # Clean any stray brackets or malformed tags from the prose
    # (safety net in case the model mixed approaches)
    prose = re.sub(r'\[\[([^|\]]+?)(?:\|\|[^|\]]*)*\]\]', r'\1', prose)

    return prose, annotations


# ─────────────────────────────────────────────
# Post-processing: catch entities the LLM missed
# ─────────────────────────────────────────────

def _build_reference_lookup(payload):
    """
    Build a list of all known entities with their IDs, names, and types
    from the pipeline payload for use in fallback tagging.
    """
    refs = []
    seen_ids = set()

    def _add(name, eid, etype):
        if not name or not eid:
            return
        if eid in seen_ids:
            return
        seen_ids.add(eid)
        refs.append({"name": name, "id": eid, "type": etype or "Entity"})

    # Primary linked entities
    for item in payload.get("linked", []):
        mapped = (item or {}).get("mapped", {})
        if mapped.get("is_category"):
            continue
        _add(mapped.get("name"), mapped.get("id"), mapped.get("type"))

    # Context neighbors (one-hop)
    context = payload.get("context", {})
    for ent_ctx in context.get("entities", []):
        ctx = ent_ctx.get("context", {})
        for hop in (ctx.get("one_hop") or []):
            name = hop.get("neighbor_display_name") or hop.get("neighbor_name")
            _add(name, hop.get("neighbor_id"), hop.get("neighbor_type"))

    # Single-entity context neighbors
    single = context.get("single_entity", {})
    single_ctx = single.get("context", {})
    for hop in (single_ctx.get("neighbors") or []):
        name = hop.get("neighbor_display_name") or hop.get("neighbor_name")
        _add(name, hop.get("neighbor_id"), hop.get("neighbor_type"))

    # Link prediction candidates
    for block in (payload.get("lp", {}).get("per_entity", []) or []):
        for target in (block.get("target_blocks", []) or []):
            for cand in (target.get("candidates") or [])[:5]:
                _add(cand.get("tail_name"), cand.get("tail_id"), cand.get("tail_type"))

    # Verification entities
    for item in (payload.get("verify", []) or []):
        pred = item.get("predicted", {})
        _add(pred.get("h_name"), pred.get("h_id"), None)
        _add(pred.get("t_name"), pred.get("t_id"), None)

    # Category neighbors (direct_result in category mode)
    for item in (payload.get("direct_result", []) or []):
        neighbor = item.get("neighbor") or {}
        _add(neighbor.get("name"), neighbor.get("id"), neighbor.get("type"))

    return refs


def _postprocess_annotations(prose, annotations, payload):
    """
    Cross-reference the prose against known entities from the pipeline payload.
    If an entity name appears in the prose but is NOT in the annotations list,
    add it as a fallback annotation.
    """
    if not prose:
        return annotations

    ref_lookup = _build_reference_lookup(payload)
    if not ref_lookup:
        return annotations

    prose_lower = prose.lower()

    # Build set of already-tagged text (lowercase)
    tagged_texts = set()
    tagged_ids = set()
    for ann in annotations:
        tagged_texts.add(ann["text"].lower())
        if ann.get("kg_id") and ann["kg_id"] != "NONE":
            tagged_ids.add(ann["kg_id"])

    # Skip very short or generic names that would cause false positives
    SKIP_NAMES = {
        "the", "a", "an", "is", "are", "was", "were", "has", "have",
        "unknown", "none", "n/a", "na", "entity", "target",
    }

    new_annotations = list(annotations)

    # Sort by name length descending to match longer names first
    ref_lookup_sorted = sorted(ref_lookup, key=lambda r: len(r.get("name") or ""), reverse=True)

    for ref in ref_lookup_sorted:
        name = ref.get("name", "").strip()
        eid = ref.get("id", "")
        etype = ref.get("type", "Entity")

        if not name or len(name) < 3:
            continue
        if name.lower() in SKIP_NAMES:
            continue
        if name.lower() in tagged_texts:
            continue
        if eid in tagged_ids:
            continue

        # Check if this entity name appears in the prose
        # Use word-boundary-aware matching to avoid partial matches
        # e.g., "war" shouldn't match inside "warfarin"
        pattern = re.compile(r'\b' + re.escape(name) + r'\b', re.IGNORECASE)
        match = pattern.search(prose)
        if match:
            # Use the exact text as it appears in the prose
            exact_text = match.group(0)
            new_annotations.append({
                "text": exact_text,
                "kg_id": eid,
                "type": etype,
            })
            tagged_texts.add(exact_text.lower())
            tagged_ids.add(eid)

    return new_annotations


def _build_entity_reference_block(payload):
    refs = []
    seen_ids = set()

    for item in payload.get("linked", []):
        mapped = (item or {}).get("mapped", {})
        if mapped.get("is_category"):
            continue
        eid = mapped.get("id")
        if eid and eid not in seen_ids:
            seen_ids.add(eid)
            refs.append(f"  - {mapped.get('name', eid)} | id={eid} | type={mapped.get('type', 'Entity')}")

    context = payload.get("context", {})
    for ent_ctx in context.get("entities", []):
        ctx = ent_ctx.get("context", {})
        for hop in (ctx.get("one_hop") or []):
            nid = hop.get("neighbor_id")
            nname = hop.get("neighbor_display_name") or hop.get("neighbor_name")
            ntype = hop.get("neighbor_type")
            if nid and nid not in seen_ids and nname:
                seen_ids.add(nid)
                refs.append(f"  - {nname} | id={nid} | type={ntype or 'Entity'}")

    single = context.get("single_entity", {})
    single_ctx = single.get("context", {})
    for hop in (single_ctx.get("neighbors") or []):
        nid = hop.get("neighbor_id")
        nname = hop.get("neighbor_display_name") or hop.get("neighbor_name")
        ntype = hop.get("neighbor_type")
        if nid and nid not in seen_ids and nname:
            seen_ids.add(nid)
            refs.append(f"  - {nname} | id={nid} | type={ntype or 'Entity'}")

    for block in (payload.get("lp", {}).get("per_entity", []) or []):
        for target in (block.get("target_blocks", []) or []):
            for cand in (target.get("candidates") or [])[:3]:
                tid = cand.get("tail_id")
                tname = cand.get("tail_name")
                ttype = cand.get("tail_type")
                if tid and tid not in seen_ids and tname:
                    seen_ids.add(tid)
                    refs.append(f"  - {tname} | id={tid} | type={ttype or 'Entity'}")

    for item in (payload.get("verify", []) or []):
        pred = item.get("predicted", {})
        for prefix in ["h", "t"]:
            eid = pred.get(f"{prefix}_id")
            ename = pred.get(f"{prefix}_name")
            if eid and eid not in seen_ids and ename:
                seen_ids.add(eid)
                refs.append(f"  - {ename} | id={eid} | type=Entity")

    if not refs:
        return ""

    return "=== Entity Reference (use these IDs in the JSON) ===\n" + "\n".join(refs[:50]) + "\n\n"


def summarize(payload: dict) -> str:
    """
    Produce a summary with separate entity annotations.
    Side effect: sets payload['_entity_annotations'] with the structured tags.
    """
    # === 1. Entity mapping ===
    linked = payload.get("linked", [])
    ent_bits = []
    for e in linked:
        _in = (e or {}).get("input", {})
        _m = (e or {}).get("mapped", {})
        ent_bits.append(
            f"{_in.get('text', 'N/A')} → {_m.get('name', 'N/A')} ({_m.get('id', 'N/A')}, type={_m.get('type', 'N/A')})"
        )
    entities_summary = "; ".join(ent_bits) if ent_bits else "No entities mapped."

    # === 2. Background ===
    brief_backgrounds = []
    bg_list = _walk_find_backgrounds(payload.get("direct_result", []))
    bg_list.extend(_walk_find_backgrounds(payload.get("node_attributes", [])))
    for bg in bg_list:
        short = _truncate(bg, 200)
        brief_backgrounds.append(short)
    background_text = (
        "\n".join([f"- {b}" for b in brief_backgrounds[:3]])
        if brief_backgrounds else ""
    )

    # === 2b. Node attributes ===
    node_attr_summary = _format_node_attributes(payload.get("node_attributes"))

    # === 3. Direct relationship ===
    direct_relations = []
    for item in payload.get("direct_result", []) or []:
        for rel in item.get("rel_info", []) or []:
            props = rel.get("properties", {}) or {}
            rel_type = props.get("Type") or rel.get("edge_type") or "UNKNOWN_RELATION"
            source = props.get("Source") or props.get("source") or "Unknown"
            direct_relations.append(f"{rel_type} (Source: {source})")

    mode = payload.get("mode") or ("pair" if len(linked) >= 2 else "single")
    category_info = payload.get("category_info") or {}

    # Get entity names for pair mode
    e1_name = None
    e2_name = None
    if mode == "pair" and len(linked) >= 2:
        m1 = (linked[0] or {}).get("mapped", {})
        m2 = (linked[1] or {}).get("mapped", {})
        e1_name = m1.get("name") or m1.get("id") or "Entity 1"
        e2_name = m2.get("name") or m2.get("id") or "Entity 2"

    if mode == "category_single":
        target_entity = None
        for ent in linked:
            mapped = (ent or {}).get("mapped") or {}
            if mapped.get("is_category"):
                continue
            if mapped.get("id"):
                target_entity = mapped
                break
        target_name = (target_entity or {}).get("name") or (target_entity or {}).get("id") or "the target entity"
        category_label = category_info.get("label") or (linked[0].get("mapped", {}).get("type") if linked else None)
        display_name = category_info.get("display") or CATEGORY_DISPLAY_NAMES.get(category_label, (category_label or "category entities").lower())
        category_terms = category_info.get("inputs") or []
        first_term = category_terms[0] if category_terms else None
        header = f"Top {display_name}"
        if first_term and first_term.lower() not in display_name.lower():
            header += f" (parsed from \"{first_term}\")"
        neighbor_summaries = []
        for item in payload.get("direct_result", []) or []:
            neighbor = item.get("neighbor") or {}
            neighbor_name = neighbor.get("name") or neighbor.get("id")
            rels = item.get("rel_info") or []
            rel_types = []
            for rel in rels:
                rtype = rel.get("edge_type")
                if rtype and rtype not in rel_types:
                    rel_types.append(rtype)
            snippet = None
            if neighbor_name:
                snippet = neighbor_name
                if rel_types:
                    snippet += f" ({', '.join(rel_types)})"
                metrics = item.get("metrics") or {}
                count = metrics.get("relation_count")
                if count:
                    try:
                        count_int = int(count)
                    except Exception:
                        count_int = None
                    if count_int:
                        snippet += f" – {count_int} link(s)"
            if snippet:
                neighbor_summaries.append(snippet)
        if neighbor_summaries:
            direct_summary = (
                    f"{header} linked to {target_name}: "
                    + "; ".join(neighbor_summaries[:5])
                    + "."
            )
        else:
            direct_summary = (
                f"No connections to {display_name} were found for {target_name} in eDISK."
            )
    elif direct_relations:
        if e1_name and e2_name:
            direct_summary = (
                f"Direct relationship between {e1_name} and {e2_name} in eDISK: "
                f"{', '.join(direct_relations)}."
            )
        else:
            direct_summary = f"Direct relationship(s) found in eDISK: {', '.join(direct_relations)}."
    else:
        if mode == "single":
            direct_summary = "Direct relationship lookup was skipped because only one entity was provided."
        elif e1_name and e2_name:
            direct_summary = f"No direct relationship found between {e1_name} and {e2_name} in eDISK."
        else:
            direct_summary = "No direct relationship found between the mapped entities in eDISK."

    # === 4. Context ===
    context = payload.get("context", {})
    context_highlights = context.get("highlights") or []
    if context_highlights:
        context_summary = "Context highlights: " + "; ".join(context_highlights[:3]) + "."
    else:
        if mode == "single":
            context_summary = "No first-hop context was retrieved for the single entity."
        else:
            context_summary = "Context highlights were not retrieved."

    # === 5. Link prediction ===
    lp = payload.get("lp", {})
    lp_bits = []
    for block in lp.get("per_entity", []) or []:
        ent = block.get("entity", {}) or {}
        ent_name = ent.get("name") or ent.get("text") or ent.get("id") or "Mapped entity"
        ent_type = block.get("head_type") or ent.get("type") or "Entity"
        targets = []
        for target in block.get("target_blocks", []) or []:
            candidates = target.get("candidates") or []
            if not candidates:
                continue
            label = target.get("target_type") or "Entity"
            relation = target.get("relation") or "related_to"
            method = target.get("method") or (candidates[0].get("method")) or "heuristic"
            desc = []
            for cand in candidates[:3]:
                name = cand.get("tail_name") or cand.get("tail_id") or "Unknown"
                score = cand.get("score")
                if score is not None:
                    try:
                        score_txt = f"{float(score):.2f}"
                    except Exception:
                        score_txt = str(score)
                    snippet = f"{name} (score {score_txt})"
                else:
                    snippet = name
                explanation = cand.get("explanation")
                if explanation:
                    snippet += f" via {explanation}"
                desc.append(snippet)
            notes = target.get("notes")
            text = f"{label} ({relation}, {method}): {', '.join(desc)}"
            if notes:
                text += f" [{notes}]"
            targets.append(text)
        if targets:
            lp_bits.append(f"For {ent_name} ({ent_type}): " + "; ".join(targets))

    backend = lp.get("backend")
    if lp_bits:
        suffix = ""
        if backend:
            suffix = f" Backend: {backend.get('mode')} ({backend.get('details')})."
        lp_summary = "Link prediction insights: " + " | ".join(lp_bits) + "." + suffix
    else:
        lp_summary = "Link prediction did not return additional candidates."

    # === 6. Verification ===
    verify = payload.get("verify") or []
    verify_bits = []
    verification_citations = []
    verification_seen = set()
    for item in verify:
        pred = item.get("predicted", {})
        paths = item.get("support_paths") or []
        direct_edges = item.get("direct_relations") or []
        external_refs = item.get("external_citations") or []
        h_name = pred.get("h_name") or pred.get("h_id") or "Head"
        t_name = pred.get("t_name") or pred.get("t_id") or "Tail"
        relation = pred.get("relation") or "related_to"
        if paths or direct_edges:
            first = paths[0] if paths else {}
            summary = first.get("summary") or ("multi-hop path" if paths else "direct edge evaluation")
            evidence = first.get("evidence", []) if paths else []
            citations = []
            seen = set()

            def _ingest(collection):
                for entry in collection or []:
                    for citation in entry.get("citations", []) or []:
                        key = (citation.get("type"), citation.get("value"))
                        if key in seen:
                            continue
                        seen.add(key)
                        citations.append(citation)

            _ingest(paths)
            _ingest(direct_edges)
            ext_dedup = []
            if isinstance(external_refs, list):
                for ext in external_refs:
                    if not isinstance(ext, dict):
                        continue
                    key = (ext.get("type"), ext.get("value"))
                    if key in seen:
                        continue
                    seen.add(key)
                    ext_dedup.append(ext)

            snippet = f"{h_name} → {t_name} ({relation})"
            if direct_edges:
                rel_desc = []
                for edge in direct_edges[:2]:
                    etype = edge.get("type") or "relation"
                    edge_ev = edge.get("evidence", [])
                    if edge_ev:
                        rel_desc.append(f"{etype} [{'; '.join(edge_ev[:2])}]")
                    else:
                        rel_desc.append(etype)
                snippet += " direct edge(s): " + "; ".join(rel_desc)
            if summary:
                snippet += f"; support path {summary}"
            if evidence:
                snippet += f" (evidence: {', '.join(evidence[:2])})"
            citation_text = _format_citation_snippet(citations)
            if citation_text:
                snippet += f" [references: {citation_text}]"
                for citation in citations:
                    key = (citation.get("type"), citation.get("value"))
                    if key in verification_seen:
                        continue
                    verification_seen.add(key)
                    verification_citations.append(citation)
            if ext_dedup:
                ext_text = _format_citation_snippet(ext_dedup)
                if ext_text:
                    snippet += f" [PubMed search: {ext_text}]"
                for ext in ext_dedup:
                    key = (ext.get("type"), ext.get("value"))
                    if key in verification_seen:
                        continue
                    verification_seen.add(key)
                    verification_citations.append(ext)
            verify_bits.append(snippet)
        else:
            verify_bits.append(f"{h_name} → {t_name} ({relation}) had no supporting path within three hops.")

    if verify_bits:
        verify_summary = "Verification results: " + " ; ".join(verify_bits) + "."
    else:
        verify_summary = "Verification could not identify supporting evidence for the predictions."

    verification_citations_text = _format_citation_snippet(verification_citations)

    # === 7. Entity reference block ===
    entity_ref_block = _build_entity_reference_block(payload)

    # === 8. Assemble prompt ===
    user_question = payload.get("question", "")

    user_sections = [
        entity_ref_block,
        f"=== User Question ===\n{user_question}\n\n",
        f"=== Entities Mapped ===\n{entities_summary}\n\n",
    ]
    if background_text:
        user_sections.append(f"=== Background Information ===\n{background_text}\n\n")
    if node_attr_summary:
        user_sections.append(f"=== Node Attributes ===\n{node_attr_summary}\n\n")
    user_sections.extend([
        f"=== Direct Relationship ===\n{direct_summary}\n\n",
        f"=== Context ===\n{context_summary}\n\n",
        f"=== Link Prediction ===\n{lp_summary}\n\n",
        f"=== Verification ===\n{verify_summary}\n\n",
    ])
    if verification_citations_text:
        user_sections.append(f"Verification references: {verification_citations_text}\n\n")
    user_sections.append(
        "Now write your response: first the prose answer (5-7 sentences, answer the question first), "
        "then ---ENTITIES--- followed by the JSON array.\n\n"
        "REMINDER: The JSON array MUST include EVERY biomedical entity (disease, drug, gene, supplement, symptom) "
        "you mention in the prose — not just the two primary entities. "
        "If you mention inflammation, Alzheimer's, insomnia, warfarin, or ANY other entity in your prose, "
        "it MUST be in the JSON. Use \"NONE\" for kg_id if you don't have the eDISK ID."
    )
    user = "".join(user_sections)

    raw_answer = chat(
        [
            {"role": "system", "content": SUMMARY_SYS},
            {"role": "user", "content": user}
        ],
        model=SUMMARIZER_MODEL,
        temperature=0.1
    )

    # Parse: split prose from JSON annotations
    clean_answer, annotations = _parse_response_with_annotations(raw_answer)

    # Post-processing: catch entities the LLM missed by cross-referencing
    # the prose against known entities from the pipeline payload
    annotations = _postprocess_annotations(clean_answer, annotations, payload)

    if verification_citations_text:
        clean_answer = clean_answer.rstrip() + "\n\nVerification references: " + verification_citations_text

    # Store annotations on the payload so the orchestrator can access them
    payload['_entity_annotations'] = annotations

    return clean_answer