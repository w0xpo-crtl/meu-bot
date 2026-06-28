# ═══════════════════════════════════════════════════════
#  IMPORTS
# ═══════════════════════════════════════════════════════
import logging, json, os, asyncio, hashlib, re
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
#  ██████╗ ██████╗ ███╗   ██╗███████╗██╗ ██████╗
#  ██╔════╝██╔═══██╗████╗  ██║██╔════╝██║██╔════╝
#  ██║     ██║   ██║██╔██╗ ██║█████╗  ██║██║  ███╗
#  ██║     ██║   ██║██║╚██╗██║██╔══╝  ██║██║   ██║
#  ╚██████╗╚██████╔╝██║ ╚████║██║     ██║╚██████╔╝
#   ╚═════╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝     ╚═╝ ╚═════╝
#  EDITE APENAS ESTE BLOCO ANTES DE RODAR
# ═══════════════════════════════════════════════════════

CONFIG = {
    # ── Bot ──────────────────────────────────────────
    "TOKEN":            "7740841715:AAEHBEhh46VtwhN17OHsbefqqrM-snNAh_c",       # @BotFather
    "ADMIN_ID":         8145171278,              # Seu ID (@userinfobot)

    # ── Canal de conteúdo (opcional) ─────────────────
    # Crie um canal privado, adicione o bot como admin
    # e cole o ID aqui (ex: -1001234567890)
    # Deixe "" para usar link externo
    "CANAL_ID":         "",

    # ── Link do conteúdo (se não usar canal) ─────────
    "LINK_CONTEUDO":    "https://seusite.com/conteudo",

    # ── PIX ──────────────────────────────────────────
    "CHAVE_PIX":        "cbba5bc2-d199-41ce-b758-c019cee88cc3",
    "NOME_RECEBEDOR":   "Kaua Gobo",

    # ── Suporte ──────────────────────────────────────
    "SUPORTE_USER":     "@W0xpo",

    # ── Mercado Pago (deixe "" para usar PIX manual) ─
    # Crie conta em mercadopago.com.br → Credenciais
    "MP_ACCESS_TOKEN":  "",
}

# ── Planos de venda ──────────────────────────────────
PLANOS = {
    "basic": {
        "nome":     "🔥 Basic",
        "preco":    "19,90",
        "preco_int": 1990,           # em centavos
        "descricao": "Pack básico com os melhores conteúdos",
        "emoji":    "🔥",
    },
    "premium": {
        "nome":     "💎 Premium",
        "preco":    "39,90",
        "preco_int": 3990,
        "descricao": "Pack completo + atualizações mensais",
        "emoji":    "💎",
    },
    "vip": {
        "nome":     "👑 VIP",
        "preco":    "79,90",
        "preco_int": 7990,
        "descricao": "Tudo + conteúdo exclusivo + prioridade no suporte",
        "emoji":    "👑",
    },
}

# ── Cupons de desconto ───────────────────────────────
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
DB_FILE      = "clientes.json"
CUPONS_FILE  = "cupons.json"
FRAUDE_FILE  = "hashes_comprovantes.json"
BLOQUEIOS_FILE = "bloqueados.json"

