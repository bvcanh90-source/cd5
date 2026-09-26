"""
Affiliate Toolkit - Link Converter & Shortener
All-in-one file cho Render free tier.

Sections:
1. Imports & Constants
2. Configuration
3. URL Cleaner (Shopee + Lazada)
4. Link Resolver (Short links)
5. FastAPI App
6. Main Entry Point
"""

# ═══════════════════════════════════════════════════════════
# 1. IMPORTS & CONSTANTS
# ═══════════════════════════════════════════════════════════

import os
import re
from typing import Optional, Tuple, Set, List
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, unquote

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
    LAZADA_LITEAPP_SECRET: str = os.getenv("LAZADA_LITEAPP_SECRET", "r8ZMKhPxu1JZUCwTUBVMJiJnZKjhWeQF")
    LAZADA_USER_TOKEN: str = os.getenv("LAZADA_USER_TOKEN", "f879c4163b0f4c5a90c1567fcffac91e")
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


# ═══════════════════════════════════════════════════════════
# 3. URL CLEANER - SHOPEE (CẢI TIẾN)
# ═══════════════════════════════════════════════════════════

# Whitelist params cần giữ lại (cho search/other URLs)
SHOPEE_KEEP_PARAMS: Set[str] = {
    # Search page
    'keyword', 'sortBy', 'order', 'page', 'limit',
    'priceMin', 'priceMax', 'rating',
    # Category
    'category', 'categoryId',
    # Shop
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
            # Kiểm tra shop_id và item_id là số
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


def clean_shopee_url(url: str) -> str:
    """
    Làm sạch URL Shopee - strategy hybrid (whitelist + blacklist).
    
    Logic:
    - Product URL → Xóa TẤT CẢ query params
    - Landing page → Xóa TẤT CẢ query params  
    - Shop URL → Xóa TẤT CẢ query params
    - Search/Other → Chỉ giữ whitelist params
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
            # Xóa TẤT CẢ params - không cần bất kỳ tracking nào
            clean_params = {}
        elif url_type == 'search':
            # Search: chỉ giữ whitelist params
            clean_params = {
                k: v for k, v in query_params.items()
                if k.lower() in SHOPEE_KEEP_PARAMS
            }
        else:
            # Other: whitelist params (an toàn nhất)
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
            ''  # Xóa fragment
        ))
        
        # Normalize: remove trailing slash (trừ homepage)
        if clean_url.endswith('/') and parsed.path != '/':
            clean_url = clean_url.rstrip('/')
        
        return clean_url
        
    except Exception as e:
        print(f"[clean_shopee_url] Error: {e}")
        return url


def normalize_shopee_product_url(url: str) -> str:
    """
    Chuẩn hóa product URL về dạng chuẩn.
    
    Input:  https://shopee.vn/opaanlp/507867749/19180372828
    Output: https://shopee.vn/product/507867749/19180372828
    
    Việc này giúp URL ổn định, tránh duplicate khi cùng 1 sản phẩm
    có nhiều slug khác nhau.
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

# ═══════════════════════════════════════════════════════════
# 3. URL CLEANER - LAZADA
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
    
    Args:
        url: URL Lazada gốc
    
    Returns:
        URL Lazada đã được làm sạch
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
            ''  # Xóa fragment
        ))
        
        return clean_url
        
    except Exception as e:
        print(f"[clean_lazada_url] Error: {e}")
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
# 4. LINK RESOLVER
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
    """
    Tìm URL redirect trong JavaScript hoặc meta refresh.
    
    Args:
        html_body: Nội dung HTML của trang
    
    Returns:
        URL redirect nếu tìm thấy, None nếu không
    """
    if not html_body:
        return None
    
    for pattern in JS_REDIRECT_PATTERNS:
        match = re.search(pattern, html_body, re.IGNORECASE)
        if match:
            url = match.group(1)
            # Decode HTML entities
            url = url.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
            return url
    
    return None


def extract_url_param(url: str, param_name: str = 'url') -> Optional[str]:
    """
    Trích xuất giá trị của một query parameter.
    
    Args:
        url: URL cần trích xuất
        param_name: Tên parameter (mặc định là 'url')
    
    Returns:
        Giá trị parameter đã decode, hoặc None nếu không tìm thấy
    """
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
    """
    Detect platform từ URL.
    
    Returns:
        'shopee', 'lazada', hoặc None nếu không xác định
    """
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
    
    Hỗ trợ:
    - HTTP redirects (301, 302, 303, 307, 308)
    - JavaScript redirects (window.location.href, meta refresh)
    - Lazada c.lazada.vn/t/ URL với ?url= parameter
    
    Args:
        url: Short link cần resolve
        max_redirects: Số lần redirect tối đa
        timeout: Timeout cho mỗi request (giây)
    
    Returns:
        Tuple (final_url, platform)
        - final_url: Link gốc cuối cùng
        - platform: 'shopee', 'lazada', hoặc None
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
        follow_redirects=False,  # Tự xử lý redirect
        verify=False,  # Bỏ qua SSL verification
        headers=headers
    ) as client:
        
        for attempt in range(max_redirects):
            if current_url in visited:
                # Loop detected
                break
            
            visited.add(current_url)
            
            try:
                response = await client.get(current_url)
                
                # Xử lý HTTP redirect
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get('Location', '')
                    if location:
                        # Handle relative URLs
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
                print(f"[resolve_short_link] Timeout: {current_url}")
                return None, None
            except Exception as e:
                print(f"[resolve_short_link] Error: {e}")
                return None, None
    
    # Nếu sau max_redirects vẫn chưa tìm được platform
    platform = detect_platform(current_url)
    return current_url, platform


