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
- **Reconectar Dropi**: abre una ventana con el perfil de los agentes
  (`data/navegador-dropi`). Si la sesión sigue viva te avisa y se cierra; si no,
  inicias sesión ahí. (Chrome no deja que un programa maneje tu perfil normal,
  por eso los agentes tienen el suyo.)
- **Aprender búsqueda de Dropi**: abre el catálogo; pones los filtros con los que
  encuentras productos top («Con órdenes», categoría, orden), aplicas y cierras la
  ventana. Los agentes repiten esa búsqueda.
- **Publicar en mi Chrome**: abre Marketplace en tu Chrome con tu sesión, deja la
  descripción copiada y las fotos en Finder; título y precio se copian del panel.

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
2. **Cotización de fletes**: ya no hay que calibrar nada. El analista cotiza como el
   formulario «Crear orden» de Dropi (ciudades del departamento, bodega de origen del
   producto y tarifa de cada transportadora), toma la más barata por ciudad y deja el
   detalle en `data/cotizaciones/<id>.json`. Solo necesita la sesión de Dropi activa.
   La calibración completa sigue disponible por si Dropi cambia su web:
   ```bash
   cd agentes && uv run --with playwright==1.60.0 python cotizador.py calibrar
   ```
   Se abre un Chromium con el perfil de Dropi. Inicias sesión, pones en el
   catálogo los filtros con los que buscas productos top («Con órdenes»), armas
   una orden ficticia hasta ver el flete (**sin confirmarla**) y respondes en la
   terminal la ciudad y el valor que viste. Desde ahí el analista trae productos
   con esa búsqueda, cotiza las 4 ciudades de cada uno y reemplaza los precios
   provisionales.
3. Los productos prohibidos en Marketplace (suplementos, réplicas, armas, perfumes…)
   se descartan con una regla fija además del criterio del modelo (`PROHIBIDOS` en
   `orquestador.py`).

Si prefieres no calibrar, puedes poner los fletes a mano en
`agentes/data/fletes_manuales.json`:

```json
{ "2099675": { "BOGOTA": 12500, "MEDELLIN": 13000, "CALI": 14500, "BARRANQUILLA": 16000 } }
```

## Ajustes

Todo está en [`config.json`](config.json): modelos, ciudades, ganancia mínima,
markup, terminación del precio (…900), palabras de búsqueda en Dropi y cada
cuánto se revisa el catálogo.