def _ler(arquivo: str) -> dict:
    if not os.path.exists(arquivo):
        return {}
    try:
        with open(arquivo, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def _salvar(arquivo: str, dados: dict):
    with open(arquivo, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=2, ensure_ascii=False)

# ── Clientes ─────────────────────────────────────────
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

# ── Anti-fraude ──────────────────────────────────────
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

def bloquear_usuario(user_id: int, motivo: str):
    db = _ler(BLOQUEIOS_FILE)
    db[str(user_id)] = {"motivo": motivo, "data": datetime.now().strftime("%d/%m/%Y %H:%M")}
    _salvar(BLOQUEIOS_FILE, db)
    log.warning(f"🚫 Usuário bloqueado: {user_id} — {motivo}")

def desbloquear_usuario(user_id: int):
    db = _ler(BLOQUEIOS_FILE)
    db.pop(str(user_id), None)
    _salvar(BLOQUEIOS_FILE, db)

# ── Cupons ───────────────────────────────────────────
def validar_cupom(codigo: str, plano_id: str) -> Optional[dict]:
    cupons = _ler(CUPONS_FILE) or CUPONS
    codigo = codigo.upper().strip()
    if codigo not in cupons:
        return None
    c = cupons[codigo]
    if c["usos"] >= c["usos_max"]:
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
    else:
        return max(0, preco_int - cupom["desconto"] * 100)

# ═══════════════════════════════════════════════════════
#  MERCADO PAGO (PIX automático)
# ═══════════════════════════════════════════════════════
def gerar_pix_mp(plano_id: str, user_id: int, preco_final_int: int) -> Optional[dict]:
    """Gera cobrança PIX no Mercado Pago e retorna {qr_code, qr_code_base64, id}"""
    token = CONFIG.get("MP_ACCESS_TOKEN", "")
    if not token:
        return None
    try:
        import requests
        plano = PLANOS[plano_id]
        payload = {
            "transaction_amount": preco_final_int / 100,
            "description": f"Pack Premium +18 — {plano['nome']}",
            "payment_method_id": "pix",
            "payer": {"email": f"cliente_{user_id}@bot.com"},
            "notification_url": "",
            "external_reference": f"{user_id}_{plano_id}_{int(datetime.now().timestamp())}",
        }
        r = requests.post(
            "https://api.mercadopago.com/v1/payments",
            json=payload,
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
                "status_url": f"https://api.mercadopago.com/v1/payments/{data['id']}",
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
        data = r.json()
        return data.get("status") == "approved"
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
        "✅ Conteúdo atualizado constantemente\n"
        "✅ 100% discreto e seguro\n"
        "✅ Liberação automática após pagamento\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "👇 Escolha seu plano abaixo:"
    )

def txt_planos() -> str:
    linhas = ["🛒 *Escolha seu plano:*\n"]
    for pid, p in PLANOS.items():
        linhas.append(
            f"{p['emoji']} *{p['nome']}* — R$ {p['preco']}\n"
            f"   _{p['descricao']}_\n"
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
        f"⏱️ _Acesso liberado em até 2 minutos._"
    )
    if qr_code:
        base += f"\n\n📱 *PIX Copia e Cola:*\n`{qr_code}`"
    return base

def txt_acesso_liberado(plano_id: str, link: str) -> str:
    p = PLANOS[plano_id]
    return (
        f"🎉 *Acesso Liberado! Seja bem-vindo(a)!*\n\n"
        f"✅ Plano: *{p['nome']}*\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 *Seu acesso exclusivo:*\n{link}\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚠️ *Importante:*\n"
        f"• Não compartilhe este link/convite\n"
        f"• Acesso pessoal e intransferível\n"
        f"• Compartilhar = cancelamento sem reembolso\n\n"
        f"Aproveite! 🔥🔥🔥"
    )

def txt_follow_up_1h() -> str:
    return (
        "⏰ *Ei, você esqueceu de algo...*\n\n"
        "Vi que você visitou nosso catálogo mas ainda não garantiu seu acesso! 😏\n\n"
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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Menu Principal", callback_data=destino)]
    ])

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
#  JOBS — FOLLOW-UP AUTOMÁTICO
# ═══════════════════════════════════════════════════════
async def job_follow_up(context: ContextTypes.DEFAULT_TYPE):
    """Roda a cada 15min e envia follow-up para quem não comprou."""
    db = _ler(DB_FILE)
    agora = datetime.now()
    for uid_str, dados in db.items():
        if dados.get("acesso") or dados.get("follow_up_enviado"):
            continue
        primeira = dados.get("primeira_visita")
        if not primeira:
            continue
        try:
            dt = datetime.strptime(primeira, "%d/%m/%Y %H:%M")
        except:
            continue
        diff = agora - dt
        uid = int(uid_str)
        try:
            if timedelta(hours=1) <= diff < timedelta(hours=2):
                await context.bot.send_message(
                    uid, txt_follow_up_1h(),
                    parse_mode="Markdown", reply_markup=kb_follow_up()
                )
                dados["follow_up_1h"] = True
                cliente_salvar(uid, dados)
                log.info(f"📩 Follow-up 1h enviado para {uid}")
            elif diff >= timedelta(hours=24) and not dados.get("follow_up_24h"):
                await context.bot.send_message(
                    uid, txt_follow_up_24h(),
                    parse_mode="Markdown", reply_markup=kb_follow_up()
                )
                dados["follow_up_24h"] = True
                dados["follow_up_enviado"] = True
                cliente_salvar(uid, dados)
                log.info(f"📩 Follow-up 24h enviado para {uid}")
        except TelegramError:
            pass

