import logging, json, os, asyncio, hashlib
from datetime import datetime, timedelta
from typing import Optional
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatInviteLink
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, JobQueue
)
from telegram.error import TelegramError

# ═══════════════════════════════════════════════════════
#  CONFIGURAÇÕES — lidas do Railway (Variables)
# ═══════════════════════════════════════════════════════

CONFIG = {
    "TOKEN":              os.environ.get("TOKEN",             "SEU_TOKEN_AQUI"),
    "ADMIN_IDS":          [int(x.strip()) for x in os.environ.get("ADMIN_ID", "123456789").split(",")],
    "CANAL_ID":           os.environ.get("CANAL_ID",          ""),        # canal de acesso dos clientes
    "CANAL_STORAGE_ID":   os.environ.get("CANAL_STORAGE_ID",  ""),        # canal secreto com seus conteúdos
    "LINK_CONTEUDO":      os.environ.get("LINK_CONTEUDO",     "https://seusite.com/conteudo"),
    "CHAVE_PIX":          os.environ.get("CHAVE_PIX",         "sua_chave_pix_aqui"),
    "NOME_RECEBEDOR":     os.environ.get("NOME_RECEBEDOR",    "Seu Nome"),
    "SUPORTE_USER":       os.environ.get("SUPORTE_USER",      "@seu_usuario"),
    "MP_ACCESS_TOKEN":    os.environ.get("MP_ACCESS_TOKEN",   ""),
    "DELAY_ENTRE_MIDIAS": float(os.environ.get("DELAY_ENTRE_MIDIAS", "1.5")),  # segundos entre envios
}

# ═══════════════════════════════════════════════════════
#  PLANOS
# ═══════════════════════════════════════════════════════

PLANOS = {
    "basic": {
        "nome":      "🔥 Basic",
        "preco":     "19,90",
        "preco_int": 1990,
        "descricao": "Pack básico com os melhores conteúdos",
        "emoji":     "🔥",
        "limite":    20,   # quantas mídias envia do canal storage
    },
    "premium": {
        "nome":      "💎 Premium",
        "preco":     "39,90",
        "preco_int": 3990,
        "descricao": "Pack completo + atualizações mensais",
        "emoji":     "💎",
        "limite":    50,
    },
    "vip": {
        "nome":      "👑 VIP",
        "preco":     "79,90",
        "preco_int": 7990,
        "descricao": "Tudo + conteúdo exclusivo + prioridade no suporte",
        "emoji":     "👑",
        "limite":    999,  # envia tudo
    },
}

CUPONS = {
    "PROMO50":  {"desconto": 50, "tipo": "percent", "usos_max": 100, "usos": 0},
    "INICIO10": {"desconto": 10, "tipo": "reais",   "usos_max": 50,  "usos": 0},
    "VIP20":    {"desconto": 20, "tipo": "percent", "usos_max": 30,  "usos": 0},
}

# ═══════════════════════════════════════════════════════
#  LOGGING
# ═══════════════════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot_pro.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
#  BANCO DE DADOS
# ═══════════════════════════════════════════════════════

DB_FILE        = "clientes.json"
CUPONS_FILE    = "cupons.json"
FRAUDE_FILE    = "hashes_comprovantes.json"
BLOQUEIOS_FILE = "bloqueados.json"
STORAGE_FILE   = "storage_ids.json"   # cache dos file_ids do canal secreto

