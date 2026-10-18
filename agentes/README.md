# Agentes locales de Monkey Store

Dos agentes con modelos de Ollama que trabajan solos sobre el proceso de
[`docs/MODELO-DE-NEGOCIO.md`](../docs/MODELO-DE-NEGOCIO.md).

| Agente | Modelo | Qué hace |
|---|---|---|
| analista | `qwen-tools` | Trae catálogo de Dropi, evalúa cada producto, cotiza el flete y pone el precio |
| redactor | `gemma-work` | Mira la foto y escribe el anuncio de Marketplace; lo deja en la cola |

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

## Comandos

```bash
./agentes/instalar.sh                     # instala o reinicia el servicio (launchd, 24/7)
./agentes/instalar.sh quitar              # lo detiene y lo desinstala
python3 agentes/orquestador.py --una-vez  # un ciclo de prueba en primer plano
tail -f agentes/data/logs/launchd.log     # qué está haciendo
```

## Lo que necesita de ti (una sola vez)

1. **Token de Dropi**: Dropi → Integraciones → Generar token, y pegarlo en
   `.env.local` como `DROPI_INTEGRATION_KEY`. Sin él no hay productos nuevos;
   los agentes siguen trabajando con el catálogo de la tienda.
2. **Calibrar el cotizador** (unos 3 minutos):
   ```bash
   cd agentes && uv run --with playwright==1.60.0 python cotizador.py calibrar
   ```
   Se abre un Chromium con un perfil propio. Inicias sesión en Dropi, armas una
   orden ficticia hasta ver el flete (**sin confirmarla**) y respondes en la
   terminal la ciudad y el valor que viste. Desde ahí el analista cotiza solo
   las 4 ciudades de cada producto y reemplaza los precios provisionales.

Si prefieres no calibrar, puedes poner los fletes a mano en
`agentes/data/fletes_manuales.json`:

```json
{ "2099675": { "BOGOTA": 12500, "MEDELLIN": 13000, "CALI": 14500, "BARRANQUILLA": 16000 } }
```

## Ajustes

Todo está en [`config.json`](config.json): modelos, ciudades, ganancia mínima,
markup, terminación del precio (…900), palabras de búsqueda en Dropi y cada
cuánto se revisa el catálogo.
