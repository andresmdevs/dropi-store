// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// Sitio 100% estático → se despliega GRATIS en Render Static Site o Azure SWA.
// (El build genera /dist con HTML/CSS/JS servible por cualquier CDN.)
//
// `site` no es opcional: sin él no hay URLs absolutas, y og:image y canonical
// las exigen. También es lo que hace que @astrojs/sitemap genere algo.
export default defineConfig({
  site: 'https://monkey-store.onrender.com',
  output: 'static',
  integrations: [sitemap()],
});