def _ler(arquivo: str) -> dict:
    if not os.path.exists(arquivo):
        return {}
    try:
        with open(arquivo, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def _salvar(arquivo: str, dados):
    with open(arquivo, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=2, ensure_ascii=False)

def cliente_get(user_id: int) -> dict:
    return _ler(DB_FILE).get(str(user_id), {})

def cliente_salvar(user_id: int, dados: dict):
    db = _ler(DB_FILE)
    db[str(user_id)] = dados
    _salvar(DB_FILE, db)

def tem_acesso(user_id: int) -> bool:
    return cliente_get(user_id).get("acesso", False)

def esta_bloqueado(user_id: int) -> bool:
    return str(user_id) in _ler(BLOQUEIOS_FILE)

def liberar_acesso(user_id: int, username: str, nome: str, plano: str):
    dados = cliente_get(user_id)
    dados.update({
        "username": username,
        "nome": nome,
        "acesso": True,
        "plano": plano,
        "data_compra": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "follow_up_enviado": True,
        "conteudo_enviado": False,
    })
    cliente_salvar(user_id, dados)
    log.info(f"✅ Acesso liberado: ID={user_id} plano={plano}")

def registrar_visita(user_id: int, username: str, nome: str):
    dados = cliente_get(user_id)
    if not dados:
        dados = {
            "username": username,
            "nome": nome,
            "acesso": False,
            "primeira_visita": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "follow_up_enviado": False,
        }
        cliente_salvar(user_id, dados)

def bloquear_usuario(user_id: int, motivo: str):
    db = _ler(BLOQUEIOS_FILE)
    db[str(user_id)] = {"motivo": motivo, "data": datetime.now().strftime("%d/%m/%Y %H:%M")}
    _salvar(BLOQUEIOS_FILE, db)

def desbloquear_usuario(user_id: int):
    db = _ler(BLOQUEIOS_FILE)
    db.pop(str(user_id), None)
    _salvar(BLOQUEIOS_FILE, db)

def hash_arquivo(file_id: str) -> str:
    return hashlib.md5(file_id.encode()).hexdigest()

def comprovante_ja_usado(file_id: str) -> bool:
    hashes = _ler(FRAUDE_FILE)
    h = hash_arquivo(file_id)
    if h in hashes:
        return True
    hashes[h] = datetime.now().strftime("%d/%m/%Y %H:%M")
    _salvar(FRAUDE_FILE, hashes)
    return False

def validar_cupom(codigo: str) -> Optional[dict]:
    cupons = _ler(CUPONS_FILE) or CUPONS
    codigo = codigo.upper().strip()
    c = cupons.get(codigo)
    if not c or c["usos"] >= c["usos_max"]:
        return None
    return c

def usar_cupom(codigo: str):
    cupons = _ler(CUPONS_FILE) or CUPONS
    codigo = codigo.upper().strip()
    if codigo in cupons:
        cupons[codigo]["usos"] += 1
        _salvar(CUPONS_FILE, cupons)

def calcular_preco_com_cupom(preco_int: int, cupom: dict) -> int:
    if cupom["tipo"] == "percent":
        return int(preco_int * (1 - cupom["desconto"] / 100))
    return max(0, preco_int - int(cupom["desconto"] * 100))

# ═══════════════════════════════════════════════════════
#  CANAL STORAGE — buscar e enviar conteúdos
# ═══════════════════════════════════════════════════════

async def buscar_midias_storage(bot, forcar=False) -> list:
    """
    Busca todas as mídias do canal secreto e salva em cache.
    Retorna lista de dicts: [{type, file_id, caption}, ...]
    """
    storage = _ler(STORAGE_FILE)
    midias  = storage.get("midias", [])

    # Usa cache se já tiver e não forçar atualização
    if midias and not forcar:
        return midias

    canal_id = CONFIG.get("CANAL_STORAGE_ID", "")
    if not canal_id:
        log.warning("CANAL_STORAGE_ID não configurado!")
        return []

    log.info("🔄 Buscando mídias do canal storage...")
    midias = []

    try:
        # Pega as últimas 200 mensagens do canal
        # O Telegram não tem API de "listar mensagens" diretamente,
        # então usamos forward_messages com IDs sequenciais
        msg_id = 1
        erros_seguidos = 0

        while erros_seguidos < 10 and msg_id < 500:
            try:
                msg = await bot.forward_message(
                    chat_id=CONFIG["ADMIN_IDS"][0],
                    from_chat_id=canal_id,
                    message_id=msg_id,
                    disable_notification=True,
                )
                item = None
                if msg.photo:
                    item = {"type": "photo",    "file_id": msg.photo[-1].file_id, "caption": msg.caption or ""}
                elif msg.video:
                    item = {"type": "video",    "file_id": msg.video.file_id,     "caption": msg.caption or ""}
                elif msg.document:
                    item = {"type": "document", "file_id": msg.document.file_id,  "caption": msg.caption or ""}
                elif msg.animation:
                    item = {"type": "animation","file_id": msg.animation.file_id, "caption": msg.caption or ""}

                if item:
                    midias.append(item)
                    erros_seguidos = 0
                    # Deleta a mensagem encaminhada (limpeza)
                    try:
                        await bot.delete_message(CONFIG["ADMIN_IDS"][0], msg.message_id)
                    except:
                        pass

                msg_id += 1
                await asyncio.sleep(0.2)

            except TelegramError:
                erros_seguidos += 1
                msg_id += 1

    except Exception as e:
        log.error(f"Erro ao buscar mídias: {e}")

    if midias:
        _salvar(STORAGE_FILE, {"midias": midias, "atualizado": datetime.now().strftime("%d/%m/%Y %H:%M")})
        log.info(f"✅ {len(midias)} mídias encontradas no storage!")
    else:
        log.warning("⚠️ Nenhuma mídia encontrada no canal storage.")

    return midias

async def enviar_conteudos_cliente(bot, user_id: int, plano_id: str):
    """Envia as mídias do storage direto para o cliente."""
    midias = _ler(STORAGE_FILE).get("midias", [])

    if not midias:
        log.warning(f"Storage vazio ao enviar para {user_id}")
        await bot.send_message(
            user_id,
            "📦 Seus conteúdos estão sendo preparados e serão enviados em breve!",
            parse_mode="Markdown"
        )
        return

    limite = PLANOS.get(plano_id, {}).get("limite", 20)
    lista  = midias[:limite]
    total  = len(lista)

    await bot.send_message(
        user_id,
        f"🎬 *Enviando seu pack agora!*\n\n"
        f"📦 Total: *{total} conteúdos*\n"
        f"⏳ Aguarde, enviando um por um...",
        parse_mode="Markdown"
    )
    await asyncio.sleep(1)

    enviados = 0
    for item in lista:
        try:
            fid     = item["file_id"]
            caption = item.get("caption", "") or ""
            tipo    = item["type"]

            if tipo == "photo":
                await bot.send_photo(user_id,    photo=fid,     caption=caption)
            elif tipo == "video":
                await bot.send_video(user_id,    video=fid,     caption=caption)
            elif tipo == "document":
                await bot.send_document(user_id, document=fid,  caption=caption)
            elif tipo == "animation":
                await bot.send_animation(user_id,animation=fid, caption=caption)

            enviados += 1
            await asyncio.sleep(CONFIG["DELAY_ENTRE_MIDIAS"])

        except TelegramError as e:
            log.error(f"Erro ao enviar mídia para {user_id}: {e}")

    await bot.send_message(
        user_id,
        f"✅ *Pack completo enviado!*\n\n"
        f"📦 {enviados}/{total} conteúdos entregues.\n\n"
        f"Aproveite! 🔥\n"
        f"Dúvidas? Fale com {CONFIG['SUPORTE_USER']}",
        parse_mode="Markdown"
    )

    # Marca como enviado
    dados = cliente_get(user_id)
    dados["conteudo_enviado"] = True
    dados["conteudo_enviado_em"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    cliente_salvar(user_id, dados)
    log.info(f"📦 Pack enviado para {user_id}: {enviados} mídias")

# ═══════════════════════════════════════════════════════
#  MERCADO PAGO
# ═══════════════════════════════════════════════════════

def gerar_pix_mp(plano_id: str, user_id: int, preco_int: int) -> Optional[dict]:
    token = CONFIG.get("MP_ACCESS_TOKEN", "")
    if not token:
        return None
    try:
        import requests
        plano = PLANOS[plano_id]
        r = requests.post(
            "https://api.mercadopago.com/v1/payments",
            json={
                "transaction_amount": preco_int / 100,
                "description": f"Pack Premium +18 — {plano['nome']}",
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

async def verificar_pagamento_mp(payment_id: str) -> bool:
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

# ═══════════════════════════════════════════════════════
#  TEXTOS
# ═══════════════════════════════════════════════════════

def txt_boas_vindas() -> str:
    return (
        "👋 *Bem-vindo(a) ao Pack Premium +18!*\n\n"
        "Conteúdo adulto exclusivo e de altíssima qualidade. 🔥\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "✅ Acesso vitalício — pague uma vez\n"
        "✅ Conteúdo enviado direto aqui no Telegram\n"
        "✅ Sem link externo — tudo dentro do app\n"
        "✅ 100% discreto e seguro\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "👇 Escolha seu plano abaixo:"
    )

def txt_planos() -> str:
    linhas = ["🛒 *Escolha seu plano:*\n"]
    for pid, p in PLANOS.items():
        qtd = f"{p['limite']} conteúdos" if p["limite"] < 999 else "conteúdo ilimitado"
        linhas.append(
            f"{p['emoji']} *{p['nome']}* — R$ {p['preco']}\n"
            f"   _{p['descricao']} ({qtd})_\n"
        )
    linhas.append("\n💡 _Tem cupom de desconto? Clique em 🎁 Cupom_")
    return "\n".join(linhas)

def txt_pagamento_pix(plano_id: str, preco_str: str, qr_code: str = None) -> str:
    p = PLANOS[plano_id]
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
        f"4️⃣ Confirme o valor R$ {preco_str}\n"
        f"5️⃣ Clique em ✅ Já Paguei abaixo\n\n"
        f"⏱️ _Conteúdo enviado automaticamente em até 2 minutos._"
    )
    if qr_code:
        base += f"\n\n📱 *PIX Copia e Cola:*\n`{qr_code}`"
    return base

def txt_acesso_liberado(plano_id: str) -> str:
    p = PLANOS[plano_id]
    return (
        f"🎉 *Pagamento Confirmado!*\n\n"
        f"✅ Plano: *{p['nome']}*\n\n"
        f"📦 Seu pack está sendo preparado e será enviado aqui em instantes!\n\n"
        f"⏳ _Aguarde alguns segundos..._"
    )

def txt_follow_up_1h() -> str:
    return (
        "⏰ *Ei, você esqueceu de algo...*\n\n"
        "Você visitou nosso catálogo mas ainda não garantiu seu acesso! 😏\n\n"
        "🔥 O conteúdo está esperando por você.\n\n"
        "👇 Clique abaixo e garanta agora:"
    )

def txt_follow_up_24h() -> str:
    return (
        "🚨 *OFERTA ESPECIAL — só até hoje!*\n\n"
        "Use o cupom `PROMO50` e ganhe *50% de desconto* agora!\n\n"
        "⏳ _Esta oferta expira em 24h._\n\n"
        "👇 Garanta agora antes que acabe:"
    )

# ═══════════════════════════════════════════════════════
#  TECLADOS
# ═══════════════════════════════════════════════════════

def kb_principal() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Ver Planos e Comprar", callback_data="planos")],
        [InlineKeyboardButton("🎁 Tenho um Cupom",       callback_data="cupom")],
        [InlineKeyboardButton("❓ Dúvidas Frequentes",   callback_data="faq")],
        [InlineKeyboardButton("🔓 Já tenho acesso",      callback_data="meu_acesso")],
        [InlineKeyboardButton("💬 Suporte",              callback_data="suporte")],
    ])

def kb_planos() -> InlineKeyboardMarkup:
    botoes = []
    for pid, p in PLANOS.items():
        botoes.append([InlineKeyboardButton(
            f"{p['emoji']} {p['nome']} — R$ {p['preco']}",
            callback_data=f"plano_{pid}"
        )])
    botoes.append([InlineKeyboardButton("🔙 Voltar", callback_data="inicio")])
    return InlineKeyboardMarkup(botoes)

def kb_pagamento(plano_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Já Paguei!", callback_data=f"paguei_{plano_id}")],
        [InlineKeyboardButton("🔙 Voltar",    callback_data="planos")],
    ])

