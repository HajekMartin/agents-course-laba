import { randomBytes } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const root = new URL('../', import.meta.url);
let template = readFileSync(new URL('.env.example', root), 'utf8');
for (const key of [
  'POSTGRES_PASSWORD', 'N8N_DB_PASSWORD', 'FINANCE_DB_PASSWORD', 'N8N_ENCRYPTION_KEY',
]) {
  template = template.replace(new RegExp(`^${key}=$`, 'm'), `${key}=${randomBytes(32).toString('hex')}`);
}

try {
  writeFileSync(new URL('.env', root), template, { flag: 'wx', mode: 0o600 });
  console.log(`Created ${fileURLToPath(new URL('.env', root))} with independent random secrets.`);
  console.log('Set UNSLOTH_BASE_URL and UNSLOTH_MODEL before checking the existing local model.');
} catch (error) {
  if (error.code !== 'EEXIST') throw error;
  console.error('.env already exists; it was left unchanged.');
  process.exitCode = 1;
}
