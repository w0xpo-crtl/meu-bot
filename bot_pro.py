import logging, json, os, asyncio, hashlib
from datetime import datetime, timedelta
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatInviteLink
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, JobQueue
)
from telegram.error import TelegramError

# ═══════════════════════════════════════════
#  CONFIGURAÇÕES
# ═══════════════════════════════════════════

CONFIG = {
    "TOKEN":              os.environ.get("TOKEN",             "SEU_TOKEN_AQUI"),
    "ADMIN_IDS":          [int(x.strip()) for x in os.environ.get("ADMIN_ID", "123456789").split(",")],
    "CANAL_ID":           os.environ.get("CANAL_ID",          ""),
    "CANAL_STORAGE_ID":   os.environ.get("CANAL_STORAGE_ID",  ""),
    "LINK_CONTEUDO":      os.environ.get("LINK_CONTEUDO",     "https://seusite.com/conteudo"),
    "CHAVE_PIX":          os.environ.get("CHAVE_PIX",         "sua_chave_pix_aqui"),
    "NOME_RECEBEDOR":     os.environ.get("NOME_RECEBEDOR",    "Seu Nome"),
    "SUPORTE_USER":       os.environ.get("SUPORTE_USER",      "@seu_usuario"),
    "MP_ACCESS_TOKEN":    os.environ.get("MP_ACCESS_TOKEN",   ""),
    "GRUPO_COMPROVANTES": os.environ.get("GRUPO_COMPROVANTES",""),
    "DELAY_MIDIAS":       float(os.environ.get("DELAY_MIDIAS","1.5")),
}

PLANOS = {
    "basic": {
        "nome": "🔥 Basic", "preco": "19,90", "preco_int": 1990,
        "descricao": "Pack básico com os melhores conteúdos", "emoji": "🔥", "limite": 20,
    },
    "premium": {
        "nome": "💎 Premium", "preco": "39,90", "preco_int": 3990,
        "descricao": "Pack completo + atualizações mensais", "emoji": "💎", "limite": 50,
    },
    "vip": {
        "nome": "👑 VIP", "preco": "79,90", "preco_int": 7990,
        "descricao": "Tudo + conteúdo exclusivo + prioridade", "emoji": "👑", "limite": 999,
    },
}

CUPONS_PADRAO = {
    "PROMO50":  {"desconto": 50, "tipo": "percent", "usos_max": 100, "usos": 0},
    "INICIO10": {"desconto": 10, "tipo": "reais",   "usos_max": 50,  "usos": 0},
    "VIP20":    {"desconto": 20, "tipo": "percent", "usos_max": 30,  "usos": 0},
}

# ═══════════════════════════════════════════
#  LOGGING
# ═══════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ═══════════════════════════════════════════
#  BANCO DE DADOS
# ═══════════════════════════════════════════

DB_FILE        = "clientes.json"
CUPONS_FILE    = "cupons.json"
FRAUDE_FILE    = "fraudes.json"
BLOQUEIOS_FILE = "bloqueados.json"
STORAGE_FILE   = "storage.json"

