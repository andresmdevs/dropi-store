"""Precio único para Marketplace a partir del flete de las ciudades de referencia.

Ver docs/MODELO-DE-NEGOCIO.md, paso 3.
"""
from __future__ import annotations

import math

from comun import CONFIG


def redondear(valor: float, terminacion: int) -> int:
    """Sube al siguiente número que termina en `terminacion` (900 -> 79.900)."""
    base = 1000
    precio = math.floor(valor / base) * base + terminacion
    if precio < valor:
        precio += base
    return int(precio)


def calcular(costo: int, fletes: dict[str, int] | None, precio_referencia: int | None = None) -> dict:
    """Devuelve precio, ganancia por ciudad y alertas.

    - Con fletes: precio = costo + flete promedio + ganancia objetivo.
    - Sin fletes: usa `precio_referencia` (precio de la tienda) y lo marca provisional.
    """
    p = CONFIG["precios"]
    alertas: list[str] = []

    if fletes:
        promedio = sum(fletes.values()) / len(fletes)
        objetivo = max(p["ganancia_minima"], costo * p["markup"])
        precio = redondear(costo + promedio + objetivo, p["terminacion"])
        por_ciudad = {c: precio - costo - f for c, f in fletes.items()}
        piso = p["ganancia_minima"] / 2
        flojas = [c for c, g in por_ciudad.items() if g < piso]
        if flojas:
            alertas.append(f"Poca ganancia en {', '.join(flojas)}")
        faltan = [c for c in p["ciudades"] if c not in fletes]
        if faltan:
            alertas.append(f"Sin cotización en {', '.join(faltan)}")
        return {
            "precio": precio,
            "provisional": False,
            "flete_promedio": round(promedio),
            "ganancia_por_ciudad": por_ciudad,
            "ganancia_estimada": round(precio - costo - promedio),
            "alertas": alertas,
        }

    if precio_referencia:
        alertas = ["Precio provisional (el de la tienda): falta cotizar el flete"]
        margen_bruto = int(precio_referencia) - costo
        if margen_bruto < p["ganancia_minima"]:
            alertas.append(f"Antes del flete solo quedan ${margen_bruto:,}".replace(",", ".")
                           + ": no alcanza para flete + ganancia mínima. No lo publiques hasta cotizar.")
        return {
            "precio": int(precio_referencia),
            "provisional": True,
            "flete_promedio": None,
            "margen_antes_de_flete": margen_bruto,
            "ganancia_por_ciudad": {},
            "ganancia_estimada": None,
            "alertas": alertas,
        }

    return {"precio": None, "provisional": True, "alertas": ["Sin flete ni precio de referencia"]}
