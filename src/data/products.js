// Catálogo de la tienda.
// ⚠️ DEMO: reemplaza estos por tus productos reales de Dropi.
// La estructura mapea 1:1 con lo que devuelve Dropi (gallery -> images), así que
// cuando me pases el JSON de productos de tu panel, los cargo aquí tal cual.
//
// Campos: id, slug (url), name, price, category, description, images[] (1+ urls).

export const products = [
  {
    id: 'p1',
    slug: 'audifonos-bluetooth-pro',
    name: 'Audífonos Bluetooth Pro',
    price: 79900,
    category: 'Tecnología',
    description:
      'Audífonos inalámbricos con cancelación activa de ruido, hasta 30 horas de batería, ' +
      'estuche de carga rápida y micrófono con reducción de eco. Compatibles con iOS y Android.',
    images: [
      'https://picsum.photos/seed/audio1/800/600',
      'https://picsum.photos/seed/audio2/800/600',
      'https://picsum.photos/seed/audio3/800/600',
    ],
  },
  {
    id: 'p2',
    slug: 'smartwatch-fit-2',
    name: 'Smartwatch Fit 2',
    price: 119900,
    category: 'Tecnología',
    description:
      'Reloj inteligente con monitor de ritmo cardíaco, oxígeno en sangre (SpO2), más de 100 modos ' +
      'deportivos, notificaciones y resistencia al agua IP68. Pantalla AMOLED de 1.8".',
    images: [
      'https://picsum.photos/seed/watch1/800/600',
      'https://picsum.photos/seed/watch2/800/600',
      'https://picsum.photos/seed/watch3/800/600',
    ],
  },
  {
    id: 'p3',
    slug: 'camara-seguridad-wifi',
    name: 'Cámara de Seguridad WiFi',
    price: 89900,
    category: 'Hogar',
    description:
      'Cámara de vigilancia WiFi 1080p con visión nocturna, detección de movimiento, audio ' +
      'bidireccional y app móvil. Rotación 360°. Ideal para casa, negocio o mascotas.',
    images: [
      'https://picsum.photos/seed/cam1/800/600',
      'https://picsum.photos/seed/cam2/800/600',
    ],
  },
  {
    id: 'p4',
    slug: 'organizador-cocina-8pzs',
    name: 'Organizador de Cocina 8 piezas',
    price: 49900,
    category: 'Hogar',
    description:
      'Set organizador de 8 piezas en acero inoxidable con base antideslizante. Ahorra espacio y ' +
      'mantiene tu cocina ordenada. Fácil de limpiar y resistente.',
    images: [
      'https://picsum.photos/seed/kitchen1/800/600',
      'https://picsum.photos/seed/kitchen2/800/600',
    ],
  },
  {
    id: 'p5',
    slug: 'lampara-led-escritorio',
    name: 'Lámpara LED de Escritorio',
    price: 39900,
    category: 'Hogar',
    description:
      'Lámpara LED con 3 tonos de luz e intensidad ajustable, brazo flexible y puerto de carga USB. ' +
      'Protege la vista, ideal para estudio y trabajo.',
    images: [
      'https://picsum.photos/seed/lamp1/800/600',
      'https://picsum.photos/seed/lamp2/800/600',
    ],
  },
  {
    id: 'p6',
    slug: 'mini-proyector-portatil',
    name: 'Mini Proyector Portátil',
    price: 159900,
    category: 'Tecnología',
    description:
      'Proyector portátil HD con entrada HDMI y USB, compatible con celular, PC y consolas. ' +
      'Perfecto para películas y presentaciones. Incluye control remoto.',
    images: [
      'https://picsum.photos/seed/proj1/800/600',
      'https://picsum.photos/seed/proj2/800/600',
      'https://picsum.photos/seed/proj3/800/600',
    ],
  },
];

export const getProduct = (slug) => products.find((p) => p.slug === slug);
export const categories = [...new Set(products.map((p) => p.category))].sort();
