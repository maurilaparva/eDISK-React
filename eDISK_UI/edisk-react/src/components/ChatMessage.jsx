import React, { useState, useMemo, useEffect } from 'react';
import GraphPanel from './GraphPanel';
import { fetchRecommendations } from '../api';

/* ─────────────────────────────────────────────
   Shared type → highlight group
   Must stay in sync with GraphPanel.jsx TYPE_TO_GROUP
   ───────────────────────────────────────────── */

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

/* ─────────────────────────────────────────────
   PRIMARY PATH: Use LLM-provided entity tags
   The summarizer wraps entities in [[text||id||type]] tags,
   which are parsed into entityTags = [{text, kg_id, type}, ...]
   The clean prose has tags stripped — the display text remains.
   ───────────────────────────────────────────── */

function extractEntitiesFromTags(entityTags, graphData) {
  if (!entityTags || !entityTags.length) return [];

  const entities = [];
  const seen = new Set();

  // Build a set of primary entity IDs so we can force them to 'primary' group
  const primaryIds = new Set();
  if (graphData) {
    for (const ent of graphData.entities || []) {
      if (ent.id) primaryIds.add(ent.id);
    }
  }

  for (const tag of entityTags) {
    const text = tag.text;
    if (!text || text.length < 2) continue;

    const key = text.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);

    // Primary entities (the query subjects) are always blue
    const isPrimary = primaryIds.has(tag.kg_id);
    const group = isPrimary ? 'primary' : (TYPE_TO_GROUP[tag.type] || 'context');

    entities.push({
      term: text,
      group,
      kg_id: tag.kg_id,
      type: tag.type,
    });
  }

  // Sort longest first to avoid partial-match clobbering
  entities.sort((a, b) => b.term.length - a.term.length);
  return entities;
}

/* ─────────────────────────────────────────────
   FALLBACK: regex extraction for demo / no tags
   (unchanged from original)
   ───────────────────────────────────────────── */