async def job_verificar_pagamentos_mp(context: ContextTypes.DEFAULT_TYPE):
    """Verifica pagamentos pendentes no Mercado Pago."""
    if not CONFIG.get("MP_ACCESS_TOKEN"):
        return
    db = _ler(DB_FILE)
    for uid_str, dados in db.items():
        if dados.get("acesso"):
            continue
        pid = dados.get("mp_payment_id")
        plano_id = dados.get("plano_pendente")
        if not pid or not plano_id:
            continue
        pago = await verificar_pagamento_mp(str(pid))
        if pago:
            uid = int(uid_str)
            nome = dados.get("nome", "")
            username = dados.get("username", "")
            liberar_acesso(uid, username, nome, plano_id)
            link = await gerar_link_canal(context.bot, uid)
            try:
                await context.bot.send_message(
                    uid, txt_acesso_liberado(plano_id, link),
                    parse_mode="Markdown"
                )
                await context.bot.send_message(
                    CONFIG["ADMIN_ID"],
                    f"💰 *Pagamento automático confirmado!*\n"
                    f"👤 @{username} | ID `{uid}`\n"
                    f"📦 Plano: {PLANOS[plano_id]['nome']}",
                    parse_mode="Markdown"
                )
            except TelegramError as e:
                log.error(e)

# ═══════════════════════════════════════════════════════
#  HANDLERS — COMANDOS
# ═══════════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    log.info(f"/start — {user.id} @{user.username}")

    if esta_bloqueado(user.id):
        await update.message.reply_text("❌ Seu acesso foi suspenso. Contate o suporte.")
        return

    registrar_visita(user.id, user.username or "", user.full_name)

    if tem_acesso(user.id):
        dados = cliente_get(user.id)
        plano_id = dados.get("plano", "basic")
        link = await gerar_link_canal(ctx.bot, user.id)
        await update.message.reply_text(
            txt_acesso_liberado(plano_id, link),
            parse_mode="Markdown", reply_markup=kb_voltar("inicio")
        )
        return

    await update.message.reply_text(
        txt_boas_vindas(), parse_mode="Markdown", reply_markup=kb_principal()
    )

async def cmd_liberar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin: /liberar <user_id> <plano>"""
    if update.effective_user.id != CONFIG["ADMIN_ID"]:
        return
    args = ctx.args
    if len(args) < 2:
        await update.message.reply_text("Uso: /liberar <user_id> <basic|premium|vip>")
        return
    uid, plano_id = int(args[0]), args[1]
    if plano_id not in PLANOS:
        await update.message.reply_text(f"Plano inválido. Use: {', '.join(PLANOS.keys())}")
        return
    liberar_acesso(uid, "manual", "manual", plano_id)
    link = await gerar_link_canal(ctx.bot, uid)
    try:
        await ctx.bot.send_message(uid, txt_acesso_liberado(plano_id, link), parse_mode="Markdown")
        await update.message.reply_text(f"✅ Acesso {plano_id} liberado para `{uid}`!", parse_mode="Markdown")
    except TelegramError as e:
        await update.message.reply_text(f"⚠️ Salvo, erro ao notificar: {e}")

async def cmd_bloquear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin: /bloquear <user_id> <motivo>"""
    if update.effective_user.id != CONFIG["ADMIN_ID"]:
        return
    args = ctx.args
    if not args:
        await update.message.reply_text("Uso: /bloquear <user_id> [motivo]")
        return
    uid = int(args[0])
    motivo = " ".join(args[1:]) if len(args) > 1 else "sem motivo"
    bloquear_usuario(uid, motivo)
    await update.message.reply_text(f"🚫 Usuário `{uid}` bloqueado.", parse_mode="Markdown")