def kb_voltar(destino="inicio") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu Principal", callback_data=destino)]])

def kb_follow_up() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Quero Agora!", callback_data="planos")],
        [InlineKeyboardButton("🎁 Ver Cupons",   callback_data="cupom")],
    ])

# ═══════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════

async def responder(update: Update, texto: str, teclado=None, editar=True):
    kwargs = {"text": texto, "parse_mode": "Markdown", "reply_markup": teclado}
    try:
        if editar and update.callback_query:
            await update.callback_query.edit_message_text(**kwargs)
        else:
            msg = update.message or update.callback_query.message
            await msg.reply_text(**kwargs)
    except TelegramError as e:
        log.warning(f"responder(): {e}")

async def gerar_link_canal(bot, user_id: int) -> str:
    canal_id = CONFIG.get("CANAL_ID", "")
    if canal_id:
        try:
            invite: ChatInviteLink = await bot.create_chat_invite_link(
                chat_id=canal_id,
                member_limit=1,
                name=f"Cliente {user_id}",
            )
            return invite.invite_link
        except TelegramError as e:
            log.error(f"Erro ao criar link do canal: {e}")
    return CONFIG["LINK_CONTEUDO"]

# ═══════════════════════════════════════════════════════
#  JOBS AUTOMÁTICOS
# ═══════════════════════════════════════════════════════

