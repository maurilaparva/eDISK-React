import React, { useMemo } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  useNodesState,
  useEdgesState,
  MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

const TYPE_TO_GROUP = {
  DSI:     'primary',
  DSP:     'primary',
  Drug:    'substance',
  Disease: 'context',
  Dis:     'context',
  Gene:    'prediction',
  Symptom: 'substance',
  SS:      'substance',
};

const RELATION_LABELS = {
  DSI_Disease:          'effective for',
  DSI_Drug:             'interacts with',
  DSI_Gene:             'interacts with',
  DSI_Symptom:          'effective for',
  DSI_DSI:              'associated with',
  DSP_DSI:              'has ingredient',
  Disease_Gene:         'associated with',
  Drug_Disease:         'effective for',
  Drug_Gene:            'interacts with',
  is_effective_for:     'effective for',
  associated_with:      'associated with',
  ASSOCIATED_WITH:      'associated with',
  interacts_with:       'interacts with',
  INTERACTS_WITH:       'interacts with',
  inhibits:             'inhibits',
  stimulates:           'stimulates',
  Causes:               'causes',
  has_adverse_reaction: 'adverse reaction',
  biomarker_of:         'biomarker of',
  has_ingredient:       'has ingredient',
  presents_with:        'presents with',
};

const cleanRelation = (raw) => {
  if (!raw) return 'related to';
  return RELATION_LABELS[raw] || raw.replace(/_/g, ' ').toLowerCase();
};

/* ─────────────────────────────────────────────
   Edge factory — consistent styling with better label offset
   ───────────────────────────────────────────── */

function makeEdge(source, target, label, dashed = false, existingEdges = []) {
  // Check for duplicate (by same source+target pair in either direction)
  const fwdId = `${source}→${target}`;
  const revId = `${target}→${source}`;
  if (existingEdges.find((e) => e.id === fwdId || e.id === revId)) return null;

  return {
    id: fwdId,
    source: String(source),
    target: String(target),
    label,
    type: 'default',
    animated: dashed,
    style: {
      stroke: dashed ? '#4ade80' : '#6366f1',
      strokeWidth: 2,
      strokeDasharray: dashed ? '6 3' : undefined,
    },
    labelStyle: {
      fontSize: 10,
      fontWeight: 600,
      fill: dashed ? '#166534' : '#4338ca',
    },
    labelBgStyle: {
      fill: dashed ? '#f0fdf4' : '#eef2ff',
      fillOpacity: 0.95,
    },
    labelBgPadding: [6, 4],
    labelBgBorderRadius: 6,
    markerEnd: {
      type: MarkerType.ArrowClosed,
      color: dashed ? '#4ade80' : '#6366f1',
      width: 18,
      height: 18,
    },
  };
}

/* ─────────────────────────────────────────────
   PRIMARY: Build graph using entityTags from the LLM
   Only show neighbors whose kg_id appears in the tags
   ───────────────────────────────────────────── */

