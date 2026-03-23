"""
bot_editais.py
--------------
Bot Telegram para detectar anomalias em editais públicos.

Instalação:
    pip install python-telegram-bot requests tqdm

Uso:
    python bot_editais.py

Coloque este arquivo na mesma pasta do analisar_anomalias.py / atualizar.py
"""

import os, sys, json, re, math, time, unicodedata, threading, logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)

# ═══════════════════════════════════════════════
# CONFIG — ajuste aqui
# ═══════════════════════════════════════════════
PASTA         = os.path.dirname(os.path.abspath(__file__))
DATA_DIR      = os.path.join(PASTA, "data")
OUT_FILE      = os.path.join(DATA_DIR, "editais.json")

BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
MEU_CHAT_ID = int(os.environ.get("CHAT_ID", "0"))

if not BOT_TOKEN:
    print("❌ Variável BOT_TOKEN não definida.")
    sys.exit(1)
if not MEU_CHAT_ID:
    print("❌ Variável CHAT_ID não definida.")
    sys.exit(1)

BASE_URL       = "https://painel.localizadordeeditais.com.br"
ENDPOINT_ITENS = "/wp-json/lc/v1/licitacoes/{id}/itens"
HTTP_TIMEOUT   = 15
WORKERS        = 8
SCORE_MINIMO   = 40
MAX_RESULTADOS = 20   # máximo de anomalias retornadas por busca

# ═══════════════════════════════════════════════
# CREDENCIAIS DA API
# ═══════════════════════════════════════════════
def ler_arquivo(nome):
    p = os.path.join(PASTA, nome)
    if not os.path.exists(p):
        raise FileNotFoundError(f"{nome} não encontrado. Rode atualizar.py primeiro.")
    return open(p, encoding="utf-8").read().strip()

nonce  = ler_arquivo("nonce.txt")
cookie = ler_arquivo("cookie.txt")

API_HEADERS = {
    "Cookie": cookie, "X-WP-Nonce": nonce,
    "Referer": f"{BASE_URL}/buscador/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
}
_session = requests.Session()
_session.headers.update(API_HEADERS)

# ═══════════════════════════════════════════════
# COORDENADAS — todas as cidades BR
# (versão reduzida aqui; o arquivo completo está em analisar_anomalias.py)
# O bot importa do script principal se estiver na mesma pasta.
# ═══════════════════════════════════════════════
try:
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "analisar", pathlib.Path(PASTA) / "analisar_anomalias.py"
    )
    mod = importlib.util.load_module_from_spec(spec)  # type: ignore
    # Carrega só as coordenadas e funções necessárias
    _src = open(pathlib.Path(PASTA) / "analisar_anomalias.py", encoding="utf-8").read()
    # Extrai COORDENADAS executando num namespace isolado
    _ns = {}
    exec(re.search(r"(COORDENADAS = \{.*?\})", _src, re.DOTALL).group(1), _ns)
    COORDENADAS = _ns["COORDENADAS"]
except Exception:
    COORDENADAS = {}   # fallback sem coordenadas

