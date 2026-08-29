// El catálogo vive en products.json (fuente única): lo usan tanto este módulo
// como el pipeline de imágenes (scripts/build-images.py).
//
// Las imágenes se sirven ya procesadas desde /public/products/, generadas con:
//   .venv-img/bin/python scripts/build-images.py
//
// Convención de nombres que produce el pipeline:
//   {slug}.webp      -> imagen principal (900px)
//   {slug}-sm.webp   -> miniatura para las tarjetas (450px)
//   {slug}-2.webp    -> segunda imagen de la galería, y así sucesivamente.
import catalog from './products.json';

export const products = catalog.map((product) => {
  const total = (product.sourceImages || []).length || 1;
  // La galería del detalle se deriva de cuántas imágenes de origen tiene el producto.
  const images = Array.from({ length: total }, (_, i) =>
    i === 0 ? `/products/${product.slug}.webp` : `/products/${product.slug}-${i + 1}.webp`,
  );

  // `cost` se deja fuera a propósito: cualquier cosa que quede en este objeto puede
  // terminar serializada al HTML público. La rentabilidad se calcula aparte.
  const { cost, ...publicFields } = product;

  return {
    ...publicFields,
    images,
    image: images[0],
    thumb: `/products/${product.slug}-sm.webp`,
  };
});

/** Rentabilidad por producto. Solo para uso en build/scripts, nunca en una página. */
export const margins = catalog.map((p) => ({
  slug: p.slug,
  cost: p.cost,
  price: p.price,
  margin: p.price - p.cost,
}));

export const getProduct = (slug) => products.find((p) => p.slug === slug);

export const categories = [...new Set(products.map((p) => p.category))].sort();
