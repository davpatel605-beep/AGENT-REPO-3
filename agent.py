#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║  PRICEYAAR SUPER AGENT v7.1 - SINGLE AGENT TEST MODE               ║
║  Python + Playwright + DOM Strikethrough + EARBUDS ONLY (20 items)  ║
╚══════════════════════════════════════════════════════════════════════╝

EXTRACTION LOGIC:
1. ₹ symbol = price indicator
2. text-decoration: line-through = ORIGINAL PRICE (MRP)
3. Normal ₹ without strikethrough = SELLING PRICE
4. XX% off = DISCOUNT PERCENT (1-99 max)
5. X.X ★ = STAR RATING (1.0-5.0)
6. XX.XK+ = REVIEWS COUNT

VALIDATION RULES:
- Original > Selling (MRP must be higher)
- Ratio: 1.05x to 3x (not 10x!)
- Discount: 1% to 90% (>90% = fake, reject)
- If validation fails → save ONLY selling price
"""

import asyncio
import json
import re
import random
import os
import logging
import sys
from datetime import datetime
from typing import Optional, Dict, List, Tuple

from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from supabase import create_client, Client


# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL")
if not SUPABASE_URL:
    SUPABASE_URL = "https://wolhksrjrossztdsuuly.supabase.co"

SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not SUPABASE_KEY:
    logging.error("CRITICAL ERROR: SUPABASE_KEY is missing. Please set it in your environment/GitHub Secrets.")
    sys.exit(1)

TEST_MODE = True
TEST_BATCH_SIZE = 20

ALL_AGENTS = [
    {"id": 1,  "name": "smart phone", "table": "smart phone"},
    {"id": 2,  "name": "laptop",      "table": "laptop"},
    {"id": 3,  "name": "earbuds",     "table": "earbuds"},
    {"id": 4,  "name": "iphone",      "table": "iphone"},
    {"id": 5,  "name": "smart+tv",    "table": "smart+tv"},
    {"id": 6,  "name": "smartwatch",  "table": "smartwatch"},
    {"id": 7,  "name": "induction",   "table": "induction"},
    {"id": 8,  "name": "keyboard",    "table": "keybord"},
    {"id": 9,  "name": "mouse",       "table": "mouse"},
    {"id": 10, "name": "monitor",     "table": "monitar"},
]

AGENTS = [a for a in ALL_AGENTS if a["name"] == "earbuds"] if TEST_MODE else ALL_AGENTS

HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
DELAY_MIN = 2.0
DELAY_MAX = 5.0

PAGE_LOAD_TIMEOUT = 180000
NAVIGATION_WAIT = "domcontentloaded"
MAX_SCRAPE_RETRIES = 3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("PriceYaarSuperAgent")


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 1: SUPABASE HELPERS
# ═══════════════════════════════════════════════════════════════════════

def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_category_products(sb: Client, table: str, limit: int = 10) -> list[dict]:
    actual_limit = TEST_BATCH_SIZE if TEST_MODE else limit
    try:
        res = sb.table(table).select("*").limit(actual_limit).execute()
        products = res.data or []
        log.info(f"📦 {len(products)} products in '{table}' (Batch size: {actual_limit})")
        return products
    except Exception as e:
        log.error(f"❌ Fetch error for '{table}': {e}")
        return []

def update_product(sb: Client, table: str, product_id, data: dict):
    try:
        sb.table(table).update(data).eq("id", product_id).execute()
        return True
    except Exception as e:
        log.error(f"❌ Update error for id={product_id}: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 2: STRICT PRICE VALIDATION
# ═══════════════════════════════════════════════════════════════════════

def validate_prices(selling_price: float, original_price: float) -> dict:
    valid_selling = selling_price if (100 < selling_price < 50000000) else 0
    valid_original = 0
    discount_str = None
    discount_pct = 0

    if valid_selling > 0 and original_price > 0:
        is_higher = original_price > valid_selling
        min_ratio = original_price >= valid_selling * 1.05
        max_ratio = original_price <= valid_selling * 3.0

        if is_higher and min_ratio and max_ratio:
            pct = round(((original_price - valid_selling) / original_price) * 100)
            if 1 <= pct <= 90:
                valid_original = original_price
                discount_str = f"{pct}% off"
                discount_pct = pct

    final_selling = valid_selling if valid_selling > 0 else (
        original_price if (100 < original_price < 50000000) else 0
    )

    return {
        "final_selling": final_selling,
        "valid_original": valid_original,
        "discount_str": discount_str,
        "discount_pct": discount_pct
    }

def parse_indian_number(s: str) -> Optional[float]:
    if not s:
        return None
    s = str(s).strip().replace(",", "").replace("₹", "").replace(" ", "")
    if s.lower().endswith("k"):
        try:
            return float(s[:-1]) * 1000
        except:
            return None
    try:
        return float(s)
    except:
        return None


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 3: FLIPKART CSS SELECTORS
# ═══════════════════════════════════════════════════════════════════════

FLIPKART_SELECTORS = {
    "selling_price": [
        "div._30jeq3._16Jk6d",
        "div._30jeq3",
        "._16Jk6d",
        "[class*='_30jeq3']",
        "div.Nx9bqj",
        "div._25b18c ._30jeq3",
        "div.UOCQB1 ._30jeq3",
        "span._30jeq3",
        "._30jeq3._16Jk6d",
    ],
    "original_price": [
        "div._3I9_wc._2p6lqe",
        "div._3I9_wc",
        "._2p6lqe",
        "[class*='_3I9_wc']",
        "div.yRaY8j",
        "div._3I9_wc._2p6lqe",
        "span._3I9_wc",
        "._3I9_wc._2p6lqe",
    ],
    "discount": [
        "div._3Ay6Sb._31Dcoz ._3Ay6Sb",
        "div._3Ay6Sb",
        "._31Dcoz",
        "[class*='_3Ay6Sb']",
        "div.UkUFwK span",
        "span._3Ay6Sb",
    ],
    "rating": [
        "div._3LWZlK",
        "div._3LWZlK._1rdVr6",
        "[class*='_3LWZlK']",
        "div.XQDdHH",
        "span._3LWZlK",
    ],
    "reviews": [
        "span._2_R_DZ",
        "span._13vcmD",
        "[class*='_2_R_DZ']",
        "div._2_R_DZ",
    ]
}


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 4: DOM STRIKETHROUGH DETECTION (KEY FEATURE)
# ═══════════════════════════════════════════════════════════════════════

async def extract_with_dom_strikethrough(page: Page) -> dict:
    return await page.evaluate("""
        () => {
            const result = {
                sellingPrice: null,
                originalPrice: null,
                discountPercent: null,
                rating: null,
                reviews: null
            };

            const allElements = document.querySelectorAll('*');
            const rupeeElements = [];

            for (const el of allElements) {
                const text = el.textContent || '';
                if (!text.includes('₹')) continue;

                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') continue;

                const matches = text.match(/₹\\s*[0-9,]+/g);
                if (!matches) continue;

                for (const match of matches) {
                    const num = parseInt(match.replace(/[^0-9]/g, ''));
                    if (num < 500) continue;

                    const isStrike = style.textDecoration.includes('line-through') ||
                                     el.closest('[style*="line-through"]') !== null;

                    let parent = el.parentElement;
                    let parentStrike = false;
                    for (let i = 0; i < 3 && parent; i++) {
                        const ps = window.getComputedStyle(parent);
                        if (ps.textDecoration.includes('line-through')) {
                            parentStrike = true;
                            break;
                        }
                        parent = parent.parentElement;
                    }

                    const isOriginal = isStrike || parentStrike;

                    const lowerText = text.toLowerCase();
                    const badKeywords = ['emi', '/m', 'per month', 'monthly',
                                        'warranty', 'protection', 'insurance',
                                        'case', 'cover', 'screen guard', 'charger'];
                    const isBad = badKeywords.some(k => lowerText.includes(k));
                    if (isBad) continue;

                    rupeeElements.push({ match, num, isOriginal });
                }
            }

            if (rupeeElements.length > 0) {
                const originals = rupeeElements.filter(e => e.isOriginal).map(e => e.num);
                const sellings = rupeeElements.filter(e => !e.isOriginal).map(e => e.num);

                const uniqueOriginals = [...new Set(originals)].sort((a, b) => b - a);
                const uniqueSellings = [...new Set(sellings)].sort((a, b) => a - b);

                if (uniqueSellings.length > 0) {
                    result.sellingPrice = uniqueSellings[0];
                }
                if (uniqueOriginals.length > 0) {
                    result.originalPrice = uniqueOriginals[0];
                }
            }

            const bodyText = document.body.innerText || '';
            const discMatch = bodyText.match(/[↓]\\s*(\\d{1,2})\\s*%/);
            if (discMatch) {
                result.discountPercent = parseInt(discMatch[1]);
            } else {
                const discMatch2 = bodyText.match(/(\\d{1,2})\\s*%\\s*(?:off|Off|OFF)/);
                if (discMatch2) result.discountPercent = parseInt(discMatch2[1]);
            }

            const ratingMatch = bodyText.match(/(\\d\\.\\d)\\s*★/);
            if (ratingMatch) {
                const val = parseFloat(ratingMatch[1]);
                if (val >= 1 && val <= 5) result.rating = val.toFixed(1);
            }

            const revMatch = bodyText.match(/([0-9]+(?:\\.[0-9]+)?)\\s*K\\+/);
            if (revMatch) {
                result.reviews = Math.round(parseFloat(revMatch[1]) * 1000).toString();
            } else {
                const revMatch2 = bodyText.match(/([0-9,]+)\\s*(?:Ratings?\\s*[&+]\\s*)?Reviews?/i);
                if (revMatch2) result.reviews = revMatch2[1].replace(/,/g, '');
            }

            return result;
        }
    """)


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 5: CSS SELECTOR FALLBACK
# ═══════════════════════════════════════════════════════════════════════

async def extract_with_css_selectors(page: Page) -> dict:
    result = {
        "sellingPrice": None,
        "originalPrice": None,
        "discountPercent": None,
        "rating": None,
        "reviews": None
    }

    for field, selectors in FLIPKART_SELECTORS.items():
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = await el.inner_text()
                    text = text.strip()
                    if text:
                        val = parse_indian_number(re.sub(r'[₹%\s]', '', text))
                        if val:
                            if field == "selling_price":
                                result["sellingPrice"] = val
                            elif field == "original_price":
                                result["originalPrice"] = val
                            elif field == "discount":
                                result["discountPercent"] = int(val)
                            elif field == "rating":
                                if 1 <= val <= 5:
                                    result["rating"] = f"{val:.1f}"
                            elif field == "reviews":
                                result["reviews"] = str(int(val))
                            break
            except:
                continue

    return result


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 6: TEXT-BASED FALLBACK
# ═══════════════════════════════════════════════════════════════════════

async def extract_with_text_parsing(page: Page) -> dict:
    page_text = await page.inner_text("body")

    result = {
        "sellingPrice": None,
        "originalPrice": None,
        "discountPercent": None,
        "rating": None,
        "reviews": None
    }

    prices = []
    price_matches = re.findall(r'₹\s*([\d,]+)', page_text)
    for p in price_matches:
        val = parse_indian_number(p)
        if val and val > 500:
            prices.append(val)

    lines = page_text.split('\n')
    bad_keywords = ['emi', '/m', 'per month', 'monthly', 'warranty',
                    'protection', 'insurance', 'case', 'cover']
    clean_prices = []
    for i, line in enumerate(lines):
        lower = line.lower()
        if any(k in lower for k in bad_keywords):
            continue
        line_prices = re.findall(r'₹\s*([\d,]+)', line)
        for p in line_prices:
            val = parse_indian_number(p)
            if val and val > 500:
                clean_prices.append(val)

    unique = sorted(set(clean_prices))
    if len(unique) >= 2:
        result["sellingPrice"] = unique[0]
        result["originalPrice"] = unique[-1]
    elif len(unique) == 1:
        result["sellingPrice"] = unique[0]

    disc_match = re.search(r'(\d{1,2})\s*%\s*off', page_text, re.IGNORECASE)
    if disc_match:
        result["discountPercent"] = int(disc_match.group(1))

    rating_match = re.search(r'(\d\.\d)\s*★', page_text)
    if rating_match:
        val = float(rating_match.group(1))
        if 1 <= val <= 5:
            result["rating"] = f"{val:.1f}"

    rev_match = re.search(r'(\d+\.?\d*)\s*K\+', page_text)
    if rev_match:
        result["reviews"] = str(int(float(rev_match.group(1)) * 1000))
    else:
        rev_match2 = re.search(r'([\d,]+)\s*(?:Ratings?\s*[&+]\s*)?Reviews?', page_text, re.IGNORECASE)
        if rev_match2:
            result["reviews"] = rev_match2.group(1).replace(',', '')

    return result


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 6B: CAPTCHA / BLOCK DETECTION
# ═══════════════════════════════════════════════════════════════════════

async def is_captcha_or_blocked(page: Page) -> bool:
    try:
        current_url = page.url
        page_title = await page.title()
        body_text = await page.inner_text("body")

        block_url_keywords = ["captcha", "robot", "challenge", "security", "blocked", "verify"]
        for kw in block_url_keywords:
            if kw in current_url.lower():
                log.warning(f"  🤖 CAPTCHA/BLOCK detected via URL: {current_url[:80]}")
                return True

        block_title_keywords = ["attention required", "just a moment", "access denied",
                                 "bot", "security check", "captcha", "403"]
        for kw in block_title_keywords:
            if kw in page_title.lower():
                log.warning(f"  🤖 CAPTCHA/BLOCK detected via title: '{page_title}'")
                return True

        block_content_keywords = [
            "please verify you are a human",
            "enable javascript and cookies",
            "security check to access",
            "your browser does not support",
            "access to this page has been denied",
            "checking your browser",
            "cf-browser-verification"
        ]
        body_lower = body_text.lower()
        for kw in block_content_keywords:
            if kw in body_lower:
                log.warning(f"  🤖 CAPTCHA/BLOCK detected via content: '{kw}'")
                return True

        if len(body_text.strip()) < 200:
            log.warning(f"  ⚠️ Page too short ({len(body_text)} chars) - possibly blocked")
            return True

        return False
    except Exception as e:
        log.warning(f"  ⚠️ Captcha check failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 7: MASTER EXTRACTION - Try all 3 methods
# ═══════════════════════════════════════════════════════════════════════

async def extract_product_data(page: Page, url: str, browser: Browser) -> dict:
    log.info(f"  🌐 Opening: {url[:80]}...")

    for scrape_attempt in range(1, MAX_SCRAPE_RETRIES + 1):
        try:
            if scrape_attempt > 1:
                log.info(f"  🔄 Scrape retry {scrape_attempt}/{MAX_SCRAPE_RETRIES} with fresh context...")
                await asyncio.sleep(random.uniform(8.0, 15.0))
                fresh_context = await create_stealth_context(browser)
                page = await fresh_context.new_page()

            nav_success = False
            for wait_strategy in ["domcontentloaded", "load"]:
                try:
                    log.info(f"  ⏳ Navigation strategy: '{wait_strategy}' (timeout={PAGE_LOAD_TIMEOUT//1000}s)")
                    await page.goto(url, wait_until=wait_strategy, timeout=PAGE_LOAD_TIMEOUT)
                    nav_success = True
                    break
                except Exception as nav_err:
                    if "timeout" in str(nav_err).lower():
                        log.warning(f"  ⏰ Navigation timeout with '{wait_strategy}', trying next strategy...")
                        try:
                            body_check = await page.inner_text("body")
                            if len(body_check) > 500:
                                log.info(f"  ⚡ Page partially loaded ({len(body_check)} chars), proceeding...")
                                nav_success = True
                                break
                        except:
                            pass
                    else:
                        raise nav_err

            if not nav_success:
                log.error(f"  ❌ All navigation strategies failed for: {url[:60]}")
                continue

            await asyncio.sleep(random.uniform(2.5, 4.5))

            current_url = page.url
            if "login" in current_url or "error" in current_url.lower():
                log.warning(f"  ⚠️ Redirected to: {current_url[:60]}")
                return {}

            if await is_captcha_or_blocked(page):
                log.warning(f"  🤖 Bot block detected! Will retry with fresh context...")
                if scrape_attempt < MAX_SCRAPE_RETRIES:
                    await asyncio.sleep(random.uniform(15.0, 25.0))
                    continue
                else:
                    log.error(f"  ❌ Still blocked after {MAX_SCRAPE_RETRIES} attempts. Giving up.")
                    return {}

            data = {}
            method = ""

            for attempt in range(1, 16):
                await human_scroll(page)
                await asyncio.sleep(random.uniform(1.0, 2.0))

                data_try = await extract_with_dom_strikethrough(page)
                if data_try.get("sellingPrice"):
                    data = data_try
                    method = "DOM_strikethrough"
                    break

                css_data = await extract_with_css_selectors(page)
                if css_data.get("sellingPrice"):
                    data["sellingPrice"] = css_data["sellingPrice"]
                    if css_data.get("originalPrice"):
                        data["originalPrice"] = css_data["originalPrice"]
                    data.update({k: v for k, v in css_data.items() if v and not data.get(k)})
                    method = "CSS_selectors"
                    break

                text_data = await extract_with_text_parsing(page)
                if text_data.get("sellingPrice"):
                    data = text_data
                    method = "text_parsing"
                    break

                log.warning(f"  ⏳ Attempt {attempt}/15: Price not found yet, retrying & waiting...")
                await asyncio.sleep(random.uniform(2.0, 4.0))

            if data.get("sellingPrice"):
                log.info(f"  ✅ Right | [{method}] ₹{int(data['sellingPrice']):,} | "
                         f"MRP:₹{int(data['originalPrice'] or 0):,} | "
                         f"Disc:{data.get('discountPercent') or 'N/A'}% | "
                         f"⭐{data.get('rating') or 'N/A'} | "
                         f"Rev:{data.get('reviews') or 'N/A'}")
                return data
            else:
                log.error(f"  ❌ Failed to extract data even after maximum attempts!")
                return {}

        except Exception as e:
            err_str = str(e).lower()
            if "timeout" in err_str or "timed out" in err_str:
                log.warning(f"  ⏰ ReadTimeoutError on attempt {scrape_attempt}: {e}")
                if scrape_attempt < MAX_SCRAPE_RETRIES:
                    log.info(f"  🔄 Will retry with fresh context...")
                    continue
                else:
                    log.error(f"  ❌ Timeout after {MAX_SCRAPE_RETRIES} retries. Skipping.")
                    return {}
            else:
                log.error(f"  ❌ Scrape failed: {e}")
                return {}

    return {}


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 8: HUMAN-LIKE BEHAVIOR
# ═══════════════════════════════════════════════════════════════════════

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.86 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]

VIEWPORTS = [
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1920, "height": 1080},
    {"width": 1280, "height": 800},
]

async def human_scroll(page: Page):
    scroll_height = await page.evaluate("document.body.scrollHeight")
    current = 0
    while current < min(scroll_height * 0.6, 2000):
        scroll_amount = random.randint(100, 300)
        current += scroll_amount
        await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
        await asyncio.sleep(random.uniform(0.1, 0.4))

async def human_mouse_move(page: Page):
    try:
        viewport = page.viewport_size or {"width": 1366, "height": 768}
        for _ in range(random.randint(2, 5)):
            x = random.randint(100, viewport["width"] - 100)
            y = random.randint(100, viewport["height"] - 100)
            await page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.1, 0.3))
    except:
        pass

async def setup_browser(playwright):
    return await playwright.chromium.launch(
        headless=HEADLESS,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--disable-extensions",
            "--disable-dev-shm-usage",
            "--disable-features=VizDisplayCompositor",
            "--disable-ipc-flooding-protection",
            "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
        ]
    )

async def create_stealth_context(browser: Browser) -> BrowserContext:
    ua = random.choice(USER_AGENTS)
    vp = random.choice(VIEWPORTS)
    context = await browser.new_context(
        user_agent=ua,
        viewport=vp,
        locale="en-IN",
        timezone_id="Asia/Kolkata",
        extra_http_headers={
            "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "max-age=0",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }
    )
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en', 'hi'] });
        window.chrome = { runtime: {} };
        Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
        Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
        Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
        Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 });
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters)
        );
        const getContext = HTMLCanvasElement.prototype.getContext;
        HTMLCanvasElement.prototype.getContext = function(type, ...args) {
            const ctx = getContext.call(this, type, ...args);
            if (ctx && type === '2d') {
                const originalFillText = ctx.fillText.bind(ctx);
                ctx.fillText = function(...fargs) {
                    return originalFillText(...fargs);
                };
            }
            return ctx;
        };
    """)
    return context


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 9: BUILD SUPABASE UPDATE
# ═══════════════════════════════════════════════════════════════════════