# ═══════════════════════════════════════════════
# CATEGORIAS E ANÁLISE (cópia compacta)
# ═══════════════════════════════════════════════
CATEGORIAS = {
    "limpeza_higiene": ["limpeza","higiene","desinfetante","detergente","sabão","sabonete",
        "agua sanitaria","água sanitária","alvejante","vassoura","rodo","pano de chão",
        "esponja","papel higienico","papel higiênico","papel toalha","saco de lixo",
        "bactericida","desengordurante","sanitizante","multiuso"],
    "alimento_genero": ["aliment","gênero","genero alimentic","merenda","refeição","refeicao",
        "marmita","café","cafe","arroz","feijão","feijao","macarrão","farinha","açúcar",
        "acucar","sal ","óleo","leite","carne","frango","peixe","fruta","verdura","legume",
        "pão","pao ","bolacha","biscoito","suco","refrigerante","agua mineral","enlatado",
        "margarina","manteiga","queijo","iogurte","sardinha","atum "],
    "medicamento_saude": ["medicament","fármaco","farmaco","remédio","remedio","insumo farmac",
        "material médico","material medico","hospitalar","cirúrgico","curativo","seringa",
        "agulha","soro ","vacina","antibiótico","antibiotico","analgésico","analgesico",
        "dipirona","paracetamol","amoxicilina","omeprazol"],
    "informatica_ti": ["informática","informatica","computador","notebook","desktop","servidor",
        "impressora","scanner","monitor","teclado","mouse","software","licença","switch",
        "roteador","nobreak","tablet","smartphone","datashow","projetor","pen drive"],
    "mobiliario": ["mobiliário","mobiliario","móveis","moveis","mesa ","cadeira","armário",
        "armario","estante","gaveteiro","sofá","sofa","bancada","prateleira"],
    "combustivel": ["combustível","combustivel","gasolina","diesel","etanol","lubrificante",
        "óleo motor","oleo motor","arla 32","biodiesel"],
    "material_escritorio": ["escritório","escritorio","papelaria","papel a4","caneta","lápis",
        "borracha","grampo","toner","cartucho de tinta","fita adesiva","corretivo"],
    "fardamento_uniforme": ["fardamento","uniforme","camiseta","jaleco","colete","capacete",
        "bota","epi ","epis ","equipamento de proteção individual"],
    "construcao_obras": ["obra ","obras ","construção","construcao","reforma","ampliação",
        "pavimentação","cimento","tijolo","areia","brita","tinta predial","vergalhão","telha"],
    "veiculo_transporte": ["veículo","veiculo","automóvel","automovel","ônibus","onibus",
        "caminhão","caminhao","motocicleta","ambulância","ambulancia","pneu"],
}
PARES_SUSPEITOS = [
    ("limpeza_higiene","alimento_genero",60), ("limpeza_higiene","medicamento_saude",40),
    ("material_escritorio","alimento_genero",60), ("construcao_obras","alimento_genero",70),
    ("construcao_obras","medicamento_saude",60), ("informatica_ti","alimento_genero",70),
    ("combustivel","alimento_genero",70), ("fardamento_uniforme","alimento_genero",60),
    ("veiculo_transporte","alimento_genero",60),
]

def categorizar(texto):
    t = texto.lower()
    s = defaultdict(int)
    for cat, kws in CATEGORIAS.items():
        for kw in kws:
            if kw in t: s[cat] += 1
    return dict(s)

def top_cats(scores, n=3):
    return [k for k,_ in sorted(scores.items(), key=lambda x:x[1], reverse=True)[:n] if scores.get(k,0)>0]

def cat_item(desc):
    return top_cats(categorizar(desc), 2)

def calcular_score(objeto, itens_raw):
    cats_obj = top_cats(categorizar(objeto), 2)
    if not cats_obj or not itens_raw: return 0, [], []

    outliers = []
    for item in itens_raw:
        desc  = re.sub(r"<[^>]+>"," ", item.get("descricao") or "").strip()
        cats_i = cat_item(desc)
        bate   = bool(set(cats_obj) & set(cats_i))
        par    = next((ci for co,ci,_ in PARES_SUSPEITOS if co in cats_obj and ci in cats_i), None)
        if par or (cats_i and not bate):
            outliers.append({"num": item.get("numero_item","?"), "desc": desc[:100], "cats": cats_i})

    total = len(itens_raw)
    n_out = len(outliers)
    if total == 0 or n_out == 0: return 0, cats_obj, outliers

    pct = n_out / total
    score = 0
    if 0.05 <= pct <= 0.50:
        score = int(80*(1-abs(pct-0.20)/0.40))
    elif pct > 0.50:
        score = 50

    cats_s = {i["cats"][0] for i in outliers if i["cats"]}
    for co,ci,_ in PARES_SUSPEITOS:
        if co in cats_obj and ci in cats_s:
            score += 20; break

    return min(score, 100), cats_obj, outliers

