"""
Affiliate Toolkit - Link Converter & Shortener
All-in-one file cho Render free tier.

Sections:
1. Imports & Constants
2. Configuration
3. URL Cleaner - Shopee
4. Shopee Converter (an_redir mode)
5. URL Cleaner - Lazada
6. Link Resolver
7. FastAPI App & Endpoints
8. Main Entry Point
"""

# ═══════════════════════════════════════════════════════════
# 1. IMPORTS & CONSTANTS
# ═══════════════════════════════════════════════════════════

import os
import re
import sys
from typing import Optional, Tuple, Set, List
from urllib.parse import (
    urlparse, parse_qs, urlencode, urlunparse, unquote, quote
)

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()


# ═══════════════════════════════════════════════════════════
# 2. CONFIGURATION
# ═══════════════════════════════════════════════════════════

class Config:
    """Quản lý tất cả environment variables."""
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    ADMIN_IDS: str = os.getenv("ADMIN_IDS", "")
    
    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "")
    
    # Shopee
    SHOPEE_AFFILIATE_ID: str = os.getenv("SHOPEE_AFFILIATE_ID", "17353410295")
    SHOPEE_SUB_ID_TEMPLATE: str = os.getenv("SHOPEE_SUB_ID_TEMPLATE", "--{aff_id}--")
    
    # Lazada LiteApp
    LAZADA_LITEAPP_KEY: str = os.getenv("LAZADA_LITEAPP_KEY", "105827")
    LAZADA_LITEAPP_SECRET: str = os.getenv("LAZADA_LITEAPP_SECRET", "")
    LAZADA_USER_TOKEN: str = os.getenv("LAZADA_USER_TOKEN", "")
    LAZADA_AFF_PREFIX: str = os.getenv("LAZADA_AFF_PREFIX", "https://c.lazada.vn/t/c.YParqP")
    
    # Shortener
    SHORTENER_DB_PATH: str = os.getenv("SHORTENER_DB_PATH", "data/short_links.json")
    SHORTENER_BASE_URL: str = os.getenv("SHORTENER_BASE_URL", "https://s.salevn.top")
    
    # Frontend
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "https://s.salevn.top")
    
    @classmethod
    def get_admin_id_list(cls) -> List[int]:
        """Parse ADMIN_IDS từ string thành list int."""
        if not cls.ADMIN_IDS:
            return []
        return [
            int(x.strip()) 
            for x in cls.ADMIN_IDS.split(",") 
            if x.strip().isdigit()
        ]


# Singleton config instance
config = Config()

# Shortener API
    SHORTENER_API_URL: str = os.getenv("SHORTENER_API_URL", "https://s.salevn.top/api.php")
    SHORTENER_API_SECRET: str = os.getenv("SHORTENER_API_SECRET", "")

# ═══════════════════════════════════════════════════════════
# 3. URL CLEANER - SHOPEE
# ═══════════════════════════════════════════════════════════

# Whitelist params cần giữ lại (cho search/other URLs)
SHOPEE_KEEP_PARAMS: Set[str] = {
    'keyword', 'sortBy', 'order', 'page', 'limit',
    'priceMin', 'priceMax', 'rating',
    'category', 'categoryId',
    'shop', 'shopId',
}

# Regex patterns để nhận diện các dạng URL Shopee
SHOPEE_PATTERNS = {
    'product_legacy': re.compile(r'^/product/(\d+)/(\d+)', re.IGNORECASE),
    'product_slug': re.compile(r'^/([^/]+)/(\d+)/(\d+)$', re.IGNORECASE),
    'product_named': re.compile(r'/[^/]+-i\.(\d+)\.(\d+)', re.IGNORECASE),
    'landing': re.compile(r'^/m/([a-zA-Z0-9\-_]+)', re.IGNORECASE),
    'shop': re.compile(r'^/shop/(\d+)/?([^/]*)', re.IGNORECASE),
    'search': re.compile(r'^/search/?$', re.IGNORECASE),
    'homepage': re.compile(r'^/?$', re.IGNORECASE),
}


