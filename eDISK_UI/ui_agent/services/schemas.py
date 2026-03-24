"""
_*_CODING:UTF-8_*_
@Author: Yu Hou
@File: schemas.py
@Time: 10/16/25; 9:18 AM
"""
from typing import List, Literal, Optional, TypedDict, Dict


class ParsedQuery(TypedDict):
    query_type: Literal["fact", "verification", "discovery", "recommendation"]
    entities: List[Dict]  # [{"text":"Ginkgo Biloba","type":"DSI"}, {"text":"Memory Loss","type":"Disease"}]
    relation: Optional[str]  # e.g., "treats", "prevents", "associated_with"
    confidence: float


class LinkedEntity(TypedDict):
    original: str
    edisk_id: str
    node_type: str
    name: str
    score: float
    primary: bool


class CypherResult(TypedDict):
    paths: List[Dict]  # 原始 path + 节点/边属性


class ContextGraph(TypedDict):
    one_hop: List[Dict]
    two_hop: List[Dict]
    tips: List[str]  # 给用户的上下文推荐要点


class LinkPredictionBlock(TypedDict):
    entity: Dict
    head_type: str
    target_blocks: List[Dict]
    backend: Optional[Dict]


class LinkPrediction(TypedDict):
    per_entity: List[LinkPredictionBlock]
    backend: Optional[Dict]


class VerificationEvidence(TypedDict):
    predicted: Dict  # {"h":...,"r":...,"t":...}
    support_paths: List[Dict]  # 每条路径的分段证据