# ═══════════════════════════════════════════════
# GEO
# ═══════════════════════════════════════════════
def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    f1,f2 = math.radians(lat1), math.radians(lat2)
    df = math.radians(lat2-lat1); dl = math.radians(lon2-lon1)
    a  = math.sin(df/2)**2 + math.cos(f1)*math.cos(f2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def normalizar(texto):
    return unicodedata.normalize("NFD", texto).encode("ascii","ignore").decode().lower()

def buscar_coord(cidade, uf=""):
    cn = normalizar(cidade)
    for k, v in COORDENADAS.items():
        nome_k, uf_k = k.rsplit("/",1)
        if normalizar(nome_k) == cn and (not uf or uf_k == uf.upper()):
            return v, nome_k, uf_k
    # fallback parcial
    for k, v in COORDENADAS.items():
        nome_k, uf_k = k.rsplit("/",1)
        if normalizar(nome_k) == cn:
            return v, nome_k, uf_k
    return None, cidade, uf

# ═══════════════════════════════════════════════
# FILTROS
# ═══════════════════════════════════════════════
def filtrar_editais(editais, uf=None, cidade=None, raio=0, semanas=None, meses=None):
    agora = datetime.now()

    # Filtro de data
    if semanas:
        limite = agora + timedelta(weeks=semanas)
    elif meses:
        limite = agora + timedelta(days=30*meses)
    else:
        limite = None

    resultado = []
    for e in editais:
        # Filtro UF
        if uf and (e.get("uf") or "").upper() != uf.upper():
            continue

        # Filtro data abertura
        if limite:
            da = e.get("data_abertura") or e.get("data_prazo") or ""
            try:
                dt = datetime.strptime(da[:10], "%Y-%m-%d")
                if not (agora <= dt <= limite):
                    continue
            except Exception:
                pass  # sem data = inclui

        resultado.append(e)

    # Filtro raio
    if raio > 0 and cidade:
        centro, nome_real, uf_real = buscar_coord(cidade, uf or "")
        if not centro:
            return resultado, f"⚠️ Cidade '{cidade}' não encontrada."
        lat0, lon0 = centro
        dentro = []
        for e in resultado:
            c = None
            chave = f"{e.get('cidade','')}/{(e.get('uf') or '').upper()}"
            if chave in COORDENADAS:
                c = COORDENADAS[chave]
            else:
                c, _, _ = buscar_coord(e.get("cidade",""), e.get("uf",""))
            if c:
                if haversine(lat0, lon0, c[0], c[1]) <= raio:
                    dentro.append(e)
            else:
                if (e.get("uf") or "").upper() == uf_real.upper():
                    dentro.append(e)
        return dentro, f"📍 {nome_real}/{uf_real} | raio {raio}km → {len(dentro)} editais"

    return resultado, None

# ═══════════════════════════════════════════════
# API DE ITENS
# ═══════════════════════════════════════════════
def buscar_itens(eid):
    url = BASE_URL + ENDPOINT_ITENS.format(id=eid)
    for t in range(3):
        try:
            r = _session.get(url, timeout=HTTP_TIMEOUT)
            if r.status_code in (401, 404): return []
            if r.status_code in (429, 503): time.sleep(4*(t+1)); continue
            r.raise_for_status()
            data = r.json()
            return data.get("rows") or data.get("items") or (data if isinstance(data,list) else [])
        except Exception:
            time.sleep(2*(t+1))
    return []

def analisar_edital(edital):
    obj = edital.get("objeto","")
    eid = str(edital.get("id",""))
    if not obj or not eid: return None
    rows = buscar_itens(eid)
    if not rows: return None
    score, cats_obj, outliers = calcular_score(obj, rows)
    if score < SCORE_MINIMO: return None
    return {**edital, "score": score, "cats_obj": cats_obj,
            "outliers": outliers, "total_itens": len(rows)}

def rodar_analise(editais, max_items=500):
    """Roda análise em paralelo e retorna anomalias ordenadas."""
    amostra = editais[:max_items]
    anomalos = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(analisar_edital, e): e for e in amostra}
        for fut in futures:
            try:
                r = fut.result(timeout=30)
                if r: anomalos.append(r)
            except Exception:
                pass
    anomalos.sort(key=lambda x: x.get("score",0), reverse=True)
    return anomalos[:MAX_RESULTADOS]

