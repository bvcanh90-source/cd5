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
# 3. URL CLEANER - SHOPEE
# ═══════════════════════════════════════════════════════════

SHOPEE_REMOVE_PARAMS: Set[str] = {
    # UTM parameters
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term',
    # Shopee tracking
    'uls_trackid', 'credential_token', 'gads_t_sig', 'mmp_pid',
    'smtt', 'smid', 'sp_at', 'sp_lm', 'sp_rid',
    'af_siteid', 'pid', 'af_sub1', 'af_sub2', 'af_sub3', 'af_sub4', 'af_sub5',
    'is_retargeting', 'af_reengagement_window', 'af_sub_siteid',
    'af_click_lookback', 'af_viewthrough_lookback',
    'af_dp', 'af_web_dp', 'af_force_deeplink',
    'share_token', 's_share_source_token',
    'extraParams', 'spm', 'scm', 'clickid',
}

# Regex patterns
SHOPEE_PRODUCT_PATTERN = re.compile(r'^/product/(\d+)/(\d+)', re.IGNORECASE)
SHOPEE_LANDING_PATTERN = re.compile(r'^/m/([a-zA-Z0-9\-_]+)', re.IGNORECASE)
SHOPEE_SHOP_PATTERN = re.compile(r'^/shop/(\d+)/([a-zA-Z0-9\-_]+)', re.IGNORECASE)


def clean_shopee_url(url: str) -> str:
    """
    Làm sạch URL Shopee, loại bỏ tracking parameters.
    
    Args:
        url: URL Shopee gốc (có thể chứa tracking)
    
    Returns:
        URL Shopee đã được làm sạch
        
    Examples:
        Input:  https://shopee.vn/product/244551815/26714201843?utm_source=...
        Output: https://shopee.vn/product/244551815/26714201843
    """
    if not url:
        return url
    
    try:
        parsed = urlparse(url)
        
        # Chỉ xử lý URL Shopee
        if 'shopee' not in parsed.netloc.lower():
            return url
        
        # Parse query string
        query_params = parse_qs(parsed.query, keep_blank_values=True)
        
        # Filter out tracking params
        clean_params = {
            k: v for k, v in query_params.items()
            if k.lower() not in SHOPEE_REMOVE_PARAMS
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
        
        # Normalize path (remove trailing slash for product/landing)
        if clean_url.endswith('/') and not clean_url.endswith('/m/'):
            clean_url = clean_url.rstrip('/')
        
        return clean_url
        
    except Exception as e:
        print(f"[clean_shopee_url] Error: {e}")
        return url


def detect_shopee_url_type(url: str) -> str:
    """
    Phân loại URL Shopee.
    
    Returns:
        'product' - trang sản phẩm
        'landing' - landing page (/m/...)
        'shop' - trang shop
        'other' - không xác định
    """
    try:
        parsed = urlparse(url)
        path = parsed.path
        
        if SHOPEE_PRODUCT_PATTERN.match(path):
            return 'product'
        elif SHOPEE_LANDING_PATTERN.match(path):
            return 'landing'
        elif SHOPEE_SHOP_PATTERN.match(path):
            return 'shop'
        else:
            return 'other'
    except Exception:
        return 'other'


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


# ═══════════════════════════════════════════════════════════
# 6. MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    print(f"🚀 Starting server on port {port}")
    print(f"📊 Config loaded:")
    print(f"   - Shopee Affiliate ID: {config.SHOPEE_AFFILIATE_ID}")
    print(f"   - Lazada LiteApp Key: {config.LAZADA_LITEAPP_KEY}")
    print(f"   - Frontend URL: {config.FRONTEND_URL}")
    
    uvicorn.run(app, host="0.0.0.0", port=port)