def get_dict_value_ignore_case(d: dict, target_keys: list) -> str:
    target_keys_lower = [k.lower() for k in target_keys]
    for key, value in d.items():
        if key.lower() in target_keys_lower and value:
            return str(value)
    return ""

def find_real_column_name(all_cols: list, candidates: list) -> Optional[str]:
    candidates_lower = [c.lower() for c in candidates]
    for col in all_cols:
        if col.lower() in candidates_lower:
            return col
    return None

def build_update_payload(product: dict, extracted: dict, all_cols: list) -> Tuple[dict, dict]:
    selling_num = extracted.get("sellingPrice") or 0
    original_num = extracted.get("originalPrice") or 0
    extracted_discount = extracted.get("discountPercent") or 0

    validated = validate_prices(selling_num, original_num)

    if 1 <= extracted_discount <= 90 and validated["valid_original"] > 0:
        validated["discount_str"] = f"{extracted_discount}% off"
        validated["discount_pct"] = extracted_discount

    u = {}

    price_candidates = ["Price", "Current Price", "price", "current_price", "discounted_price"]
    mrp_candidates = ["Original Price", "Original Price-2", "original_price", "mrp"]
    discount_candidates = ["Discount", "discount", "discount_percent"]
    rating_candidates = ["Rating", "rating", "Ratings and Reviews", "Rating and Reviews"]
    reviews_candidates = ["Number of Reviews", "Reviews", "reviews", "review_count"]

    price_col = find_real_column_name(all_cols, price_candidates)
    mrp_col = find_real_column_name(all_cols, mrp_candidates)
    discount_col = find_real_column_name(all_cols, discount_candidates)
    rating_col = find_real_column_name(all_cols, rating_candidates)
    reviews_col = find_real_column_name(all_cols, reviews_candidates)

    if price_col and validated["final_selling"] > 0:
        u[price_col] = f"₹{int(validated['final_selling']):,}"
    if mrp_col and validated["valid_original"] > 0:
        u[mrp_col] = f"₹{int(validated['valid_original']):,}"
    if discount_col and validated["discount_str"]:
        u[discount_col] = validated["discount_str"]
    if rating_col and extracted.get("rating"):
        u[rating_col] = extracted["rating"]
    if reviews_col and extracted.get("reviews"):
        u[reviews_col] = extracted["reviews"]

    return u, validated


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 10: MINI AGENT RUNNER
# ═══════════════════════════════════════════════════════════════════════

