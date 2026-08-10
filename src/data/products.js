// El catálogo vive en products.json (fuente única): lo usan tanto este módulo
// como el pipeline de imágenes (scripts/build-images.py).
//
// Las imágenes se sirven ya procesadas desde /public/products/, generadas con:
//   .venv-img/bin/python scripts/build-images.py
import catalog from './products.json';

export const products = catalog.map((product) => ({
  ...product,
  // Lienzo grande para el detalle, versión ligera para las tarjetas del listado.
  image: `/products/${product.slug}.webp`,
  thumb: `/products/${product.slug}-sm.webp`,
  images: [`/products/${product.slug}.webp`],
  margin: product.price - product.cost,
}));

export const getProduct = (slug) => products.find((p) => p.slug === slug);

export const categories = [...new Set(products.map((p) => p.category))].sort();