def _ler(arquivo):
    if not os.path.exists(arquivo):
        return {}
    try:
        with open(arquivo, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def _salvar(arquivo, dados):
    with open(arquivo, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=2, ensure_ascii=False)

def cliente_get(user_id):
    return _ler(DB_FILE).get(str(user_id), {})

def cliente_salvar(user_id, dados):
    db = _ler(DB_FILE)
    db[str(user_id)] = dados
    _salvar(DB_FILE, db)

def tem_acesso(user_id):
    return cliente_get(user_id).get("acesso", False)

def esta_bloqueado(user_id):
    return str(user_id) in _ler(BLOQUEIOS_FILE)

def is_admin(user_id):
    return user_id in CONFIG["ADMIN_IDS"]

def registrar_visita(user_id, username, nome):
    dados = cliente_get(user_id)
    if not dados:
        dados = {
            "username": username, "nome": nome, "acesso": False,
            "primeira_visita": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "follow_up_enviado": False,
        }
        cliente_salvar(user_id, dados)

def liberar_acesso(user_id, username, nome, plano):
    dados = cliente_get(user_id)
    dados.update({
        "username": username, "nome": nome, "acesso": True,
        "plano": plano, "conteudo_enviado": False,
        "data_compra": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "follow_up_enviado": True,
    })
    cliente_salvar(user_id, dados)
    log.info(f"✅ Acesso liberado: {user_id} plano={plano}")

def bloquear(user_id, motivo="sem motivo"):
    db = _ler(BLOQUEIOS_FILE)
    db[str(user_id)] = {"motivo": motivo, "data": datetime.now().strftime("%d/%m/%Y %H:%M")}
    _salvar(BLOQUEIOS_FILE, db)

def desbloquear(user_id):
    db = _ler(BLOQUEIOS_FILE)
    db.pop(str(user_id), None)
    _salvar(BLOQUEIOS_FILE, db)

def comprovante_ja_usado(file_id, file_unique_id=""):
    db = _ler(FRAUDE_FILE)
    h1 = hashlib.md5(file_id.encode()).hexdigest()
    h2 = hashlib.md5(file_unique_id.encode()).hexdigest() if file_unique_id else None
    if h1 in db or (h2 and h2 in db):
        return True
    db[h1] = datetime.now().strftime("%d/%m/%Y %H:%M")
    if h2:
        db[h2] = datetime.now().strftime("%d/%m/%Y %H:%M")
    _salvar(FRAUDE_FILE, db)
    return False

def validar_cupom(codigo):
    cupons = _ler(CUPONS_FILE) or CUPONS_PADRAO
    c = cupons.get(codigo.upper().strip())
    if not c or c["usos"] >= c["usos_max"]:
        return None
    return c

def usar_cupom(codigo):
    cupons = _ler(CUPONS_FILE) or CUPONS_PADRAO
    cod = codigo.upper().strip()
    if cod in cupons:
        cupons[cod]["usos"] += 1
        _salvar(CUPONS_FILE, cupons)

def calc_preco_cupom(preco_int, cupom):
    if cupom["tipo"] == "percent":
        return int(preco_int * (1 - cupom["desconto"] / 100))
    return max(0, preco_int - int(cupom["desconto"] * 100))

# ═══════════════════════════════════════════
#  STORAGE — canal secreto de conteúdos
# ═══════════════════════════════════════════

async def buscar_midias_storage(bot, forcar=False):
    storage = _ler(STORAGE_FILE)
    midias  = storage.get("midias", [])
    if midias and not forcar:
        return midias

    canal_id = CONFIG.get("CANAL_STORAGE_ID", "")
    if not canal_id:
        log.warning("CANAL_STORAGE_ID não configurado!")
        return []

    log.info("🔄 Buscando mídias do canal storage...")
    midias = []
    msg_id = 1
    erros  = 0

    while erros < 10 and msg_id < 500:
        try:
            msg = await bot.forward_message(
                chat_id=CONFIG["ADMIN_IDS"][0],
                from_chat_id=canal_id,
                message_id=msg_id,
                disable_notification=True,
            )
            item = None
            if msg.photo:
                item = {"type": "photo",     "file_id": msg.photo[-1].file_id,  "caption": msg.caption or ""}
            elif msg.video:
                item = {"type": "video",     "file_id": msg.video.file_id,      "caption": msg.caption or ""}
            elif msg.document:
                item = {"type": "document",  "file_id": msg.document.file_id,   "caption": msg.caption or ""}
            elif msg.animation:
                item = {"type": "animation", "file_id": msg.animation.file_id,  "caption": msg.caption or ""}

            try:
                await bot.delete_message(CONFIG["ADMIN_IDS"][0], msg.message_id)
            except:
                pass

            if item:
                midias.append(item)
                erros = 0

            msg_id += 1
            await asyncio.sleep(0.3)

        except TelegramError:
            erros  += 1
            msg_id += 1

    if midias:
        _salvar(STORAGE_FILE, {
            "midias": midias,
            "atualizado": datetime.now().strftime("%d/%m/%Y %H:%M")
        })
        log.info(f"✅ {len(midias)} mídias no storage!")
    return midias

async def enviar_conteudos(bot, user_id, plano_id):
    midias = _ler(STORAGE_FILE).get("midias", [])
    if not midias:
        await bot.send_message(user_id, "📦 Seus conteúdos serão enviados em breve!")
        return

    limite = PLANOS.get(plano_id, {}).get("limite", 20)
    lista  = midias[:limite]

    await bot.send_message(
        user_id,
        f"🎬 *Enviando seu pack agora!*\n\n📦 Total: *{len(lista)} conteúdos*\n⏳ Aguarde...",
        parse_mode="Markdown"
    )
    await asyncio.sleep(1)

    enviados = 0
    for item in lista:
        try:
            fid = item["file_id"]
            cap = item.get("caption", "") or ""
            t   = item["type"]
            if t == "photo":
                await bot.send_photo(user_id, photo=fid, caption=cap)
            elif t == "video":
                await bot.send_video(user_id, video=fid, caption=cap)
            elif t == "document":
                await bot.send_document(user_id, document=fid, caption=cap)
            elif t == "animation":
                await bot.send_animation(user_id, animation=fid, caption=cap)
            enviados += 1
            await asyncio.sleep(CONFIG["DELAY_MIDIAS"])
        except TelegramError as e:
            log.error(f"Erro enviar mídia {user_id}: {e}")

    await bot.send_message(
        user_id,
        f"✅ *Pack enviado!*\n\n📦 {enviados}/{len(lista)} conteúdos entregues.\n\nAproveite! 🔥\nDúvidas? {CONFIG['SUPORTE_USER']}",
        parse_mode="Markdown"
    )
    dados = cliente_get(user_id)
    dados["conteudo_enviado"] = True
    dados["conteudo_enviado_em"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    cliente_salvar(user_id, dados)

# ═══════════════════════════════════════════
#  MERCADO PAGO
# ═══════════════════════════════════════════

def gerar_pix_mp(plano_id, user_id, preco_int):
    token = CONFIG.get("MP_ACCESS_TOKEN", "")
    if not token:
        return None
    try:
        import requests
        r = requests.post(
            "https://api.mercadopago.com/v1/payments",
            json={
                "transaction_amount": preco_int / 100,
                "description": f"Pack Premium +18 — {PLANOS[plano_id]['nome']}",
                "payment_method_id": "pix",
                "payer": {"email": f"cliente_{user_id}@bot.com"},
                "external_reference": f"{user_id}_{plano_id}_{int(datetime.now().timestamp())}",
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Idempotency-Key": f"{user_id}_{plano_id}_{datetime.now().date()}",
            },
            timeout=10,
        )
        data = r.json()
        if r.status_code == 201:
            return {
                "id": data["id"],
                "qr_code": data["point_of_interaction"]["transaction_data"]["qr_code"],
            }
    except Exception as e:
        log.error(f"Erro MP: {e}")
    return None

async def verificar_mp(payment_id):
    token = CONFIG.get("MP_ACCESS_TOKEN", "")
    if not token:
        return False
    try:
        import requests
        r = requests.get(
            f"https://api.mercadopago.com/v1/payments/{payment_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        return r.json().get("status") == "approved"
    except:
        return False

# ═══════════════════════════════════════════
#  TECLADOS
# ═══════════════════════════════════════════

def kb_principal():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Ver Planos e Comprar", callback_data="planos")],
        [InlineKeyboardButton("🎁 Tenho um Cupom",       callback_data="cupom")],
        [InlineKeyboardButton("❓ Dúvidas Frequentes",   callback_data="faq")],
        [InlineKeyboardButton("🔓 Já tenho acesso",      callback_data="meu_acesso")],
        [InlineKeyboardButton("💬 Suporte",              callback_data="suporte")],
    ])

def kb_planos():
    botoes = []
    for pid, p in PLANOS.items():
        qtd = f"{p['limite']} conteúdos" if p["limite"] < 999 else "ilimitado"
        botoes.append([InlineKeyboardButton(
            f"{p['emoji']} {p['nome']} — R$ {p['preco']} ({qtd})",
            callback_data=f"plano_{pid}"
        )])
    botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data="inicio")])
    return InlineKeyboardMarkup(botoes)

def kb_pagamento(plano_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Já Paguei!", callback_data=f"paguei_{plano_id}")],
        [InlineKeyboardButton("🔙 Voltar",    callback_data="planos")],
    ])

def kb_voltar(destino="inicio"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu Principal", callback_data=destino)]])

def kb_follow_up():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Quero Agora!", callback_data="planos")],
        [InlineKeyboardButton("🎁 Cupom 50% OFF", callback_data="cupom")],
    ])

