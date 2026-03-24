"""
_*_CODING:UTF-8_*_
@Author: Yu Hou
@File: verifier.py
@Time: 10/16/25; 11:26 AM
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import requests

from .neo4j_client import run_cypher


def _format_relation(rel: Dict[str, Any]) -> Dict[str, Any]:
    props = rel.get("properties", {})
    evidence: List[str] = []
    citations: List[Dict[str, Any]] = []

    def _record_citation(kind: str, raw_value: Any):
        if raw_value is None:
            return

        values: Iterable[str]
        if isinstance(raw_value, (list, tuple, set)):
            values = [str(v).strip() for v in raw_value]
        else:
            text = str(raw_value).strip()
            if not text:
                return
            if ";" in text:
                values = [v.strip() for v in text.split(";")]
            elif "," in text and kind != "DOI":
                # Avoid splitting DOIs on commas.
                values = [v.strip() for v in text.split(",")]
            else:
                values = [text]

        for value in values:
            if not value:
                continue
            citations.append({"type": kind, "value": value})

    for key, val in props.items():
        if not isinstance(key, str):
            continue
        if isinstance(val, (str, int, float)) and str(val).strip():
            evidence.append(f"{key}: {val}")

        lower = key.lower()
        if lower in {"pmid", "pubmed_id", "pubmedid"}:
            _record_citation("PMID", val)
        elif lower in {"pmcid", "pmc_id", "pmcid_id"}:
            _record_citation("PMCID", val)
        elif lower in {"doi", "digital_object_identifier"}:
            _record_citation("DOI", val)
        elif lower in {"clinical_trial", "nct", "nct_id"}:
            _record_citation("ClinicalTrial", val)

    return {
        "type": rel.get("type"),
        "properties": props,
        "evidence": evidence,
        "citations": citations,
    }


def find_support_paths(h_id: str, t_id: str, max_hops: int = 3, k: int = 3) -> List[Dict[str, Any]]:
    """
    Retrieve up to *k* the shortest paths between two entities and flatten them into JSON
    structures. Each path contains nodes, relations, and extracted evidence snippets so the
    summariser can highlight concrete references.
    """
    cypher = f"""
    MATCH p=allShortestPaths((h {{eDISK_ID:$h}})-[*..{max_hops}]-(t {{eDISK_ID:$t}}))
    WITH nodes(p) AS ns, relationships(p) AS rs
    RETURN [i IN range(0, size(ns)-1) | {{
                node: {{
                    id: coalesce(ns[i].eDISK_ID, ns[i].id, ns[i].ID),
                    name: coalesce(ns[i].Name, ns[i].name, ns[i].Symbol, ns[i].Label, ns[i].eDISK_ID),
                    labels: labels(ns[i])
                }},
                relation: CASE WHEN i < size(rs)
                    THEN {{
                        type: type(rs[i]),
                        properties: properties(rs[i])
                    }}
                    ELSE NULL END
            }}] AS segments
    LIMIT $limit
    """
    rows = run_cypher(cypher, {"h": h_id, "t": t_id, "limit": k})
    paths: List[Dict[str, Any]] = []

    for row in rows:
        segments = row.get("segments", []) if isinstance(row, dict) else []
        nodes: List[Dict[str, Any]] = []
        rels: List[Dict[str, Any]] = []
        summary_bits: List[str] = []

        for seg in segments:
            node = seg.get("node", {})
            rel = seg.get("relation")

            formatted_node = {
                "id": node.get("id"),
                "name": node.get("name"),
                "labels": node.get("labels", []),
            }
            nodes.append(formatted_node)

            if rel:
                formatted_rel = _format_relation(rel)
                rels.append(formatted_rel)
                if formatted_node.get("name") and formatted_rel.get("type"):
                    summary_bits.append(f"-{formatted_rel['type']}→ {formatted_node['name']}")

        if not nodes:
            continue

        summary = " ".join(summary_bits)
        evidence: List[str] = []
        citations: List[Dict[str, Any]] = []
        seen_citations: Set[Tuple[Any, Any]] = set()
        for rel in rels:
            evidence.extend(rel.get("evidence", []))
            for citation in rel.get("citations", []) or []:
                key = (citation.get("type"), citation.get("value"))
                if key in seen_citations:
                    continue
                seen_citations.add(key)
                citations.append(citation)

        paths.append(
            {
                "nodes": nodes,
                "relations": rels,
                "summary": summary.strip(),
                "evidence": evidence[:5],
                "citations": citations,
            }
        )

    return paths


def find_direct_relations(h_id: str, t_id: str) -> List[Dict[str, Any]]:
    """Fetch direct edges (both directions) between two nodes."""
    cypher = """
    MATCH (h {eDISK_ID:$h})-[rel]-(t {eDISK_ID:$t})
    RETURN type(rel) AS type, properties(rel) AS properties
    """
    rows = run_cypher(cypher, {"h": h_id, "t": t_id})
    formatted: List[Dict[str, Any]] = []
    for row in rows or []:
        rel = {"type": row.get("type"), "properties": row.get("properties", {})}
        formatted.append(_format_relation(rel))
    return formatted


def _collect_existing_keys(citations: Iterable[Dict[str, Any]]) -> Set[Tuple[Any, Any]]:
    keys: Set[Tuple[Any, Any]] = set()
    for citation in citations or []:
        if not isinstance(citation, dict):
            continue
        key = (citation.get("type"), citation.get("value"))
        if key[0] and key[1]:
            keys.add(key)
    return keys


def _pubmed_lookup(term: str, retmax: int = 3) -> List[Dict[str, Any]]:
    """Query the PubMed E-utilities API to retrieve summaries for a search term."""
    if not term:
        return []

    search_params = {
        "db": "pubmed",
        "term": term,
        "retmode": "json",
        "retmax": retmax,
        "sort": "relevance",
    }

    try:
        search_resp = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params=search_params,
            timeout=10,
        )
        search_resp.raise_for_status()
        ids = (search_resp.json().get("esearchresult", {}) or {}).get("idlist", [])
    except Exception as exc:
        print(f"[WARN] PubMed search failed for term '{term}': {exc}")
        return []

    if not ids:
        return []

    try:
        summary_resp = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
            params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
            timeout=10,
        )
        summary_resp.raise_for_status()
        summary_json = summary_resp.json().get("result", {}) or {}
    except Exception as exc:
        print(f"[WARN] PubMed summary fetch failed for ids {ids}: {exc}")
        return []

    results: List[Dict[str, Any]] = []
    for pmid in ids:
        doc = summary_json.get(pmid)
        if not doc:
            continue
        title = (doc.get("title") or "").strip()
        journal = (doc.get("fulljournalname") or doc.get("source") or "").strip()
        pubdate = (doc.get("pubdate") or "").strip()
        citation = {
            "type": "PMID",
            "value": pmid,
            "title": title,
            "journal": journal,
            "year": pubdate.split(" ")[0] if pubdate else None,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        }
        results.append(citation)

    return results


def external_literature_lookup(
        head: Dict[str, Any],
        tail: Dict[str, Any],
        relation: Optional[str],
        existing: Iterable[Dict[str, Any]],
        max_results: int = 3,
) -> List[Dict[str, Any]]:
    """Use public PubMed APIs to enrich verification citations."""

    existing_keys = _collect_existing_keys(existing)
    if any(kind == "PMID" for kind, _ in existing_keys):
        # Already have PubMed references.
        return []

    terms = []
    head_name = head.get("name") or head.get("id")
    tail_name = tail.get("name") or tail.get("id")
    if head_name:
        terms.append(head_name)
    if relation:
        terms.append(relation.replace("_", " "))
    if tail_name:
        terms.append(tail_name)
    term = " ".join(terms).strip()
    if not term:
        return []

    candidates = _pubmed_lookup(term, retmax=max_results)
    filtered: List[Dict[str, Any]] = []
    for cand in candidates:
        key = (cand.get("type"), cand.get("value"))
        if not key[0] or not key[1] or key in existing_keys:
            continue
        filtered.append(cand)
    return filtered