function buildGraphFromTags(graphData, entityTags, responseText) {
  const nodes = [];
  const edges = [];
  const nodeSet = new Set();

  const addNode = (id, label, group) => {
    if (!id || nodeSet.has(String(id))) return;
    nodeSet.add(String(id));
    nodes.push({ id: String(id), data: { label }, group, position: { x: 0, y: 0 } });
  };

  // Build set of KG IDs that the LLM actually mentioned
  const mentionedIds = new Set();
  const mentionedNames = new Set();
  for (const tag of entityTags || []) {
    if (tag.kg_id && tag.kg_id !== 'NONE') mentionedIds.add(tag.kg_id);
    if (tag.text) mentionedNames.add(tag.text.toLowerCase());
  }

  // 1. Primary mapped entities (always shown)
  const primaryIds = (graphData.entities || []).map((e) => e.id || e.name);
  for (const ent of graphData.entities || []) {
    addNode(ent.id || ent.name, ent.name || ent.id, 'primary');
  }

  // 2. Direct edge between primary entities
  const directEdges = graphData.direct_edges || [];
  if (primaryIds.length >= 2) {
    const edgeLabel = directEdges.length > 0
      ? cleanRelation(directEdges[0].properties?.Type || directEdges[0].edge_type)
      : 'associated with';
    const e = makeEdge(primaryIds[0], primaryIds[1], edgeLabel, false, edges);
    if (e) edges.push(e);
  }

  // 3. Neighbors — only those the LLM tagged (by ID match, with name fallback)
  const BLOCKED_TYPES = new Set(['Publication', 'PMID', 'Reference', 'Article']);

  for (const n of graphData.neighbors || []) {
    if (BLOCKED_TYPES.has(n.neighbor_type)) continue;
    const name = n.neighbor_name;
    if (!name || name.length < 3) continue;

    const idMatch = n.neighbor_id && mentionedIds.has(n.neighbor_id);
    const nameMatch = mentionedNames.has(name.toLowerCase());
    if (!idMatch && !nameMatch) continue;

    const nid = n.neighbor_id || name;
    const srcId = n.source_id || primaryIds[0];
    const group = TYPE_TO_GROUP[n.neighbor_type] || 'context';

    addNode(nid, name, group);

    if (nodeSet.has(String(srcId))) {
      const label = cleanRelation(n.relation);
      const isPredicted = group === 'prediction';
      const e = makeEdge(
        n.direction === 'inbound' ? String(nid) : String(srcId),
        n.direction === 'inbound' ? String(srcId) : String(nid),
        label,
        isPredicted,
        edges,
      );
      if (e) edges.push(e);
    }
  }

  // 4. Tagged entities not in neighbors (from link prediction, verification, etc.)
  for (const tag of entityTags || []) {
    const text = tag.text;
    if (!text || text.length < 2) continue;
    const tagId = (tag.kg_id && tag.kg_id !== 'NONE') ? tag.kg_id : `tag_${text}`;
    if (nodeSet.has(String(tagId))) continue;

    // Skip if already added by name match
    const alreadyPresent = nodes.some(
      (n) => n.data.label.toLowerCase() === text.toLowerCase()
    );
    if (alreadyPresent) continue;

    // Don't add the primary entities again
    if (primaryIds.includes(tagId)) continue;

    const group = TYPE_TO_GROUP[tag.type] || 'context';
    addNode(tagId, text, group);

    // Connect to the first primary entity
    const srcId = primaryIds[0];
    if (srcId && nodeSet.has(String(srcId))) {
      const isPredicted = group === 'prediction';
      const edgeLabel = group === 'context' ? 'effective for'
        : group === 'substance' ? 'interacts with'
        : group === 'prediction' ? 'interacts with'
        : 'associated with';
      const e = makeEdge(String(srcId), String(tagId), edgeLabel, isPredicted, edges);
      if (e) edges.push(e);
    }
  }

  applyLayout(nodes, edges);
  nodes.forEach((n) => { n.style = NODE_STYLES[n.group] || NODE_STYLES.context; });

  return { nodes, edges };
}

/* ─────────────────────────────────────────────
   SECONDARY: Build graph from structured data (no tags)
   ───────────────────────────────────────────── */

function buildGraphFromStructuredData(graphData, responseText) {
  const nodes = [];
  const edges = [];
  const nodeSet = new Set();

  const addNode = (id, label, group) => {
    if (!id || nodeSet.has(String(id))) return;
    nodeSet.add(String(id));
    nodes.push({ id: String(id), data: { label }, group, position: { x: 0, y: 0 } });
  };

  const primaryIds = (graphData.entities || []).map((e) => e.id || e.name);
  for (const ent of graphData.entities || []) {
    addNode(ent.id || ent.name, ent.name || ent.id, 'primary');
  }

  const directEdges = graphData.direct_edges || [];
  if (primaryIds.length >= 2) {
    const edgeLabel = directEdges.length > 0
      ? cleanRelation(directEdges[0].properties?.Type || directEdges[0].edge_type)
      : 'associated with';
    const e = makeEdge(primaryIds[0], primaryIds[1], edgeLabel, false, edges);
    if (e) edges.push(e);
  }

  const responseLower = (responseText || '').toLowerCase();
  const BLOCKED_TYPES = new Set(['Publication', 'PMID', 'Reference', 'Article']);

  for (const n of graphData.neighbors || []) {
    if (BLOCKED_TYPES.has(n.neighbor_type)) continue;
    const name = n.neighbor_name;
    if (!name || name.length < 3) continue;
    if (!responseLower.includes(name.toLowerCase())) continue;

    const nid = n.neighbor_id || name;
    const srcId = n.source_id || primaryIds[0];
    const group = TYPE_TO_GROUP[n.neighbor_type] || 'context';

    addNode(nid, name, group);

    if (nodeSet.has(String(srcId))) {
      const label = cleanRelation(n.relation);
      const isPredicted = group === 'prediction';
      const e = makeEdge(
        n.direction === 'inbound' ? String(nid) : String(srcId),
        n.direction === 'inbound' ? String(srcId) : String(nid),
        label,
        isPredicted,
        edges,
      );
      if (e) edges.push(e);
    }
  }

  applyLayout(nodes, edges);
  nodes.forEach((n) => { n.style = NODE_STYLES[n.group] || NODE_STYLES.context; });

  return { nodes, edges };
}

