import { useRef, useCallback } from 'react';
import { fetchProgress } from '../api';
import { STEPS, normaliseStep } from '../steps';

const STEP_KEYS = STEPS.map((s) => s.key);

/**
 * Parse an array of raw progress messages into structured timeline state.
 *
 * Returns:
 *   { highestIndex, detailsByStep, finalAnswer }
 */
function parseMessages(messages) {
  const detailsByStep = {};
  let highestIndex = -1;
  let finalAnswer = null;

  (messages || []).forEach((msg) => {
    const match = msg.match(/^\[(.+?)\]\s*(.*)$/);
    if (!match) return;

    const label = match[1];
    const detail = match[2].trim();
    const stepName = normaliseStep(label);
    if (!stepName) return;

    const idx = STEP_KEYS.indexOf(stepName);
    if (idx === -1) return;

    highestIndex = Math.max(highestIndex, idx);
    if (detail) detailsByStep[stepName] = detail;

    if (label.trim().toUpperCase() === 'FINAL') {
      highestIndex = STEP_KEYS.length - 1;
      finalAnswer = detail || 'Answer delivered.';
    }
  });

  return { highestIndex, detailsByStep, finalAnswer };
}

/**
 * Custom hook that manages progress polling for a single run.
 *
 * Returns { startPolling, stopPolling }
 *   - startPolling(runId, onUpdate): begins interval-based polling.
 *     `onUpdate({ highestIndex, detailsByStep, finalAnswer, finished })` is called on every tick.
 *   - stopPolling(): clears the interval.
 */
export function useProgress() {
  const timerRef = useRef(null);

  const stopPolling = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const startPolling = useCallback(
    (runId, onUpdate) => {
      stopPolling();

      const tick = async () => {
        try {
          const data = await fetchProgress(runId);
          const { highestIndex, detailsByStep, finalAnswer } = parseMessages(data.messages);
          const finished =
            data.finished || (data.messages || []).some((m) => m.includes('[DONE]'));

          onUpdate({ highestIndex, detailsByStep, finalAnswer, finished });

          if (finished) stopPolling();
        } catch {
          /* silently retry on next tick */
        }
      };

      // First tick immediately
      tick();
      timerRef.current = setInterval(tick, 850);
    },
    [stopPolling]
  );

  return { startPolling, stopPolling };
}