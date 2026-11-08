// Connectivity only: list models without inference, prompts, or financial data.
const { UNSLOTH_BASE_URL, UNSLOTH_MODEL, UNSLOTH_API_KEY } = process.env;

try {
  if (!UNSLOTH_BASE_URL) throw new Error('Set UNSLOTH_BASE_URL to your local OpenAI-compatible API base URL.');
  const url = new URL(`${UNSLOTH_BASE_URL.replace(/\/+$/, '')}/models`);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) {
    throw new Error('Use an HTTP(S) base URL without embedded credentials.');
  }
  const headers = { Accept: 'application/json' };
  if (UNSLOTH_API_KEY) headers.Authorization = `Bearer ${UNSLOTH_API_KEY}`;
  const response = await fetch(url, {
    headers,
    signal: AbortSignal.timeout(10000),
    redirect: 'error',
  });
  if (!response.ok) throw new Error(`GET /models returned HTTP ${response.status}. Check the API URL and optional key.`);
  const body = await response.json();
  if (!Array.isArray(body.data)) throw new Error('Expected an OpenAI-compatible response with a data array.');
  const ids = body.data.map(model => model.id).filter(id => typeof id === 'string');
  console.log('Available model IDs:', JSON.stringify(ids));
  if (!UNSLOTH_MODEL || !ids.includes(UNSLOTH_MODEL)) {
    throw new Error('Set UNSLOTH_MODEL to an exact ID listed above, then recreate n8n with docker compose up -d n8n.');
  }
  console.log('Verified: n8n container can reach the API and the configured model is listed. Inference was not tested.');
} catch (error) {
  console.error(`Unsloth connectivity check failed: ${error.message}`);
  process.exitCode = 1;
}
