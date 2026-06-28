// @ts-check
import { defineConfig } from 'astro/config';
import vercel from '@astrojs/vercel';

// SSR en Vercel: rutas on-demand por defecto (las páginas estáticas se pueden
// marcar luego con `export const prerender = true` para SEO máximo).
export default defineConfig({
  output: 'server',
  adapter: vercel(),
});
