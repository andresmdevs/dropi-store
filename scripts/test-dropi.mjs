/**
 * Diagnóstico del token de Dropi contra el endpoint REAL que usa el plugin oficial:
 *   POST https://api.dropi.co/integrations/products/index
 * Lee .env.local / .env (no imprime el token). No crea órdenes (solo lee productos).
 *
 * Uso:  node scripts/test-dropi.mjs
 */
import { readFileSync } from 'node:fs';

function loadEnv(path) {
  try {
    for (const line of readFileSync(path, 'utf8').split('\n')) {
      const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
      if (m && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^["']|["']$/g, '').trim();
    }
  } catch { /* no existe */ }
}
loadEnv(new URL('../.env.local', import.meta.url).pathname);
loadEnv(new URL('../.env', import.meta.url).pathname);

const BASE = (process.env.DROPI_API_URL ?? 'https://api.dropi.co').replace(/\/$/, '');
const KEY = process.env.DROPI_INTEGRATION_KEY;
if (!KEY) {
  console.error('❌ Falta DROPI_INTEGRATION_KEY en .env.local o .env');
  process.exit(1);
}
console.log(`🔑 Token detectado (oculto, ${KEY.length} chars).  Base: ${BASE}\n`);

// Payload EXACTO que arma el plugin oficial (ProductsModel.php)
const payload = {
  startData: 0,
  pageSize: 5,
  order_type: 'DESC',
  order_by: 'id',
  keywords: '',
  active: true,
  no_count: true,
  integration: true,
  get_stock: false,
};

// Probamos variantes de header de autenticación para descubrir la correcta.
const headerVariants = [
  { 'dropi-integration-key': KEY },
  { 'X-Authorization': KEY },
  { Authorization: `Bearer ${KEY}` },
  { 'dropi-integration-key': KEY, 'X-Authorization': KEY },
];

const url = `${BASE}/integrations/products/index`;
console.log(`POST ${url}\n`);

for (const h of headerVariants) {
  const label = Object.keys(h).join(' + ');
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...h },
      body: JSON.stringify(payload),
    });
    const text = await res.text();
    let info = text.slice(0, 120).replace(/\s+/g, ' ');
    try {
      const j = JSON.parse(text);
      if (j && typeof j === 'object') {
        const n = Array.isArray(j.objects) ? j.objects.length : (j.count ?? '?');
        info = `isSuccess=${j.isSuccess} objetos=${Array.isArray(j.objects) ? j.objects.length : '-'} count=${j.count ?? '-'} msg="${(j.message ?? '').slice(0,50)}"`;
      }
    } catch {}
    const flag = res.ok ? '✅' : '  ';
    console.log(`${flag} ${String(res.status).padEnd(4)} [${label}]  ${info}`);
  } catch (e) {
    console.log(`  ERR [${label}]  ${e.message}`);
  }
}
console.log('\n➡️  Un 200 con isSuccess=true confirma que el token funciona y con qué header.');
