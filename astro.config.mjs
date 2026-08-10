// @ts-check
import { defineConfig } from 'astro/config';

// Sitio 100% estático → se despliega GRATIS en Render Static Site o Azure SWA.
// (El build genera /dist con HTML/CSS/JS servible por cualquier CDN.)
export default defineConfig({
  output: 'static',
});
