/**
 * Thin wrappers around the Django API endpoints.
 *
 * DEV:        Vite proxies /api → Django at :8000 (same-origin)
 * PRODUCTION: Calls go to the EC2 backend URL defined below
 */

// ── Configure this for your deployment ──────────────────────
// In dev, empty string means "same origin" (Vite proxy handles it).
// In production (GitHub Pages), this points to your EC2 instance.
const API_BASE = import.meta.env.PROD
  ? ''   // ← Your EC2 public IP (or Elastic IP)
  : '';
// ─────────────────────────────────────────────────────────────

/**
 * Send a chat message (with optional image) to the backend.
 * Returns { run_id } on success.
 */
export async function sendChat(query, imageFile) {
  const form = new FormData();
  form.append('query', query);
  if (imageFile) form.append('image', imageFile);

  const res = await fetch(`${API_BASE}/api/chat`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || 'Unable to process your request.');
  }
  return res.json(); // { run_id }
}

/**
 * Poll the progress endpoint for a given run.
 * Returns { messages: string[], finished: boolean }.
 */
export async function fetchProgress(runId) {
  const res = await fetch(`${API_BASE}/api/progress/${runId}`);
  return res.json();
}

/**
 * Fetch follow-up question recommendations.
 */
export async function fetchRecommendations(query, response) {
  const res = await fetch(`${API_BASE}/api/recommendations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, response }),
  });
  if (!res.ok) {
    console.warn('[recommendations] fetch failed:', res.status);
    return [];
  }
  const data = await res.json();
  return Array.isArray(data.recommendations) ? data.recommendations : [];
}