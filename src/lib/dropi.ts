/**
 * Cliente de la API de Integraciones de Dropi.
 *
 * Autenticación: header `dropi-integration-key`.
 *   -> Genera el token en: Dropi -> Integraciones -> Generar Token.
 *
 * Este módulo es SOLO de servidor: lee secretos desde `process.env`, así la
 * llave nunca se expone al navegador ni se sube al repo.
 *
 * ⚠️ CONFIRMA las RUTAS exactas en tu panel (Dropi -> Integraciones ->
 *    Documentación). Si difieren, ajusta únicamente el objeto ENDPOINTS y, si
 *    hace falta, los nombres de campos en buildOrderBody(). Todo lo demás queda igual.
 */

const BASE_URL = (process.env.DROPI_API_URL ?? 'https://api.dropi.co').replace(/\/$/, '');
const KEY = process.env.DROPI_INTEGRATION_KEY;

/** Rutas de la API. Ajusta aquí si tu documentación indica otras. */
const ENDPOINTS = {
  products: '/integrations/products',
  cities: '/integrations/cities',
  carriers: '/integrations/shipping-companies',
  quoteFreight: '/integrations/quote',
  orders: '/integrations/orders',
} as const;

export function dropiConfigured(): boolean {
  return Boolean(KEY);
}

async function dropiFetch<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  if (!KEY) {
    throw new Error(
      'Falta DROPI_INTEGRATION_KEY. Pégala en .env.local (local) o en las variables de entorno de Vercel.',
    );
  }
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      'dropi-integration-key': KEY,
      ...(init.headers ?? {}),
    },
  });
  const text = await res.text();
  let json: unknown;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = text;
  }
  if (!res.ok) {
    throw new Error(`Dropi API ${res.status} en ${path}: ${typeof json === 'string' ? json : JSON.stringify(json)}`);
  }
  return json as T;
}

// ---------------------------------------------------------------------------
// Tipos (shape aproximado; ajusta a la respuesta real de tu cuenta)
// ---------------------------------------------------------------------------

export interface DropiProduct {
  id: number;
  name: string;
  sale_price?: number;
  price?: number;
  stock?: number;
  gallery?: Array<{ url?: string; urlS3?: string }>;
  description?: string;
  [key: string]: unknown;
}

export interface CreateOrderInput {
  name: string;
  surname?: string;
  phone: string;
  address: string;
  cityId: number; // id de ciudad de Dropi (ver getCities)
  notes?: string;
  products: Array<{ id: number; price: number; quantity: number }>;
  /** CON_RECAUDO = pago contra entrega (cobras al entregar). */
  collectionType?: 'CON_RECAUDO' | 'SIN_RECAUDO';
  /** Tu id interno, para conciliar la venta. */
  shopOrderId?: string;
}

// ---------------------------------------------------------------------------
// Operaciones
// ---------------------------------------------------------------------------

/** Lista/consulta productos. Algunas cuentas usan GET; ajusta el método si tu doc lo indica. */
export function getProducts(filters: Record<string, unknown> = {}): Promise<unknown> {
  return dropiFetch(ENDPOINTS.products, { method: 'POST', body: JSON.stringify(filters) });
}

/** Ciudades disponibles (necesarias para obtener el city_id de una orden). */
export function getCities(): Promise<unknown> {
  return dropiFetch(ENDPOINTS.cities, { method: 'GET' });
}

/** Transportadoras disponibles. */
export function getCarriers(): Promise<unknown> {
  return dropiFetch(ENDPOINTS.carriers, { method: 'GET' });
}

/** Cotiza el flete para una ciudad/destino. */
export function quoteFreight(payload: Record<string, unknown>): Promise<unknown> {
  return dropiFetch(ENDPOINTS.quoteFreight, { method: 'POST', body: JSON.stringify(payload) });
}

function buildOrderBody(input: CreateOrderInput) {
  // ⚠️ Nombres de campos según la doc de Integraciones. Ajusta si tu cuenta difiere.
  return {
    name: input.name,
    surname: input.surname ?? '',
    phone: input.phone,
    direction: input.address,
    city_id: input.cityId,
    notes: input.notes ?? '',
    type: input.collectionType ?? 'CON_RECAUDO',
    shop_order_id: input.shopOrderId,
    products: input.products.map((p) => ({ id: p.id, price: p.price, quantity: p.quantity })),
  };
}

/** Crea una orden en Dropi (por defecto, pago contra entrega). */
export function createOrder(input: CreateOrderInput): Promise<unknown> {
  return dropiFetch(ENDPOINTS.orders, { method: 'POST', body: JSON.stringify(buildOrderBody(input)) });
}