def detect_shopee_url_type(url: str) -> str:
    """
    Phân loại URL Shopee với nhiều dạng khác nhau.
    
    Returns:
        'product' | 'landing' | 'shop' | 'search' | 'homepage' | 'other'
    """
    try:
        parsed = urlparse(url)
        path = parsed.path
        
        # Loại bỏ trailing slash (trừ homepage)
        if path != '/' and path.endswith('/'):
            path = path.rstrip('/')
        
        # Homepage
        if SHOPEE_PATTERNS['homepage'].match(path):
            return 'homepage'
        
        # Search
        if SHOPEE_PATTERNS['search'].match(path):
            return 'search'
        
        # Product legacy: /product/123/456
        if SHOPEE_PATTERNS['product_legacy'].match(path):
            return 'product'
        
        # Product với tên: /Tên-Sản-Phẩm-i.123.456
        if SHOPEE_PATTERNS['product_named'].search(path):
            return 'product'
        
        # Product với slug: /shop-slug/123/456
        match = SHOPEE_PATTERNS['product_slug'].match(path)
        if match:
            slug, shop_id, item_id = match.groups()
            if shop_id.isdigit() and item_id.isdigit():
                return 'product'
        
        # Landing page: /m/VoucherXtra
        if SHOPEE_PATTERNS['landing'].match(path):
            return 'landing'
        
        # Shop: /shop/123/shop-name
        if SHOPEE_PATTERNS['shop'].match(path):
            return 'shop'
        
        return 'other'
    except Exception:
        return 'other'


def normalize_shopee_product_url(url: str) -> str:
    """
    Chuẩn hóa product URL về dạng chuẩn.
    
    Input:  https://shopee.vn/opaanlp/507867749/19180372828
    Output: https://shopee.vn/product/507867749/19180372828
    """
    try:
        parsed = urlparse(url)
        path = parsed.path
        
        if path.endswith('/'):
            path = path.rstrip('/')
        
        # Match dạng /slug/shopid/itemid
        match = SHOPEE_PATTERNS['product_slug'].match(path)
        if match:
            slug, shop_id, item_id = match.groups()
            if shop_id.isdigit() and item_id.isdigit():
                new_path = f"/product/{shop_id}/{item_id}"
                return urlunparse((
                    parsed.scheme,
                    parsed.netloc,
                    new_path,
                    '', '', ''
                ))
        
        # Match dạng /Tên-Sản-Phẩm-i.123.456
        match = SHOPEE_PATTERNS['product_named'].search(path)
        if match:
            shop_id, item_id = match.groups()
            new_path = f"/product/{shop_id}/{item_id}"
            return urlunparse((
                parsed.scheme,
                parsed.netloc,
                new_path,
                '', '', ''
            ))
        
        return url
    except Exception:
        return url


def clean_shopee_url(url: str) -> str:
    """
    Làm sạch URL Shopee - strategy hybrid (whitelist + blacklist).
    Tự động normalize product URL về dạng /product/shopid/itemid
    """
    if not url:
        return url
    
    try:
        parsed = urlparse(url)
        
        # Chỉ xử lý URL Shopee
        if 'shopee' not in parsed.netloc.lower():
            return url
        
        # Detect loại URL
        url_type = detect_shopee_url_type(url)
        
        # Parse query string
        query_params = parse_qs(parsed.query, keep_blank_values=True)
        
        # Áp dụng strategy theo loại URL
        if url_type in ('product', 'landing', 'shop', 'homepage'):
            clean_params = {}
        else:
            clean_params = {
                k: v for k, v in query_params.items()
                if k.lower() in SHOPEE_KEEP_PARAMS
            }
        
        # Rebuild query string
        new_query = urlencode(clean_params, doseq=True) if clean_params else ""
        
        # Rebuild URL
        clean_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            ''
        ))
        
        # Normalize: remove trailing slash (trừ homepage)
        if clean_url.endswith('/') and parsed.path != '/':
            clean_url = clean_url.rstrip('/')
        
        # Tự động normalize product URL
        if url_type == 'product':
            clean_url = normalize_shopee_product_url(clean_url)
        
        return clean_url
        
    except Exception as e:
        print(f"[clean_shopee_url] Error: {e}", file=sys.stderr)
        return url


# ═══════════════════════════════════════════════════════════
# 4. SHOPEE CONVERTER - AN_REDIR MODE
# ═══════════════════════════════════════════════════════════