async def resolve_if_needed(url: str) -> Tuple[str, Optional[str]]:
    """
    Resolve URL nếu nó là short link, ngược lại trả về URL gốc.
    
    Args:
        url: URL cần kiểm tra
    
    Returns:
        Tuple (resolved_url, platform)
    """
    # Nếu đã là full URL (không phải short link), trả về ngay
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
        # Không cần resolve
        return url, detect_platform(url)
    
    # Cần resolve
    resolved_url, platform = await resolve_short_link(url)
    return resolved_url or url, platform


# ═══════════════════════════════════════════════════════════
# 5. FASTAPI APP
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


# ═══════════════════════════════════════════════════════════
# 5.1 Pydantic Models
# ═══════════════════════════════════════════════════════════

class URLCleanRequest(BaseModel):
    """Request model cho API làm sạch URL."""
    url: str
    platform: Optional[str] = None  # 'shopee', 'lazada', hoặc None (auto-detect)


class URLCleanResponse(BaseModel):
    """Response model cho API làm sạch URL."""
    original_url: str
    cleaned_url: str
    platform: Optional[str]
    url_type: Optional[str]  # 'product', 'landing', 'shop', 'other'


class ResolveRequest(BaseModel):
    """Request model cho API resolve short link."""
    url: str


class ResolveResponse(BaseModel):
    """Response model cho API resolve short link."""
    original_url: str
    resolved_url: Optional[str]
    platform: Optional[str]


class HealthResponse(BaseModel):
    """Response model cho health check."""
    status: str
    version: str
    shopee_aff_id: str
    lazada_liteapp_key: str


# ═══════════════════════════════════════════════════════════
# 5.2 API Endpoints
# ═══════════════════════════════════════════════════════════

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
    """
    API endpoint để làm sạch URL.
    
    Tự động detect platform nếu không chỉ định.
    """
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
        url_type = None  # TODO: implement detect_lazada_url_type
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
    """
    API endpoint để resolve short link về link gốc.
    
    Hỗ trợ: s.shopee.vn, shp.ee, s.lazada.vn, c.lazada.vn, third-party domains
    """
    url = normalize_url(request.url)
    resolved_url, platform = await resolve_short_link(url)
    
    return ResolveResponse(
        original_url=request.url,
        resolved_url=resolved_url,
        platform=platform
    )


@app.post("/api/process-url")
async def process_url_api(request: ResolveRequest):
    """
    API endpoint đầy đủ: resolve + clean URL.
    
    Flow:
    1. Resolve short link (nếu cần)
    2. Clean tracking parameters
    3. Return cleaned URL
    """
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

class ProcessAndNormalizeRequest(BaseModel):
    url: str


@app.post("/api/process-url-v2")
async def process_url_v2_api(request: ProcessAndNormalizeRequest):
    """
    Process URL với normalize product URL.
    
    Flow:
    1. Resolve short link
    2. Clean tracking params  
    3. Normalize product URL (về dạng /product/shopid/itemid)
    """
    url = normalize_url(request.url)
    
    # Resolve
    resolved_url, platform = await resolve_if_needed(url)
    
    # Clean
    if platform == 'shopee':
        cleaned_url = clean_shopee_url(resolved_url)
        url_type = detect_shopee_url_type(cleaned_url)
        
        # Normalize product URL
        if url_type == 'product':
            normalized_url = normalize_shopee_product_url(cleaned_url)
        else:
            normalized_url = cleaned_url
    elif platform == 'lazada':
        cleaned_url = clean_lazada_url(resolved_url)
        normalized_url = cleaned_url
        url_type = None
    else:
        cleaned_url = resolved_url
        normalized_url = cleaned_url
        url_type = None
    
    return {
        "original_url": request.url,
        "resolved_url": resolved_url,
        "cleaned_url": cleaned_url,
        "normalized_url": normalized_url,
        "platform": platform,
        "url_type": url_type
    }


# ═══════════════════════════════════════════════════════════
# 6. MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    import sys
    
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
        log_config=None,  # ✅ Quan trọng! Tránh lỗi logging
        access_log=True
    )