/* ─────────────────────────────────────────────
   TERTIARY: Regex fallback for demo/legacy text
   ───────────────────────────────────────────── */

function buildGraphFromText(text) {
  const nodes = [];
  const edges = [];
  const nodeSet = new Set();

  const addNode = (id, label, group) => {
    if (nodeSet.has(id)) return;
    nodeSet.add(id);
    nodes.push({ id, data: { label }, group, position: { x: 0, y: 0 } });
  };

  const entityPatterns = [
    /(?:mapped\s+)?entities\s+(?:mapped\s+)?(?:in\s+this\s+query\s+)?are\s+(.+?)\s+and\s+(.+?)\./i,
    /entities\s+are\s+(.+?),?\s+commonly\s+known\s+as\s+[^,]+,\s+and\s+(.+?)[.,]/i,
    /mapped\s+(?:to\s+)?(.+?)\s+(?:\([^)]+\)\s+)?and\s+(.+?)\s+(?:\([^)]+\)\s+)?in\s+eDISK/i,
  ];
  for (const pattern of entityPatterns) {
    const m = text.match(pattern);
    if (m) {
      addNode('e1', m[1].replace(/[()]/g, '').trim(), 'primary');
      addNode('e2', m[2].trim(), 'primary');
      break;
    }
  }
  if (text.match(/is effective for/i) && nodeSet.has('e1') && nodeSet.has('e2')) {
    const e = makeEdge('e1', 'e2', 'effective for', false, edges);
    if (e) edges.push(e);
  }
  const assocMatch = text.match(/associated with.*?including\s+(.+?)(?:\.|$)/i);
  if (assocMatch) {
    splitList(assocMatch[1]).forEach((item, i) => {
      const id = `ctx_${i}`;
      addNode(id, item, 'context');
      if (nodeSet.has('e1')) {
        const e = makeEdge('e1', id, 'associated with', false, edges);
        if (e) edges.push(e);
      }
    });
  }
  const predMatch = text.match(/effective for conditions? like\s+(.+?)(?:\s+and interacts|\.|$)/i);
  if (predMatch) {
    splitList(predMatch[1]).forEach((item, i) => {
      const id = `pred_${i}`;
      addNode(id, item, 'prediction');
      if (nodeSet.has('e1')) {
        const e = makeEdge('e1', id, 'predicted for', true, edges);
        if (e) edges.push(e);
      }
    });
  }
  const linkedMatch = text.match(/linked to substances? like\s+(.+?)(?:,\s*with|\.|$)/i);
  if (linkedMatch) {
    splitList(linkedMatch[1]).forEach((item, i) => {
      const id = `sub_${i}`;
      addNode(id, item, 'substance');
      if (nodeSet.has('e2')) {
        const e = makeEdge(id, 'e2', 'linked to', false, edges);
        if (e) edges.push(e);
      }
    });
  }

  applyLayout(nodes, edges);
  nodes.forEach((n) => { n.style = NODE_STYLES[n.group] || NODE_STYLES.context; });
  return { nodes, edges };
}

function splitList(raw) {
  return raw.split(/,\s*and\s+|,\s*|\s+and\s+/).map((s) => s.trim()).filter(Boolean);
}

