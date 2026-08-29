/**
 * Trae la galería COMPLETA de cada producto desde Dropi y actualiza products.json.
 *
 * El catálogo tiene 1 sola foto por producto, pero Dropi guarda varias: el campo
 * `gallery` de la API trae todas. Como el pipeline de imágenes y products.js ya
 * soportan N imágenes, esto es puro dato: al agregar entradas a `sourceImages`
 * la galería del detalle aparece sola.
 *
 * Requiere DROPI_INTEGRATION_KEY vigente en .env.local (Dropi -> Integraciones ->
 * Generar Token). Si da 401, el token caducó: regeneralo.
 *
 * Uso:
 *   node scripts/fetch-galleries.mjs --dry     # muestra qué encontraría, no escribe
 *   node scripts/fetch-galleries.mjs           # actualiza src/data/products.json
 *   node scripts/fetch-galleries.mjs --max 6   # tope de imágenes por producto (def. 6)
 */
import { readFileSync, writeFileSync } from 'node:fs';

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
const DRY = process.argv.includes('--dry');
const MAX = Number(process.argv[process.argv.indexOf('--max') + 1]) || 6;
const DATA = new URL('../src/data/products.json', import.meta.url).pathname;

if (!KEY) {
  console.error('❌ Falta DROPI_INTEGRATION_KEY en .env.local');
  process.exit(1);
}

/** Consulta un producto por su id de Dropi y devuelve el objeto crudo. */
async function fetchProduct(id) {
  const res = await fetch(`${BASE}/integrations/products/index`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      'dropi-integration-key': KEY,
    },
    body: JSON.stringify({
      startData: 0,
      pageSize: 5,
      order_type: 'DESC',
      order_by: 'id',
      keywords: String(id),
      active: true,
      no_count: true,
      integration: true,
      get_stock: false,
    }),
  });

  if (res.status === 401) throw new Error('401 Access denied — el token caducó, regeneralo en Dropi.');
  if (!res.ok) throw new Error(`HTTP ${res.status}`);

  const json = await res.json();
  const items = json.objects ?? json.data ?? [];
  return items.find((p) => String(p.id) === String(id)) ?? items[0] ?? null;
}

/**
 * Saca las claves S3 de la galería. El pipeline las espera relativas al CDN y
 * SIN escapar (build-images.py aplica quote() por su cuenta), así que hay que
 * decodificar lo que venga con %20 y recortar el host si viene la URL completa.
 */
function galleryKeys(product) {
  const raw = product?.gallery ?? [];
  const keys = raw
    .map((g) => g?.url ?? g?.urlS3 ?? '')
    .filter(Boolean)
    .map((u) => {
      let k = u.replace(/^https?:\/\/[^/]+\//, '');   // quita el host si vino completo
      try { k = decodeURIComponent(k); } catch { /* ya venía crudo */ }
      return k;
    })
    .filter((k) => /\.(jpe?g|png|webp|gif)$/i.test(k));
  return [...new Set(keys)];                          // Dropi repite imágenes a veces
}

const catalog = JSON.parse(readFileSync(DATA, 'utf8'));
console.log(`Consultando ${catalog.length} productos en Dropi (máx ${MAX} imágenes c/u)\n`);

let mejorados = 0;
let sinCambio = 0;
const fallos = [];

for (const product of catalog) {
  try {
    const remote = await fetchProduct(product.id);
    if (!remote) { fallos.push(`${product.slug}: no encontrado`); continue; }

    const keys = galleryKeys(remote);
    if (keys.length === 0) { fallos.push(`${product.slug}: sin gallery`); continue; }

    // La imagen actual manda: es la que ya está procesada y validada visualmente.
    const actual = product.sourceImages?.[0];
    const ordenadas = actual
      ? [actual, ...keys.filter((k) => k !== actual)]
      : keys;
    const nuevas = ordenadas.slice(0, MAX);

    if (nuevas.length <= (product.sourceImages?.length ?? 0)) {
      sinCambio++;
      console.log(`  ·  ${product.slug.padEnd(42)} ${nuevas.length} img (sin cambio)`);
      continue;
    }

    console.log(`  ✅ ${product.slug.padEnd(42)} ${product.sourceImages.length} → ${nuevas.length} img`);
    if (!DRY) product.sourceImages = nuevas;
    mejorados++;
  } catch (err) {
    fallos.push(`${product.slug}: ${err.message}`);
    if (String(err.message).startsWith('401')) break;   // no seguir golpeando con token muerto
  }
}

console.log(`\n${mejorados} productos mejorados, ${sinCambio} sin cambio, ${fallos.length} fallos`);
if (fallos.length) console.log('Fallos:\n  ' + fallos.join('\n  '));

if (DRY) {
  console.log('\n(--dry: no se escribió nada)');
} else if (mejorados > 0) {
  writeFileSync(DATA, JSON.stringify(catalog, null, 2) + '\n');
  console.log(`\nEscrito ${DATA}`);
  console.log('Ahora:  .venv-img/bin/python scripts/build-images.py  &&  npm run build');
}
