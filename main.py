import os
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import utils

# Cấu hình logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Affiliate API Backend")

# ─── CẤU HÌNH CORS (Quan trọng để Web hosting gọi được API) ─────────
# Thay "*" bằng domain web hosting của bạn (ví dụ: "https://mywebsite.com") để bảo mật hơn
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── ĐỊNH DẠNG DỮ LIỆU NHẬN TỪ WEB ──────────────────────────────────
class ConvertRequest(BaseModel):
    url: str
    platform: str  # "shopee" hoặc "lazada"
    method: str    # "an_redir", "api", hoặc "cookie"

# ─── ENDPOINT CHO WEB HOSTING ───────────────────────────────────────
@app.post("/api/convert")
async def convert_link(request: ConvertRequest):
    logger.info(f"Web Request: url={request.url}, platform={request.platform}, method={request.method}")
    
    try:
        if request.platform == "shopee":
            if request.method == "an_redir":
                clean_url = utils.clean_shopee_url(request.url)
                affiliate_url = utils.generate_shopee_an_redir(clean_url)
            else:
                # TODO: Xử lý Shopee bằng Cookie (nếu cần)
                affiliate_url = request.url 
                
        elif request.platform == "lazada":
            if request.method == "api":
                affiliate_url = utils.convert_lazada_api(request.url)
            else:
                # TODO: Xử lý Lazada bằng Cookie (nếu cần)
                affiliate_url = request.url
        else:
            raise HTTPException(status_code=400, detail="Platform không hợp lệ")

        # Bước cuối: Rút gọn link qua s.salevn.top
        final_short_url = utils.shorten_link(affiliate_url)

        return {
            "success": True,
            "original": request.url,
            "converted": affiliate_url,
            "shortened": final_short_url
        }

    except Exception as e:
        logger.error(f"Conversion error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── ENDPOINT CHO TELEGRAM BOT (Webhook) ────────────────────────────
# (Bạn có thể tích hợp code bot từ "Code Python 2" vào đây, 
# và khi cần đổi link, bot sẽ gọi hàm utils.clean_shopee_url hoặc utils.convert_lazada_api)
@app.post("/webhook")
async def telegram_webhook():
    # Logic xử lý webhook của Telegram bot sẽ nằm ở đây
    return {"status": "Telegram webhook received"}


@app.get("/")
def health_check():
    return {"status": "API is running", "message": "Ready for Web and Telegram"}
