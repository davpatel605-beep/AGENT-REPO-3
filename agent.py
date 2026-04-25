#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║  PRICEYAAR SUPER AGENT v8.2 - FULL LENGTH & ANTI-BOT EDITION        ║
║  Python + Playwright + DOM Strikethrough + Safe GitHub Actions Fix   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ═══════════════════════════════════════════════════════════════════════
#  SECTION 0: AUTO-INSTALL DEPENDENCIES
# ═══════════════════════════════════════════════════════════════════════
import sys
import subprocess
import os

def ensure_dependencies():
    """Automatically installs required pip packages if not found."""
    try:
        reqs = subprocess.check_output([sys.executable, '-m', 'pip', 'freeze']).decode('utf-8').lower()
    except Exception as e:
        print(f"Error checking pip freeze: {e}")
        reqs = ""

    packages = {
        'playwright': 'playwright',
        'playwright-stealth': 'playwright-stealth',
        'supabase': 'supabase'
    }

    for pkg_name, pip_name in packages.items():
        if pkg_name not in reqs:
            print(f"[*] Installing missing package: {pip_name}...")
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', pip_name, '--quiet'])

    print("[*] Ensuring Playwright browsers are installed...")
    try:
        subprocess.check_call([sys.executable, '-m', 'playwright', 'install', 'chromium'])
    except Exception:
        pass

ensure_dependencies()

# ─────────────────────────────────────────────
#  STANDARD IMPORTS
# ─────────────────────────────────────────────
import asyncio
import re
import random
import logging
from typing import Optional, Dict, List, Tuple

from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from supabase import create_client, Client

try:
    from playwright_stealth import stealth_async
    STEALTH_AVAILABLE = True
    print("[*] playwright-stealth loaded successfully.")
except ImportError:
    stealth_async = None
    STEALTH_AVAILABLE = False
    print("⚠️ WARNING: playwright-stealth not found. Using manual evasions only.")


# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL")
if not SUPABASE_URL:
    SUPABASE_URL = "https://wolhksrjrossztdsuuly.supabase.co"

SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not SUPABASE_KEY:
    print("CRITICAL ERROR: SUPABASE_KEY is missing. Please set it in your environment/GitHub Secrets.")
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
PAGE_LOAD_TIMEOUT = 120000
MAX_SCRAPE_RETRIES = 3
MIN_URL_LENGTH = 60

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

def fetch_category_products(sb: Client, table: str, limit: int = 10) -> List[Dict]:
    """
    Fetch products from Supabase.
    Supabase API always returns the full raw string value.
    The '...' you see in the Dashboard is only a UI display truncation,
    NOT the actual stored value. This function fetches complete data.
    """
    actual_limit = TEST_BATCH_SIZE if TEST_MODE else limit
    try:
        res = sb.table(table).select("*").limit(actual_limit).execute()
        products = res.data or []
        log.info(f"📦 {len(products)} products fetched from '{table}' (limit: {actual_limit})")
        return products
    except Exception as e:
        log.error(f"❌ Fetch error for '{table}': {e}")
        return []

def update_product(sb: Client, table: str, product_id, data: dict) -> bool:
    try:
        sb.table(table).update(data).eq("id", product_id).execute()
        return True
    except Exception as e:
        log.error(f"❌ Update error for id={product_id}: {e}")
        return False

