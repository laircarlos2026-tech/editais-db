#!/usr/bin/env python3
"""
download_local.py — Baixa editais do Localizador de Editais e salva no GitHub
=============================================================================
Como usar:
  1. Abra https://painel.localizadordeeditais.com.br/buscador no Chrome
  2. Pressione F12 → Console
  3. Cole: copy(LC_SAAS.nonce)   → cole o valor em NONCE abaixo
  4. Cole: copy(document.cookie) → cole o valor em COOKIE abaixo
  5. Rode: python download_local.py

Dependências:
  pip install requests
"""

import requests
import json
import os
import sys
import subprocess
from datetime import datetime, timedelta

# ══════════════════════════════════════════════════
#  CONFIGURE AQUI — cole os valores do console F12
# ══════════════════════════════════════════════════

NONCE  = "COLE_SEU_NONCE_AQUI"    # LC_SAAS.nonce no console
COOKIE = "COLE_SEU_COOKIE_AQUI"   # document.cookie no console

# ══════════════════════════════════════════════════
#  CONFIGURAÇÕES OPCIONAIS
# ══════════════════════════════════════════════════

# Quantos dias atrás buscar editais (padrão: 60 dias)
DIAS_ATRAS = 60

# Quantos editais por página
PER_PAGE = 50

# Máximo de páginas (None = sem limite)
MAX_PAGINAS = None

# Pasta de saída (relativa ao script)
OUTPUT_DIR = "data"

# URL base da API
API_BASE = "https://painel.localizadordeeditais.com.br/wp-json/lc/v1/licitacoes"

# ══════════════════════════════════════════════════


def check_config():
    if "COLE_SEU" in NONCE or "COLE_SEU" in COOKIE:
        print("❌  Configure o NONCE e o COOKIE no início do script antes de rodar.")
        print()
        print("   Passos:")
        print("   1. Abra o site no Chrome e faça login")
        print("   2. F12 → Console")
        print("   3. copy(LC_SAAS.nonce)   → cole em NONCE")
        print("   4. copy(document.cookie) → cole em COOKIE")
        sys.exit(1)


def build_headers():
    return {
        "X-WP-Nonce": NONCE,
        "Cookie": COOKIE,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://painel.localizadordeeditais.com.br/buscador/",
        "Accept": "application/json",
    }


