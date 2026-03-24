/**
 * Timeline step definitions for the eDISK AI Agent task flow.
 * Each step maps to a stage in the backend pipeline.
 */

export const STEPS = [
  {
    key: 'Task Intake',
    icon: '📝',
    placeholder: 'Waiting for your instructions.',
  },
  {
    key: 'Entity Mapping',
    icon: '🧭',
    placeholder: 'Aligning key entities with the eDISK knowledge graph.',
  },
  {
    key: 'Evidence Retrieval',
    icon: '🔍',
    placeholder: 'Querying graph relations and literature snippets.',
  },
  {
    key: 'Context Expansion',
    icon: '🗂',
    placeholder: 'Exploring surrounding context to enrich the story.',
  },
  {
    key: 'Inference Engine',
    icon: '🧠',
    placeholder: 'Running reasoning models for deeper insights.',
  },
  {
    key: 'Cross-Checking',
    icon: '🧪',
    placeholder: 'Verifying claims against trusted references.',
  },
  {
    key: 'Final Response',
    icon: '✅',
    placeholder: 'Preparing the final answer for you.',
  },
];

/** Aliases the backend may use instead of the canonical step key */
export const STEP_ALIASES = {
  '1/7': 'Task Intake',
  '2/7': 'Entity Mapping',
  '3/7': 'Evidence Retrieval',
  '4/7': 'Context Expansion',
  '5/7': 'Inference Engine',
  '6/7': 'Cross-Checking',
  '7/7': 'Final Response',
  FINAL: 'Final Response',
  'TASK INTAKE': 'Task Intake',
  'ENTITY MAPPING': 'Entity Mapping',
  'EVIDENCE RETRIEVAL': 'Evidence Retrieval',
  'CONTEXT EXPANSION': 'Context Expansion',
  'INFERENCE ENGINE': 'Inference Engine',
  'CROSS-CHECKING': 'Cross-Checking',
  'FINAL RESPONSE': 'Final Response',
};

/**
 * Resolve a raw label from the backend into a canonical step key.
 * Returns null when the label doesn't match any known step.
 */
export function normaliseStep(label) {
  if (!label) return null;
  const trimmed = label.trim();
  const stepKeys = STEPS.map((s) => s.key);
  if (stepKeys.includes(trimmed)) return trimmed;
  if (STEP_ALIASES[trimmed]) return STEP_ALIASES[trimmed];
  if (STEP_ALIASES[trimmed.toUpperCase()]) return STEP_ALIASES[trimmed.toUpperCase()];
  return null;
}