# ═══════════════════════════════════════════
#  TEXTOS
# ═══════════════════════════════════════════

def txt_boas_vindas():
    return (
        "👋 *Bem-vindo(a) ao Pack Premium +18!*\n\n"
        "Conteúdo adulto exclusivo e de altíssima qualidade. 🔥\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "✅ Acesso vitalício — pague uma vez\n"
        "✅ Conteúdo enviado direto aqui no Telegram\n"
        "✅ 100% discreto e seguro\n"
        "✅ Liberação automática após pagamento\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "👇 Escolha seu plano abaixo:"
    )

def txt_pagamento_pix(plano_id, preco_str, qr_code=None):
    p    = PLANOS[plano_id]
    base = (
        f"💳 *Pagamento PIX — {p['nome']}*\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🔑 *Chave PIX:*\n`{CONFIG['CHAVE_PIX']}`\n"
        f"_(toque para copiar)_\n\n"
        f"👤 *Favorecido:* {CONFIG['NOME_RECEBEDOR']}\n"
        f"💰 *Valor:* R$ {preco_str}\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 *Como pagar:*\n"
        f"1️⃣ Abra seu banco\n"
        f"2️⃣ PIX → Pagar com chave\n"
        f"3️⃣ Cole a chave acima\n"
        f"4️⃣ Confirme R$ {preco_str}\n"
        f"5️⃣ Clique em ✅ Já Paguei abaixo\n\n"
        f"⏱️ _Conteúdo enviado em até 2 minutos._"
    )
    if qr_code:
        base += f"\n\n📱 *PIX Copia e Cola:*\n`{qr_code}`"
    return base

def txt_acesso_liberado(plano_id):
    p = PLANOS[plano_id]
    return (
        f"🎉 *Pagamento Confirmado!*\n\n"
        f"✅ Plano: *{p['nome']}*\n\n"
        f"📦 Seu pack está sendo preparado e será enviado aqui em instantes!\n\n"
        f"⏳ _Aguarde alguns segundos..._"
    )

# ═══════════════════════════════════════════
#  HELPER
# ═══════════════════════════════════════════

async def responder(update, texto, teclado=None, editar=True):
    kwargs = {"text": texto, "parse_mode": "Markdown", "reply_markup": teclado}
    try:
        if editar and update.callback_query:
            await update.callback_query.edit_message_text(**kwargs)
        else:
            msg = update.message or update.callback_query.message
            await msg.reply_text(**kwargs)
    except TelegramError as e:
        log.warning(f"responder(): {e}")

async def gerar_link_canal(bot, user_id):
    canal_id = CONFIG.get("CANAL_ID", "")
    if canal_id:
        try:
            invite = await bot.create_chat_invite_link(
                chat_id=canal_id, member_limit=1, name=f"Cliente {user_id}"
            )
            return invite.invite_link
        except TelegramError as e:
            log.error(f"Erro link canal: {e}")
    return CONFIG["LINK_CONTEUDO"]

async def notificar_admins(bot, texto, teclado=None):
    destinos = CONFIG.get("GRUPO_COMPROVANTES", "")
    lista    = [int(destinos)] if destinos else CONFIG["ADMIN_IDS"]
    for dest in lista:
        try:
            await bot.send_message(dest, texto, parse_mode="Markdown", reply_markup=teclado)
        except TelegramError as e:
            log.error(f"Erro notificar {dest}: {e}")

# ═══════════════════════════════════════════
#  JOBS AUTOMÁTICOS
# ═══════════════════════════════════════════

async def job_follow_up(context):
    db    = _ler(DB_FILE)
    agora = datetime.now()
    for uid_str, dados in db.items():
        if dados.get("acesso") or dados.get("follow_up_enviado"):
            continue
        primeira = dados.get("primeira_visita")
        if not primeira:
            continue
        try:
            dt   = datetime.strptime(primeira, "%d/%m/%Y %H:%M")
            diff = agora - dt
            uid  = int(uid_str)
            if timedelta(hours=1) <= diff < timedelta(hours=2) and not dados.get("fu1"):
                await context.bot.send_message(
                    uid,
                    "⏰ *Ei, você esqueceu de algo...*\n\nVocê visitou nosso catálogo mas ainda não garantiu seu acesso! 😏\n\n🔥 O conteúdo está esperando por você.",
                    parse_mode="Markdown", reply_markup=kb_follow_up()
                )
                dados["fu1"] = True
                cliente_salvar(uid, dados)
            elif diff >= timedelta(hours=24) and not dados.get("fu2"):
                await context.bot.send_message(
                    uid,
                    "🚨 *OFERTA ESPECIAL — só até hoje!*\n\nUse o cupom `PROMO50` e ganhe *50% de desconto*!\n\n⏳ _Expira em 24h._",
                    parse_mode="Markdown", reply_markup=kb_follow_up()
                )
                dados["fu2"] = True
                dados["follow_up_enviado"] = True
                cliente_salvar(uid, dados)
        except TelegramError:
            pass

async def job_verificar_mp(context):
    if not CONFIG.get("MP_ACCESS_TOKEN"):
        return
    db = _ler(DB_FILE)
    for uid_str, dados in db.items():
        if dados.get("acesso"):
            continue
        pid      = dados.get("mp_payment_id")
        plano_id = dados.get("plano_pendente")
        if not pid or not plano_id:
            continue
        pago = await verificar_mp(str(pid))
        if pago:
            uid = int(uid_str)
            liberar_acesso(uid, dados.get("username",""), dados.get("nome",""), plano_id)
            try:
                await context.bot.send_message(uid, txt_acesso_liberado(plano_id), parse_mode="Markdown")
                await asyncio.sleep(2)
                await enviar_conteudos(context.bot, uid, plano_id)
            except TelegramError as e:
                log.error(e)

async def job_storage(context):
    await buscar_midias_storage(context.bot, forcar=True)

# ═══════════════════════════════════════════
#  COMANDOS — CLIENTES
# ═══════════════════════════════════════════

