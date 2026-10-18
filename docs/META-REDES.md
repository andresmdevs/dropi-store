# Publicación automática en Facebook e Instagram (Monkey Store)

El agente **publicista** (`agentes/redes.py`, modelo `gemma-work`) publica solo
tres veces al día (9:00, 13:00 y 19:00) en la **Página de Facebook** y en el
**Instagram** de Monkey Store. Usa únicamente la API oficial de Meta con el token
de un **Usuario del sistema** del negocio:

- Lo publicado sale como **la Página** y como **la cuenta de Instagram del
  negocio**. Tu perfil personal no aparece como autor ante nadie.
- No usa navegador, cookies ni grupos, así que no hay nada que Facebook tenga que
  detectar ni bloquear.
- Solo publica productos con precio **cotizado de verdad** (flete de las 4
  ciudades). Nunca usa un precio provisional y no repite un producto en 21 días.
- Gemma escribe cada texto con una ciudad foco que va rotando (Medellín, Cali,
  Bogotá, Barranquilla). El programa pone el precio y el WhatsApp 311 791 8947,
  para que el modelo no se equivoque en los números.

Por qué no grupos ni Marketplace: Meta eliminó la API de grupos en abril de 2024,
y Marketplace no tiene API para tiendas pequeñas. Todo lo que publica ahí "en
automático" maneja tu cuenta personal con un navegador. Eso hace que la autora
seas tú y te expone a un bloqueo. La revisión completa de los repos está en el
historial del proyecto.

## Configuración (una sola vez, unos 30 minutos)

Tu cuenta personal se usa solo para **crear** las cosas. Queda como administradora
privada y no se muestra.

1. **Portafolio comercial.** En <https://business.facebook.com> crea el
   portafolio «Monkey Store».
2. **Página.** En *Configuración del negocio → Cuentas → Páginas → Agregar →
   Crear una Página nueva*, crea «Monkey Store». Así la Página es del negocio.
   - Categoría: Tienda de comercio electrónico.
   - Contacto: WhatsApp 311 791 8947 y el sitio <https://monkey-store.onrender.com>.
   - No pongas tu nombre en la información de la Página.
3. **Instagram.** Crea una cuenta nueva (por ejemplo `@monkeystore.co`). No uses
   tu Instagram personal.
   - Pásala a **cuenta profesional → Empresa**.
   - Vincúlala a la Página: *Página → Configuración → Cuentas vinculadas → Instagram*.
   - Agrégala al portafolio: *Configuración del negocio → Cuentas → Cuentas de Instagram*.
   - En el Centro de cuentas, no la unas a tu perfil personal de Facebook; basta
     con el vínculo a la Página.
4. **App.** En <https://developers.facebook.com/apps> crea una app de tipo
   **Empresa (Business)** y asóciala al portafolio Monkey Store.
   - Agrega los casos de uso para administrar la Página y publicar en Instagram
     (Instagram API con inicio de sesión de Facebook).
   - En *Configuración → Básica*, pon como política de privacidad
     <https://monkey-store.onrender.com/legal> y pasa la app a modo **Publicado
     (Live)**. Si queda en desarrollo, las publicaciones no son públicas.
5. **Usuario del sistema.** En *Configuración del negocio → Usuarios → Usuarios
   del sistema → Agregar*, crea «publicador-monkey» con rol **Empleado**. En
   *Asignar activos* dale:
   - la app (control total);
   - la Página (control total, o al menos crear contenido);
   - la cuenta de Instagram.
6. **Token.** En ese usuario del sistema, *Generar nuevo token*:
   - Elige la app.
   - Caducidad: **Nunca**.
   - Permisos: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`,
     `instagram_basic`, `instagram_content_publish` y `business_management`.
     Agrega `ads_read` solo si Instagram responde con un error de permisos.
7. **ID de la Página.** Está en *Página → Información → Transparencia de la
   página* (un número largo).
8. **Pégalos en `dropi-store/.env.local`** (no se sube a git):
   ```
   META_TOKEN=EAAG...
   META_PAGE_ID=123456789012345
   ```
9. En el panel (<http://localhost:8790>), tarjeta **Redes de Monkey Store**:
   - **Verificar conexión**: debe decir «Publica como Monkey Store y @...».
   - **Publicar uno ahora**, si quieres probar sin esperar al siguiente turno.

## Uso diario

- Desde el panel puedes **pausar o reanudar** solo las redes, sin parar a los
  demás agentes.
- Horarios, fotos por publicación, días sin repetir y hashtags están en
  `agentes/config.json` → `redes`.
- Cada publicación queda en `agentes/data/redes.json`, con los enlaces de
  Facebook e Instagram.
- Ensayo sin publicar nada: `python3 agentes/redes.py ensayo`.

## Para que tu perfil personal no aparezca

- Publica solo con el token del Usuario del sistema. No publiques ni compartas
  desde tu perfil.
- La Página y el Instagram deben ser **del portafolio**, no de tu perfil.
- La transparencia de la Página muestra la fecha de creación y, en Páginas
  grandes, el **país** de quienes la administran, nunca nombres.
- El sitio web sí debe mostrar quién vende (Ley 1480, página `/legal`). Eso es
  aparte de las redes.