async def cmd_desbloquear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin: /desbloquear <user_id>"""
    if update.effective_user.id != CONFIG["ADMIN_ID"]:
        return
    args = ctx.args
    if not args:
        return
    desbloquear_usuario(int(args[0]))
    await update.message.reply_text(f"✅ Usuário `{args[0]}` desbloqueado.", parse_mode="Markdown")

async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin: /broadcast <mensagem>"""
    if update.effective_user.id != CONFIG["ADMIN_ID"]:
        return
    if not ctx.args:
        await update.message.reply_text("Uso: /broadcast <mensagem>")
        return
    mensagem = " ".join(ctx.args)
    db = _ler(DB_FILE)
    enviados, erros = 0, 0
    for uid_str in db:
        try:
            await ctx.bot.send_message(int(uid_str), f"📢 {mensagem}", parse_mode="Markdown")
            enviados += 1
            await asyncio.sleep(0.05)
        except:
            erros += 1
    await update.message.reply_text(
        f"📢 Broadcast enviado!\n✅ {enviados} entregues | ❌ {erros} erros"
    )

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin: /stats"""
    if update.effective_user.id != CONFIG["ADMIN_ID"]:
        return
    db    = _ler(DB_FILE)
    total = len(db)
    ativos = {k: v for k, v in db.items() if v.get("acesso")}
    hoje  = datetime.now().strftime("%d/%m/%Y")
    vendas_hoje = sum(1 for v in ativos.values() if v.get("data_compra", "").startswith(hoje))
    por_plano = {}
    for v in ativos.values():
        p = v.get("plano", "?")
        por_plano[p] = por_plano.get(p, 0) + 1
    linhas_planos = "\n".join([f"   {PLANOS.get(k, {}).get('emoji','?')} {k}: {n}" for k, n in por_plano.items()])
    await update.message.reply_text(
        f"📊 *Estatísticas*\n\n"
        f"👥 Total usuários: `{total}`\n"
        f"✅ Com acesso: `{len(ativos)}`\n"
        f"📅 Vendas hoje: `{vendas_hoje}`\n\n"
        f"📦 *Por plano:*\n{linhas_planos or '   nenhum'}",
        parse_mode="Markdown"
    )

async def cmd_clientes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin: /clientes"""
    if update.effective_user.id != CONFIG["ADMIN_ID"]:
        return
    db = _ler(DB_FILE)
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