def convert_shopee_an_redir(cleaned_url: str, affiliate_id: str, sub_id: str = "") -> str:
    """
    Tạo Shopee affiliate link dạng an_redir (không cần cookie).
    
    Args:
        cleaned_url: URL Shopee đã được làm sạch
        affiliate_id: Shopee Affiliate ID
        sub_id: Sub ID (mặc định là --{affiliate_id}--)
    
    Returns:
        Link affiliate dạng: https://s.shopee.vn/an_redir?origin_link=...&affiliate_id=...&sub_id=...
    """
    if not cleaned_url or not affiliate_id:
        return cleaned_url
    
    # URL encode the cleaned URL
    encoded_url = quote(cleaned_url, safe='')
    
    # Format sub_id nếu không được cung cấp
    if not sub_id:
        sub_id = f"--{affiliate_id}--"
    
    # Build an_redir URL
    an_redir_url = (
        f"https://s.shopee.vn/an_redir"
        f"?origin_link={encoded_url}"
        f"&affiliate_id={affiliate_id}"
        f"&sub_id={sub_id}"
    )
    
    return an_redir_url

# ═══════════════════════════════════════════════════════════
# 4B. URL SHORTENER (gọi sang hosting PHP)
# ═══════════════════════════════════════════════════════════

async def shorten_url(long_url: str) -> Optional[str]:
    """
    Gửi link dài sang api.php trên s.salevn.top để rút gọn.
    
    Args:
        long_url: Link affiliate dài (vd: https://s.shopee.vn/an_redir?...)
    
    Returns:
        Link rút gọn (vd: https://s.salevn.top/aB3xY), hoặc None nếu lỗi
    """
    if not config.SHORTENER_API_SECRET:
        print("[shorten_url] API_SECRET chưa cấu hình!", file=sys.stderr)
        return None
    
    payload = {
        "secret": config.SHORTENER_API_SECRET,
        "long_url": long_url
    }
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                config.SHORTENER_API_URL,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success") and data.get("short_url"):
                    print(f"[shorten_url] OK: {long_url[:60]}... → {data['short_url']}", 
                          file=sys.stderr)
                    return data["short_url"]
            
            print(f"[shorten_url] Error: {response.status_code} - {response.text[:200]}", 
                  file=sys.stderr)
            return None
            
    except Exception as e:
        print(f"[shorten_url] Exception: {e}", file=sys.stderr)
        return None
        
# ═══════════════════════════════════════════════════════════
# 5. URL CLEANER - LAZADA
# ═══════════════════════════════════════════════════════════

LAZADA_REMOVE_PARAMS: Set[str] = {
    'exlaz', 'laz_share_info', 'laz_token', 'trafficfrom',
    'laz_trackid', 'mkttid', 'spm', 'from_affiliate', 't',
    'dsource', 'data_prefetch', 'hybrid', 'at_iframe',
    'disable_bounces', 'lzd_navbar_hidden', 'pha',
    'disable_pull_refresh', 'prefetch_replace',
    'wx_navbar_transparent', 'c', 'clickid', 'sub_aff_id',
    'sub_id1', 'sub_id2', 'sub_id3', 'sub_id4', 'sub_id5', 'sub_id6',
    'epid', 'laz_prefetch_id', 'etype', 'eurl', 'eredirect',
    'zarsrc', 'utm_source', 'utm_medium', 'utm_campaign',
    'scm', 'lpid', 'nav_right_item_hidden', 'sbucket', 'k',
    '__wml_data_prefetch', 'web_view_type', 'e',
    'clicktrackinfo', 'aff_trace_key', 'aff_platform',
    'aff_request_id', 'utparam', 'abbucket', 'sk', 'mp',
    'search', 'from', 'cc', 'src',
}


def clean_lazada_url(url: str) -> str:
    """
    Làm sạch URL Lazada, loại bỏ tracking parameters.
    """
    if not url:
        return url
    
    try:
        parsed = urlparse(url)
        
        # Chỉ xử lý URL Lazada
        if 'lazada' not in parsed.netloc.lower():
            return url
        
        # Parse query string
        query_params = parse_qs(parsed.query, keep_blank_values=True)
        
        # Filter out tracking params
        clean_params = {
            k: v for k, v in query_params.items()
            if k.lower() not in LAZADA_REMOVE_PARAMS
        }
        
        # Rebuild query string
        new_query = urlencode(clean_params, doseq=True) if clean_params else ""
        
        # Rebuild URL
        clean_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            ''
        ))
        
        return clean_url
        
    except Exception as e:
        print(f"[clean_lazada_url] Error: {e}", file=sys.stderr)
        return url