def update_product_url(sb: Client, table: str, product_id, url_col: str, new_url: str) -> bool:
    """Save a corrected/recovered Flipkart URL back to the database."""
    try:
        sb.table(table).update({url_col: new_url}).eq("id", product_id).execute()
        log.info(f"  💾 Corrected URL saved to DB for id={product_id}")
        return True
    except Exception as e:
        log.error(f"  ❌ URL save failed for id={product_id}: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 2: TRUNCATED URL DETECTION
# ═══════════════════════════════════════════════════════════════════════

def is_url_truncated(url: str) -> bool:
    """
    Returns True if URL is missing, truncated, or invalid.

    Valid Flipkart product URL example:
    https://www.flipkart.com/boult-audio-z40-pro/p/itm123abc?pid=XYZ

    Signs of a bad URL:
    - Ends with '...' (Supabase Dashboard UI artifact — actual DB value may differ)
    - Shorter than MIN_URL_LENGTH characters
    - Missing '/p/' segment which all Flipkart product pages must have
    - Contains whitespace (URL is broken)
    - Not starting with http
    - Not a flipkart.com domain
    """
    if not url:
        log.warning("  ⚠️ URL is empty or None.")
        return True

    url = url.strip()

    if url.endswith("...") or url.endswith("-...") or url.endswith("…"):
        log.warning(f"  ⚠️ URL ends with ellipsis (truncated): {url}")
        return True

    if len(url) < MIN_URL_LENGTH:
        log.warning(f"  ⚠️ URL too short ({len(url)} chars): {url}")
        return True

    if not url.startswith("http"):
        log.warning(f"  ⚠️ URL does not start with http: {url}")
        return True

    if "flipkart.com" not in url:
        log.warning(f"  ⚠️ Not a Flipkart URL: {url}")
        return True

    if "/p/" not in url:
        log.warning(f"  ⚠️ Missing '/p/' in URL (not a product page): {url}")
        return True

    if " " in url:
        log.warning(f"  ⚠️ URL contains spaces (broken): {url}")
        return True

    return False


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 3: FLIPKART SEARCH FALLBACK + DATABASE SYNC
# ═══════════════════════════════════════════════════════════════════════

async def search_flipkart_for_url(page: Page, product_name: str) -> Optional[str]:
    """
    If product URL is truncated/invalid, search Flipkart by product name
    and extract the first valid product URL from search results.
    """
    if not product_name or product_name.strip().lower() == "unknown":
        log.error("  ❌ Cannot search: product name is empty or 'Unknown'.")
        return None

    search_query = product_name.strip().replace(" ", "+")
    search_url = f"https://www.flipkart.com/search?q={search_query}"
    log.info(f"  🔍 Flipkart search for: '{product_name}'")

    try:
        await page.goto(
            search_url,
            referer="https://www.google.com/",
            wait_until="domcontentloaded",
            timeout=PAGE_LOAD_TIMEOUT
        )
        await asyncio.sleep(random.uniform(2.5, 5.0))

        # Try selectors in order of reliability
        product_link_selectors = [
            "a[href*='/p/itm']",
            "a._1fQZEK",
            "a.s1Q9rs",
            "a._2rpwqI",
            "div._1AtVbE a",
            "div._13oc-S a",
            "div.CXW8mj a",
            "a[data-id]",
        ]

        for sel in product_link_selectors:
            try:
                links = page.locator(sel)
                count = await links.count()
                if count > 0:
                    href = await links.first.get_attribute("href")
                    if href:
                        if href.startswith("/"):
                            href = "https://www.flipkart.com" + href
                        if "flipkart.com" in href and "/p/" in href:
                            log.info(f"  ✅ URL found via selector '{sel}': {href[:80]}")
                            return href
            except:
                continue

        # Last resort: full DOM scan for any /p/itm link
        log.warning("  ⚠️ Standard selectors failed. Scanning all anchor tags...")
        all_hrefs = await page.evaluate("""
            () => {
                const links = Array.from(document.querySelectorAll('a[href]'));
                return links
                    .map(a => a.href)
                    .filter(h => h.includes('/p/itm') || h.includes('/p/ITM'));
            }
        """)
        if all_hrefs:
            log.info(f"  ✅ URL found via DOM scan: {all_hrefs[0][:80]}")
            return all_hrefs[0]

        log.error(f"  ❌ No product URL found on search results for: '{product_name}'")
        return None

    except Exception as e:
        log.error(f"  ❌ Flipkart search exception for '{product_name}': {e}")
        return None


async def resolve_product_url(
    page: Page,
    product: dict,
    sb: Client,
    table: str,
    product_id
) -> Optional[str]:
    """
    Master URL resolver:
    1. Read URL from product (case-insensitive column match)
    2. If truncated/invalid → search Flipkart by product name
    3. If found → save corrected URL to DB (database sync)
    4. Return working URL or None
    """
    url_col_candidates = ["Product Link", "product_url", "link", "Product URL", "url"]
    url = None
    url_col = None

    for key, value in product.items():
        if key.lower() in [c.lower() for c in url_col_candidates] and value:
            url = str(value).strip()
            url_col = key
            break

    log.info(f"  🔗 URL from DB ({url_col}): {url[:80] if url else 'EMPTY'}...")

    if is_url_truncated(url):
        log.warning("  ⚠️ URL is truncated or invalid → Starting search fallback...")

        name_candidates = ["Product Name-2", "Product Name", "name", "Brand Name", "title"]
        product_name = None
        for nc in name_candidates:
            for key, value in product.items():
                if key.lower() == nc.lower() and value:
                    product_name = str(value).strip()
                    break
            if product_name:
                break

        if not product_name:
            log.error("  ❌ No product name found. Cannot search Flipkart. Skipping.")
            return None

        recovered_url = await search_flipkart_for_url(page, product_name)

        if recovered_url:
            log.info(f"  🔧 Recovered URL: {recovered_url[:80]}")
            if url_col and product_id:
                update_product_url(sb, table, product_id, url_col, recovered_url)
            return recovered_url
        else:
            log.error(f"  ❌ URL recovery failed for '{product_name}'. Skipping.")
            return None

    return url


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 4: EXTRACTION LOGIC - DOM STRIKETHROUGH (PRIMARY)
# ═══════════════════════════════════════════════════════════════════════

async def extract_with_dom_strikethrough(page: Page) -> dict:
    """
    Primary extraction method.
    Strikethrough ₹ = MRP (Original Price)
    Normal ₹ = Selling Price
    """
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
                    if (badKeywords.some(k => lowerText.includes(k))) continue;

                    rupeeElements.push({ num, isOriginal });
                }
            }

            if (rupeeElements.length > 0) {
                const originals = rupeeElements.filter(e => e.isOriginal).map(e => e.num);
                const sellings  = rupeeElements.filter(e => !e.isOriginal).map(e => e.num);
                if (sellings.length > 0)  result.sellingPrice  = Math.min(...sellings);
                if (originals.length > 0) result.originalPrice = Math.max(...originals);
            }

            const bodyText = document.body.innerText || '';

            const discMatch = bodyText.match(/(\\d{1,2})\\s*%\\s*(?:off|Off|OFF)/);
            if (discMatch) result.discountPercent = parseInt(discMatch[1]);

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
#  SECTION 5: EXTRACTION LOGIC - CSS SELECTORS (FALLBACK)
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
    ],
    "original_price": [
        "div._3I9_wc._2p6lqe",
        "div._3I9_wc",
        "._2p6lqe",
        "[class*='_3I9_wc']",
        "div.yRaY8j",
        "span._3I9_wc",
    ],
    "discount": [
        "div._3Ay6Sb._31Dcoz",
        "div._3Ay6Sb",
        "._31Dcoz",
        "div.UkUFwK span",
        "span._3Ay6Sb",
    ],
    "rating": [
        "div._3LWZlK",
        "div._3LWZlK._1rdVr6",
        "[class*='_3LWZlK']",
        "div.XQDdHH",
    ],
    "reviews": [
        "span._2_R_DZ",
        "span._13vcmD",
        "[class*='_2_R_DZ']",
        "div._2_R_DZ",
    ]
}

