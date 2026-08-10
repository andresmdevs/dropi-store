// Catálogo real (curado de Dropi) — nicho tech + fitness.
// price = precio de venta al público (COP). Tu costo Dropi es menor → ese es tu margen.
// Imágenes servidas desde el CDN de Dropi (CloudFront).

const CDN = 'https://d39ru7awumhhs2.cloudfront.net/';
const img = (path) => CDN + encodeURI(path);

export const products = [
  // ---------------- TECNOLOGÍA ----------------
  {
    id: '2099675',
    slug: 'audifonos-tws-f9',
    name: 'Audífonos Inalámbricos TWS F9',
    price: 49900,
    category: 'Tecnología',
    description:
      'Audífonos Bluetooth TWS con estuche de carga, sonido estéreo, manos libres y pantalla de batería. ' +
      'Compatibles con todos los celulares. Ideales para el día a día, trabajo y ejercicio.',
    images: [img('colombia/products/2099675/1772655108AUDIFONOS F9 2.jpeg')],
  },
  {
    id: '1737794',
    slug: 'audifonos-deportivos-lenovo-lp75',
    name: 'Audífonos Deportivos Lenovo LP75',
    price: 90000,
    category: 'Tecnología',
    description:
      'Audífonos deportivos Lenovo LP75 con Bluetooth, resistencia al sudor y gran autonomía. ' +
      'Ajuste seguro para entrenar sin que se caigan. Sonido potente con graves reforzados.',
    images: [img('colombia/products/1737794/1743444011lp75.PNG')],
  },
  {
    id: '1864794',
    slug: 'smartwatch-ac-10-serie-10',
    name: 'Smartwatch AC-10 Serie 10',
    price: 46000,
    category: 'Tecnología',
    description:
      'Reloj inteligente con pantalla amplia, llamadas Bluetooth, monitor de pasos, ritmo cardíaco y ' +
      'múltiples modos deportivos. Notificaciones de WhatsApp y redes. Varios colores disponibles.',
    images: [img('colombia/products/1864794/1751402578image - 2025-05-14T151420.485.jpg')],
  },
  {
    id: '2181681',
    slug: 'reloj-inteligente-gtide-r6-pro',
    name: 'Reloj Inteligente G-Tide R6 Pro',
    price: 293000,
    category: 'Tecnología',
    description:
      'Smartwatch premium G-Tide R6 Pro con pantalla AMOLED, llamadas, SpO2, ritmo cardíaco y GPS. ' +
      'Diseño elegante en plateado o negro. Batería de larga duración.',
    images: [img('colombia/products/2181681/17819054031.png')],
  },
  {
    id: '2169893',
    slug: 'camara-seguridad-wifi-3-antenas',
    name: 'Cámara de Seguridad IP WiFi 3 Antenas',
    price: 64000,
    category: 'Tecnología',
    description:
      'Cámara WiFi con 3 antenas para mayor cobertura, visión nocturna, detección de movimiento y ' +
      'audio bidireccional. Control desde la app en tu celular. Ideal para casa, negocio o mascotas.',
    images: [img('colombia/products/2169893/1780614633camara 3 antenas.jpeg')],
  },
  {
    id: '2108013',
    slug: 'power-bank-5000-mah',
    name: 'Power Bank 5000 mAh',
    price: 28000,
    category: 'Tecnología',
    description:
      'Batería portátil compacta de 5000 mAh para cargar tu celular donde estés. Ligera, cabe en el ' +
      'bolsillo y es perfecta para viajes, salidas y emergencias.',
    images: [img('colombia/products/2108013/1773667654Gemini_Generated_Image_5jvlzk5jvlzk5jvl.png')],
  },
  {
    id: '796386',
    slug: 'parlante-bluetooth-gts-1372',
    name: 'Parlante Bluetooth GTS-1372',
    price: 39900,
    category: 'Tecnología',
    description:
      'Parlante Bluetooth portátil con sonido potente, radio FM, entrada USB/microSD y batería ' +
      'recargable. Llévalo a todos lados: casa, paseos y reuniones.',
    images: [img('colombia/products/796386/1713804089PARLANTE GTS-1347.jpg')],
  },
  {
    id: '2211461',
    slug: 'mini-camara-retro-hd',
    name: 'Mini Cámara Retro HD',
    price: 35000,
    category: 'Tecnología',
    description:
      'Mini cámara digital estilo retro, ligera y fácil de usar. Captura fotos y videos con un look ' +
      'vintage muy de moda. Regalo perfecto para creadores de contenido.',
    images: [img('colombia/products/2211461/1784917122magnific_1.-input-image-plantilla-_wPSg9Vi7EI.png')],
  },

  // ---------------- FITNESS ----------------
  {
    id: '2042806',
    slug: 'set-bandas-elasticas-resistencia',
    name: 'Set de Bandas Elásticas de Resistencia',
    price: 40900,
    category: 'Fitness',
    description:
      'Set de bandas elásticas circulares con distintos niveles de resistencia. Ideales para glúteos, ' +
      'piernas y entrenamiento en casa. Livianas, portátiles y perfectas para tonificar.',
    images: [img('colombia/products/2042806/176894863759.png')],
  },
  {
    id: '1983913',
    slug: 'barra-puerta-ejercicios',
    name: 'Barra de Puerta para Ejercicios',
    price: 55000,
    category: 'Fitness',
    description:
      'Barra fija para marco de puerta: haz dominadas, flexiones y trabajo de espalda y brazos en casa. ' +
      'Instalación sin tornillos, resistente y ajustable. Tu gimnasio en casa.',
    images: [img('colombia/products/1983913/1768931231WhatsApp Image 2026-01-20 at 12.45.40 PM.jpeg')],
  },
  {
    id: '1074680',
    slug: 'colchoneta-mat-yoga',
    name: 'Colchoneta / Mat para Yoga y Ejercicio',
    price: 47000,
    category: 'Fitness',
    description:
      'Tapete antideslizante para yoga, pilates y ejercicio. Acolchado para proteger articulaciones, ' +
      'fácil de enrollar y transportar. Superficie cómoda y duradera.',
    images: [img('colombia/products/1074680/1723584061TAPETE YOGA 5.jpeg')],
  },
  {
    id: '1931141',
    slug: 'pistola-masaje-recargable',
    name: 'Pistola de Masaje Portátil Recargable',
    price: 32000,
    category: 'Fitness',
    description:
      'Masajeador muscular tipo pistola con varias velocidades y cabezales intercambiables. Alivia ' +
      'tensión y acelera la recuperación después de entrenar. Recargable y silencioso.',
    images: [img('colombia/products/1931141/17582469331000110782.jpg')],
  },
  {
    id: '296625',
    slug: 'toalla-refrescante-gimnasio',
    name: 'Toalla Refrescante para Gimnasio',
    price: 29900,
    category: 'Fitness',
    description:
      'Toalla de enfriamiento que se activa con agua para refrescarte durante el ejercicio, el deporte ' +
      'o el calor. Ligera, reutilizable e incluye estuche. Un básico del gym.',
    images: [img('colombia/products/296625/17018918801701891880Toalla Refrescante 5.jpg')],
  },
  {
    id: '440337',
    slug: 'mini-masajeador-parche-8-modos',
    name: 'Mini Masajeador Eléctrico 8 Modos',
    price: 32000,
    category: 'Fitness',
    description:
      'Parche masajeador eléctrico con 8 modos y niveles de intensidad. Relaja cuello, espalda y ' +
      'piernas después del entrenamiento. Compacto, recargable y fácil de usar.',
    images: [img('colombia/products/440337/1697229992MASAJEADOR 0.7.jpeg')],
  },
];

export const getProduct = (slug) => products.find((p) => p.slug === slug);
export const categories = [...new Set(products.map((p) => p.category))].sort();
