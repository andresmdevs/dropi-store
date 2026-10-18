#!/bin/zsh
# Guarda en .env.local el token de Meta que copiaste (⌘C), sin mostrarlo en pantalla.
# Uso: copia el token del Usuario del sistema y corre ./agentes/guardar_token_meta.sh
set -e
ENV=${0:A:h}/../.env.local
TOKEN=$(pbpaste | tr -d '[:space:]')
if [[ "$TOKEN" != EAA* || ${#TOKEN} -lt 100 ]]; then
  echo "⚠️  Lo que hay en el portapapeles no parece un token de Meta (debe empezar por EAA). Cópialo de nuevo."
  exit 1
fi
touch "$ENV"
grep -v '^META_TOKEN=' "$ENV" > "$ENV.tmp" || true
echo "META_TOKEN=$TOKEN" >> "$ENV.tmp"
mv "$ENV.tmp" "$ENV"
chmod 600 "$ENV"
echo -n "" | pbcopy   # limpia el portapapeles
echo "✅ Token guardado (${#TOKEN} caracteres). Ahora dale «Verificar conexión» en el panel."