async def extract_with_css_selectors(page: Page) -> dict:
    result = {
        "sellingPrice": None,
        "originalPrice": None,
        "discountPercent": None,
        "rating": None,
        "reviews": None
    }

    field_map = {
        "selling_price": "sellingPrice",
        "original_price": "originalPrice",
        "discount": "discountPercent",
        "rating": "rating",
        "reviews": "reviews"
    }

    for field, selectors in FLIPKART_SELECTORS.items():
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = await el.inner_text()
                    text = text.strip()
                    if text:
                        clean = re.sub(r'[₹%\s,]', '', text)
                        val = None
                        try:
                            val = float(clean)
                        except:
                            pass
                        if val is not None:
                            key = field_map[field]
                            if field == "rating":
                                if 1.0 <= val <= 5.0:
                                    result[key] = f"{val:.1f}"
                            elif field == "reviews":
                                result[key] = str(int(val))
                            elif field == "discount":
                                result[key] = int(val)
                            else:
                                result[key] = val
                            break
            except:
                continue

    return result


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 6: EXTRACTION LOGIC - TEXT PARSING (LAST RESORT)
# ═══════════════════════════════════════════════════════════════════════

async def extract_with_text_parsing(page: Page) -> dict:
    result = {
        "sellingPrice": None,
        "originalPrice": None,
        "discountPercent": None,
        "rating": None,
        "reviews": None
    }
    try:
        page_text = await page.inner_text("body")
    except:
        return result

    lines = page_text.split('\n')
    bad_keywords = ['emi', '/m', 'per month', 'monthly', 'warranty',
                    'protection', 'insurance', 'case', 'cover']
    clean_prices = []
    for line in lines:
        if any(k in line.lower() for k in bad_keywords):
            continue
        for p in re.findall(r'₹\s*([\d,]+)', line):
            val_str = p.replace(',', '')
            try:
                val = float(val_str)
                if val > 500:
                    clean_prices.append(val)
            except:
                pass

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
#  SECTION 7: CAPTCHA / BLOCK DETECTION
# ═══════════════════════════════════════════════════════════════════════