/* ─────────────────────────────────────────────
   Layout — tiered hierarchy with smart spacing
   Primary nodes at top center, secondary nodes
   fanned out below by group, with enough spacing
   so edge labels stay readable.
   ───────────────────────────────────────────── */

function applyLayout(nodes, edges) {
  if (!nodes.length) return;

  // Bucket nodes by group
  const groups = { primary: [], context: [], prediction: [], substance: [] };
  nodes.forEach((n) => {
    const g = groups[n.group];
    if (g) g.push(n);
    else groups.context.push(n);
  });

  const primaryCount = groups.primary.length;
  const secondaryGroups = ['context', 'prediction', 'substance'].filter(
    (g) => groups[g].length > 0
  );
  const totalSecondary = secondaryGroups.reduce((sum, g) => sum + groups[g].length, 0);

  // Adaptive sizing based on node count
  const NODE_WIDTH = 150;
  const NODE_HEIGHT = 50;
  const MIN_H_GAP = 60;    // minimum horizontal gap between nodes
  const V_GAP_PRIMARY_TO_SECONDARY = 140; // vertical space for edge labels
  const V_GAP_BETWEEN_ROWS = 100;

  // Calculate canvas dimensions needed
  const maxPerRow = Math.max(primaryCount, totalSecondary, 1);
  const canvasWidth = Math.max(700, maxPerRow * (NODE_WIDTH + MIN_H_GAP));
  const centerX = canvasWidth / 2;

  // ── TIER 1: Primary entities — top center ──
  const primaryY = 40;
  if (primaryCount === 1) {
    groups.primary[0].position = { x: centerX - NODE_WIDTH / 2, y: primaryY };
  } else if (primaryCount === 2) {
    // Space them apart enough for the edge label between them
    const spacing = Math.max(240, NODE_WIDTH + 100);
    groups.primary[0].position = { x: centerX - spacing / 2 - NODE_WIDTH / 2, y: primaryY };
    groups.primary[1].position = { x: centerX + spacing / 2 - NODE_WIDTH / 2, y: primaryY };
  } else {
    // 3+ primary (rare): spread evenly
    const totalWidth = (primaryCount - 1) * (NODE_WIDTH + MIN_H_GAP);
    const startX = centerX - totalWidth / 2;
    groups.primary.forEach((node, i) => {
      node.position = { x: startX + i * (NODE_WIDTH + MIN_H_GAP), y: primaryY };
    });
  }

  // ── TIER 2+: Secondary nodes — fanned out below ──
  // Each group gets its own column region to avoid overlap

  if (secondaryGroups.length === 0) return;

  const secondaryStartY = primaryY + NODE_HEIGHT + V_GAP_PRIMARY_TO_SECONDARY;

  if (secondaryGroups.length === 1) {
    // Single group: fan out centered below primary
    const groupKey = secondaryGroups[0];
    const groupNodes = groups[groupKey];
    _layoutGroupCentered(groupNodes, centerX, secondaryStartY, NODE_WIDTH, MIN_H_GAP, V_GAP_BETWEEN_ROWS);
  } else if (secondaryGroups.length === 2) {
    // Two groups: left and right of center
    const colWidth = canvasWidth / 2;
    secondaryGroups.forEach((groupKey, gi) => {
      const groupNodes = groups[groupKey];
      const colCenter = colWidth * gi + colWidth / 2;
      _layoutGroupCentered(groupNodes, colCenter, secondaryStartY, NODE_WIDTH, MIN_H_GAP, V_GAP_BETWEEN_ROWS);
    });
  } else {
    // Three groups: left, center, right
    const colWidth = canvasWidth / 3;
    secondaryGroups.forEach((groupKey, gi) => {
      const groupNodes = groups[groupKey];
      const colCenter = colWidth * gi + colWidth / 2;
      _layoutGroupCentered(groupNodes, colCenter, secondaryStartY, NODE_WIDTH, MIN_H_GAP, V_GAP_BETWEEN_ROWS);
    });
  }
}

/**
 * Position a group of nodes in a centered column.
 * If 3 or fewer: single column. If more: 2-column grid.
 */