async def run_mini_agent(agent_config: dict, sb: Client, browser: Browser):
    agent_id = agent_config["id"]
    agent_name = agent_config["name"]
    table = agent_config["table"]
    label = f"Agent-{agent_id:02d} [{agent_name.upper()}]"

    log.info(f"\n{'='*60}")
    log.info(f"  {label} STARTING {'(TEST MODE - 20 items)' if TEST_MODE else ''}")
    log.info(f"{'='*60}")

    products = fetch_category_products(sb, table, limit=10)
    if not products:
        log.warning(f"  [{label}] No products found")
        return {"agent": label, "updated": 0, "failed": 0, "total": 0}

    context = await create_stealth_context(browser)
    page = await context.new_page()

    updated = 0
    failed = 0

    for i, product in enumerate(products, 1):
        url = get_dict_value_ignore_case(product, ["Product Link", "product_url", "link", "Product URL"])

        if not url or "flipkart.com" not in url:
            log.warning(f"  [{label}] ({i}/{len(products)}) No valid Flipkart URL, skipping")
            continue

        product_name = get_dict_value_ignore_case(product, ["Product Name-2", "Product Name", "name", "Brand Name"])
        if not product_name:
            product_name = "Unknown"

        log.info(f"\n  [{label}] ({i}/{len(products)}) {product_name[:50]}...")

        await human_mouse_move(page)

        extracted = await extract_product_data(page, url, browser)

        if not extracted or not extracted.get("sellingPrice"):
            log.warning(f"  [{label}] No price extracted, skipping")
            failed += 1
            continue

        all_cols = list(product.keys())
        update_data, validated = build_update_payload(product, extracted, all_cols)

        if not update_data:
            log.warning(f"  [{label}] No columns to update")
            failed += 1
            continue

        product_id = product.get("id")
        success = update_product(sb, table, product_id, update_data)

        if success:
            updated += 1
            log.info(f"  [{label}] ✅ Right! Updated DB: "
                     f"₹{int(validated['final_selling']):,} | "
                     f"MRP:₹{int(validated['valid_original'] or 0):,} | "
                     f"{validated['discount_str'] or 'No discount'}")
        else:
            failed += 1

        if i < len(products):
            delay = random.uniform(4.0, 8.0)
            log.info(f"  [{label}] ⏳ Waiting {delay:.1f}s...")
            await asyncio.sleep(delay)

    await context.close()

    log.info(f"\n  [{label}] ✅ DONE: {updated} updated, {failed} failed, {len(products)} total")
    return {"agent": label, "updated": updated, "failed": failed, "total": len(products)}