def fetch_page(session, page, date_from):
    params = {
        "page": page,
        "per_page": PER_PAGE,
        "prazo_ini": date_from,
        "orderby": "data_abertura",
        "order": "asc",
    }
    r = session.get(API_BASE, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def normalize_edital(e):
    """Extrai só os campos necessários para a extensão."""
    return {
        "id":            e.get("id") or e.get("numero_edital", ""),
        "objeto":        (e.get("objeto") or "")[:200],
        "cidade":        e.get("municipio") or e.get("cidade") or "",
        "uf":            e.get("uf") or "",
        "data_abertura": e.get("data_abertura") or e.get("abertura") or "",
        "valor":         e.get("valor_estimado") or e.get("valor") or 0,
        "modalidade":    e.get("modalidade") or "",
        "orgao":         (e.get("orgao") or "")[:100],
    }


def save_files(editais, version):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    editais_path = os.path.join(OUTPUT_DIR, "editais.json")
    meta_path    = os.path.join(OUTPUT_DIR, "meta.json")

    with open(editais_path, "w", encoding="utf-8") as f:
        json.dump(editais, f, ensure_ascii=False, separators=(",", ":"))

    meta = {
        "version":    version,
        "total":      len(editais),
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "dias_atras": DIAS_ATRAS,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(editais_path) / 1024
    print(f"\n💾  {editais_path} ({size_kb:.1f} KB) — {len(editais)} editais")
    print(f"📋  {meta_path}")
    return editais_path, meta_path


def push_to_github(files):
    """Faz commit e push para o GitHub se o diretório for um repositório git."""
    try:
        # Verifica se é um repositório git
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print("\n⚠️  Diretório não é um repositório git — pulando push automático.")
            print("    Para fazer push manual: git add data/ && git commit -m 'atualiza editais' && git push")
            return

        print("\n📤  Fazendo push para o GitHub...")
        subprocess.run(["git", "add"] + list(files), check=True)
        version = datetime.now().strftime("%Y%m%d")
        subprocess.run(
            ["git", "commit", "-m", f"atualiza editais {version}"],
            check=True
        )
        subprocess.run(["git", "push"], check=True)
        print("✅  Push concluído!")

    except subprocess.CalledProcessError as e:
        print(f"\n⚠️  Erro no git: {e}")
        print("    Faça push manualmente: git add data/ && git commit -m 'atualiza editais' && git push")
    except FileNotFoundError:
        print("\n⚠️  Git não encontrado — faça push manualmente.")


def main():
    check_config()

    date_from = (datetime.now() - timedelta(days=DIAS_ATRAS)).strftime("%Y-%m-%d")
    version   = datetime.now().strftime("%Y%m%d")

    print(f"🔍  Buscando editais a partir de {date_from} ({DIAS_ATRAS} dias)...")
    print()

    session = requests.Session()
    session.headers.update(build_headers())

    # Detecta total de páginas na primeira requisição
    try:
        first = fetch_page(session, 1, date_from)
    except requests.HTTPError as e:
        if e.response.status_code == 403:
            print("❌  Erro 403 — autenticação falhou.")
            print("   Verifique se o NONCE e o COOKIE ainda são válidos.")
            print("   Pegue valores novos no console F12 do Chrome.")
        else:
            print(f"❌  Erro HTTP {e.response.status_code}: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌  Erro: {e}")
        sys.exit(1)

    # Descobre total de páginas
    total_pages = 1
    if isinstance(first, dict):
        total_pages = first.get("pages") or first.get("total_pages") or 1
        items = first.get("data") or first.get("items") or []
    elif isinstance(first, list):
        items = first
        # Estima páginas pelo header (requests armazena em r.headers mas já perdemos)
        if len(items) == PER_PAGE:
            total_pages = 999  # sem info, vamos até acabar
    else:
        print(f"❌  Resposta inesperada da API: {type(first)}")
        sys.exit(1)

    if MAX_PAGINAS:
        total_pages = min(total_pages, MAX_PAGINAS)

    print(f"📄  Total de páginas: {total_pages if total_pages < 999 else '?'}")

    # Coleta todos os editais
    all_ids    = set()
    all_editais = []

    def process_items(items_list):
        for e in items_list:
            eid = e.get("id") or e.get("numero_edital")
            if eid and eid in all_ids:
                continue
            if eid:
                all_ids.add(eid)
            all_editais.append(normalize_edital(e))

    process_items(items)

    for page in range(2, total_pages + 1):
        try:
            data = fetch_page(session, page, date_from)
            if isinstance(data, dict):
                page_items = data.get("data") or data.get("items") or []
            elif isinstance(data, list):
                page_items = data
            else:
                break

            if not page_items:
                break  # chegou ao fim

            process_items(page_items)

            # Progress
            bar_len = 30
            filled  = int(bar_len * page / total_pages) if total_pages < 999 else (page % bar_len)
            bar     = "█" * filled + "░" * (bar_len - filled)
            print(f"\r   [{bar}] página {page}/{total_pages if total_pages < 999 else '?'} — {len(all_editais)} editais", end="", flush=True)

        except KeyboardInterrupt:
            print(f"\n\n⏹  Interrompido pelo usuário na página {page}.")
            break
        except Exception as e:
            print(f"\n⚠️  Erro na página {page}: {e} — continuando...")
            continue

    print()  # nova linha após a barra de progresso

    if not all_editais:
        print("❌  Nenhum edital coletado. Verifique as credenciais.")
        sys.exit(1)

    print(f"\n✅  {len(all_editais)} editais únicos coletados em {total_pages if total_pages < 999 else page} páginas")

    # Salva arquivos
    editais_path, meta_path = save_files(all_editais, version)

    # Push para GitHub
    push_to_github([editais_path, meta_path])

    print("\n🎉  Concluído! A extensão vai detectar a versão nova automaticamente.")


if __name__ == "__main__":
    main()
