import re
import urllib.parse
import hashlib
import requests
import logging

logger = logging.getLogger(__name__)

# ─── SHOPEE URL CLEANER ───────────────────────────────────────────────
def resolve_short_link(url: str) -> str:
    """Follow redirects để lấy link đích cuối cùng"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.head(url, headers=headers, allow_redirects=True, timeout=10)
        return response.url
    except Exception as e:
        logger.error(f"Error resolving link {url}: {e}")
        return url

def clean_shopee_url(url: str) -> str:
    """Làm sạch link Shopee về dạng chuẩn: /product/{shop_id}/{item_id}? hoặc /m/{landing}?"""
    url = resolve_short_link(url)
    parsed = urllib.parse.urlparse(url)
    
    # Chỉ xử lý nếu là shopee.vn
    if "shopee.vn" not in parsed.netloc:
        return url

    path = parsed.path
    
    # Trường hợp 1: Landing page (ví dụ: /m/VoucherXtra)
    if path.startswith("/m/"):
        return f"https://shopee.vn{path}?"

    # Trường hợp 2: Link sản phẩm dạng mới: /product/{shop_id}/{item_id}
    match_new = re.search(r"/product/(\d+)/(\d+)", path)
    if match_new:
        shop_id, item_id = match_new.groups()
        return f"https://shopee.vn/product/{shop_id}/{item_id}?"

    # Trường hợp 3: Link sản phẩm dạng cũ: /ten-san-pham-i.{shop_id}.{item_id}
    match_old = re.search(r"-i\.(\d+)\.(\d+)", path)
    if match_old:
        shop_id, item_id = match_old.groups()
        return f"https://shopee.vn/product/{shop_id}/{item_id}?"

    # Fallback: Trả về đường dẫn gốc nhưng xóa hết query params
    return f"https://{parsed.netloc}{path}?"


def generate_shopee_an_redir(clean_url: str) -> str:
    """Tạo link affiliate Shopee dạng an_redir"""
    affiliate_id = "17353410295"
    sub_id = "--17353410295--"
    encoded_url = urllib.parse.quote(clean_url, safe="")
    return f"https://s.shopee.vn/an_redir?origin_link={encoded_url}&affiliate_id={affiliate_id}&sub_id={sub_id}"


# ─── LAZADA API HELPER ────────────────────────────────────────────────
def generate_lazada_sign(params: dict, app_secret: str) -> str:
    """Tạo chữ ký SHA256 cho Lazada Open API"""
    sorted_keys = sorted(params.keys())
    sign_str = app_secret
    for key in sorted_keys:
        sign_str += f"{key}{params[key]}"
    sign_str += app_secret
    return hashlib.sha256(sign_str.encode('utf-8')).hexdigest()


def convert_lazada_api(target_url: str) -> str:
    """Gọi API Lazada Open API để tạo link affiliate (Dựa trên Code 2)"""
    app_key = "105827"
    app_secret = "r8ZMKhPxu1JZUCwTUBVMJiJnZKjhWeQF"
    user_token = "f879c4163b0f4c5a90c1567fcffac91e"
    
    import time
    params = {
        "app_key": app_key,
        "timestamp": str(int(time.time() * 1000)),
        "sign_method": "sha256",
        "userToken": user_token,
        "inputType": "url",
        "inputValue": target_url,
    }
    params["sign"] = generate_lazada_sign(params, app_secret)
    
    api_url = f"https://api.lazada.vn/rest/marketing/getlink?{urllib.parse.urlencode(params)}"
    
    try:
        response = requests.get(api_url, timeout=15)
        data = response.json()
        if data.get("code") == "0":
            url_list = data.get("data", {}).get("urlBatchGetLinkInfoList", [])
            if url_list:
                return url_list[0].get("regularPromotionLink", target_url)
        logger.warning(f"Lazada API response: {data}")
        return target_url
    except Exception as e:
        logger.error(f"Lazada API Error: {e}")
        return target_url


# ─── SHORTENER PLACEHOLDER ────────────────────────────────────────────
def shorten_link(long_url: str) -> str:
    """
    TODO: Tích hợp API rút gọn link của s.salevn.top tại đây.
    Hiện tại trả về chính long_url để test luồng trước.
    """
    # Ví dụ: 
    # res = requests.post("https://s.salevn.top/api/shorten", json={"url": long_url})
    # return res.json()["short_url"]
    return long_url 