def is_shopee_url(url: str) -> bool:
    """Kiểm tra URL có phải Shopee không."""
    try:
        host = urlparse(url).netloc.lower()
        return 'shopee.' in host or 'shp.ee' in host
    except Exception:
        return False


def is_lazada_url(url: str) -> bool:
    """Kiểm tra URL có phải Lazada không."""
    try:
        host = urlparse(url).netloc.lower()
        return 'lazada.' in host
    except Exception:
        return False


def normalize_url(url: str) -> str:
    """Chuẩn hóa URL, đảm bảo có scheme đầy đủ."""
    if not url:
        return url
    
    url = url.strip()
    
    if url.startswith('//'):
        return 'https:' + url
    elif url.startswith('http://') or url.startswith('https://'):
        return url
    else:
        return 'https://' + url


# ═══════════════════════════════════════════════════════════
# 6. LINK RESOLVER
# ═══════════════════════════════════════════════════════════

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

THIRD_PARTY_DOMAINS = [
    "dealgiare.com",
    "thuydeal.site",
    "nghien.co",
    "buichung.net",
]

# Patterns để detect JS redirect trong HTML body
JS_REDIRECT_PATTERNS = [
    r'window\.location\.href\s*=\s*["\']([^"\']+)["\']',
    r'window\.location\.replace\s*\(\s*["\']([^"\']+)["\']',
    r'window\.location\s*=\s*["\']([^"\']+)["\']',
    r'location\.href\s*=\s*["\']([^"\']+)["\']',
    r'location\.replace\s*\(\s*["\']([^"\']+)["\']',
    r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]+content=["\']?\d+;\s*url=([^"\'>\s]+)',
    r'data-redirect=[\'"]([^\'"]+)[\'"]',
]


def find_js_redirect(html_body: str) -> Optional[str]:
    """Tìm URL redirect trong JavaScript hoặc meta refresh."""
    if not html_body:
        return None
    
    for pattern in JS_REDIRECT_PATTERNS:
        match = re.search(pattern, html_body, re.IGNORECASE)
        if match:
            url = match.group(1)
            url = url.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
            return url
    
    return None


def extract_url_param(url: str, param_name: str = 'url') -> Optional[str]:
    """Trích xuất giá trị của một query parameter."""
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        if param_name in params:
            return unquote(params[param_name][0])
    except Exception:
        pass
    return None


def is_shopee_host(url: str) -> bool:
    """Kiểm tra host có phải Shopee không."""
    try:
        host = urlparse(url).netloc.lower()
        return 'shopee.' in host or 'shp.ee' in host
    except Exception:
        return False


def is_lazada_host(url: str) -> bool:
    """Kiểm tra host có phải Lazada không."""
    try:
        host = urlparse(url).netloc.lower()
        return 'lazada.' in host
    except Exception:
        return False


def is_third_party_host(url: str) -> bool:
    """Kiểm tra host có phải third-party short domain không."""
    try:
        host = urlparse(url).netloc.lower()
        return any(domain in host for domain in THIRD_PARTY_DOMAINS)
    except Exception:
        return False


def detect_platform(url: str) -> Optional[str]:
    """Detect platform từ URL."""
    if is_shopee_host(url):
        return 'shopee'
    elif is_lazada_host(url):
        return 'lazada'
    return None


