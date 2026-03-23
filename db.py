"""
db.py — Módulo de acesso ao PostgreSQL
Compartilhado entre bot_editais.py e sincronizar_db.py
"""

import os
import json
import psycopg2
import psycopg2.extras
from datetime import datetime

# Railway injeta DATABASE_URL automaticamente no serviço do bot
# Para rodar local, defina DATABASE_PUBLIC_URL no .env ou no sistema
DATABASE_URL = (
    os.environ.get("DATABASE_URL") or
    os.environ.get("DATABASE_PUBLIC_URL") or
    ""
)

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL não definida. Configure a variável de ambiente.")


def conectar():
    """Retorna uma conexão com o PostgreSQL."""
    # Railway usa SSL internamente mas às vezes precisa de sslmode
    try:
        return psycopg2.connect(DATABASE_URL, sslmode="require")
    except Exception:
        return psycopg2.connect(DATABASE_URL)


def criar_tabela():
    """Cria a tabela de editais se não existir."""
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS editais (
                    id              TEXT PRIMARY KEY,
                    numero_edital   TEXT,
                    orgao_nome      TEXT,
                    orgao_cnpj      TEXT,
                    modalidade      TEXT,
                    objeto          TEXT,
                    valor_estimado  TEXT,
                    data_abertura   TIMESTAMP,
                    data_prazo      TIMESTAMP,
                    uf              TEXT,
                    cidade          TEXT,
                    situacao        TEXT,
                    url_site_oficial TEXT,
                    pncp_link       TEXT,
                    dados_completos JSONB,
                    atualizado_em   TIMESTAMP DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_editais_uf       ON editais(uf);
                CREATE INDEX IF NOT EXISTS idx_editais_cidade    ON editais(cidade);
                CREATE INDEX IF NOT EXISTS idx_editais_abertura  ON editais(data_abertura);
                CREATE INDEX IF NOT EXISTS idx_editais_prazo     ON editais(data_prazo);
            """)
        conn.commit()
    print("✅ Tabela 'editais' OK")


def parse_dt(valor):
    """Converte string de data para datetime ou None."""
    if not valor:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(valor)[:19], fmt)
        except Exception:
            continue
    return None


def inserir_editais(editais: list, batch_size=500) -> int:
    """
    Insere ou atualiza editais no banco (upsert por id).
    Retorna quantidade de registros processados.
    """
    if not editais:
        return 0

    sql = """
        INSERT INTO editais (
            id, numero_edital, orgao_nome, orgao_cnpj, modalidade,
            objeto, valor_estimado, data_abertura, data_prazo,
            uf, cidade, situacao, url_site_oficial, pncp_link,
            dados_completos
        ) VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            objeto          = EXCLUDED.objeto,
            valor_estimado  = EXCLUDED.valor_estimado,
            data_abertura   = EXCLUDED.data_abertura,
            data_prazo      = EXCLUDED.data_prazo,
            situacao        = EXCLUDED.situacao,
            dados_completos = EXCLUDED.dados_completos,
            atualizado_em   = NOW()
    """

    total = 0
    with conectar() as conn:
        with conn.cursor() as cur:
            for i in range(0, len(editais), batch_size):
                lote = editais[i:i+batch_size]
                valores = []
                for e in lote:
                    valores.append((
                        str(e.get("id", "")),
                        e.get("numero_edital"),
                        e.get("orgao_nome"),
                        e.get("orgao_cnpj"),
                        e.get("modalidade"),
                        e.get("objeto"),
                        str(e.get("valor_estimado") or "0"),
                        parse_dt(e.get("data_abertura")),
                        parse_dt(e.get("data_prazo")),
                        e.get("uf"),
                        e.get("cidade"),
                        e.get("situacao"),
                        e.get("url_site_oficial"),
                        e.get("pncp_link_sistema_origem"),
                        json.dumps(e, ensure_ascii=False),
                    ))  # 15 valores = 15 colunas
                psycopg2.extras.execute_values(cur, sql, valores)
                total += len(lote)
        conn.commit()
    return total


def buscar_editais(uf=None, cidade=None, data_ini=None, data_fim=None, limite=5000) -> list:
    """
    Busca editais com filtros opcionais.
    Retorna lista de dicts com os dados completos.
    """
    conditions = []
    params     = []

    if uf:
        conditions.append("UPPER(uf) = UPPER(%s)")
        params.append(uf)

    if cidade:
        conditions.append("UPPER(cidade) ILIKE %s")
        params.append(f"%{cidade}%")

    if data_ini:
        conditions.append("data_abertura >= %s")
        params.append(data_ini)

    if data_fim:
        conditions.append("data_abertura <= %s")
        params.append(data_fim)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    sql = f"""
        SELECT dados_completos
        FROM editais
        {where}
        ORDER BY data_abertura DESC
        LIMIT %s
    """
    params.append(limite)

    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    return [r[0] for r in rows if r[0]]


def total_editais() -> int:
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM editais")
            return cur.fetchone()[0]