async def cmd_cupom_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin: /cupom_add <CODIGO> <desconto> <percent|reais> <usos_max>"""
    if update.effective_user.id != CONFIG["ADMIN_ID"]:
        return
    args = ctx.args
    if len(args) < 4:
        await update.message.reply_text("Uso: /cupom_add <CODIGO> <desconto> <percent|reais> <usos_max>")
        return
    cupons = _ler(CUPONS_FILE) or CUPONS
    cupons[args[0].upper()] = {
        "desconto": float(args[1]), "tipo": args[2],
        "usos_max": int(args[3]), "usos": 0
    }
    _salvar(CUPONS_FILE, cupons)
    await update.message.reply_text(f"✅ Cupom `{args[0].upper()}` criado!", parse_mode="Markdown")

async def cmd_ajuda_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != CONFIG["ADMIN_ID"]:
        return
    await update.message.reply_text(
        "🛠️ *Comandos Admin*\n\n"
        "/stats — estatísticas gerais\n"
        "/clientes — lista clientes ativos\n"
        "/liberar `<id>` `<plano>` — libera acesso manualmente\n"
        "/bloquear `<id>` `[motivo]` — bloqueia usuário\n"
        "/desbloquear `<id>` — desbloqueia usuário\n"
        "/broadcast `<msg>` — manda msg para todos\n"
        "/cupom_add `<COD>` `<desc>` `<tipo>` `<usos>` — cria cupom\n"
        "/admin — este menu",
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
            link = await gerar_link_canal(ctx.bot, user.id)
            await responder(update, txt_acesso_liberado(dados.get("plano","basic"), link), kb_voltar())
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
        ctx.user_data["preco_final"] = p["preco"]
        ctx.user_data["preco_final_int"] = p["preco_int"]

        # Tenta gerar PIX automático (Mercado Pago)
        mp = gerar_pix_mp(plano_id, user.id, p["preco_int"])
        qr = None
        if mp:
            dados = cliente_get(user.id)
            dados["mp_payment_id"] = mp["id"]
            dados["plano_pendente"] = plano_id
            cliente_salvar(user.id, dados)
            qr = mp.get("qr_code")

        await responder(
            update,
            txt_pagamento_pix(plano_id, p["preco"], qr),
            kb_pagamento(plano_id)
        )

    elif data == "cupom":
        ctx.user_data["aguardando_cupom"] = True
        await responder(
            update,
            "🎁 *Cupom de Desconto*\n\n"
            "Digite o código do seu cupom abaixo:\n\n"
            "_Ex: PROMO50_",
            kb_voltar("planos")
        )

    elif data == "faq":
        await responder(update,
            "❓ *Perguntas Frequentes*\n\n"
            "🔹 *O acesso é vitalício?*\nSim! Pague uma vez, acesse para sempre.\n\n"
            "🔹 *Quando libera após o pagamento?*\nEm até 2 minutos automaticamente.\n\n"
            "🔹 *Aceita outros pagamentos?*\nApenas PIX no momento.\n\n"
            "🔹 *É seguro e discreto?*\n100%. Sua privacidade é prioridade.\n\n"
            "🔹 *Posso compartilhar o acesso?*\nNão — acesso pessoal e intransferível.\n\n"
            "🔹 *Tem conteúdo novo?*\nSim, atualizado constantemente.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 Comprar Agora", callback_data="planos")],
                [InlineKeyboardButton("🔙 Voltar",        callback_data="inicio")],
            ])
        )

    elif data == "suporte":
        await responder(update,
            f"💬 *Suporte*\n\n"
            f"Fale diretamente: {CONFIG['SUPORTE_USER']}\n\n"
            f"⏱️ Resposta em até 1 hora.",
            kb_voltar()
        )

    elif data == "meu_acesso":
        if tem_acesso(user.id):
            dados = cliente_get(user.id)
            link = await gerar_link_canal(ctx.bot, user.id)
            await responder(update, txt_acesso_liberado(dados.get("plano","basic"), link), kb_voltar())
        else:
            await responder(update,
                "🔒 *Acesso não encontrado*\n\n"
                "Se você já pagou, aguarde ou contate o suporte.",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 Comprar",   callback_data="planos")],
                    [InlineKeyboardButton("💬 Suporte",   callback_data="suporte")],
                ])
            )

    elif data.startswith("paguei_"):
        plano_id = data.replace("paguei_", "")
        ctx.user_data["aguardando_comprovante"] = True
        ctx.user_data["plano_selecionado"] = plano_id
        await responder(update,
            "📸 *Envie o comprovante de pagamento*\n\n"
            "Envie uma *foto ou print* do comprovante PIX.\n\n"
            "⏱️ _Acesso liberado em até 2 minutos._",
            kb_voltar("planos")
        )

    elif data.startswith("adm_liberar_"):
        await cb_admin_liberar(update, ctx)

# ═══════════════════════════════════════════════════════
#  ADMIN — liberar pelo botão no comprovante
# ═══════════════════════════════════════════════════════
async def cb_admin_liberar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != CONFIG["ADMIN_ID"]:
        await q.answer("❌ Sem permissão.", show_alert=True)
        return
    # adm_liberar_{uid}_{username}_{nome}_{plano}
    partes   = q.data.split("_", 5)
    uid      = int(partes[2])
    username = partes[3]
    nome     = partes[4]
    plano_id = partes[5] if len(partes) > 5 else "basic"
    liberar_acesso(uid, username, nome, plano_id)
    link = await gerar_link_canal(ctx.bot, uid)
    try:
        await ctx.bot.send_message(uid, txt_acesso_liberado(plano_id, link), parse_mode="Markdown")
    except TelegramError as e:
        log.error(e)
    try:
        legenda = (q.message.caption or "") + "\n\n✅ *Acesso liberado!*"
        await q.edit_message_caption(caption=legenda, parse_mode="Markdown")
    except:
        await q.answer("✅ Acesso liberado!", show_alert=True)

# ═══════════════════════════════════════════════════════
#  HANDLER — COMPROVANTE (foto/doc)
# ═══════════════════════════════════════════════════════
async def receber_midia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if esta_bloqueado(user.id):
        return

    if not ctx.user_data.get("aguardando_comprovante"):
        await update.message.reply_text(
            "📎 Recebemos sua mídia!\n\n"
            "Se é um comprovante, clique em *Comprar* → *Já Paguei* primeiro.",
            parse_mode="Markdown", reply_markup=kb_principal()
        )
        return

    # Anti-fraude: verifica hash
    file_id = None
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.document:
        file_id = update.message.document.file_id

    if file_id and comprovante_ja_usado(file_id):
        bloquear_usuario(user.id, "comprovante duplicado")
        await update.message.reply_text(
            "🚫 *Comprovante já utilizado!*\n\n"
            "Este comprovante já foi enviado anteriormente.\n"
            "Conta suspensa por tentativa de fraude.",
            parse_mode="Markdown"
        )
        await ctx.bot.send_message(
            CONFIG["ADMIN_ID"],
            f"🚨 *FRAUDE DETECTADA*\n👤 @{user.username} ID `{user.id}`\n"
            f"Comprovante duplicado enviado.",
            parse_mode="Markdown"
        )
        return

    plano_id = ctx.user_data.get("plano_selecionado", "basic")
    ctx.user_data["aguardando_comprovante"] = False

    await update.message.reply_text(
        "✅ *Comprovante recebido!*\n\n"
        "Verificando seu pagamento... Você receberá o acesso em até 2 minutos. 🙏",
        parse_mode="Markdown"
    )

    uname = (user.username or "sem_username").replace("_","-")
    nome  = user.full_name.replace("_","-")[:20]
    cb    = f"adm_liberar_{user.id}_{uname}_{nome}_{plano_id}"

    legenda = (
        f"🧾 *Novo Comprovante*\n"
        f"👤 @{user.username or 'sem_username'}\n"
        f"🆔 `{user.id}`\n"
        f"📦 Plano: {PLANOS.get(plano_id,{}).get('nome','?')}\n"
        f"💰 Valor: R$ {PLANOS.get(plano_id,{}).get('preco','?')}"
    )
    kb_admin = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"✅ Liberar {PLANOS.get(plano_id,{}).get('nome','')}", callback_data=cb)
    ]])

    try:
        if update.message.photo:
            await ctx.bot.send_photo(CONFIG["ADMIN_ID"], update.message.photo[-1].file_id,
                caption=legenda, parse_mode="Markdown", reply_markup=kb_admin)
        elif update.message.document:
            await ctx.bot.send_document(CONFIG["ADMIN_ID"], update.message.document.file_id,
                caption=legenda, parse_mode="Markdown", reply_markup=kb_admin)
        else:
            await ctx.bot.send_message(CONFIG["ADMIN_ID"], legenda + "\n_(sem mídia)_",
                parse_mode="Markdown", reply_markup=kb_admin)
    except TelegramError as e:
        log.error(f"Erro ao enviar ao admin: {e}")

# ═══════════════════════════════════════════════════════
#  HANDLER — TEXTO LIVRE
# ═══════════════════════════════════════════════════════
PALAVRAS = {
    "preco":    ["preço","preco","valor","quanto","custa","custo"],
    "pix":      ["pix","pagar","pagamento","como pagar","chave","transferencia"],
    "acesso":   ["acesso","link","conteudo","conteúdo","site","onde","como acessar"],
    "faq":      ["duvida","dúvida","faq","pergunta","como funciona"],
    "suporte":  ["suporte","ajuda","help","problema","erro"],
    "saudacao": ["oi","olá","ola","bom dia","boa tarde","boa noite","hey","hello"],
    "cupom":    ["cupom","desconto","promo","promocao","código"],
}

async def texto_livre(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user  = update.effective_user
    texto = update.message.text.strip()

    if esta_bloqueado(user.id):
        return

    registrar_visita(user.id, user.username or "", user.full_name)

    if tem_acesso(user.id):
        dados = cliente_get(user.id)
        link = await gerar_link_canal(ctx.bot, user.id)
        await update.message.reply_text(
            txt_acesso_liberado(dados.get("plano","basic"), link), parse_mode="Markdown"
        )
        return

    # Aguardando cupom
    if ctx.user_data.get("aguardando_cupom"):
        ctx.user_data["aguardando_cupom"] = False
        plano_id = ctx.user_data.get("plano_selecionado", "basic")
        cupom = validar_cupom(texto, plano_id)
        if not cupom:
            await update.message.reply_text(
                "❌ *Cupom inválido ou expirado.*\n\nTente outro ou prossiga sem desconto.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 Comprar sem cupom", callback_data="planos")],
                    [InlineKeyboardButton("🔙 Menu",              callback_data="inicio")],
                ])
            )
            return

        plano = PLANOS[plano_id]
        novo_preco_int = calcular_preco_com_cupom(plano["preco_int"], cupom)
        novo_preco_str = f"{novo_preco_int/100:.2f}".replace(".", ",")
        ctx.user_data["preco_final"]     = novo_preco_str
        ctx.user_data["preco_final_int"] = novo_preco_int
        ctx.user_data["cupom_usado"]     = texto.upper()
        usar_cupom(texto)

        tipo_desc = f"{cupom['desconto']}%" if cupom["tipo"]=="percent" else f"R$ {cupom['desconto']}"
        await update.message.reply_text(
            f"🎉 *Cupom `{texto.upper()}` aplicado!*\n\n"
            f"💸 Desconto de {tipo_desc}\n"
            f"💰 Novo valor: *R$ {novo_preco_str}*\n\n"
            f"Prossiga para o pagamento 👇",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"💳 Pagar R$ {novo_preco_str}", callback_data=f"plano_{plano_id}")]
            ])
        )
        return

    # Palavras-chave
    tl = texto.lower()
    for tipo, palavras in PALAVRAS.items():
        if any(p in tl for p in palavras):
            if tipo == "preco":
                await update.message.reply_text(
                    f"💰 Temos 3 planos:\n\n"
                    + "\n".join([f"{p['emoji']} *{p['nome']}* — R$ {p['preco']}" for p in PLANOS.values()]),
                    parse_mode="Markdown", reply_markup=kb_planos()
                )
            elif tipo == "pix":
                await update.message.reply_text(
                    "Escolha um plano para ver a chave PIX e as instruções de pagamento 👇",
                    reply_markup=kb_planos()
                )
            elif tipo == "cupom":
                ctx.user_data["aguardando_cupom"] = True
                await update.message.reply_text(
                    "🎁 Digite o código do seu cupom:", reply_markup=kb_voltar("planos")
                )
            elif tipo in ("acesso","faq","suporte","saudacao"):
                await update.message.reply_text(
                    txt_boas_vindas(), parse_mode="Markdown", reply_markup=kb_principal()
                )
            return

    await update.message.reply_text(
        "😊 Use o menu abaixo ou fale com o suporte!",
        reply_markup=kb_principal()
    )

# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════
def main():
    if CONFIG["TOKEN"] == "SEU_TOKEN_AQUI":
        print("\n❌ ERRO: Configure o TOKEN do bot no bloco CONFIG antes de rodar!\n")
        return
    if CONFIG["ADMIN_ID"] == 123456789:
        print("\n⚠️  AVISO: Lembre-se de configurar seu ADMIN_ID no bloco CONFIG!\n")

    app = Application.builder().token(CONFIG["TOKEN"]).build()

    # Comandos
    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("liberar",      cmd_liberar))
    app.add_handler(CommandHandler("bloquear",     cmd_bloquear))
    app.add_handler(CommandHandler("desbloquear",  cmd_desbloquear))
    app.add_handler(CommandHandler("broadcast",    cmd_broadcast))
    app.add_handler(CommandHandler("stats",        cmd_stats))
    app.add_handler(CommandHandler("clientes",     cmd_clientes))
    app.add_handler(CommandHandler("cupom_add",    cmd_cupom_add))
    app.add_handler(CommandHandler("admin",        cmd_ajuda_admin))

    # Callbacks
    app.add_handler(CallbackQueryHandler(cb_admin_liberar, pattern=r"^adm_liberar_"))
    app.add_handler(CallbackQueryHandler(cb_handler))

    # Mídia
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, receber_midia))

    # Texto
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, texto_livre))

    # Jobs automáticos
    jq: JobQueue = app.job_queue
    jq.run_repeating(job_follow_up,                 interval=900,  first=60)   # follow-up a cada 15min
    jq.run_repeating(job_verificar_pagamentos_mp,   interval=30,   first=10)   # MP a cada 30s

    log.info("🚀 Bot PRO iniciado! Pressione Ctrl+C para parar.")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
