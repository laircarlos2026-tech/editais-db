"""
sincronizar_db.py
------------------
Lê o editais.json local e sincroniza com o PostgreSQL do Railway.
Rode após o atualizar.py para manter o banco atualizado.

Instalação:
    pip install psycopg2-binary

Uso:
    set DATABASE_PUBLIC_URL=postgresql://postgres:SENHA@HOST:PORT/railway
    python sincronizar_db.py

Ou coloque no .env e use python-dotenv.
"""

import os
import json
import sys
import time
from pathlib import Path

# ── Carrega .env se existir ──
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# ── Verifica DATABASE_PUBLIC_URL ──
if not os.environ.get("DATABASE_URL") and not os.environ.get("DATABASE_PUBLIC_URL"):
    print("❌ DATABASE_PUBLIC_URL não definida!")
    print("\nComo configurar:")
    print("  1. Railway → Postgres-c6Eo → Variables → DATABASE_PUBLIC_URL")
    print("  2. Copie o valor e cole aqui:")
    print("     set DATABASE_PUBLIC_URL=postgresql://postgres:SENHA@HOST:PORT/railway")
    print("\n  Ou crie um arquivo .env na pasta com:")
    print("     DATABASE_PUBLIC_URL=postgresql://postgres:SENHA@HOST:PORT/railway")
    sys.exit(1)

# Garante que DATABASE_URL aponta para a URL pública quando rodando local
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["DATABASE_PUBLIC_URL"]

import db  # importa após setar DATABASE_URL

PASTA    = Path(__file__).parent
OUT_FILE = PASTA / "data" / "editais.json"


def main():
    print("=" * 55)
    print("  📤 SINCRONIZADOR: JSON → PostgreSQL")
    print("=" * 55)

    # 1. Cria tabela se não existir
    db.criar_tabela()

    # 2. Carrega JSON local
    if not OUT_FILE.exists():
        print(f"❌ {OUT_FILE} não encontrado. Rode atualizar.py primeiro.")
        sys.exit(1)

    print(f"📂 Lendo {OUT_FILE}...")
    t0 = time.time()
    editais = json.loads(OUT_FILE.read_text(encoding="utf-8"))
    print(f"   {len(editais):,} editais carregados em {time.time()-t0:.1f}s")

    # 3. Insere no banco
    print(f"🔄 Sincronizando com o PostgreSQL...")
    t1 = time.time()
    total = db.inserir_editais(editais)
    print(f"✅ {total:,} registros sincronizados em {time.time()-t1:.1f}s")

    # 4. Contagem final
    count = db.total_editais()
    print(f"📊 Total no banco: {count:,} editais")


if __name__ == "__main__":
    main()