async def resolve_short_link(
    url: str,
    max_redirects: int = 10,
    timeout: float = 20.0
) -> Tuple[Optional[str], Optional[str]]:
    """
    Resolve short link về link gốc cuối cùng.
    
    Hỗ trợ HTTP redirects, JavaScript redirects, và Lazada c.lazada.vn/t/ URLs.
    """
    headers = {
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7',
    }
    
    current_url = url
    visited = set()
    
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        verify=False,
        headers=headers
    ) as client:
        
        for attempt in range(max_redirects):
            if current_url in visited:
                break
            
            visited.add(current_url)
            
            try:
                response = await client.get(current_url)
                
                # Xử lý HTTP redirect
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get('Location', '')
                    if location:
                        if location.startswith('/'):
                            parsed = urlparse(current_url)
                            current_url = f"{parsed.scheme}://{parsed.netloc}{location}"
                        else:
                            current_url = location
                        continue
                
                # Kiểm tra platform
                platform = detect_platform(current_url)
                if platform:
                    return current_url, platform
                
                # Xử lý Lazada c.lazada.vn/t/ URLs
                if re.match(r'https?://c\.lazada\.vn/t/', current_url, re.IGNORECASE):
                    dest = extract_url_param(current_url, 'url')
                    if dest:
                        if not dest.startswith('http'):
                            dest = unquote(dest)
                        if dest.startswith('http'):
                            platform = detect_platform(dest)
                            return dest, platform or 'lazada'
                
                # Tìm JS redirect trong HTML body
                js_url = find_js_redirect(response.text)
                if js_url and js_url.startswith('http'):
                    current_url = js_url
                    continue
                
                # Không còn redirect nào
                platform = detect_platform(current_url)
                return current_url, platform
                
            except httpx.TimeoutException:
                print(f"[resolve_short_link] Timeout: {current_url}", file=sys.stderr)
                return None, None
            except Exception as e:
                print(f"[resolve_short_link] Error: {e}", file=sys.stderr)
                return None, None
    
    # Nếu sau max_redirects vẫn chưa tìm được platform
    platform = detect_platform(current_url)
    return current_url, platform


