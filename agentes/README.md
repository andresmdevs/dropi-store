# Agentes locales de Monkey Store

Dos agentes con modelos de Ollama que trabajan solos sobre el proceso de
[`docs/MODELO-DE-NEGOCIO.md`](../docs/MODELO-DE-NEGOCIO.md).

| Agente | Modelo | Qué hace |
|---|---|---|
| analista | `qwen-tools` | Trae catálogo de Dropi, evalúa cada producto, cotiza el flete y pone el precio |
| redactor | `gemma-work` | Mira la foto y escribe el anuncio de Marketplace; lo deja en la cola. Marca las fotos con teléfonos o marcas de otros vendedores |

El estado de los dos, y de cualquier otro proyecto que use Ollama, se ve en
**http://localhost:8790** (`~/code/personal/llm-panel`).

## Etapas de un producto

```
nuevo → evaluado → con_precio → en_cola → publicado
            └→ descartado
```

Cada producto es un archivo en `agentes/data/productos/<id>.json`. El paso a
**publicado** lo das tú en el panel («Ya lo publiqué»), después de publicar en
Facebook.

## Cómo se maneja

Lo normal es usar la app **Monkey Agentes** (Aplicaciones o barra de menú 🐒) o
el panel en http://localhost:8790:

- **Pausar / Seguir / Trabajar ahora**: escriben `data/control.json`; los agentes
  terminan lo que estén haciendo y obedecen.
- **Reconectar Dropi / Facebook**: abre una ventana con el perfil del agente
  (`data/navegador-dropi`, `data/navegador-facebook`); inicias sesión y se cierra sola.
- **Publicar con asistente**: llena el formulario de Marketplace y te deja el clic
  final.

El servicio corre con `caffeinate -i`, así el Mac no se duerme por inactividad
mientras trabaja (cerrar la tapa sí lo duerme).

```bash
./agentes/instalar.sh                     # instala o reinicia el servicio (launchd, 24/7)
./agentes/instalar.sh quitar              # lo detiene y lo desinstala
python3 agentes/orquestador.py --una-vez  # un ciclo de prueba en primer plano
tail -f agentes/data/logs/launchd.log     # qué está haciendo
```

## Lo que necesita de ti (una sola vez)

1. **Token de Dropi** (opcional si calibras): Dropi → Integraciones → Generar
   token, y pegarlo en `.env.local` como `DROPI_INTEGRATION_KEY`. Si no hay token,
   el analista usa la búsqueda del catálogo que aprende la calibración.
2. **Calibrar el cotizador** (unos 3 minutos):
   ```bash
   cd agentes && uv run --with playwright==1.60.0 python cotizador.py calibrar
   ```
   Se abre un Chromium con el perfil de Dropi. Inicias sesión, pones en el
   catálogo los filtros con los que buscas productos top («Con órdenes»), armas
   una orden ficticia hasta ver el flete (**sin confirmarla**) y respondes en la
   terminal la ciudad y el valor que viste. Desde ahí el analista trae productos
   con esa búsqueda, cotiza las 4 ciudades de cada uno y reemplaza los precios
   provisionales.
3. **Conectar Facebook** una vez con «Reconectar Facebook», para que el
   asistente de publicación pueda abrir el formulario.

Si prefieres no calibrar, puedes poner los fletes a mano en
`agentes/data/fletes_manuales.json`:

```json
{ "2099675": { "BOGOTA": 12500, "MEDELLIN": 13000, "CALI": 14500, "BARRANQUILLA": 16000 } }
```

## Ajustes

Todo está en [`config.json`](config.json): modelos, ciudades, ganancia mínima,
markup, terminación del precio (…900), palabras de búsqueda en Dropi y cada
cuánto se revisa el catálogo.