async def job_follow_up(context: ContextTypes.DEFAULT_TYPE):
    db   = _ler(DB_FILE)
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
            if timedelta(hours=1) <= diff < timedelta(hours=2) and not dados.get("follow_up_1h"):
                await context.bot.send_message(uid, txt_follow_up_1h(), parse_mode="Markdown", reply_markup=kb_follow_up())
                dados["follow_up_1h"] = True
                cliente_salvar(uid, dados)
            elif diff >= timedelta(hours=24) and not dados.get("follow_up_24h"):
                await context.bot.send_message(uid, txt_follow_up_24h(), parse_mode="Markdown", reply_markup=kb_follow_up())
                dados["follow_up_24h"]      = True
                dados["follow_up_enviado"]  = True
                cliente_salvar(uid, dados)
        except TelegramError:
            pass

async def job_verificar_mp(context: ContextTypes.DEFAULT_TYPE):
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
        pago = await verificar_pagamento_mp(str(pid))
        if pago:
            uid = int(uid_str)
            liberar_acesso(uid, dados.get("username",""), dados.get("nome",""), plano_id)
            try:
                await context.bot.send_message(uid, txt_acesso_liberado(plano_id), parse_mode="Markdown")
                await asyncio.sleep(2)
                await enviar_conteudos_cliente(context.bot, uid, plano_id)
            except TelegramError as e:
                log.error(e)

async def job_atualizar_storage(context: ContextTypes.DEFAULT_TYPE):
    """Atualiza o cache de mídias do canal secreto a cada hora."""
    await buscar_midias_storage(context.bot, forcar=True)