# ═══════════════════════════════════════════════
# FORMATAÇÃO DA MENSAGEM
# ═══════════════════════════════════════════════
def formatar_edital(e, idx):
    score    = e.get("score", 0)
    orgao    = (e.get("orgao_nome") or "")[:45]
    objeto   = e.get("objeto","")
    uf       = e.get("uf","")
    cidade   = e.get("cidade","")
    valor    = e.get("valor_estimado") or "0"
    try: valor_fmt = f"R$ {float(valor):,.2f}".replace(",","X").replace(".",",").replace("X",".")
    except: valor_fmt = "R$ —"

    # Data e hora
    da = e.get("data_abertura","") or ""
    try:
        dt = datetime.strptime(da[:19], "%Y-%m-%d %H:%M:%S")
        data_fmt = dt.strftime("%d/%m/%Y às %H:%M")
    except:
        data_fmt = da[:10] if da else "—"

    # Prazo
    dp = e.get("data_prazo","") or ""
    try:
        dtp = datetime.strptime(dp[:10], "%Y-%m-%d")
        prazo_fmt = dtp.strftime("%d/%m/%Y")
        hoje = datetime.now()
        dias = (dtp - hoje).days
        if dias >= 0:
            prazo_fmt += f" ({dias}d restantes)"
        else:
            prazo_fmt += " ⚠️ encerrado"
    except:
        prazo_fmt = "—"

    # Itens outlier
    outliers = e.get("outliers",[])[:3]
    itens_txt = ""
    for o in outliers:
        cats_str = "/".join(o.get("cats",[]))
        itens_txt += f"\n  ⚠️ Item {o.get('num')}: {o.get('desc','')[:60]}… [{cats_str}]"

    url = e.get("url_site_oficial") or e.get("pncp_link_sistema_origem") or ""
    link = f"\n🔗 <a href='{url}'>Acessar edital</a>" if url else ""

    total_out = len(e.get("outliers",[]))
    total_it  = e.get("total_itens",0)

    emoji = "🚨" if score >= 70 else "⚠️"

    return (
        f"{emoji} <b>#{idx} — Score {score}/100</b>\n"
        f"🏛 {orgao}\n"
        f"📋 <b>Objeto:</b> {objeto}\n"
        f"📍 {cidade}/{uf} | {e.get('modalidade','')}\n"
        f"💰 {valor_fmt}\n"
        f"📅 Abertura: {data_fmt}\n"
        f"⏳ Prazo: {prazo_fmt}\n"
        f"📦 {total_out}/{total_it} itens suspeitos:{itens_txt}"
        f"{link}"
    )

# ═══════════════════════════════════════════════
# HANDLERS DO BOT
# ═══════════════════════════════════════════════

def check_auth(update: Update) -> bool:
    return update.effective_user.id == MEU_CHAT_ID

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update): return
    texto = (
        "🔍 <b>Detector de Anomalias em Editais</b>\n\n"
        "Use os comandos abaixo:\n\n"
        "<b>/buscar</b> — busca com filtros interativos\n"
        "<b>/buscar cidade=Manaus raio=200</b>\n"
        "<b>/buscar uf=AM semanas=2</b>\n"
        "<b>/buscar cidade=Recife raio=100 mes=1</b>\n\n"
        "Parâmetros disponíveis:\n"
        "• <code>cidade=</code> nome da cidade (sem acento ok)\n"
        "• <code>uf=</code> sigla do estado\n"
        "• <code>raio=</code> km a partir da cidade\n"
        "• <code>semanas=</code> 1, 2 ou 3\n"
        "• <code>mes=</code> 1\n"
        "• <code>score=</code> mínimo de anomalia (padrão: 40)\n\n"
        "Ou use /buscar para ver o menu de opções rápidas."
    )
    await update.message.reply_text(texto, parse_mode="HTML")