async def resolve_if_needed(url: str) -> Tuple[str, Optional[str]]:
    """
    Resolve URL nếu nó là short link, ngược lại trả về URL gốc.
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    
    # Kiểm tra có phải short link cần resolve không
    is_short_link = (
        's.shopee.vn' in host or
        'shp.ee' in host or
        's.lazada.vn' in host or
        'c.lazada.vn' in host or
        is_third_party_host(url)
    )
    
    if not is_short_link:
        return url, detect_platform(url)
    
    # Cần resolve
    resolved_url, platform = await resolve_short_link(url)
    return resolved_url or url, platform


# ═══════════════════════════════════════════════════════════
# 7. FASTAPI APP & ENDPOINTS
# ═══════════════════════════════════════════════════════════

app = FastAPI(
    title="Affiliate Toolkit API",
    description="Link converter & shortener for Shopee/Lazada",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.FRONTEND_URL, "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Pydantic Models ───

class URLCleanRequest(BaseModel):
    url: str
    platform: Optional[str] = None


class URLCleanResponse(BaseModel):
    original_url: str
    cleaned_url: str
    platform: Optional[str]
    url_type: Optional[str]


class ResolveRequest(BaseModel):
    url: str


class ResolveResponse(BaseModel):
    original_url: str
    resolved_url: Optional[str]
    platform: Optional[str]


class HealthResponse(BaseModel):
    status: str
    version: str
    shopee_aff_id: str
    lazada_liteapp_key: str


class ConvertShopeeRequest(BaseModel):
    url: str
    mode: str = "an_redir"
    affiliate_id: Optional[str] = None
    sub_id: Optional[str] = None


class ConvertShopeeResponse(BaseModel):
    original_url: str
    cleaned_url: str
    affiliate_url: str
    mode: str
    platform: str
    url_type: str


# ─── API Endpoints ───

@app.get("/", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="ok",
        version="1.0.0",
        shopee_aff_id=config.SHOPEE_AFFILIATE_ID,
        lazada_liteapp_key=config.LAZADA_LITEAPP_KEY
    )


@app.post("/api/clean-url", response_model=URLCleanResponse)
async def clean_url_api(request: URLCleanRequest):
    """API endpoint để làm sạch URL."""
    url = normalize_url(request.url)
    
    # Auto-detect platform
    platform = request.platform
    if not platform:
        if is_shopee_url(url):
            platform = 'shopee'
        elif is_lazada_url(url):
            platform = 'lazada'
    
    # Clean URL
    if platform == 'shopee':
        cleaned_url = clean_shopee_url(url)
        url_type = detect_shopee_url_type(cleaned_url)
    elif platform == 'lazada':
        cleaned_url = clean_lazada_url(url)
        url_type = None
    else:
        cleaned_url = url
        url_type = None
    
    return URLCleanResponse(
        original_url=request.url,
        cleaned_url=cleaned_url,
        platform=platform,
        url_type=url_type
    )


@app.post("/api/resolve-url", response_model=ResolveResponse)
async def resolve_url_api(request: ResolveRequest):
    """API endpoint để resolve short link về link gốc."""
    url = normalize_url(request.url)
    resolved_url, platform = await resolve_short_link(url)
    
    return ResolveResponse(
        original_url=request.url,
        resolved_url=resolved_url,
        platform=platform
    )


@app.post("/api/process-url")
async def process_url_api(request: ResolveRequest):
    """API endpoint đầy đủ: resolve + clean URL."""
    url = normalize_url(request.url)
    
    # Step 1: Resolve if needed
    resolved_url, platform = await resolve_if_needed(url)
    
    # Step 2: Clean URL
    if platform == 'shopee':
        cleaned_url = clean_shopee_url(resolved_url)
        url_type = detect_shopee_url_type(cleaned_url)
    elif platform == 'lazada':
        cleaned_url = clean_lazada_url(resolved_url)
        url_type = None
    else:
        cleaned_url = resolved_url
        url_type = None
    
    return {
        "original_url": request.url,
        "resolved_url": resolved_url,
        "cleaned_url": cleaned_url,
        "platform": platform,
        "url_type": url_type
    }


@app.post("/api/process-url-v2")
async def process_url_v2_api(request: ResolveRequest):
    """Process URL với tự động normalize."""
    url = normalize_url(request.url)
    
    # Resolve
    resolved_url, platform = await resolve_if_needed(url)
    
    # Clean (đã bao gồm normalize cho product URL)
    if platform == 'shopee':
        cleaned_url = clean_shopee_url(resolved_url)
        url_type = detect_shopee_url_type(cleaned_url)
    elif platform == 'lazada':
        cleaned_url = clean_lazada_url(resolved_url)
        url_type = None
    else:
        cleaned_url = resolved_url
        url_type = None
    
    return {
        "original_url": request.url,
        "resolved_url": resolved_url,
        "cleaned_url": cleaned_url,
        "platform": platform,
        "url_type": url_type
    }


@app.post("/api/convert-shopee", response_model=ConvertShopeeResponse)
async def convert_shopee_api(request: ConvertShopeeRequest):
    """
    Chuyển đổi URL Shopee thành affiliate link và rút gọn.
    """
    url = normalize_url(request.url)
    
    # Step 1: Resolve
    resolved_url, platform = await resolve_if_needed(url)
    
    if platform != 'shopee':
        raise HTTPException(
            status_code=400, 
            detail=f"URL không phải Shopee. Platform detected: {platform}"
        )
    
    # Step 2: Clean + Normalize
    cleaned_url = clean_shopee_url(resolved_url)
    url_type = detect_shopee_url_type(cleaned_url)
    
    # Step 3: Convert to affiliate link (an_redir)
    affiliate_id = request.affiliate_id or config.SHOPEE_AFFILIATE_ID
    sub_id = request.sub_id or ""
    
    if request.mode == "an_redir":
        long_affiliate_url = convert_shopee_an_redir(cleaned_url, affiliate_id, sub_id)
    elif request.mode == "cookie":
        raise HTTPException(
            status_code=501,
            detail="Cookie mode chưa được implement."
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Mode không hợp lệ: {request.mode}."
        )
    
    # Step 4: Rút gọn link qua s.salevn.top
    short_url = await shorten_url(long_affiliate_url)
    final_url = short_url if short_url else long_affiliate_url  # Fallback nếu lỗi
    
    return ConvertShopeeResponse(
        original_url=request.url,
        cleaned_url=cleaned_url,
        affiliate_url=final_url,  # ← Giờ là link rút gọn!
        mode=request.mode,
        platform=platform,
        url_type=url_type
    )

# ═══════════════════════════════════════════════════════════
# 8. MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    
    # Lấy PORT từ environment, fallback về 10000 nếu không có
    port_str = os.getenv("PORT", "10000")
    try:
        port = int(port_str)
    except ValueError:
        port = 10000
    
    host = os.getenv("HOST", "0.0.0.0")
    
    print(f"🚀 Starting server on {host}:{port}", file=sys.stderr, flush=True)
    print(f"📊 Shopee Affiliate ID: {config.SHOPEE_AFFILIATE_ID}", file=sys.stderr, flush=True)
    print(f"📊 Lazada LiteApp Key: {config.LAZADA_LITEAPP_KEY}", file=sys.stderr, flush=True)
    
    # log_config=None để tránh lỗi logging trên Render
    uvicorn.run(
        app, 
        host=host, 
        port=port, 
        log_level="info",
        log_config=None,
        access_log=True
    )
