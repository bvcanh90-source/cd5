import os
import re
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager

import utils
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── ENVIRONMENT VARIABLES ────────────────────────────────────────────
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

# ─── FASTAPI SETUP ────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Khởi chạy Telegram Bot khi server start
    if BOT_TOKEN:
        app.state.bot_app = Application.builder().token(BOT_TOKEN).updater(None).build()
        setup_telegram_handlers(app.state.bot_app)
        await app.state.bot_app.initialize()
        await app.state.bot_app.start()
        
        # Tự động set Webhook dựa trên URL của Render
        render_url = os.environ.get("RENDER_EXTERNAL_URL", "")
        if render_url:
            webhook_url = f"{render_url.rstrip('/')}/webhook"
            await app.state.bot_app.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
            logger.info(f"Telegram Webhook set to: {webhook_url}")
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not found. Bot will not start.")
        app.state.bot_app = None
        
    yield
    
    # Dọn dẹp khi server shutdown
    if app.state.bot_app:
        await app.state.bot_app.stop()
        await app.state.bot_app.shutdown()

app = FastAPI(title="Affiliate API & Bot", lifespan=lifespan)

# Cho phép Web hosting của bạn gọi API (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Nên thay "*" bằng domain web của bạn, vd: "https://yourdomain.com"
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── WEB API ENDPOINT ─────────────────────────────────────────────────
class ConvertRequest(BaseModel):
    url: str
    platform: str  # "shopee" hoặc "lazada"
    method: str    # "an_redir" hoặc "api"

@app.post("/api/convert")
async def convert_link(request: ConvertRequest):
    try:
        if request.platform == "shopee":
            clean_url = utils.clean_shopee_url(request.url)
            affiliate_url = utils.generate_shopee_an_redir(clean_url)
        elif request.platform == "lazada":
            affiliate_url = utils.convert_lazada_api(request.url)
        else:
            raise HTTPException(status_code=400, detail="Platform không hợp lệ")

        final_short_url = utils.shorten_link(affiliate_url)

        return {
            "success": True,
            "original": request.url,
            "converted": affiliate_url,
            "shortened": final_short_url
        }
    except Exception as e:
        logger.error(f"API Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── TELEGRAM BOT LOGIC ───────────────────────────────────────────────
def is_admin(user_id: int) -> bool:
    if not ADMIN_IDS:
        return True # Nếu không set ADMIN_IDS, cho phép tất cả
    return user_id in ADMIN_IDS

# Regex tìm link Shopee/Lazada trong đoạn text
LINK_REGEX = re.compile(
    r'https?://(?:shopee\.vn|s\.shopee\.vn|shp\.ee|vn\.shp\.ee|lazada\.vn|s\.lazada\.vn|c\.lazada\.vn)[^\s<>"{}|\\^`\[\]]+',
    re.IGNORECASE
)

def setup_telegram_handlers(app: Application):
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id): return
        await update.message.reply_text(
            "👋 Chào bạn! Hãy gửi bất kỳ link Shopee hoặc Lazada nào, \n"
            "Bot sẽ tự động làm sạch, gắn mã Affiliate và rút gọn link cho bạn! 🔥"
        )

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id): return
        
        text = update.message.text or ""
        links = LINK_REGEX.findall(text)
        
        if not links:
            await update.message.reply_text("❌ Không tìm thấy link Shopee hoặc Lazada hợp lệ.")
            return

        await update.message.reply_text("⏳ Đang xử lý link...")
        
        results = []
        for link in links:
            try:
                # Tự động nhận diện platform
                if "shopee" in link.lower():
                    clean_url = utils.clean_shopee_url(link)
                    aff_url = utils.generate_shopee_an_redir(clean_url)
                else:
                    aff_url = utils.convert_lazada_api(link)
                
                # Rút gọn link
                short_url = utils.shorten_link(aff_url)
                results.append(f"✅ Link gốc: {link}\n🔗 Link mới: {short_url}")
            except Exception as e:
                results.append(f"❌ Lỗi với link {link}: {str(e)}")

        # Gửi kết quả (nếu quá dài thì cắt bớt, nhưng thường 1-2 link là vừa)
        final_msg = "\n\n".join(results)
        await update.message.reply_text(final_msg)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


# ─── TELEGRAM WEBHOOK ENDPOINT ────────────────────────────────────────
@app.post("/webhook")
async def telegram_webhook(request: dict):
    if not app.state.bot_app:
        return {"status": "Bot not initialized"}
    try:
        update = Update.de_json(request, app.state.bot_app.bot)
        await app.state.bot_app.process_update(update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"status": "error", "detail": str(e)}

@app.get("/")
def health_check():
    return {"status": "ok", "bot_active": bool(BOT_TOKEN)}