function _layoutGroupCentered(groupNodes, centerX, startY, nodeWidth, hGap, vGap) {
  const count = groupNodes.length;
  if (count === 0) return;

  if (count <= 3) {
    // Single column, centered
    groupNodes.forEach((node, i) => {
      node.position = {
        x: centerX - nodeWidth / 2,
        y: startY + i * vGap,
      };
    });
  } else {
    // 2-column grid
    const colSpacing = nodeWidth + hGap;
    groupNodes.forEach((node, i) => {
      const col = i % 2;
      const row = Math.floor(i / 2);
      node.position = {
        x: centerX + (col === 0 ? -colSpacing / 2 : colSpacing / 2) - nodeWidth / 2,
        y: startY + row * vGap,
      };
    });
  }
}

/* ─────────────────────────────────────────────
   Node styles — refined with consistent sizing
   ───────────────────────────────────────────── */

const NODE_STYLES = {
  primary: {
    background: 'linear-gradient(135deg, #818cf8, #6366f1)',
    color: '#ffffff',
    border: '2px solid rgba(99,102,241,0.8)',
    borderRadius: '16px',
    padding: '14px 24px',
    fontSize: '14px',
    fontWeight: 700,
    boxShadow: '0 8px 24px rgba(99,102,241,0.35)',
    minWidth: '130px',
    textAlign: 'center',
    zIndex: 10,
  },
  context: {
    background: '#fef3c7',
    color: '#92400e',
    border: '2px solid #fbbf24',
    borderRadius: '12px',
    padding: '10px 18px',
    fontSize: '13px',
    fontWeight: 600,
    boxShadow: '0 4px 14px rgba(251,191,36,0.25)',
    textAlign: 'center',
    minWidth: '100px',
  },
  prediction: {
    background: '#dcfce7',
    color: '#166534',
    border: '2px dashed #4ade80',
    borderRadius: '12px',
    padding: '10px 18px',
    fontSize: '13px',
    fontWeight: 600,
    boxShadow: '0 4px 14px rgba(74,222,128,0.2)',
    textAlign: 'center',
    minWidth: '100px',
  },
  substance: {
    background: '#fce7f3',
    color: '#9d174d',
    border: '2px solid #f472b6',
    borderRadius: '12px',
    padding: '10px 18px',
    fontSize: '13px',
    fontWeight: 600,
    boxShadow: '0 4px 14px rgba(244,114,182,0.2)',
    textAlign: 'center',
    minWidth: '100px',
  },
};

/* ─────────────────────────────────────────────
   Component
   ───────────────────────────────────────────── */

export default function GraphPanel({ responseText, graphData, entityTags, onClose, inline = false }) {
  const { nodes: initialNodes, edges: initialEdges } = useMemo(() => {
    // Priority 1: Tags + structured data (best accuracy)
    if (entityTags && entityTags.length > 0 && graphData && (graphData.entities || []).length > 0) {
      return buildGraphFromTags(graphData, entityTags, responseText);
    }
    // Priority 2: Structured data only (name matching)
    if (graphData && (graphData.entities || []).length > 0) {
      return buildGraphFromStructuredData(graphData, responseText);
    }
    // Priority 3: Regex fallback (demo mode)
    return buildGraphFromText(responseText || '');
  }, [graphData, entityTags, responseText]);

  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState(initialEdges);

  return (
    <div className={inline ? 'graph-panel graph-panel-inline' : 'graph-panel'}>
      <div className="graph-header">
        <h2>Knowledge Graph</h2>
        <div className="graph-legend">
          <span className="legend-item legend-primary">Entity</span>
          <span className="legend-item legend-context">Disease</span>
          <span className="legend-item legend-prediction">Gene</span>
          <span className="legend-item legend-substance">Drug / Symptom</span>
        </div>
        <button className="graph-close-btn" onClick={onClose} aria-label="Close graph view">✕</button>
      </div>
      <div className="graph-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          minZoom={0.2}
          maxZoom={2.5}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#c7d2fe" gap={24} size={1} />
          <Controls showInteractive={false} position="bottom-right" />
        </ReactFlow>
      </div>
    </div>
  );
}