async def cmd_start(update, ctx):
    if update.effective_chat.type != "private":
        return
    user = update.effective_user
    if esta_bloqueado(user.id):
        await update.message.reply_text("❌ Seu acesso foi suspenso. Contate o suporte.")
        return
    registrar_visita(user.id, user.username or "", user.full_name)
    if tem_acesso(user.id):
        dados = cliente_get(user.id)
        if not dados.get("conteudo_enviado"):
            await update.message.reply_text("📦 Reenviando seu pack...", parse_mode="Markdown")
            await enviar_conteudos(ctx.bot, user.id, dados.get("plano","basic"))
        else:
            await update.message.reply_text(
                f"✅ Você já tem acesso ao plano *{PLANOS[dados.get('plano','basic')]['nome']}*!\n\nUse /reenviar para receber os conteúdos novamente.",
                parse_mode="Markdown"
            )
        return
    await update.message.reply_text(txt_boas_vindas(), parse_mode="Markdown", reply_markup=kb_principal())

async def cmd_reenviar(update, ctx):
    if update.effective_chat.type != "private":
        return
    user = update.effective_user
    if not tem_acesso(user.id):
        await update.message.reply_text("❌ Você não tem acesso. Use /start para comprar.")
        return
    dados = cliente_get(user.id)
    await update.message.reply_text("📦 Reenviando seu pack completo!", parse_mode="Markdown")
    await enviar_conteudos(ctx.bot, user.id, dados.get("plano","basic"))

# ═══════════════════════════════════════════
#  COMANDOS — ADMIN
# ═══════════════════════════════════════════

async def cmd_painel(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    db      = _ler(DB_FILE)
    ativos  = sum(1 for v in db.values() if v.get("acesso"))
    hoje    = datetime.now().strftime("%d/%m/%Y")
    hoje_v  = sum(1 for v in db.values() if v.get("acesso") and v.get("data_compra","").startswith(hoje))
    storage = _ler(STORAGE_FILE)
    midias  = len(storage.get("midias", []))
    texto   = (
        "📊 *PAINEL ADMIN*\n"
        f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
        f"👥 Total usuários: `{len(db)}`\n"
        f"✅ Com acesso: `{ativos}`\n"
        f"💰 Vendas hoje: `{hoje_v}`\n"
        f"📦 Mídias no storage: `{midias}`\n\n"
        "Escolha uma ação:"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Clientes",         callback_data="adm_clientes"),
         InlineKeyboardButton("📊 Stats",            callback_data="adm_stats")],
        [InlineKeyboardButton("📦 Storage",          callback_data="adm_storage"),
         InlineKeyboardButton("🔄 Atualizar",        callback_data="adm_atualizar")],
        [InlineKeyboardButton("🎁 Cupons",           callback_data="adm_cupons"),
         InlineKeyboardButton("📈 Relatório",        callback_data="adm_relatorio")],
        [InlineKeyboardButton("📢 Broadcast",        callback_data="adm_broadcast_menu")],
    ])
    await update.message.reply_text(texto, parse_mode="Markdown", reply_markup=kb)