# ═══════════════════════════════════════════════════════
#  HANDLERS — COMANDOS
# ═══════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if esta_bloqueado(user.id):
        await update.message.reply_text("❌ Seu acesso foi suspenso. Contate o suporte.")
        return
    registrar_visita(user.id, user.username or "", user.full_name)
    if tem_acesso(user.id):
        dados    = cliente_get(user.id)
        plano_id = dados.get("plano", "basic")
        if not dados.get("conteudo_enviado"):
            await update.message.reply_text("📦 Reenviando seu pack...", parse_mode="Markdown")
            await enviar_conteudos_cliente(ctx.bot, user.id, plano_id)
        else:
            await update.message.reply_text(
                f"✅ Você já tem acesso ao plano *{PLANOS[plano_id]['nome']}*!\n\n"
                f"Use /reenviar para receber os conteúdos novamente.",
                parse_mode="Markdown"
            )
        return
    await update.message.reply_text(txt_boas_vindas(), parse_mode="Markdown", reply_markup=kb_principal())

async def cmd_reenviar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Cliente pode pedir reenvio dos conteúdos."""
    user = update.effective_user
    if not tem_acesso(user.id):
        await update.message.reply_text("❌ Você não tem acesso. Use /start para comprar.")
        return
    dados    = cliente_get(user.id)
    plano_id = dados.get("plano", "basic")
    await update.message.reply_text("📦 Reenviando seu pack completo!", parse_mode="Markdown")
    await enviar_conteudos_cliente(ctx.bot, user.id, plano_id)

async def cmd_atualizar_storage(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin: /atualizar_storage — recarrega as mídias do canal secreto."""
    if update.effective_user.id not in CONFIG["ADMIN_IDS"]:
        return
    await update.message.reply_text("🔄 Atualizando mídias do canal secreto...")
    midias = await buscar_midias_storage(ctx.bot, forcar=True)
    await update.message.reply_text(
        f"✅ Storage atualizado!\n📦 *{len(midias)} mídias* encontradas.",
        parse_mode="Markdown"
    )

