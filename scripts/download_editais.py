"""
Script: download_editais.py
Baixa editais dos últimos 60 dias da API do Localizador de Editais
e salva em data/editais.json e data/meta.json

Configuração (GitHub Secrets):
  SITE_NONCE  → valor de LC_SAAS.nonce (obtenha abrindo o site e rodando no console: LC_SAAS.nonce)
  SITE_COOKIE → cookie de sessão (obtenha no DevTools → Application → Cookies → wordpress_logged_in_*)

Como obter os valores:
  1. Abra painel.localizadordeeditais.com.br/buscador
  2. Abra DevTools (F12) → Console
  3. Digite: LC_SAAS.nonce  → copie o valor para SITE_NONCE
  4. DevTools → Application → Cookies → copie o cookie wordpress_logged_in_* para SITE_COOKIE
"""

import requests
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Configuração ──────────────────────────────────────────────────────────────

API_BASE   = "https://painel.localizadordeeditais.com.br/wp-json/lc/v1/licitacoes"
NONCE      = os.environ.get("SITE_NONCE", "")
COOKIE     = os.environ.get("SITE_COOKIE", "")
PER_PAGE   = 50
DELAY_SECS = 0.5      # delay entre requisições (respeita o servidor)
DAYS_BACK  = 60       # busca editais dos últimos X dias
MAX_PAGES  = 200      # limite de segurança (200 × 50 = 10.000 editais)

OUTPUT_DIR  = Path("data")
OUTPUT_FILE = OUTPUT_DIR / "editais.json"
META_FILE   = OUTPUT_DIR / "meta.json"

# ── Validação ─────────────────────────────────────────────────────────────────

if not NONCE:
    print("❌ SITE_NONCE não configurado. Adicione nos GitHub Secrets.")
    sys.exit(1)

if not COOKIE:
    print("⚠️  SITE_COOKIE não configurado. A API pode rejeitar as requisições.")

# ── Headers ───────────────────────────────────────────────────────────────────

headers = {
    "X-WP-Nonce": NONCE,
    "Cookie":     COOKIE,
    "User-Agent": "CSD-Extension-Updater/1.0 (github-actions; educational use)",
    "Accept":     "application/json",
}

# ── Data mínima ───────────────────────────────────────────────────────────────

date_from = (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")
print(f"📅 Buscando editais a partir de: {date_from}")

# ── Download ──────────────────────────────────────────────────────────────────

import time

all_items = []
page = 1
total_pages = None

while True:
    params = {
        "page":      page,
        "per_page":  PER_PAGE,
        "prazo_ini": date_from,   # filtro de data — só editais recentes
    }

    try:
        r = requests.get(API_BASE, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ Erro na página {page}: {e}")
        break

    # Detecta formato da resposta
    items = data.get("data") or data.get("licitacoes") or data.get("items") or (data if isinstance(data, list) else [])

    if not items:
        print(f"✅ Sem mais itens na página {page}. Encerrando.")
        break

    # Total de páginas (primeira vez)
    if total_pages is None:
        total = int(data.get("total") or data.get("meta", {}).get("total") or 0)
        total_pages = max(1, -(-total // PER_PAGE))  # ceil division
        total_pages = min(total_pages, MAX_PAGES)
        print(f"📊 Total de editais: {total} → {total_pages} páginas")

    # Extrai só os campos necessários (reduz tamanho do arquivo)
    for item in items:
        all_items.append({
            "id":         item.get("id") or item.get("licitacao_id"),
            "objeto":     (item.get("objeto") or "")[:200],  # trunca objeto longo
            "cidade":     item.get("cidade") or "",
            "uf":         item.get("uf") or "",
            "abertura":   item.get("data_abertura") or item.get("abertura") or "",
            "valor":      item.get("valor_estimado"),
            "modalidade": item.get("modalidade") or "",
            "orgao":      (item.get("orgao") or item.get("entidade") or "")[:100],
            "edital":     item.get("numero_edital") or item.get("edital") or "",
            "plataforma": item.get("plataforma") or "",
        })

    print(f"  Página {page}/{total_pages} — {len(all_items)} editais coletados")

    if page >= total_pages:
        break

    page += 1
    time.sleep(DELAY_SECS)  # respeita o servidor

# ── Salva arquivos ────────────────────────────────────────────────────────────

OUTPUT_DIR.mkdir(exist_ok=True)

# Remove duplicatas por ID
seen = set()
unique = []
for item in all_items:
    key = item.get("id") or item.get("edital")
    if key and key not in seen:
        seen.add(key)
        unique.append(item)

print(f"\n✅ {len(unique)} editais únicos coletados")

# Salva editais
with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(unique, f, ensure_ascii=False, separators=(",", ":"))

# Salva metadados
meta = {
    "updated_at":   datetime.now(timezone.utc).isoformat(),
    "total":        len(unique),
    "days_back":    DAYS_BACK,
    "date_from":    date_from,
    "version":      datetime.now(timezone.utc).strftime("%Y%m%d"),
}
with open(META_FILE, "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)

size_kb = OUTPUT_FILE.stat().st_size / 1024
print(f"💾 Arquivo: {OUTPUT_FILE} ({size_kb:.1f} KB)")
print(f"📋 Meta:    {META_FILE}")
print(f"🏷️  Versão:  {meta['version']}")
