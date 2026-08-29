// Feed de productos para Google Merchant Center (fichas gratuitas), formato RSS 2.0
// con el namespace g: que exige la especificación de Google Shopping.
//
// Se genera en build time a partir de la misma fuente que alimenta el catálogo y el
// JSON-LD de cada ficha (src/data/products.json), así que se actualiza solo con cada
// deploy: no hay una hoja de cálculo ni un archivo separado que mantener a mano.
//
// Referencia: https://support.google.com/merchants/answer/7052112
import { products } from '../data/products.js';
import { STORE_NAME } from '../config.js';

// Solo caracteres válidos en XML. Los nombres/descripciones del catálogo pueden traer
// &, comillas o tildes que rompen el XML si se insertan crudos.
const escapeXml = (value) =>
  String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');

export function GET(context) {
  const site = (context.site ?? new URL('https://monkey-store.onrender.com')).toString().replace(/\/$/, '');

  const items = products
    .map((product) => {
      const link = `${site}/producto/${product.slug}/`;
      const imageLink = `${site}${product.image}`;
      // COP no maneja centavos: el formato válido es "<entero> COP", sin decimales.
      const price = `${product.price} COP`;

      return `
    <item>
      <g:id>${escapeXml(product.slug)}</g:id>
      <title>${escapeXml(product.name)}</title>
      <description>${escapeXml(product.description)}</description>
      <link>${escapeXml(link)}</link>
      <g:image_link>${escapeXml(imageLink)}</g:image_link>
      <g:availability>in stock</g:availability>
      <g:price>${escapeXml(price)}</g:price>
      <g:condition>new</g:condition>
      <g:brand>${escapeXml(STORE_NAME)}</g:brand>
      <g:product_type>${escapeXml(product.category)}</g:product_type>
    </item>`;
    })
    .join('');

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">
  <channel>
    <title>${escapeXml(STORE_NAME)}</title>
    <link>${escapeXml(site)}</link>
    <description>Catálogo de ${escapeXml(STORE_NAME)} — pago contra entrega en Colombia.</description>
    ${items}
  </channel>
</rss>
`;

  return new Response(xml, {
    headers: { 'Content-Type': 'application/xml; charset=UTF-8' },
  });
}