async def cmd_storage_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin: /storage_info — mostra quantas mídias tem no cache."""
    if update.effective_user.id not in CONFIG["ADMIN_IDS"]:
        return
    storage = _ler(STORAGE_FILE)
    midias  = storage.get("midias", [])
    atz     = storage.get("atualizado", "nunca")
    fotos   = sum(1 for m in midias if m["type"] == "photo")
    videos  = sum(1 for m in midias if m["type"] == "video")
    docs    = sum(1 for m in midias if m["type"] == "document")
    gifs    = sum(1 for m in midias if m["type"] == "animation")
    await update.message.reply_text(
        f"📦 *Storage de Conteúdos*\n\n"
        f"📸 Fotos: `{fotos}`\n"
        f"🎬 Vídeos: `{videos}`\n"
        f"📄 Docs: `{docs}`\n"
        f"🎞️ GIFs: `{gifs}`\n"
        f"📊 Total: `{len(midias)}`\n\n"
        f"🕐 Última atualização: {atz}",
        parse_mode="Markdown"
    )

async def cmd_liberar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in CONFIG["ADMIN_IDS"]:
        return
    args = ctx.args
    if len(args) < 2:
        await update.message.reply_text("Uso: /liberar <user_id> <basic|premium|vip>")
        return
    uid, plano_id = int(args[0]), args[1]
    if plano_id not in PLANOS:
        await update.message.reply_text(f"Plano inválido. Use: {', '.join(PLANOS.keys())}")
        return
    dados = cliente_get(uid)
    liberar_acesso(uid, dados.get("username","manual"), dados.get("nome","manual"), plano_id)
    try:
        await ctx.bot.send_message(uid, txt_acesso_liberado(plano_id), parse_mode="Markdown")
        await asyncio.sleep(2)
        await enviar_conteudos_cliente(ctx.bot, uid, plano_id)
        await update.message.reply_text(f"✅ Acesso e conteúdos enviados para `{uid}`!", parse_mode="Markdown")
    except TelegramError as e:
        await update.message.reply_text(f"⚠️ Salvo, erro ao notificar: {e}")

async def cmd_bloquear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in CONFIG["ADMIN_IDS"]:
        return
    args = ctx.args
    if not args:
        return
    uid    = int(args[0])
    motivo = " ".join(args[1:]) if len(args) > 1 else "sem motivo"
    bloquear_usuario(uid, motivo)
    await update.message.reply_text(f"🚫 `{uid}` bloqueado.", parse_mode="Markdown")

async def cmd_desbloquear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in CONFIG["ADMIN_IDS"]:
        return
    args = ctx.args
    if not args:
        return
    desbloquear_usuario(int(args[0]))
    await update.message.reply_text(f"✅ `{args[0]}` desbloqueado.", parse_mode="Markdown")

async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in CONFIG["ADMIN_IDS"]:
        return
    if not ctx.args:
        await update.message.reply_text("Uso: /broadcast <mensagem>")
        return
    mensagem  = " ".join(ctx.args)
    db        = _ler(DB_FILE)
    enviados, erros = 0, 0
    for uid_str in db:
        try:
            await ctx.bot.send_message(int(uid_str), f"📢 {mensagem}", parse_mode="Markdown")
            enviados += 1
            await asyncio.sleep(0.05)
        except:
            erros += 1
    await update.message.reply_text(f"📢 Enviado!\n✅ {enviados} | ❌ {erros}")

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in CONFIG["ADMIN_IDS"]:
        return
    db     = _ler(DB_FILE)
    ativos = {k: v for k, v in db.items() if v.get("acesso")}
    hoje   = datetime.now().strftime("%d/%m/%Y")
    hoje_v = sum(1 for v in ativos.values() if v.get("data_compra","").startswith(hoje))
    por_plano = {}
    for v in ativos.values():
        p = v.get("plano","?")
        por_plano[p] = por_plano.get(p, 0) + 1
    linhas = "\n".join([f"   {PLANOS.get(k,{}).get('emoji','?')} {k}: {n}" for k, n in por_plano.items()])
    await update.message.reply_text(
        f"📊 *Estatísticas*\n\n"
        f"👥 Total: `{len(db)}`\n"
        f"✅ Ativos: `{len(ativos)}`\n"
        f"📅 Hoje: `{hoje_v}`\n\n"
        f"📦 Por plano:\n{linhas or '   nenhum'}",
        parse_mode="Markdown"
    )

async def cmd_clientes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in CONFIG["ADMIN_IDS"]:
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
        f"📋 *Clientes ({len(ativos)}):*\n\n" + "\n".join(linhas),
        parse_mode="Markdown"
    )

async def cmd_cupom_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in CONFIG["ADMIN_IDS"]:
        return
    args = ctx.args
    if len(args) < 4:
        await update.message.reply_text("Uso: /cupom_add <CODIGO> <desconto> <percent|reais> <usos_max>")
        return
    cupons = _ler(CUPONS_FILE) or CUPONS
    cupons[args[0].upper()] = {"desconto": float(args[1]), "tipo": args[2], "usos_max": int(args[3]), "usos": 0}
    _salvar(CUPONS_FILE, cupons)
    await update.message.reply_text(f"✅ Cupom `{args[0].upper()}` criado!", parse_mode="Markdown")

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in CONFIG["ADMIN_IDS"]:
        return
    await update.message.reply_text(
        "🛠️ *Comandos Admin*\n\n"
        "📦 *Storage (conteúdos):*\n"
        "/atualizar\\_storage — recarrega mídias do canal secreto\n"
        "/storage\\_info — quantas mídias tem no cache\n\n"
        "👥 *Clientes:*\n"
        "/stats — estatísticas\n"
        "/clientes — lista clientes\n"
        "/liberar `<id>` `<plano>` — libera e envia conteúdo\n"
        "/bloquear `<id>` — bloqueia usuário\n"
        "/desbloquear `<id>` — desbloqueia\n"
        "/broadcast `<msg>` — manda para todos\n\n"
        "🎁 *Cupons:*\n"
        "/cupom\\_add `<COD>` `<desc>` `<tipo>` `<usos>`",
        parse_mode="Markdown"
    )

# ═══════════════════════════════════════════════════════
#  HANDLERS — BOTÕES
# ═══════════════════════════════════════════════════════

async def cb_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    data = q.data
    await q.answer()

    if esta_bloqueado(user.id):
        await q.answer("❌ Acesso suspenso.", show_alert=True)
        return

    if data == "inicio":
        if tem_acesso(user.id):
            dados = cliente_get(user.id)
            await responder(update,
                f"✅ Você já tem o plano *{PLANOS[dados.get('plano','basic')]['nome']}*!\n\n"
                f"Use /reenviar para receber os conteúdos.",
                parse_mode="Markdown"
            )
        else:
            await responder(update, txt_boas_vindas(), kb_principal())

    elif data == "planos":
        await responder(update, txt_planos(), kb_planos())

    elif data.startswith("plano_"):
        plano_id = data.replace("plano_", "")
        if plano_id not in PLANOS:
            return
        p = PLANOS[plano_id]
        ctx.user_data["plano_selecionado"] = plano_id
        ctx.user_data["preco_final"]       = p["preco"]
        mp = gerar_pix_mp(plano_id, user.id, p["preco_int"])
        qr = mp.get("qr_code") if mp else None
        if mp:
            dados = cliente_get(user.id)
            dados["mp_payment_id"]  = mp["id"]
            dados["plano_pendente"] = plano_id
            cliente_salvar(user.id, dados)
        await responder(update, txt_pagamento_pix(plano_id, p["preco"], qr), kb_pagamento(plano_id))

    elif data == "cupom":
        ctx.user_data["aguardando_cupom"] = True
        await responder(update,
            "🎁 *Cupom de Desconto*\n\nDigite o código do seu cupom:",
            kb_voltar("planos")
        )

    elif data == "faq":
        await responder(update,
            "❓ *Perguntas Frequentes*\n\n"
            "🔹 *O acesso é vitalício?*\nSim! Pague uma vez, acesse para sempre.\n\n"
            "🔹 *Como recebo o conteúdo?*\nDireto aqui no Telegram, automaticamente após o pagamento.\n\n"
            "🔹 *Posso pedir reenvio?*\nSim! Use o comando /reenviar a qualquer momento.\n\n"
            "🔹 *Quanto tempo para liberar?*\nEm até 2 minutos após envio do comprovante.\n\n"
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
                f"✅ Você tem o plano *{PLANOS[dados.get('plano','basic')]['nome']}*!\n\n"
                f"Use /reenviar para receber os conteúdos novamente.",
                kb_voltar()
            )
        else:
            await responder(update,
                "🔒 *Acesso não encontrado*\n\nSe você já pagou, aguarde ou contate o suporte.",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 Comprar",  callback_data="planos")],
                    [InlineKeyboardButton("💬 Suporte",  callback_data="suporte")],
                ])
            )

    elif data.startswith("paguei_"):
        plano_id = data.replace("paguei_", "")
        ctx.user_data["aguardando_comprovante"] = True
        ctx.user_data["plano_selecionado"]      = plano_id
        await responder(update,
            "📸 *Envie o comprovante de pagamento*\n\n"
            "Envie uma *foto ou print* do comprovante PIX.\n\n"
            "⏱️ _Conteúdo liberado em até 2 minutos._",
            kb_voltar("planos")
        )

    elif data.startswith("adm_liberar_"):
        await cb_admin_liberar(update, ctx)

# ═══════════════════════════════════════════════════════
#  ADMIN — liberar pelo botão
# ═══════════════════════════════════════════════════════

async def cb_admin_liberar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id not in CONFIG["ADMIN_IDS"]:
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
        await enviar_conteudos_cliente(ctx.bot, uid, plano_id)
    except TelegramError as e:
        log.error(e)
    try:
        legenda = (q.message.caption or "") + "\n\n✅ *Liberado e conteúdo enviado!*"
        await q.edit_message_caption(caption=legenda, parse_mode="Markdown")
    except:
        await q.answer("✅ Liberado!", show_alert=True)

# ═══════════════════════════════════════════════════════
#  HANDLER — COMPROVANTE
# ═══════════════════════════════════════════════════════

async def receber_midia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if esta_bloqueado(user.id):
        return
    if not ctx.user_data.get("aguardando_comprovante"):
        await update.message.reply_text(
            "📎 Se é um comprovante, clique em *Comprar* → *Já Paguei* primeiro.",
            parse_mode="Markdown", reply_markup=kb_principal()
        )
        return

    file_id = None
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.document:
        file_id = update.message.document.file_id

    if file_id and comprovante_ja_usado(file_id):
        bloquear_usuario(user.id, "comprovante duplicado")
        await update.message.reply_text("🚫 *Comprovante já utilizado! Conta suspensa.*", parse_mode="Markdown")
        for admin_id in CONFIG["ADMIN_IDS"]:
            await ctx.bot.send_message(
                admin_id,
                f"🚨 *FRAUDE* — @{user.username} ID `{user.id}`", parse_mode="Markdown"
            )
        return

    plano_id = ctx.user_data.get("plano_selecionado", "basic")
    ctx.user_data["aguardando_comprovante"] = False

    await update.message.reply_text(
        "✅ *Comprovante recebido!*\n\nVerificando... você receberá os conteúdos em até 2 minutos. 🙏",
        parse_mode="Markdown"
    )

    uname = (user.username or "sem_username").replace("_", "-")
    nome  = user.full_name.replace("_", "-")[:20]
    cb    = f"adm_liberar_{user.id}_{uname}_{nome}_{plano_id}"
    legenda = (
        f"🧾 *Novo Comprovante*\n"
        f"👤 @{user.username or 'sem_username'}\n"
        f"🆔 `{user.id}`\n"
        f"📦 Plano: {PLANOS.get(plano_id,{}).get('nome','?')}\n"
        f"💰 Valor: R$ {PLANOS.get(plano_id,{}).get('preco','?')}"
    )
    kb_admin = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"✅ Liberar + Enviar Pack", callback_data=cb)
    ]])
    try:
        for admin_id in CONFIG["ADMIN_IDS"]:
            if update.message.photo:
                await ctx.bot.send_photo(admin_id, update.message.photo[-1].file_id,
                    caption=legenda, parse_mode="Markdown", reply_markup=kb_admin)
            elif update.message.document:
                await ctx.bot.send_document(admin_id, update.message.document.file_id,
                    caption=legenda, parse_mode="Markdown", reply_markup=kb_admin)
    except TelegramError as e:
        log.error(e)

# ═══════════════════════════════════════════════════════
#  HANDLER — TEXTO LIVRE
# ═══════════════════════════════════════════════════════

PALAVRAS = {
    "preco":    ["preço","preco","valor","quanto","custa"],
    "pix":      ["pix","pagar","pagamento","chave"],
    "acesso":   ["acesso","conteudo","conteúdo","onde","como acessar","reenviar"],
    "faq":      ["duvida","dúvida","faq","como funciona"],
    "suporte":  ["suporte","ajuda","help","problema","erro"],
    "saudacao": ["oi","olá","ola","bom dia","boa tarde","boa noite"],
    "cupom":    ["cupom","desconto","promo","código"],
}

async def texto_livre(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user  = update.effective_user
    texto = update.message.text.strip()
    if esta_bloqueado(user.id):
        return
    registrar_visita(user.id, user.username or "", user.full_name)
    if tem_acesso(user.id):
        await update.message.reply_text(
            "✅ Você já tem acesso!\n\nUse /reenviar para receber seus conteúdos.",
            reply_markup=kb_principal()
        )
        return
    if ctx.user_data.get("aguardando_cupom"):
        ctx.user_data["aguardando_cupom"] = False
        plano_id = ctx.user_data.get("plano_selecionado", "basic")
        cupom    = validar_cupom(texto)
        if not cupom:
            await update.message.reply_text(
                "❌ *Cupom inválido ou expirado.*", parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 Comprar sem cupom", callback_data="planos")]
                ])
            )
            return
        plano          = PLANOS[plano_id]
        novo_int       = calcular_preco_com_cupom(plano["preco_int"], cupom)
        novo_str       = f"{novo_int/100:.2f}".replace(".", ",")
        ctx.user_data["preco_final"]     = novo_str
        ctx.user_data["preco_final_int"] = novo_int
        usar_cupom(texto)
        tipo_desc = f"{cupom['desconto']}%" if cupom["tipo"] == "percent" else f"R$ {cupom['desconto']}"
        await update.message.reply_text(
            f"🎉 *Cupom `{texto.upper()}` aplicado!*\n💸 Desconto: {tipo_desc}\n💰 Novo valor: *R$ {novo_str}*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"💳 Pagar R$ {novo_str}", callback_data=f"plano_{plano_id}")]
            ])
        )
        return

    tl = texto.lower()
    for tipo, palavras in PALAVRAS.items():
        if any(p in tl for p in palavras):
            if tipo in ("preco", "pix", "saudacao", "acesso", "faq", "suporte"):
                await update.message.reply_text(txt_boas_vindas(), parse_mode="Markdown", reply_markup=kb_principal())
            elif tipo == "cupom":
                ctx.user_data["aguardando_cupom"] = True
                await update.message.reply_text("🎁 Digite o código do seu cupom:")
            return

    await update.message.reply_text("😊 Use o menu abaixo!", reply_markup=kb_principal())

# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════

def main():
    if CONFIG["TOKEN"] == "SEU_TOKEN_AQUI":
        print("\n❌ Configure o TOKEN nas variáveis do Railway!\n")
        return

    app = Application.builder().token(CONFIG["TOKEN"]).build()

    # Comandos
    app.add_handler(CommandHandler("start",             cmd_start))
    app.add_handler(CommandHandler("reenviar",          cmd_reenviar))
    app.add_handler(CommandHandler("atualizar_storage", cmd_atualizar_storage))
    app.add_handler(CommandHandler("storage_info",      cmd_storage_info))
    app.add_handler(CommandHandler("liberar",           cmd_liberar))
    app.add_handler(CommandHandler("bloquear",          cmd_bloquear))
    app.add_handler(CommandHandler("desbloquear",       cmd_desbloquear))
    app.add_handler(CommandHandler("broadcast",         cmd_broadcast))
    app.add_handler(CommandHandler("stats",             cmd_stats))
    app.add_handler(CommandHandler("clientes",          cmd_clientes))
    app.add_handler(CommandHandler("cupom_add",         cmd_cupom_add))
    app.add_handler(CommandHandler("admin",             cmd_admin))

    # Callbacks
    app.add_handler(CallbackQueryHandler(cb_admin_liberar, pattern=r"^adm_liberar_"))
    app.add_handler(CallbackQueryHandler(cb_handler))

    # Mídia
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, receber_midia))

    # Texto
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, texto_livre))

    # Jobs
    jq = app.job_queue
    jq.run_repeating(job_follow_up,          interval=900, first=60)
    jq.run_repeating(job_verificar_mp,       interval=30,  first=10)
    jq.run_repeating(job_atualizar_storage,  interval=3600, first=30)  # atualiza storage a cada 1h

    log.info("🚀 Bot PRO + Storage iniciado!")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
