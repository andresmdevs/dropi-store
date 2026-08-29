export const STORE_NAME = 'Monkey Store';

// WhatsApp del negocio (código país 57 = Colombia).
export const WHATSAPP = '573008427074';

// Identificación del vendedor. La Ley 1480 de 2011 (art. 50) obliga a publicar
// quién vende, su identificación y una dirección de notificación.
//
// ⚠️ COMPLETAR ANTES DE PROMOCIONAR EL SITIO. Mientras estos campos estén vacíos,
// /legal muestra un aviso visible de que faltan. No los llenes con datos inventados:
// un NIT falso es peor que no tener página legal.
export const SELLER = {
  legalName: '',   // Ej: 'Andrés Mora' o la razón social de tu empresa
  taxId: '',       // Ej: 'C.C. 1.234.567.890' o 'NIT 901.234.567-8'
  address: '',     // Ej: 'Calle 10 # 43-25, Medellín, Antioquia'
  email: '',       // Correo de contacto real y monitoreado
};

export const sellerComplete = Object.values(SELLER).every((v) => v.trim() !== '');
