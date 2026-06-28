import type { APIRoute } from 'astro';
import { createOrder, dropiConfigured } from '../../lib/dropi';

export const prerender = false;

const REQUIRED = ['name', 'phone', 'address', 'city', 'productId'] as const;

export const POST: APIRoute = async ({ request }) => {
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });

  let data: Record<string, any>;
  try {
    data = await request.json();
  } catch {
    return json({ ok: false, error: 'Body inválido (se espera JSON).' }, 400);
  }

  for (const field of REQUIRED) {
    if (!data[field]) return json({ ok: false, error: `Campo requerido: ${field}` }, 400);
  }

  // Sin credenciales de Dropi todavía -> modo DEMO: el sitio funciona end-to-end
  // y queda listo para crear órdenes reales en cuanto pongas la llave.
  if (!dropiConfigured()) {
    return json({
      ok: true,
      demo: true,
      message:
        'Pedido recibido en modo DEMO. Configura DROPI_INTEGRATION_KEY para crear la orden real en Dropi.',
      order: data,
    });
  }

  try {
    const order = await createOrder({
      name: data.name,
      phone: data.phone,
      address: data.address,
      // TODO: mapear el nombre de la ciudad -> city_id usando getCities() y un cache.
      cityId: Number(data.cityId) || 0,
      notes: data.notes,
      products: [
        {
          id: Number(data.productId),
          price: Number(data.price) || 0,
          quantity: Number(data.quantity) || 1,
        },
      ],
      collectionType: 'CON_RECAUDO',
      shopOrderId: `web-${Date.now()}`,
    });
    return json({ ok: true, order });
  } catch (e) {
    return json({ ok: false, error: e instanceof Error ? e.message : String(e) }, 500);
  }
};
