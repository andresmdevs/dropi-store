# Modelo de negocio — Monkey Store (dropshipping con Dropi)

Este documento es la referencia para mí y para los agentes locales (`agentes/`).
Si un agente duda, manda lo que dice aquí.

## En una frase

Busco productos que ya se venden bien en **Dropi**, les pongo un precio único que
cubra el flete a cualquier ciudad de Colombia y los publico en **Facebook
Marketplace** con **pago contra entrega**. No tengo inventario: Dropi despacha
cuando entra un pedido.

## Cómo entra la plata

```
Precio que paga el cliente (contra entrega)
  − precio del proveedor en Dropi
  − flete (depende de la ciudad de destino)
  = mi ganancia
```

El flete cambia según el departamento o municipio, pero en Marketplace publico
**un solo precio para todo el país**. Por eso promedio el flete de cuatro
ciudades de referencia: **Bogotá, Medellín, Cali y Barranquilla**.

## El proceso, paso a paso

### 1. Buscar productos top en Dropi

- Catálogo de Dropi (`app.dropi.co/dashboard/search`), con el filtro
  **«Con órdenes»** activo y ordenado por lo que más se vende.
- Categorías que me funcionan: tecnología, audio, accesorios de celular,
  fitness, hogar.
- Un buen candidato tiene:
  - **stock** suficiente (más de 20 unidades);
  - **margen**: el precio sugerido de Dropi deja al menos $20.000 sobre costo y flete;
  - **fotos** limpias que se pueden usar en Marketplace;
  - nada de lo que prohíbe Marketplace (ver «Reglas»).

### 2. Cotizar el flete con una orden ficticia (sin confirmarla)

Para cada producto que voy a publicar armo una orden **de prueba** en Dropi con
direcciones ficticias en las cuatro ciudades y anoto el flete que muestra cada
transportadora.

> ⚠️ **Nunca se confirma la orden ficticia.** Solo se llega a la pantalla donde
> Dropi muestra el valor del envío. Una orden confirmada se despacha de verdad
> y la devolución la pago yo.

El agente hace lo mismo sin abrir el formulario: repite **solo la consulta de
cotización** que hace Dropi (ver `agentes/cotizador.py`) y nunca llama al
endpoint que crea órdenes.

### 3. Calcular el precio promedio

```
flete_promedio = promedio(flete Bogotá, Medellín, Cali, Barranquilla)
ganancia       = max(ganancia_minima, costo × markup)
precio         = costo + flete_promedio + ganancia, redondeado hacia arriba a ...900
```

Los valores (`ganancia_minima`, `markup`, redondeo) están en
`agentes/config.json`. Después se revisa cuánto gano en **cada** ciudad. Si en
alguna la ganancia queda por debajo de la mitad de la mínima, el producto se
marca para revisión.

Si todavía no hay cotización, el agente usa el precio de la tienda
(`src/data/products.json`) y lo marca como **provisional**.

### 4. Publicar en Facebook Marketplace

- **Título**: corto, con el nombre real del producto y el beneficio principal
  (máximo 80 caracteres).
- **Precio**: el promedio del paso 3.
- **Estado**: Nuevo.
- **Descripción**: qué es, para qué sirve, qué incluye y dos frases fijas:
  «Pago contra entrega en toda Colombia» y «Envío incluido».
- **Fotos**: las del proveedor en Dropi (están en `public/products/`).
- **Ritmo**: máximo 10 publicaciones al día y textos distintos entre sí, para
  que Facebook no lo trate como spam.

**El clic en «Publicar» lo hago yo.** Los agentes dejan cada anuncio listo en la
cola del panel. El botón **«Publicar en mi Chrome»** abre el formulario de
Marketplace en mi Chrome (con mi sesión), deja la descripción copiada y las
fotos listas en Finder para arrastrarlas; título y precio se copian desde el
panel. Al terminar marco «Ya lo publiqué».
Publicar con un bot sin intervención va contra los términos de Facebook y es la
forma más rápida de perder la cuenta.

### 5. Cuando entra un pedido

1. El cliente escribe por Marketplace o por WhatsApp al **311 791 8947** (el
   número del negocio; el anterior ya no se usa).
2. Confirmo nombre, celular, dirección y ciudad.
3. Creo la orden **real** en Dropi como contra entrega (`CON_RECAUDO`).
4. Hago seguimiento hasta la entrega. Las devoluciones salen de mi ganancia.

## Reglas para los agentes

1. **Nunca** confirmar ni crear órdenes en Dropi. Solo se cotiza.
2. **Nunca** publicar en Facebook. Solo se dejan anuncios en la cola.
3. **Nada** de suplementos, medicamentos, productos de salud con promesas
   médicas, armas, ni réplicas de marcas: Marketplace los prohíbe. Se marcan
   como `descartar`.
4. No inventar características. Si el dato no está en Dropi, no va en el anuncio.
5. Precios en pesos colombianos, sin decimales, con formato `$79.900`.
6. Todo en español de Colombia, con tono cercano y sin exagerar.
7. Si algo bloquea el trabajo (token vencido, sesión caída, cotizador sin
   calibrar, Ollama apagado), se reporta en el panel y se sigue con lo que sí se
   puede hacer.
8. El único teléfono del negocio es el **3117918947**. Si aparece el anterior
   (está en `agentes/config.json`) o el de otro vendedor en un texto o una foto,
   se corrige o se salta esa foto.

## Quién hace qué

| Paso | Lo hace | Modelo |
|---|---|---|
| Traer catálogo de Dropi | `agentes/orquestador.py` (API de Integraciones) | — |
| Evaluar y puntuar productos | Analista | `qwen-tools` |
| Cotizar flete en 4 ciudades | `agentes/cotizador.py` | — |
| Calcular precio promedio | `agentes/precios.py` | — |
| Redactar el anuncio | Redactor | `gemma-work` |
| Revisar fotos (teléfonos o marcas de otros) | Redactor | `gemma-work` |
| Publicar en Marketplace | Yo, desde mi Chrome con lo que prepara el panel | — |
| Crear la orden real | Yo, en Dropi | — |

El estado de los agentes y de todos los modelos locales se ve en el panel:
<http://localhost:8790> (proyecto `~/code/personal/llm-panel`). La app
**Monkey Agentes** (en Aplicaciones y en la barra de menú) lo arranca todo y
permite pausar, seguir y reconectar la sesión de Dropi de los agentes.