async def cmd_buscar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update): return

    args_raw = " ".join(ctx.args) if ctx.args else ""

    # Se não veio argumento, mostra menu de ranges rápidos
    if not args_raw.strip():
        kb = [
            [InlineKeyboardButton("📅 Próxima semana",    callback_data="range:semanas=1")],
            [InlineKeyboardButton("📅 Próximas 2 semanas", callback_data="range:semanas=2")],
            [InlineKeyboardButton("📅 Próximas 3 semanas", callback_data="range:semanas=3")],
            [InlineKeyboardButton("📅 Próximo mês",        callback_data="range:mes=1")],
            [InlineKeyboardButton("🗺️ Filtrar por estado", callback_data="menu:uf")],
            [InlineKeyboardButton("🔍 Todos (sem filtro)", callback_data="range:todos")],
        ]
        await update.message.reply_text(
            "📋 <b>Escolha o período dos editais:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    # Veio com argumentos — parseia e roda
    await executar_busca(update, ctx, args_raw)


async def callback_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update): return
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "menu:uf":
        # Mostra estados em grade
        estados = ["AC","AL","AM","AP","BA","CE","DF","ES","GO","MA",
                   "MG","MS","MT","PA","PB","PE","PI","PR","RJ","RN",
                   "RO","RR","RS","SC","SE","SP","TO"]
        kb = []
        row = []
        for uf in estados:
            row.append(InlineKeyboardButton(uf, callback_data=f"range:uf={uf}"))
            if len(row) == 5:
                kb.append(row); row = []
        if row: kb.append(row)
        kb.append([InlineKeyboardButton("« Voltar", callback_data="menu:inicio")])
        await query.edit_message_text("🗺️ <b>Escolha o estado:</b>", parse_mode="HTML",
                                       reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "menu:inicio":
        kb = [
            [InlineKeyboardButton("📅 Próxima semana",    callback_data="range:semanas=1")],
            [InlineKeyboardButton("📅 Próximas 2 semanas", callback_data="range:semanas=2")],
            [InlineKeyboardButton("📅 Próximas 3 semanas", callback_data="range:semanas=3")],
            [InlineKeyboardButton("📅 Próximo mês",        callback_data="range:mes=1")],
            [InlineKeyboardButton("🗺️ Filtrar por estado", callback_data="menu:uf")],
            [InlineKeyboardButton("🔍 Todos (sem filtro)", callback_data="range:todos")],
        ]
        await query.edit_message_text("📋 <b>Escolha o período:</b>", parse_mode="HTML",
                                       reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("range:"):
        params = data[6:]  # ex: "semanas=1" ou "uf=SP" ou "todos"
        if params == "todos":
            params = ""
        await query.edit_message_text(f"⏳ Iniciando análise... (<code>{params or 'sem filtro'}</code>)",
                                       parse_mode="HTML")
        await executar_busca(update, ctx, params, query=query)


async def executar_busca(update, ctx, args_raw, query=None):
    """Parseia os argumentos, filtra e roda a análise."""
    msg_obj = query or update.message

    # Parseia parâmetros chave=valor
    params = {}
    for part in args_raw.split():
        if "=" in part:
            k, v = part.split("=", 1)
            params[k.lower().strip()] = v.strip()

    cidade  = params.get("cidade","")
    uf      = params.get("uf","").upper()
    raio    = int(params.get("raio", 0))
    semanas = int(params.get("semanas", 0))
    meses   = int(params.get("mes", 0))
    score   = int(params.get("score", SCORE_MINIMO))

    # Carrega editais
    if not os.path.exists(OUT_FILE):
        await msg_obj.reply_text("❌ editais.json não encontrado. Rode atualizar.py.")
        return

    editais = json.load(open(OUT_FILE, encoding="utf-8"))

    # Status
    resumo = []
    if cidade: resumo.append(f"cidade={cidade}")
    if uf:     resumo.append(f"uf={uf}")
    if raio:   resumo.append(f"raio={raio}km")
    if semanas: resumo.append(f"próximas {semanas} semana(s)")
    if meses:  resumo.append(f"próximo {meses} mês")
    filtro_desc = " | ".join(resumo) if resumo else "sem filtro"

    texto_status = f"🔍 Filtrando {len(editais):,} editais...\n📌 Filtros: <code>{filtro_desc}</code>"
    if query:
        await query.edit_message_text(texto_status, parse_mode="HTML")
    else:
        status_msg = await update.message.reply_text(texto_status, parse_mode="HTML")

    # Aplica filtros
    filtrados, info_geo = filtrar_editais(
        editais, uf=uf or None, cidade=cidade or None,
        raio=raio, semanas=semanas or None, meses=meses or None
    )

    if not filtrados:
        await (query or status_msg).reply_text("😕 Nenhum edital encontrado com esses filtros.")
        return

    texto_status2 = (
        f"⚙️ Analisando <b>{len(filtrados):,}</b> editais...\n"
        f"{info_geo or ''}\n"
        f"⏱ Pode levar alguns minutos..."
    )
    if query:
        await query.edit_message_text(texto_status2, parse_mode="HTML")
    else:
        await status_msg.edit_text(texto_status2, parse_mode="HTML")

    # Roda análise em thread separada para não travar o bot
    loop = ctx.application.loop if hasattr(ctx.application, "loop") else None

    import asyncio
    anomalos = await asyncio.get_event_loop().run_in_executor(
        None, lambda: rodar_analise(filtrados, max_items=min(len(filtrados), 1000))
    )

    if not anomalos:
        txt = (
            f"✅ Análise concluída!\n"
            f"📊 {len(filtrados):,} editais analisados\n"
            f"🎉 Nenhuma anomalia encontrada (score ≥ {score})"
        )
        if query:
            await query.edit_message_text(txt)
        else:
            await status_msg.edit_text(txt)
        return

    # Cabeçalho do resultado
    cab = (
        f"✅ <b>Análise concluída!</b>\n"
        f"📊 {len(filtrados):,} editais | 🚨 {len(anomalos)} anomalias\n"
        f"📌 {filtro_desc}\n"
        f"{'─'*30}"
    )
    if query:
        await query.edit_message_text(cab, parse_mode="HTML")
    else:
        await status_msg.edit_text(cab, parse_mode="HTML")

    # Envia cada resultado
    chat_id = update.effective_chat.id
    for i, e in enumerate(anomalos, 1):
        texto = formatar_edital(e, i)
        try:
            await ctx.bot.send_message(chat_id=chat_id, text=texto,
                                        parse_mode="HTML", disable_web_page_preview=True)
            await asyncio.sleep(0.3)  # evita flood
        except Exception as err:
            logging.warning(f"Erro ao enviar edital {i}: {err}")

    # Rodapé
    await ctx.bot.send_message(
        chat_id=chat_id,
        text=f"📋 <b>Fim da lista</b> — {len(anomalos)} anomalia(s) encontrada(s).\n"
             f"Use /buscar para nova busca.",
        parse_mode="HTML"
    )


# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════
def main():
    print("=" * 50)
    print("  🤖 BOT DETECTOR DE ANOMALIAS EM EDITAIS")
    print("=" * 50)
    print(f"  Editais: {OUT_FILE}")
    print(f"  Coordenadas: {len(COORDENADAS):,} cidades")
    print(f"  Aguardando mensagens...")
    print()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("buscar", cmd_buscar))
    app.add_handler(CallbackQueryHandler(callback_menu))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