function extractEntitiesFromText(text) {
  const entities = [];
  const add = (term, group) => {
    if (term && term.length > 1) entities.push({ term: term.trim(), group });
  };

  const patterns = [
    /(?:mapped\s+)?entities\s+(?:mapped\s+)?(?:in\s+this\s+query\s+)?are\s+(.+?)\s+and\s+(.+?)\./i,
    /(?:the\s+)?(?:two\s+)?entities\s+(?:identified|found|are)\s+(?:are\s+)?(.+?)\s+and\s+(.+?)[.,]/i,
    /mapped\s+(?:to\s+)?(.+?)\s+(?:\([^)]+\)\s+)?and\s+(.+?)\s+(?:\([^)]+\)\s+)?in\s+eDISK/i,
    /entities\s+are\s+(.+?),\s+commonly\s+known\s+as\s+(.+?),\s+and\s+(.+?)[.,]/i,
  ];
  for (const pattern of patterns) {
    const m = text.match(pattern);
    if (m) {
      const raw1 = m[1].trim();
      const parenMatch = raw1.match(/^(.+?)\s*\((.+?)\)/);
      if (parenMatch) {
        add(parenMatch[1], 'primary');
        add(parenMatch[2], 'primary');
      } else {
        add(raw1, 'primary');
      }
      add(m[2].trim(), 'primary');
      break;
    }
  }

  const assocMatch = text.match(/associated with.*?including\s+(.+?)(?:\.|$)/i);
  if (assocMatch) splitList(assocMatch[1]).forEach((item) => add(item, 'context'));

  const predMatch = text.match(/effective for conditions? like\s+(.+?)(?:\s+and interacts|\.|$)/i);
  if (predMatch) splitList(predMatch[1]).forEach((item) => add(item, 'prediction'));

  const linkedMatch = text.match(/linked to substances? like\s+(.+?)(?:,\s*with|\.|$)/i);
  if (linkedMatch) splitList(linkedMatch[1]).forEach((item) => add(item, 'substance'));

  entities.sort((a, b) => b.term.length - a.term.length);
  const seen = new Set();
  return entities.filter((e) => {
    const key = e.term.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function splitList(raw) {
  return raw.split(/,\s*and\s+|,\s*|\s+and\s+/).map((s) => s.trim()).filter(Boolean);
}

/* ─────────────────────────────────────────────
   Highlight styles — keyed to group names
   ───────────────────────────────────────────── */

const HIGHLIGHT_STYLES = {
  primary:    { backgroundColor: 'rgba(99,102,241,0.15)', color: '#4338ca', borderRadius: '4px', padding: '1px 5px', fontWeight: 600 },
  context:    { backgroundColor: 'rgba(251,191,36,0.2)',  color: '#92400e', borderRadius: '4px', padding: '1px 5px', fontWeight: 600 },
  prediction: { backgroundColor: 'rgba(74,222,128,0.2)',  color: '#166534', borderRadius: '4px', padding: '1px 5px', fontWeight: 600 },
  substance:  { backgroundColor: 'rgba(244,114,182,0.2)', color: '#9d174d', borderRadius: '4px', padding: '1px 5px', fontWeight: 600 },
};

function highlightText(text, entities) {
  if (!entities.length) return [text];
  const escaped = entities.map((e) => e.term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const pattern = new RegExp(`(${escaped.join('|')})`, 'gi');
  const groupMap = {};
  entities.forEach((e) => { groupMap[e.term.toLowerCase()] = e.group; });
  return text.split(pattern).map((part, i) => {
    const group = groupMap[part.toLowerCase()];
    return group
      ? <span key={i} style={HIGHLIGHT_STYLES[group]}>{part}</span>
      : part;
  });
}

/* ─────────────────────────────────────────────
   Recommendation Buttons
   ───────────────────────────────────────────── */

function RecommendationButtons({ query, responseText, onSelect }) {
  const [recommendations, setRecommendations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setVisible(false);
    fetchRecommendations(query, responseText)
      .then((recs) => {
        if (!cancelled) {
          setRecommendations(recs);
          setLoading(false);
          setTimeout(() => setVisible(true), 120);
        }
      })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [query, responseText]);

  if (loading) {
    return (
      <div className="recs-loading">
        <span className="recs-loading-dot" />
        <span className="recs-loading-dot" />
        <span className="recs-loading-dot" />
      </div>
    );
  }
  if (!recommendations.length) return null;

  return (
    <div className={`recs-container ${visible ? 'recs-visible' : ''}`}>
      <span className="recs-label">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
          style={{ marginRight: '5px', verticalAlign: 'middle' }}>
          <path d="M9 18l6-6-6-6" />
        </svg>
        Explore next
      </span>
      <div className="recs-buttons">
        {recommendations.map((rec, i) => (
          <button key={i} className="rec-btn" style={{ animationDelay: `${i * 80}ms` }}
            onClick={() => onSelect(rec)} title={rec}>
            {rec}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────
   Main ChatMessage component
   ───────────────────────────────────────────── */

export default function ChatMessage({ role, text, query, graphData, entityTags, onRecommendationSelect }) {
  const [showGraph, setShowGraph] = useState(false);

  const entities = useMemo(() => {
    if (role !== 'bot') return [];
    // PRIMARY: use LLM-provided entity tags when available
    if (entityTags && entityTags.length > 0) {
      return extractEntitiesFromTags(entityTags, graphData);
    }
    // FALLBACK: regex for demo mode / old responses without tags
    return extractEntitiesFromText(text);
  }, [role, text, entityTags, graphData]);

  const content = useMemo(() => {
    if (role !== 'bot' || !entities.length) return text;
    return highlightText(text, entities);
  }, [role, text, entities]);

  const hasEntities = role === 'bot' && entities.length > 0;

  return (
    <div className="msg-wrapper">
      <div className={`msg ${role}`}>
        {content}
        {hasEntities && (
          <button
            className={`graph-btn ${showGraph ? 'graph-btn-active' : ''}`}
            onClick={() => setShowGraph((prev) => !prev)}
            title={showGraph ? 'Hide knowledge graph' : 'View as knowledge graph'}
            aria-label={showGraph ? 'Hide knowledge graph' : 'View as knowledge graph'}
          >
            🕸️
          </button>
        )}
      </div>

      {showGraph && (
        <div className="inline-graph">
          <GraphPanel
            responseText={text}
            graphData={graphData}
            entityTags={entityTags}
            onClose={() => setShowGraph(false)}
            inline
          />
        </div>
      )}

      {role === 'bot' && onRecommendationSelect && (
        <RecommendationButtons
          query={query || ''}
          responseText={text}
          onSelect={onRecommendationSelect}
        />
      )}
    </div>
  );
}