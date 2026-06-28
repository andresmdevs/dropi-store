# 🛍️ dropi-store

Tienda de dropshipping con **pago contra entrega**, construida con **Astro + Supabase** e
integrada a la **API de Dropi**. Pensada para arrancar con **cero inversión**:

- Proveedor **gratis** (Dropi): sin inventario, pagas al vender.
- **Pago contra entrega (COD)**: no necesitas pasarela de pagos al inicio.
- Hosting **gratis** (Vercel) con **deploy automático en cada commit**.

## Stack

| Pieza        | Tecnología                         | Costo  |
|--------------|------------------------------------|--------|
| Frontend/SSR | Astro 5 (`output: server`)         | $0     |
| Hosting/CI   | Vercel (auto-deploy desde GitHub)  | $0     |
| Datos        | Supabase (Postgres + `jsonb`)      | $0     |
| Proveedor    | Dropi (API de Integraciones)       | $0     |
| Pagos        | Contra entrega (sin pasarela)      | $0     |

## Cómo correr en local

```bash
npm install
cp .env.example .env.local   # pega tus credenciales en .env.local
npm run dev                  # http://localhost:4321
```

> El sitio **funciona en modo demo sin credenciales**: muestra un catálogo de
> ejemplo y simula los pedidos. Cuando agregas la llave de Dropi, pasa a real.

## Variables de entorno

Crea `.env.local` (NO se sube a git) a partir de `.env.example`:

| Variable                   | Dónde se usa | Cómo obtenerla |
|----------------------------|--------------|----------------|
| `DROPI_INTEGRATION_KEY`    | servidor     | Dropi → Integraciones → Generar Token |
| `DROPI_API_URL`            | servidor     | `https://api.dropi.co` (o la URL de TEST) |
| `PUBLIC_SUPABASE_URL`      | navegador    | Supabase → Project Settings → API |
| `PUBLIC_SUPABASE_ANON_KEY` | navegador    | Supabase → Project Settings → API |

🔐 **Nunca** pongas la llave de Dropi en el código ni en el chat. Va solo en
`.env.local` (local) y en las *Environment Variables* de Vercel (producción).

## Integración con Dropi

El cliente está en [`src/lib/dropi.ts`](src/lib/dropi.ts). Si tu documentación de
Integraciones indica rutas distintas, ajusta **solo** el objeto `ENDPOINTS` (y, si
hace falta, los nombres de campos en `buildOrderBody()`). El resto no cambia.

Funciones disponibles: `getProducts`, `getCities`, `getCarriers`, `quoteFreight`,
`createOrder` (por defecto `CON_RECAUDO` = contra entrega).

## Deploy (pipeline gratuito)

1. Sube el repo a GitHub.
2. En [vercel.com](https://vercel.com) → *Add New Project* → importa el repo.
3. Agrega las *Environment Variables* (las mismas de `.env.local`).
4. Listo: cada `git push` a `main` redepliega automáticamente.

## Estructura

```
src/
  lib/
    dropi.ts        # cliente API de Dropi (server-only)
    supabase.ts     # cliente Supabase (null hasta configurar)
  pages/
    index.astro     # catálogo + checkout contra entrega
    api/
      orders.ts     # crea la orden en Dropi (POST)
```

## Roadmap

- [ ] Mapear ciudad → `city_id` de Dropi (cache de `getCities()`).
- [ ] Guardar pedidos en Supabase (tabla `orders`).
- [ ] Página de detalle de producto + SEO por producto.
- [ ] Dominio propio.
- [ ] (Fase 2) App móvil con Ionic/Capacitor sobre el mismo backend.