async def is_captcha_or_blocked(page: Page) -> bool:
    try:
        current_url = page.url
        page_title = await page.title()

        block_url_keywords = ["captcha", "robot", "challenge", "security", "blocked", "verify"]
        for kw in block_url_keywords:
            if kw in current_url.lower():
                log.warning(f"  🤖 BLOCK detected via URL: {current_url[:80]}")
                return True

        block_title_keywords = ["attention required", "just a moment", "access denied",
                                 "security check", "captcha", "403"]
        for kw in block_title_keywords:
            if kw in page_title.lower():
                log.warning(f"  🤖 BLOCK detected via title: '{page_title}'")
                return True

        body_text = await page.inner_text("body")
        block_content_keywords = [
            "please verify you are a human",
            "enable javascript and cookies",
            "security check to access",
            "access to this page has been denied",
            "checking your browser",
            "cf-browser-verification"
        ]
        body_lower = body_text.lower()
        for kw in block_content_keywords:
            if kw in body_lower:
                log.warning(f"  🤖 BLOCK detected via content keyword: '{kw}'")
                return True

        if len(body_text.strip()) < 200:
            log.warning(f"  ⚠️ Page body too short ({len(body_text)} chars) — possibly blocked.")
            return True

        return False
    except Exception as e:
        log.warning(f"  ⚠️ Block-check exception (non-critical): {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 8: MASTER EXTRACTION WITH OPERATION CANCELED PROTECTION
# ═══════════════════════════════════════════════════════════════════════

async def extract_product_data(page: Page, url: str, browser: Browser) -> dict:
    """
    Navigate to product URL and extract price data.
    Handles: Timeout, Operation Canceled, 404, Bot Block.
    Tries 3 methods: DOM Strikethrough → CSS Selectors → Text Parsing.
    """
    log.info(f"  🌐 Opening: {url[:80]}...")

    for scrape_attempt in range(1, MAX_SCRAPE_RETRIES + 1):
        try:
            if scrape_attempt > 1:
                log.info(f"  🔄 Retry {scrape_attempt}/{MAX_SCRAPE_RETRIES} with fresh context...")
                await asyncio.sleep(random.uniform(8.0, 15.0))
                fresh_context = await create_stealth_context(browser)
                page = await fresh_context.new_page()
                if STEALTH_AVAILABLE and stealth_async:
                    try:
                        await stealth_async(page)
                    except Exception:
                        pass

            nav_success = False
            response = None

            for wait_strategy in ["domcontentloaded", "load"]:
                try:
                    response = await page.goto(
                        url,
                        referer="https://www.google.com/",
                        wait_until=wait_strategy,
                        timeout=PAGE_LOAD_TIMEOUT
                    )
                    nav_success = True
                    break

                except Exception as nav_err:
                    err_msg = str(nav_err).lower()

                    if any(k in err_msg for k in ["timeout", "cancel", "abort", "net::err"]):
                        log.warning(f"  ⏰ Navigation '{wait_strategy}' failed ({err_msg[:50]}). "
                                    f"Checking if page partially loaded...")
                        try:
                            body_check = await page.inner_text("body")
                            if len(body_check) > 500:
                                log.info(f"  ⚡ Page partially loaded ({len(body_check)} chars). Proceeding.")
                                nav_success = True
                                break
                        except:
                            pass
                    else:
                        log.error(f"  ❌ Unexpected nav error: {nav_err}")
                        raise nav_err

            if not nav_success:
                log.error(f"  ❌ All navigation strategies failed. Skipping this product.")
                return {}

            # Check HTTP status for 404 / 410 (deleted product)
            if response and response.status in [404, 410]:
                log.error(f"  ❌ HTTP {response.status} — Product page not found on Flipkart. Skipping.")
                return {}

            await asyncio.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

            # Check redirect to login/error
            current_url = page.url
            if "login" in current_url or "error" in current_url.lower():
                log.warning(f"  ⚠️ Redirected to: {current_url[:60]}")
                return {}

            # Check for 404 in page title/content
            try:
                page_title = (await page.title()).lower()
                if "page not found" in page_title or "doesn't exist" in page_title or "404" in page_title:
                    log.error(f"  ❌ 404 in page title: '{page_title}'. Skipping.")
                    return {}
            except:
                pass

            # Check for bot block / captcha
            if await is_captcha_or_blocked(page):
                log.warning("  🤖 Bot block detected!")
                if scrape_attempt < MAX_SCRAPE_RETRIES:
                    log.info(f"  💤 Waiting 20s before retry with fresh context...")
                    await asyncio.sleep(random.uniform(15.0, 25.0))
                    continue
                else:
                    log.error(f"  ❌ Still blocked after {MAX_SCRAPE_RETRIES} retries. Giving up.")
                    return {}

            # Inner retry loop for extraction
            data = {}
            method = ""

            for attempt in range(1, 16):
                await page.evaluate("window.scrollBy(0, 500)")
                await asyncio.sleep(random.uniform(1.0, 2.0))

                data_try = await extract_with_dom_strikethrough(page)
                if data_try.get("sellingPrice"):
                    data = data_try
                    method = "DOM_strikethrough"
                    break

                css_data = await extract_with_css_selectors(page)
                if css_data.get("sellingPrice"):
                    data = css_data
                    method = "CSS_selectors"
                    break

                text_data = await extract_with_text_parsing(page)
                if text_data.get("sellingPrice"):
                    data = text_data
                    method = "text_parsing"
                    break

                log.warning(f"  ⏳ Attempt {attempt}/15: Price not found. Retrying...")
                await asyncio.sleep(random.uniform(2.0, 4.0))

            if data.get("sellingPrice"):
                log.info(
                    f"  ✅ [{method}] "
                    f"₹{int(data['sellingPrice']):,} | "
                    f"MRP:₹{int(data['originalPrice'] or 0):,} | "
                    f"Disc:{data.get('discountPercent') or 'N/A'}% | "
                    f"⭐{data.get('rating') or 'N/A'} | "
                    f"Rev:{data.get('reviews') or 'N/A'}"
                )
                return data
            else:
                log.error("  ❌ All extraction methods failed for this product.")
                return {}

        except Exception as e:
            err_str = str(e).lower()
            if any(k in err_str for k in ["timeout", "timed out", "cancel", "abort"]):
                log.warning(f"  ⏰ Operation Canceled / Timeout (attempt {scrape_attempt}): {e}")
                if scrape_attempt < MAX_SCRAPE_RETRIES:
                    continue
                else:
                    log.error(f"  ❌ Giving up after {MAX_SCRAPE_RETRIES} retries.")
                    return {}
            else:
                log.error(f"  ❌ Unexpected scrape error: {e}")
                return {}

    return {}


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 9: PRICE VALIDATION
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


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 10: BUILD SUPABASE UPDATE PAYLOAD
# ═══════════════════════════════════════════════════════════════════════

def find_real_column_name(all_cols: list, candidates: list) -> Optional[str]:
    """Case-insensitive column name matcher."""
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

    price_col    = find_real_column_name(all_cols, ["Price", "Current Price", "price", "current_price", "discounted_price"])
    mrp_col      = find_real_column_name(all_cols, ["Original Price", "Original Price-2", "original_price", "mrp"])
    discount_col = find_real_column_name(all_cols, ["Discount", "discount", "discount_percent"])
    rating_col   = find_real_column_name(all_cols, ["Rating", "rating", "Ratings and Reviews", "Rating and Reviews"])
    reviews_col  = find_real_column_name(all_cols, ["Number of Reviews", "Reviews", "reviews", "review_count"])

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
#  SECTION 11: HUMAN-LIKE BEHAVIOR & BROWSER SETUP
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
    try:
        scroll_height = await page.evaluate("document.body.scrollHeight")
        current = 0
        while current < min(scroll_height * 0.6, 2000):
            scroll_amount = random.randint(100, 300)
            current += scroll_amount
            await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            await asyncio.sleep(random.uniform(0.1, 0.4))
    except:
        pass

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
                ctx.fillText = function(...fargs) { return originalFillText(...fargs); };
            }
            return ctx;
        };
    """)
    return context


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 12: MINI AGENT RUNNER
# ═══════════════════════════════════════════════════════════════════════

async def run_mini_agent(agent_config: dict, sb: Client, browser: Browser):
    agent_id   = agent_config["id"]
    agent_name = agent_config["name"]
    table      = agent_config["table"]
    label      = f"Agent-{agent_id:02d} [{agent_name.upper()}]"

    log.info(f"\n{'='*60}")
    log.info(f"  {label} STARTING {'(TEST MODE - 20 items)' if TEST_MODE else ''}")
    log.info(f"{'='*60}")

    products = fetch_category_products(sb, table, limit=10)
    if not products:
        log.warning(f"  [{label}] No products found in '{table}'.")
        return {"agent": label, "updated": 0, "failed": 0, "total": 0}

    context = await create_stealth_context(browser)
    page = await context.new_page()

    if STEALTH_AVAILABLE and stealth_async:
        try:
            await stealth_async(page)
            log.info("  🛡️ playwright-stealth applied.")
        except Exception as e:
            log.warning(f"  ⚠️ Stealth apply failed (non-critical): {e}")

    updated = 0
    failed  = 0

    for i, product in enumerate(products, 1):
        product_id = product.get("id")

        name_candidates = ["Product Name-2", "Product Name", "name", "Brand Name", "title"]
        product_name = None
        for nc in name_candidates:
            for key, value in product.items():
                if key.lower() == nc.lower() and value:
                    product_name = str(value).strip()
                    break
            if product_name:
                break
        if not product_name:
            product_name = "Unknown"

        log.info(f"\n  [{label}] ({i}/{len(products)}) {product_name[:50]}...")

        # Resolve URL (with truncated URL fix + search fallback)
        url = await resolve_product_url(page, product, sb, table, product_id)

        if not url:
            log.warning(f"  [{label}] No valid URL. Skipping.")
            failed += 1
            continue

        await human_mouse_move(page)

        extracted = await extract_product_data(page, url, browser)

        if not extracted or not extracted.get("sellingPrice"):
            log.warning(f"  [{label}] No price extracted. Skipping.")
            failed += 1
            continue

        all_cols = list(product.keys())
        update_data, validated = build_update_payload(product, extracted, all_cols)

        if not update_data:
            log.warning(f"  [{label}] No matching DB columns to update. Skipping.")
            failed += 1
            continue

        success = update_product(sb, table, product_id, update_data)

        if success:
            updated += 1
            log.info(
                f"  [{label}] ✅ DB Updated: "
                f"₹{int(validated['final_selling']):,} | "
                f"MRP:₹{int(validated['valid_original'] or 0):,} | "
                f"{validated['discount_str'] or 'No discount'}"
            )
        else:
            failed += 1

        if i < len(products):
            delay = random.uniform(4.0, 8.0)
            log.info(f"  [{label}] ⏳ Cooling down {delay:.1f}s before next product...")
            await asyncio.sleep(delay)

    await context.close()
    log.info(f"\n  [{label}] DONE: {updated} updated | {failed} failed | {len(products)} total")
    return {"agent": label, "updated": updated, "failed": failed, "total": len(products)}


# ═══════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════

async def main():
    log.info("╔══════════════════════════════════════════════════════════════╗")
    if TEST_MODE:
        log.info("║  PRICEYAAR SUPER AGENT v8.2 - SINGLE AGENT TEST MODE        ║")
        log.info("║  🎯 TARGET: earbuds table (20 products)                      ║")
    else:
        log.info("║  PRICEYAAR SUPER AGENT v8.2 - FULL MODE (All 10 Agents)     ║")
    log.info("║  Python + Playwright + DOM Strikethrough + URL Recovery       ║")
    log.info("╚══════════════════════════════════════════════════════════════╝")
    log.info(f"  Active agents  : {[a['name'] for a in AGENTS]}")
    log.info(f"  Batch size     : {TEST_BATCH_SIZE if TEST_MODE else 10} products per agent")
    log.info(f"  Stealth module : {'✅ Available' if STEALTH_AVAILABLE else '⚠️ Not available (manual evasions active)'}")

    sb = get_supabase()
    log.info(f"✅ Supabase connected: {SUPABASE_URL[:40]}...")

    async with async_playwright() as playwright:
        browser = await setup_browser(playwright)
        log.info(f"🌐 Browser launched (headless={HEADLESS})")

        results = []
        for agent in AGENTS:
            result = await run_mini_agent(agent, sb, browser)
            results.append(result)

            if not TEST_MODE and agent["id"] < len(ALL_AGENTS):
                rest = random.uniform(5.0, 10.0)
                log.info(f"\n💤 Resting {rest:.0f}s before next agent...")
                await asyncio.sleep(rest)

        await browser.close()

    log.info(f"\n{'='*60}")
    log.info("  FINAL REPORT")
    log.info(f"{'='*60}")
    total_updated  = 0
    total_failed   = 0
    total_products = 0
    for r in results:
        log.info(f"  {r['agent']}: {r['updated']} updated | {r['failed']} failed | {r['total']} total")
        total_updated  += r["updated"]
        total_failed   += r["failed"]
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

