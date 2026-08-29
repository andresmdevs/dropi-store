export const STORE_NAME = 'Monkey Store';

// WhatsApp del negocio (código país 57 = Colombia).
export const WHATSAPP = '573008427074';

// Identificación del vendedor. La Ley 1480 de 2011 (art. 50) obliga a publicar
// quién vende y cómo contactarlo.
//
// Se publica nombre, correo y WhatsApp. NO se publican cédula ni dirección de
// residencia: como persona natural el NIT es la cédula, y exponerla es
// justamente el vector de suplantación que queremos evitar. Cuando exista un
// establecimiento de comercio o una SAS, ahí sí van NIT y dirección comercial.
export const SELLER = {
  legalName: 'Andrés Felipe Mora Vélez',
  email: 'andreshcp@gmail.com',
  // Se dejan vacíos a propósito; la página omite la fila si no hay valor.
  taxId: '',
  address: '',
};

/** Campos mínimos para que la página de identificación tenga sentido. */
export const sellerComplete = Boolean(SELLER.legalName && SELLER.email);
