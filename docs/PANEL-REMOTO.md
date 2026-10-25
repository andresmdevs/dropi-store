# Panel remoto de Monkey Store

El panel se aloja en el servicio web declarado por `render.yaml`, junto al
webhook y la cola PostgreSQL. Es una PWA responsive: en iPhone, abrir en Safari
y elegir **Compartir → Añadir a pantalla de inicio**.

## Qué muestra y controla

- Estado de conexión del Mac, disponibilidad de Ollama, modelos cargados y
  latidos/tarea de los agentes de `dropi-store`.
- Conteos y casos en revisión de la cola de comentarios y mensajes.
- Acciones acotadas a iniciar o detener `com.andresmo.dropi-agentes`; no admite
  comandos de shell ni rutas elegidas desde el navegador.
- El puente local funciona de forma independiente al servicio de agentes. Para
  que el control remoto responda, el Mac debe estar encendido, con sesión de
  usuario activa y el puente instalado.

El panel no publica fichas de productos, prompts, logs de inferencia ni
documentos del RAG. Los datos de cliente no se usan como contexto de modelos.
Las respuestas se basan en reglas deterministas y datos verificados localmente;
los casos inciertos se dejan para revisión humana.

## Despliegue en Render

El Blueprint está configurado en el plan gratuito para permitir una prueba sin
crear recursos de pago. Es solo una modalidad de demostración, no adecuada para
depender de ella al atender clientes:

- El servicio web gratuito se duerme tras 15 minutos sin tráfico y puede tardar
  alrededor de un minuto en volver. Mientras el puente del Mac consulta cada
  10 segundos, normalmente lo mantendrá activo; cuando el Mac/puente estén
  desconectados, los webhooks pueden demorarse durante el arranque en frío.
- PostgreSQL gratuito tiene 1 GB, no ofrece copias de seguridad administradas y
  vence 30 días después de crearse. Tras vencer, hay 14 días para actualizarlo
  antes de que Render elimine la base y sus datos. Render también puede reiniciar
  o poner la base en mantenimiento.
- Antes de usarlo con clientes, exportar los datos necesarios y actualizar la
  base a un plan con persistencia apropiada; no confiar la única copia de una
  cola activa a esta base gratuita.

1. Crear un Blueprint desde `render.yaml`. Este crea el servicio web y la base
   PostgreSQL gratuitos. Revisar que Render muestre ambos recursos como
   gratuitos antes de confirmar; si solicita un plan de pago, detenerse y no
   confirmar.
2. Crear una GitHub OAuth App:
   - Homepage: `https://monkey-store-interacciones.onrender.com`
   - Callback: `https://monkey-store-interacciones.onrender.com/auth/github/callback`
   - Scope: `read:user`
   El acceso se restringe al login GitHub `andresmdevs` (la cuenta asociada al
   correo indicado); la autorización compara el nombre de usuario, no el correo.
3. En la configuración del servicio Render, añadir `GITHUB_OAUTH_CLIENT_ID` y
   `GITHUB_OAUTH_CLIENT_SECRET` como secretos. El Blueprint limita el login a
   `PANEL_GITHUB_USERS`; `PANEL_SESSION_SECRET` y
   `INTERACCIONES_QUEUE_TOKEN` son secretos generados por Render.
4. La sesión web dura 12 horas y usa cookie `Secure`, `HttpOnly`,
   `SameSite=Lax`, firma HMAC, CSRF y comprobación del origen. `/api/panel` y
   las acciones requieren sesión válida. Las rutas `/internal/` exigen el token
   de cola y nunca se llaman desde el navegador.
5. Meta no está activado por defecto. El webhook devuelve `503` hasta definir
   `META_APP_SECRET`, `META_WEBHOOK_VERIFY_TOKEN`, `META_PAGE_ID` y `META_IG_ID`.
   Esto permite desplegar el panel antes de terminar la configuración de Meta.

## Webhooks y cola de interacciones

Cuando la app de Meta esté lista, configurar como callback:
`https://monkey-store-interacciones.onrender.com/webhook`, con el valor de
`META_WEBHOOK_VERIFY_TOKEN`. Suscribir:

- Página: `feed`, `messages`.
- Instagram profesional: `comments`, `messages`.

Agregar en Render `META_APP_SECRET`, `META_WEBHOOK_VERIFY_TOKEN`, `META_PAGE_ID`
y `META_IG_ID`. Aplicar los permisos de comentarios y mensajería requeridos por
la versión de API de Meta y el tipo de cuenta; para clientes externos, Meta
puede exigir Advanced Access/App Review.

Los eventos se deduplican y se conservan en PostgreSQL mientras estén pendientes
o en revisión. El agente local procesa los pendientes en orden de llegada cuando
las respuestas están activadas; los casos sensibles/no reconocidos requieren
revisión. Al responder o marcar como atendido, se borra el texto del evento y
el registro procesado se purga después de 30 días.

## Conectar el Mac

En `.env.local` (excluido de git) definir:

```text
INTERACCIONES_QUEUE_URL=https://monkey-store-interacciones.onrender.com
INTERACCIONES_QUEUE_TOKEN=<copiado de Render; no compartir>
```

Instalar el puente sin reiniciar ni interrumpir los agentes:

```bash
./agentes/panel_puente.sh
```

El puente solo hace conexiones HTTPS salientes. Envía un latido cada 30
segundos y consulta acciones cada 10 segundos. Para desinstalar solo el puente:

```bash
./agentes/panel_puente.sh quitar
```

Si el Mac o el puente no están disponibles, el panel muestra el equipo como
desconectado. Una acción remota no se ejecuta hasta que el puente vuelva a
conectarse.