# ═══════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════

async def main():
    log.info("╔══════════════════════════════════════════════════════════════╗")
    if TEST_MODE:
        log.info("║  PRICEYAAR SUPER AGENT v7.1 - SINGLE AGENT TEST MODE        ║")
        log.info("║  🎯 TARGET: earbuds table (20 products)                      ║")
    else:
        log.info("║  PRICEYAAR SUPER AGENT v7.1 - FULL MODE (All 10 Agents)     ║")
    log.info("║  Python + Playwright + DOM Strikethrough + Anti-Bot           ║")
    log.info("╚══════════════════════════════════════════════════════════════╝")
    log.info(f"  Active agents: {[a['name'] for a in AGENTS]}")
    log.info(f"  Batch size: {TEST_BATCH_SIZE if TEST_MODE else 10} products per agent")

    sb = get_supabase()
    log.info(f"✅ Supabase connected to: {SUPABASE_URL[:40]}...")

    async with async_playwright() as playwright:
        browser = await setup_browser(playwright)
        log.info(f"🌐 Browser launched (headless={HEADLESS})")

        results = []
        for agent in AGENTS:
            result = await run_mini_agent(agent, sb, browser)
            results.append(result)

            if agent["id"] < len(ALL_AGENTS) and not TEST_MODE:
                rest = random.uniform(5.0, 10.0)
                log.info(f"\n💤 Resting {rest:.0f}s before next agent...")
                await asyncio.sleep(rest)

        await browser.close()

    log.info(f"\n{'='*60}")
    log.info("  FINAL REPORT")
    log.info(f"{'='*60}")
    total_updated = 0
    total_failed = 0
    total_products = 0
    for r in results:
        log.info(f"  {r['agent']}: {r['updated']} updated | {r['failed']} failed | {r['total']} total")
        total_updated += r["updated"]
        total_failed += r["failed"]
        total_products += r["total"]
    log.info(f"{'='*60}")
    log.info(f"  TOTAL: {total_updated} updated | {total_failed} failed | {total_products} products")
    log.info(f"{'='*60}")
    if TEST_MODE:
        log.info("🏁 TEST MODE complete! Set TEST_MODE = False to run all 10 agents.")
    else:
        log.info("🏁 All 10 agents finished!")


if __name__ == "__main__":
    asyncio.run(main())