async def cmd_stats(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    db     = _ler(DB_FILE)
    ativos = {k: v for k, v in db.items() if v.get("acesso")}
    hoje   = datetime.now().strftime("%d/%m/%Y")
    hoje_v = sum(1 for v in ativos.values() if v.get("data_compra","").startswith(hoje))
    por_plano = {}
    for v in ativos.values():
        p = v.get("plano","?")
        por_plano[p] = por_plano.get(p,0) + 1
    linhas = "\n".join([f"   {PLANOS.get(k,{}).get('emoji','?')} {k}: {n}" for k,n in por_plano.items()])
    await update.message.reply_text(
        f"📊 *Estatísticas*\n\n"
        f"👥 Total: `{len(db)}`\n"
        f"✅ Ativos: `{len(ativos)}`\n"
        f"📅 Hoje: `{hoje_v}`\n\n"
        f"📦 Por plano:\n{linhas or '   nenhum'}",
        parse_mode="Markdown"
    )

async def cmd_clientes(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    db     = _ler(DB_FILE)
    ativos = {k: v for k, v in db.items() if v.get("acesso")}
    if not ativos:
        await update.message.reply_text("Nenhum cliente ativo.")
        return
    linhas = [
        f"• `{uid}` @{v.get('username','?')} [{v.get('plano','?')}] {v.get('data_compra','?')}"
        for uid, v in list(ativos.items())[:30]
    ]
    await update.message.reply_text(
        f"📋 *Clientes ativos ({len(ativos)}):*\n\n" + "\n".join(linhas),
        parse_mode="Markdown"
    )

async def cmd_buscar(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Uso: /buscar <@username ou user_id>")
        return
    termo = ctx.args[0].replace("@","").lower()
    db    = _ler(DB_FILE)
    encontrados = [(uid, d) for uid, d in db.items()
                   if termo in uid or termo in d.get("username","").lower()]
    if not encontrados:
        await update.message.reply_text("❌ Nenhum usuário encontrado.")
        return
    linhas = []
    for uid, d in encontrados[:10]:
        status = "✅" if d.get("acesso") else "❌"
        linhas.append(f"{status} `{uid}` @{d.get('username','?')} [{d.get('plano','?')}] {d.get('data_compra','nunca')}")
    await update.message.reply_text(
        f"🔍 *Resultado ({len(encontrados)}):*\n\n" + "\n".join(linhas),
        parse_mode="Markdown"
    )

async def cmd_liberar(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    if len(ctx.args) < 2:
        await update.message.reply_text("Uso: /liberar <user_id> <basic|premium|vip>")
        return
    uid      = int(ctx.args[0])
    plano_id = ctx.args[1]
    if plano_id not in PLANOS:
        await update.message.reply_text(f"Plano inválido. Use: {', '.join(PLANOS.keys())}")
        return
    dados = cliente_get(uid)
    liberar_acesso(uid, dados.get("username","manual"), dados.get("nome","manual"), plano_id)
    try:
        await ctx.bot.send_message(uid, txt_acesso_liberado(plano_id), parse_mode="Markdown")
        await asyncio.sleep(2)
        await enviar_conteudos(ctx.bot, uid, plano_id)
        await update.message.reply_text(f"✅ Liberado e pack enviado para `{uid}`!", parse_mode="Markdown")
    except TelegramError as e:
        await update.message.reply_text(f"⚠️ Salvo, erro ao notificar: {e}")

async def cmd_bloquear(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        return
    uid    = int(ctx.args[0])
    motivo = " ".join(ctx.args[1:]) if len(ctx.args) > 1 else "sem motivo"
    bloquear(uid, motivo)
    await update.message.reply_text(f"🚫 `{uid}` bloqueado: {motivo}", parse_mode="Markdown")

async def cmd_desbloquear(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        return
    desbloquear(int(ctx.args[0]))
    await update.message.reply_text(f"✅ `{ctx.args[0]}` desbloqueado.", parse_mode="Markdown")

async def cmd_broadcast(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Uso: /broadcast <mensagem>")
        return
    msg      = " ".join(ctx.args)
    db       = _ler(DB_FILE)
    ok, err  = 0, 0
    for uid_str in db:
        try:
            await ctx.bot.send_message(int(uid_str), f"📢 {msg}", parse_mode="Markdown")
            ok += 1
            await asyncio.sleep(0.05)
        except:
            err += 1
    await update.message.reply_text(f"📢 Enviado!\n✅ {ok} | ❌ {err}")

async def cmd_broadcast_ativos(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Uso: /broadcast_ativos <mensagem>")
        return
    msg    = " ".join(ctx.args)
    db     = _ler(DB_FILE)
    ativos = {k: v for k, v in db.items() if v.get("acesso")}
    ok, err = 0, 0
    for uid_str in ativos:
        try:
            await ctx.bot.send_message(int(uid_str), f"📢 {msg}", parse_mode="Markdown")
            ok += 1
            await asyncio.sleep(0.05)
        except:
            err += 1
    await update.message.reply_text(f"📢 Enviado para ativos!\n✅ {ok} | ❌ {err}")

async def cmd_relatorio(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    db    = _ler(DB_FILE)
    hoje  = datetime.now()
    dias  = {}
    for i in range(7):
        dia = (hoje - timedelta(days=i)).strftime("%d/%m/%Y")
        dias[dia] = {"vendas": 0, "receita": 0}
    for uid, d in db.items():
        if not d.get("acesso"):
            continue
        dc = d.get("data_compra","")[:10]
        if dc in dias:
            preco = PLANOS.get(d.get("plano","basic"),{}).get("preco_int",0)
            dias[dc]["vendas"]  += 1
            dias[dc]["receita"] += preco
    linhas = []
    rt, tv = 0, 0
    for dia, info in sorted(dias.items(), reverse=True):
        barra = "█" * info["vendas"] if info["vendas"] else "─"
        linhas.append(f"`{dia}` {barra} {info['vendas']}v — R$ {info['receita']/100:.2f}")
        rt += info["receita"]
        tv += info["vendas"]
    await update.message.reply_text(
        "📈 *Relatório — 7 dias*\n\n" + "\n".join(linhas) +
        f"\n\n💰 Total: R$ {rt/100:.2f}\n🛒 Vendas: {tv}",
        parse_mode="Markdown"
    )

async def cmd_cupons(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    cupons = _ler(CUPONS_FILE) or CUPONS_PADRAO
    linhas = []
    for cod, c in cupons.items():
        tipo  = "%" if c["tipo"] == "percent" else "R$"
        resto = c["usos_max"] - c["usos"]
        linhas.append(f"🎁 `{cod}` — {c['desconto']}{tipo} | {c['usos']}/{c['usos_max']} usos | {resto} restantes")
    await update.message.reply_text(
        f"🎁 *Cupons ({len(cupons)}):*\n\n" + "\n".join(linhas),
        parse_mode="Markdown"
    )

async def cmd_cupom_add(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    if len(ctx.args) < 4:
        await update.message.reply_text("Uso: /cupom_add <CODIGO> <desconto> <percent|reais> <usos_max>")
        return
    cupons = _ler(CUPONS_FILE) or CUPONS_PADRAO
    cupons[ctx.args[0].upper()] = {
        "desconto": float(ctx.args[1]), "tipo": ctx.args[2],
        "usos_max": int(ctx.args[3]), "usos": 0
    }
    _salvar(CUPONS_FILE, cupons)
    await update.message.reply_text(f"✅ Cupom `{ctx.args[0].upper()}` criado!", parse_mode="Markdown")

async def cmd_atualizar_storage(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("🔄 Atualizando mídias do canal secreto...")
    midias = await buscar_midias_storage(ctx.bot, forcar=True)
    await update.message.reply_text(f"✅ Storage atualizado!\n📦 *{len(midias)} mídias* encontradas.", parse_mode="Markdown")

async def cmd_storage_info(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    storage = _ler(STORAGE_FILE)
    midias  = storage.get("midias", [])
    fotos   = sum(1 for m in midias if m["type"] == "photo")
    videos  = sum(1 for m in midias if m["type"] == "video")
    gifs    = sum(1 for m in midias if m["type"] == "animation")
    await update.message.reply_text(
        f"📦 *Storage*\n\n"
        f"📸 Fotos: `{fotos}`\n"
        f"🎬 Vídeos: `{videos}`\n"
        f"🎞️ GIFs: `{gifs}`\n"
        f"📊 Total: `{len(midias)}`\n"
        f"🕐 Atualizado: {storage.get('atualizado','nunca')}",
        parse_mode="Markdown"
    )

async def cmd_admin(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "🛠️ *Comandos Admin*\n\n"
        "📊 /painel — painel com botões\n"
        "📊 /stats — estatísticas\n"
        "📋 /clientes — lista clientes\n"
        "🔍 /buscar `<id ou @user>` — busca cliente\n"
        "📈 /relatorio — vendas 7 dias\n\n"
        "✅ /liberar `<id>` `<plano>` — libera acesso\n"
        "🚫 /bloquear `<id>` `[motivo]` — bloqueia\n"
        "🔓 /desbloquear `<id>` — desbloqueia\n\n"
        "📢 /broadcast `<msg>` — envia para todos\n"
        "📢 /broadcast\\_ativos `<msg>` — só ativos\n\n"
        "🎁 /cupons — lista cupons\n"
        "🎁 /cupom\\_add `<COD>` `<desc>` `<tipo>` `<usos>`\n\n"
        "📦 /atualizar\\_storage — recarrega mídias\n"
        "📦 /storage\\_info — info do cache",
        parse_mode="Markdown"
    )

# ═══════════════════════════════════════════
#  CALLBACKS — BOTÕES
# ═══════════════════════════════════════════

async def cb_handler(update, ctx):
    q    = update.callback_query
    user = q.from_user
    data = q.data
    await q.answer()

    if esta_bloqueado(user.id):
        await q.answer("❌ Acesso suspenso.", show_alert=True)
        return

    if data == "inicio":
        if tem_acesso(user.id):
            await responder(update, f"✅ Você já tem acesso!\n\nUse /reenviar para receber seus conteúdos.", kb_voltar())
        else:
            await responder(update, txt_boas_vindas(), kb_principal())

    elif data == "planos":
        linhas = ["🛒 *Escolha seu plano:*\n"]
        for pid, p in PLANOS.items():
            qtd = f"{p['limite']} conteúdos" if p["limite"] < 999 else "ilimitado"
            linhas.append(f"{p['emoji']} *{p['nome']}* — R$ {p['preco']}\n   _{p['descricao']} ({qtd})_\n")
        linhas.append("\n💡 _Tem cupom? Clique em 🎁 Cupom_")
        await responder(update, "\n".join(linhas), kb_planos())

    elif data.startswith("plano_"):
        plano_id = data.replace("plano_","")
        if plano_id not in PLANOS:
            return
        p  = PLANOS[plano_id]
        mp = gerar_pix_mp(plano_id, user.id, p["preco_int"])
        qr = mp.get("qr_code") if mp else None
        if mp:
            dados = cliente_get(user.id)
            dados["mp_payment_id"]  = mp["id"]
            dados["plano_pendente"] = plano_id
            cliente_salvar(user.id, dados)
        ctx.user_data["plano_selecionado"] = plano_id
        await responder(update, txt_pagamento_pix(plano_id, p["preco"], qr), kb_pagamento(plano_id))

    elif data == "cupom":
        ctx.user_data["aguardando_cupom"] = True
        await responder(update, "🎁 *Cupom de Desconto*\n\nDigite o código do seu cupom:", kb_voltar("planos"))

    elif data == "faq":
        await responder(update,
            "❓ *Perguntas Frequentes*\n\n"
            "🔹 *O acesso é vitalício?*\nSim! Pague uma vez, acesse para sempre.\n\n"
            "🔹 *Como recebo o conteúdo?*\nDireto aqui no Telegram, automaticamente.\n\n"
            "🔹 *Posso pedir reenvio?*\nSim! Use /reenviar a qualquer momento.\n\n"
            "🔹 *Quanto tempo para liberar?*\nEm até 2 minutos após o comprovante.\n\n"
            "🔹 *É seguro e discreto?*\n100%. Sua privacidade é prioridade.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 Comprar Agora", callback_data="planos")],
                [InlineKeyboardButton("🔙 Voltar",        callback_data="inicio")],
            ])
        )

    elif data == "suporte":
        await responder(update,
            f"💬 *Suporte*\n\nFale diretamente: {CONFIG['SUPORTE_USER']}\n\n⏱️ Resposta em até 1 hora.",
            kb_voltar()
        )

    elif data == "meu_acesso":
        if tem_acesso(user.id):
            dados = cliente_get(user.id)
            await responder(update,
                f"✅ Você tem o plano *{PLANOS[dados.get('plano','basic')]['nome']}*!\n\nUse /reenviar para receber seus conteúdos.",
                kb_voltar()
            )
        else:
            await responder(update, "🔒 *Acesso não encontrado.*\n\nSe já pagou, aguarde ou contate o suporte.",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 Comprar",  callback_data="planos")],
                    [InlineKeyboardButton("💬 Suporte",  callback_data="suporte")],
                ])
            )

    elif data.startswith("paguei_"):
        plano_id = data.replace("paguei_","")
        ctx.user_data["aguardando_comprovante"] = True
        ctx.user_data["plano_selecionado"]      = plano_id
        await responder(update,
            "📸 *Envie o comprovante de pagamento*\n\nEnvie uma *foto ou print* do comprovante PIX.\n\n⏱️ _Liberado em até 2 minutos._",
            kb_voltar("planos")
        )

async def cb_admin_liberar(update, ctx):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        await q.answer("❌ Sem permissão.", show_alert=True)
        return
    partes   = q.data.split("_", 5)
    uid      = int(partes[2])
    username = partes[3]
    nome     = partes[4]
    plano_id = partes[5] if len(partes) > 5 else "basic"
    liberar_acesso(uid, username, nome, plano_id)
    try:
        await ctx.bot.send_message(uid, txt_acesso_liberado(plano_id), parse_mode="Markdown")
        await asyncio.sleep(2)
        await enviar_conteudos(ctx.bot, uid, plano_id)
    except TelegramError as e:
        log.error(e)
    try:
        legenda = (q.message.caption or "") + "\n\n✅ *Liberado e pack enviado!*"
        await q.edit_message_caption(caption=legenda, parse_mode="Markdown")
    except:
        await q.answer("✅ Liberado!", show_alert=True)

async def cb_admin_recusar(update, ctx):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        await q.answer("❌ Sem permissão.", show_alert=True)
        return
    uid = int(q.data.split("_")[2])
    bloquear(uid, "comprovante recusado pelo admin")
    try:
        await ctx.bot.send_message(
            uid,
            "❌ *Seu comprovante foi recusado.*\n\nO pagamento não foi identificado.\nTente novamente ou contate o suporte.",
            parse_mode="Markdown"
        )
    except:
        pass
    try:
        legenda = (q.message.caption or "") + "\n\n🚫 *Recusado pelo admin.*"
        await q.edit_message_caption(caption=legenda, parse_mode="Markdown")
    except:
        await q.answer("🚫 Recusado!", show_alert=True)

async def cb_painel_botoes(update, ctx):
    q    = update.callback_query
    data = q.data
    await q.answer()
    if not is_admin(q.from_user.id):
        await q.answer("❌ Sem permissão.", show_alert=True)
        return

    db      = _ler(DB_FILE)
    storage = _ler(STORAGE_FILE)

    if data == "adm_stats":
        ativos = {k: v for k, v in db.items() if v.get("acesso")}
        hoje   = datetime.now().strftime("%d/%m/%Y")
        hoje_v = sum(1 for v in ativos.values() if v.get("data_compra","").startswith(hoje))
        por_plano = {}
        for v in ativos.values():
            p = v.get("plano","?")
            por_plano[p] = por_plano.get(p,0) + 1
        linhas = "\n".join([f"   {PLANOS.get(k,{}).get('emoji','?')} {k}: {n}" for k,n in por_plano.items()])
        await q.message.reply_text(
            f"📊 *Estatísticas*\n\n👥 Total: `{len(db)}`\n✅ Ativos: `{len(ativos)}`\n📅 Hoje: `{hoje_v}`\n\n📦 Por plano:\n{linhas or '   nenhum'}",
            parse_mode="Markdown"
        )

    elif data == "adm_clientes":
        ativos = {k: v for k, v in db.items() if v.get("acesso")}
        if not ativos:
            await q.message.reply_text("Nenhum cliente ativo.")
            return
        linhas = [f"• `{uid}` @{v.get('username','?')} [{v.get('plano','?')}] {v.get('data_compra','?')}" for uid, v in list(ativos.items())[:20]]
        await q.message.reply_text(f"📋 *Clientes ({len(ativos)}):*\n\n" + "\n".join(linhas), parse_mode="Markdown")

    elif data == "adm_storage":
        midias = storage.get("midias",[])
        fotos  = sum(1 for m in midias if m["type"]=="photo")
        videos = sum(1 for m in midias if m["type"]=="video")
        gifs   = sum(1 for m in midias if m["type"]=="animation")
        await q.message.reply_text(
            f"📦 *Storage*\n\n📸 Fotos: `{fotos}`\n🎬 Vídeos: `{videos}`\n🎞️ GIFs: `{gifs}`\n📊 Total: `{len(midias)}`\n🕐 {storage.get('atualizado','nunca')}",
            parse_mode="Markdown"
        )

    elif data == "adm_atualizar":
        await q.message.reply_text("🔄 Atualizando storage...")
        midias = await buscar_midias_storage(ctx.bot, forcar=True)
        await q.message.reply_text(f"✅ Storage atualizado! `{len(midias)}` mídias.", parse_mode="Markdown")

    elif data == "adm_cupons":
        cupons = _ler(CUPONS_FILE) or CUPONS_PADRAO
        linhas = []
        for cod, c in cupons.items():
            tipo = "%" if c["tipo"]=="percent" else "R$"
            linhas.append(f"🎁 `{cod}` — {c['desconto']}{tipo} | {c['usos']}/{c['usos_max']} usos")
        await q.message.reply_text(f"🎁 *Cupons ({len(cupons)}):*\n\n" + "\n".join(linhas), parse_mode="Markdown")

    elif data == "adm_relatorio":
        ativos = {k: v for k, v in db.items() if v.get("acesso") and v.get("data_compra")}
        hoje   = datetime.now()
        dias   = {}
        for i in range(7):
            dia = (hoje - timedelta(days=i)).strftime("%d/%m/%Y")
            dias[dia] = {"vendas": 0, "receita": 0}
        for uid, d in ativos.items():
            dc = d.get("data_compra","")[:10]
            if dc in dias:
                preco = PLANOS.get(d.get("plano","basic"),{}).get("preco_int",0)
                dias[dc]["vendas"]  += 1
                dias[dc]["receita"] += preco
        linhas = []
        rt, tv = 0, 0
        for dia, info in sorted(dias.items(), reverse=True):
            barra = "█" * info["vendas"] if info["vendas"] else "─"
            linhas.append(f"`{dia}` {barra} {info['vendas']}v — R$ {info['receita']/100:.2f}")
            rt += info["receita"]
            tv += info["vendas"]
        await q.message.reply_text(
            "📈 *Relatório 7 dias*\n\n" + "\n".join(linhas) + f"\n\n💰 Total: R$ {rt/100:.2f} | 🛒 {tv} vendas",
            parse_mode="Markdown"
        )

    elif data == "adm_broadcast_menu":
        ctx.user_data["aguardando_broadcast"] = True
        await q.message.reply_text("📢 *Broadcast*\n\nDigite a mensagem para *todos os usuários*:", parse_mode="Markdown")

# ═══════════════════════════════════════════
#  HANDLER — COMPROVANTE
# ═══════════════════════════════════════════

async def receber_midia(update, ctx):
    if update.effective_chat.type != "private":
        return
    user = update.effective_user
    if esta_bloqueado(user.id):
        return
    if not ctx.user_data.get("aguardando_comprovante"):
        await update.message.reply_text("📎 Se é um comprovante, clique em Comprar → Já Paguei primeiro.", reply_markup=kb_principal())
        return

    file_id        = None
    file_unique_id = None
    if update.message.photo:
        file_id        = update.message.photo[-1].file_id
        file_unique_id = update.message.photo[-1].file_unique_id
    elif update.message.document:
        file_id        = update.message.document.file_id
        file_unique_id = update.message.document.file_unique_id

    if file_id and comprovante_ja_usado(file_id, file_unique_id):
        bloquear(user.id, "comprovante duplicado")
        await update.message.reply_text("🚫 *Comprovante já utilizado! Conta suspensa por tentativa de fraude.*", parse_mode="Markdown")
        await notificar_admins(
            ctx.bot,
            f"🚨 *FRAUDE DETECTADA*\n\n👤 @{user.username or 'sem_username'}\n🆔 `{user.id}`\n📛 {user.full_name}\n\n⚠️ Comprovante duplicado — bloqueado automaticamente."
        )
        return

    plano_id = ctx.user_data.get("plano_selecionado","basic")
    ctx.user_data["aguardando_comprovante"] = False

    await update.message.reply_text(
        "✅ *Comprovante recebido!*\n\nEstamos verificando seu pagamento.\nVocê receberá os conteúdos em até 2 minutos. 🙏",
        parse_mode="Markdown"
    )

    uname   = (user.username or "sem_username").replace("_","-")
    nome    = user.full_name.replace("_","-")[:20]
    cb      = f"adm_liberar_{user.id}_{uname}_{nome}_{plano_id}"
    legenda = (
        f"🧾 *Novo Comprovante*\n"
        f"👤 @{user.username or 'sem_username'}\n"
        f"🆔 `{user.id}`\n"
        f"📛 {user.full_name}\n"
        f"📦 Plano: {PLANOS.get(plano_id,{}).get('nome','?')}\n"
        f"💰 Valor: R$ {PLANOS.get(plano_id,{}).get('preco','?')}\n"
        f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    )
    kb_admin = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Liberar + Enviar Pack", callback_data=cb)],
        [InlineKeyboardButton("🚫 Recusar (Fraude)",     callback_data=f"adm_recusar_{user.id}")],
    ])

    destinos = [int(CONFIG["GRUPO_COMPROVANTES"])] if CONFIG.get("GRUPO_COMPROVANTES") else CONFIG["ADMIN_IDS"]
    for dest in destinos:
        try:
            if update.message.photo:
                await ctx.bot.send_photo(dest, update.message.photo[-1].file_id, caption=legenda, parse_mode="Markdown", reply_markup=kb_admin)
            elif update.message.document:
                await ctx.bot.send_document(dest, update.message.document.file_id, caption=legenda, parse_mode="Markdown", reply_markup=kb_admin)
            else:
                await ctx.bot.send_message(dest, legenda + "\n_(sem imagem)_", parse_mode="Markdown", reply_markup=kb_admin)
        except TelegramError as e:
            log.error(f"Erro enviar comprovante {dest}: {e}")

# ═══════════════════════════════════════════
#  HANDLER — TEXTO LIVRE
# ═══════════════════════════════════════════

PALAVRAS = {
    "preco":   ["preço","preco","valor","quanto","custa"],
    "pix":     ["pix","pagar","pagamento","chave"],
    "cupom":   ["cupom","desconto","promo","código","codigo"],
    "acesso":  ["acesso","conteudo","conteúdo","reenviar"],
    "suporte": ["suporte","ajuda","help","problema"],
    "oi":      ["oi","olá","ola","bom dia","boa tarde","boa noite"],
}

async def texto_livre(update, ctx):
    if update.effective_chat.type != "private":
        return
    user  = update.effective_user
    texto = update.message.text.strip()

    # Broadcast pelo painel
    if is_admin(user.id) and ctx.user_data.get("aguardando_broadcast"):
        ctx.user_data["aguardando_broadcast"] = False
        db = _ler(DB_FILE)
        ok, err = 0, 0
        for uid_str in db:
            try:
                await ctx.bot.send_message(int(uid_str), f"📢 {texto}", parse_mode="Markdown")
                ok += 1
                await asyncio.sleep(0.05)
            except:
                err += 1
        await update.message.reply_text(f"📢 Broadcast enviado!\n✅ {ok} | ❌ {err}")
        return

    if esta_bloqueado(user.id):
        return
    registrar_visita(user.id, user.username or "", user.full_name)

    if tem_acesso(user.id):
        await update.message.reply_text("✅ Você já tem acesso!\n\nUse /reenviar para receber seus conteúdos.", reply_markup=kb_principal())
        return

    # Cupom digitado
    if ctx.user_data.get("aguardando_cupom"):
        ctx.user_data["aguardando_cupom"] = False
        plano_id = ctx.user_data.get("plano_selecionado","basic")
        cupom    = validar_cupom(texto)
        if not cupom:
            await update.message.reply_text("❌ *Cupom inválido ou expirado.*", parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Comprar sem cupom", callback_data="planos")]]))
            return
        plano     = PLANOS[plano_id]
        novo_int  = calc_preco_cupom(plano["preco_int"], cupom)
        novo_str  = f"{novo_int/100:.2f}".replace(".",",")
        usar_cupom(texto)
        tipo_desc = f"{cupom['desconto']}%" if cupom["tipo"]=="percent" else f"R$ {cupom['desconto']}"
        await update.message.reply_text(
            f"🎉 *Cupom `{texto.upper()}` aplicado!*\n💸 Desconto: {tipo_desc}\n💰 Novo valor: *R$ {novo_str}*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"💳 Pagar R$ {novo_str}", callback_data=f"plano_{plano_id}")]])
        )
        return

    tl = texto.lower()
    for tipo, palavras in PALAVRAS.items():
        if any(p in tl for p in palavras):
            if tipo == "cupom":
                ctx.user_data["aguardando_cupom"] = True
                await update.message.reply_text("🎁 Digite o código do seu cupom:")
            else:
                await update.message.reply_text(txt_boas_vindas(), parse_mode="Markdown", reply_markup=kb_principal())
            return

    await update.message.reply_text("😊 Use o menu abaixo!", reply_markup=kb_principal())

# ═══════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════

def main():
    if CONFIG["TOKEN"] == "SEU_TOKEN_AQUI":
        print("\n❌ Configure o TOKEN nas variáveis do Railway!\n")
        return

    app = Application.builder().token(CONFIG["TOKEN"]).build()

    # Clientes
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("reenviar", cmd_reenviar))

    # Admin
    app.add_handler(CommandHandler("admin",             cmd_admin))
    app.add_handler(CommandHandler("painel",            cmd_painel))
    app.add_handler(CommandHandler("stats",             cmd_stats))
    app.add_handler(CommandHandler("clientes",          cmd_clientes))
    app.add_handler(CommandHandler("buscar",            cmd_buscar))
    app.add_handler(CommandHandler("relatorio",         cmd_relatorio))
    app.add_handler(CommandHandler("cupons",            cmd_cupons))
    app.add_handler(CommandHandler("cupom_add",         cmd_cupom_add))
    app.add_handler(CommandHandler("liberar",           cmd_liberar))
    app.add_handler(CommandHandler("bloquear",          cmd_bloquear))
    app.add_handler(CommandHandler("desbloquear",       cmd_desbloquear))
    app.add_handler(CommandHandler("broadcast",         cmd_broadcast))
    app.add_handler(CommandHandler("broadcast_ativos",  cmd_broadcast_ativos))
    app.add_handler(CommandHandler("atualizar_storage", cmd_atualizar_storage))
    app.add_handler(CommandHandler("storage_info",      cmd_storage_info))

    # Callbacks
    app.add_handler(CallbackQueryHandler(cb_admin_liberar, pattern=r"^adm_liberar_"))
    app.add_handler(CallbackQueryHandler(cb_admin_recusar, pattern=r"^adm_recusar_"))
    app.add_handler(CallbackQueryHandler(cb_painel_botoes, pattern=r"^adm_"))
    app.add_handler(CallbackQueryHandler(cb_handler))

    # Mídia e texto
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, receber_midia))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, texto_livre))

    # Jobs
    jq = app.job_queue
    jq.run_repeating(job_follow_up,   interval=900,  first=60)
    jq.run_repeating(job_verificar_mp, interval=30,  first=10)
    jq.run_repeating(job_storage,     interval=3600, first=30)

    log.info("🚀 Bot PRO iniciado!")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
