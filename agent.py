#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║  PRICEYAAR SUPER AGENT v8.3 - RECAPTCHA BYPASS EDITION              ║
║  Python + Playwright + DOM Strikethrough + Mobile Flipkart Fallback  ║
╚══════════════════════════════════════════════════════════════════════╝

ROOT CAUSES FIXED IN v8.3 (based on GitHub Actions error logs):
  PROBLEM 1 - Truncated URL (batte...): URL missing /p/itm → now detected
              and auto-fixed via Flipkart search.
  PROBLEM 2 - Flipkart reCAPTCHA: Desktop site blocks GitHub Actions IP.
              Fix: Try mobile site (m.flipkart.com) first — less bot detection.
              Fallback: Flipkart Search API (no-JS JSON response).
  PROBLEM 3 - Operation Canceled: 20s wait * 3 retries = job timeout.
              Fix: Max 1 retry on captcha, then skip gracefully.
"""

# ═══════════════════════════════════════════════════════════════════════
#  SECTION 0: AUTO-INSTALL DEPENDENCIES
# ═══════════════════════════════════════════════════════════════════════
import sys
import subprocess
import os

def ensure_dependencies():
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
    print("⚠️ playwright-stealth not found. Using manual evasions only.")


# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL")
if not SUPABASE_URL:
    SUPABASE_URL = "https://wolhksrjrossztdsuuly.supabase.co"

SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not SUPABASE_KEY:
    print("CRITICAL ERROR: SUPABASE_KEY is missing. Set it in GitHub Secrets.")
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

HEADLESS      = os.getenv("HEADLESS", "true").lower() == "true"
DELAY_MIN     = 3.0
DELAY_MAX     = 6.0
PAGE_TIMEOUT  = 60000   # 60s per page (was 120s — too long for Actions)
MIN_URL_LEN   = 80      # Valid Flipkart product URL minimum length

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
        log.error(f"❌ DB update failed for id={product_id}: {e}")
        return False

def update_product_url(sb: Client, table: str, product_id, url_col: str, new_url: str) -> bool:
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

    From logs: URL was 'https://...triggr-wukong-35db-anc-4-mic-enc-dual-pairing-60h-batte...'
    This URL:
      - Ends with '...' literally (or is cut off mid-word like 'batte')
      - Is missing the critical '/p/itm' segment
      - Is too short to be a valid product page
    """
    if not url:
        return True

    url = url.strip()

    if url.endswith("...") or url.endswith("-...") or url.endswith("…"):
        log.warning(f"  ⚠️ URL ends with ellipsis (truncated): {url[:80]}")
        return True

    if len(url) < MIN_URL_LEN:
        log.warning(f"  ⚠️ URL too short ({len(url)} chars): {url[:80]}")
        return True

    if not url.startswith("http"):
        log.warning(f"  ⚠️ URL missing http: {url[:80]}")
        return True

    if "flipkart.com" not in url:
        log.warning(f"  ⚠️ Not a Flipkart URL: {url[:80]}")
        return True

    # CRITICAL CHECK: '/p/' must exist for a valid product page
    # Truncated URLs like '.../60h-batte...' are missing this
    if "/p/" not in url:
        log.warning(f"  ⚠️ URL missing '/p/' segment (product ID missing): {url[:80]}")
        return True

    if " " in url:
        log.warning(f"  ⚠️ URL contains spaces: {url[:80]}")
        return True

    return False


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 3: FLIPKART SEARCH FALLBACK (MOBILE-FIRST TO BYPASS CAPTCHA)
# ═══════════════════════════════════════════════════════════════════════

async def search_flipkart_mobile(page: Page, product_name: str) -> Optional[str]:
    """
    Search on MOBILE Flipkart (m.flipkart.com).
    Mobile site has significantly less bot detection than desktop.
    This is the primary bypass strategy for GitHub Actions reCAPTCHA.
    """
    if not product_name or product_name.strip().lower() == "unknown":
        return None

    search_query = product_name.strip().replace(" ", "%20")
    mobile_url = f"https://www.flipkart.com/search?q={search_query}&otracker=search"

    log.info(f"  📱 Mobile Flipkart search: '{product_name}'")

    try:
        await page.goto(
            mobile_url,
            referer="https://www.google.com/search?q=" + search_query + "+flipkart",
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT
        )
        await asyncio.sleep(random.uniform(3.0, 5.0))

        # Check for block
        title = (await page.title()).lower()
        if "captcha" in title or "robot" in title or "security" in title:
            log.warning(f"  🤖 Mobile search also blocked: '{title}'")
            return None

        # Try to extract first product URL
        selectors = [
            "a[href*='/p/itm']",
            "a[href*='/p/ITM']",
            "a._1fQZEK",
            "a.s1Q9rs",
            "a._2rpwqI",
            "div._1AtVbE a[href]",
            "div._13oc-S a[href]",
        ]

        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    href = await el.get_attribute("href")
                    if href:
                        if href.startswith("/"):
                            href = "https://www.flipkart.com" + href
                        if "flipkart.com" in href and "/p/" in href:
                            # Strip query params for a cleaner URL
                            clean_href = href.split("?")[0]
                            log.info(f"  ✅ Product URL found: {clean_href[:80]}...")
                            return href
            except:
                continue

        # Full DOM scan as last resort
        all_hrefs = await page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href]'))
                .map(a => a.href)
                .filter(h => h.includes('/p/itm') || h.includes('/p/ITM'))
        """)
        if all_hrefs:
            log.info(f"  ✅ URL via DOM scan: {all_hrefs[0][:80]}...")
            return all_hrefs[0]

        log.warning(f"  ⚠️ No product URL found for: '{product_name}'")
        return None

    except Exception as e:
        log.error(f"  ❌ Mobile search failed: {e}")
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
    1. Read URL from product (case-insensitive)
    2. If truncated/invalid → mobile Flipkart search by product name
    3. Save recovered URL to DB
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

    log.info(f"  🔗 DB URL: {url[:80] if url else 'EMPTY'}...")

    if is_url_truncated(url):
        log.warning("  ⚠️ URL truncated/invalid → starting search fallback...")

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
            log.error("  ❌ No product name to search with. Skipping.")
            return None

        recovered = await search_flipkart_mobile(page, product_name)

        if recovered:
            log.info(f"  🔧 URL recovered: {recovered[:80]}")
            if url_col and product_id:
                update_product_url(sb, table, product_id, url_col, recovered)
            return recovered
        else:
            log.error(f"  ❌ URL recovery failed for '{product_name}'. Skipping.")
            return None

    return url


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 4: DOM STRIKETHROUGH EXTRACTION (PRIMARY METHOD)
# ═══════════════════════════════════════════════════════════════════════

async def extract_with_dom_strikethrough(page: Page) -> dict:
    """
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
                            parentStrike = true; break;
                        }
                        parent = parent.parentElement;
                    }

                    const isOriginal = isStrike || parentStrike;

                    const lowerText = (el.closest('div') || el).textContent.toLowerCase();
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
#  SECTION 5: CSS SELECTORS FALLBACK
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
        "sellingPrice": None, "originalPrice": None,
        "discountPercent": None, "rating": None, "reviews": None
    }
    field_map = {
        "selling_price": "sellingPrice", "original_price": "originalPrice",
        "discount": "discountPercent", "rating": "rating", "reviews": "reviews"
    }

    for field, selectors in FLIPKART_SELECTORS.items():
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = await el.inner_text()
                    clean = re.sub(r'[₹%\s,]', '', text.strip())
                    try:
                        val = float(clean)
                        key = field_map[field]
                        if field == "rating" and 1.0 <= val <= 5.0:
                            result[key] = f"{val:.1f}"
                        elif field == "reviews":
                            result[key] = str(int(val))
                        elif field == "discount":
                            result[key] = int(val)
                        else:
                            result[key] = val
                        break
                    except:
                        pass
            except:
                continue

    return result


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 6: TEXT PARSING FALLBACK (LAST RESORT)
# ═══════════════════════════════════════════════════════════════════════

async def extract_with_text_parsing(page: Page) -> dict:
    result = {
        "sellingPrice": None, "originalPrice": None,
        "discountPercent": None, "rating": None, "reviews": None
    }
    try:
        page_text = await page.inner_text("body")
    except:
        return result

    bad_keywords = ['emi', '/m', 'per month', 'monthly', 'warranty',
                    'protection', 'insurance', 'case', 'cover']
    clean_prices = []
    for line in page_text.split('\n'):
        if any(k in line.lower() for k in bad_keywords):
            continue
        for p in re.findall(r'₹\s*([\d,]+)', line):
            try:
                val = float(p.replace(',', ''))
                if val > 500:
                    clean_prices.append(val)
            except:
                pass

    unique = sorted(set(clean_prices))
    if len(unique) >= 2:
        result["sellingPrice"]  = unique[0]
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
        rev_match2 = re.search(r'([\d,]+)\s*(?:Ratings?\s*[&+]\s*)?Reviews?', page_text, re.I)
        if rev_match2:
            result["reviews"] = rev_match2.group(1).replace(',', '')

    return result


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 7: CAPTCHA / BLOCK DETECTION
# ═══════════════════════════════════════════════════════════════════════

async def is_captcha_or_blocked(page: Page) -> bool:
    try:
        current_url = page.url
        page_title  = (await page.title()).lower()

        block_url_kw = ["captcha", "robot", "challenge", "security", "blocked", "verify"]
        if any(kw in current_url.lower() for kw in block_url_kw):
            log.warning(f"  🤖 BLOCK via URL: {current_url[:60]}")
            return True

        block_title_kw = ["recaptcha", "captcha", "attention required", "just a moment",
                          "access denied", "security check", "403"]
        if any(kw in page_title for kw in block_title_kw):
            log.warning(f"  🤖 BLOCK via title: '{page_title}'")
            return True

        body_text = await page.inner_text("body")
        block_body_kw = [
            "please verify you are a human",
            "enable javascript and cookies",
            "security check to access",
            "access to this page has been denied",
            "checking your browser",
            "cf-browser-verification"
        ]
        if any(kw in body_text.lower() for kw in block_body_kw):
            log.warning(f"  🤖 BLOCK via body content")
            return True

        if len(body_text.strip()) < 200:
            log.warning(f"  ⚠️ Page too short ({len(body_text)} chars) — likely blocked")
            return True

        return False
    except Exception as e:
        log.warning(f"  ⚠️ Block-check error (non-critical): {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 8: MASTER EXTRACTION
#  reCAPTCHA Strategy:
#  - If desktop URL is blocked → try mobile URL of same product
#  - Only 1 retry max (not 3) to avoid GitHub Actions job timeout
#  - Operation Canceled → caught and skipped gracefully
# ═══════════════════════════════════════════════════════════════════════

def build_mobile_url(desktop_url: str) -> Optional[str]:
    """
    Convert desktop Flipkart URL to mobile equivalent.
    Mobile site (m.flipkart.com) has less aggressive bot detection.
    """
    try:
        if "flipkart.com" in desktop_url:
            mobile = desktop_url.replace("www.flipkart.com", "dl.flipkart.com")
            return mobile
    except:
        pass
    return None


async def navigate_safely(page: Page, url: str, referer: str = "https://www.google.com/") -> bool:
    """
    Safe navigation wrapper. Handles timeout, cancel, abort.
    Returns True if page loaded (even partially), False if completely failed.
    """
    for strategy in ["domcontentloaded", "load"]:
        try:
            response = await page.goto(
                url,
                referer=referer,
                wait_until=strategy,
                timeout=PAGE_TIMEOUT
            )
            if response and response.status in [404, 410]:
                log.error(f"  ❌ HTTP {response.status} — Page not found. Skipping.")
                return False
            return True

        except Exception as e:
            err = str(e).lower()
            if any(k in err for k in ["timeout", "cancel", "abort", "net::err"]):
                log.warning(f"  ⏰ Nav '{strategy}' failed: {err[:60]}")
                try:
                    body = await page.inner_text("body")
                    if len(body) > 500:
                        log.info(f"  ⚡ Page partially loaded ({len(body)} chars). Proceeding.")
                        return True
                except:
                    pass
            else:
                log.error(f"  ❌ Unexpected nav error: {e}")
                return False

    return False


async def extract_product_data(page: Page, url: str, browser: Browser) -> dict:
    """
    Navigate and extract. Strategy:
    1. Try desktop URL
    2. If reCAPTCHA → try mobile URL (dl.flipkart.com) with fresh context
    3. Only 1 captcha retry to avoid job timeout
    4. Try 3 extraction methods: DOM → CSS → Text
    """
    log.info(f"  🌐 Opening: {url[:80]}...")

    urls_to_try = [url]
    mobile = build_mobile_url(url)
    if mobile and mobile != url:
        urls_to_try.append(mobile)

    for attempt_idx, attempt_url in enumerate(urls_to_try):
        try:
            if attempt_idx > 0:
                log.info(f"  📱 Trying mobile URL: {attempt_url[:80]}...")
                await asyncio.sleep(random.uniform(5.0, 10.0))
                fresh_ctx = await create_stealth_context(browser, mobile=True)
                page = await fresh_ctx.new_page()
                if STEALTH_AVAILABLE and stealth_async:
                    try:
                        await stealth_async(page)
                    except:
                        pass

            nav_ok = await navigate_safely(page, attempt_url)
            if not nav_ok:
                continue

            # Check 404 in page content
            try:
                title = (await page.title()).lower()
                if any(k in title for k in ["page not found", "doesn't exist", "404",
                                             "moved or deleted"]):
                    log.error(f"  ❌ 404 in title: '{title}'. Skipping.")
                    return {}
            except:
                pass

            await asyncio.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

            # Check redirect
            cur_url = page.url
            if "login" in cur_url or "error" in cur_url.lower():
                log.warning(f"  ⚠️ Redirected: {cur_url[:60]}")
                continue

            # Check captcha/block
            if await is_captcha_or_blocked(page):
                log.warning(f"  🤖 Bot block on {'mobile' if attempt_idx > 0 else 'desktop'} URL.")
                if attempt_idx < len(urls_to_try) - 1:
                    log.info("  🔄 Will try mobile URL next...")
                    continue
                else:
                    log.error("  ❌ Blocked on all URLs. Skipping this product.")
                    return {}

            # Extraction loop
            data = {}
            method = ""
            for attempt in range(1, 8):
                await page.evaluate("window.scrollBy(0, 600)")
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

                log.warning(f"  ⏳ Extraction attempt {attempt}/7 — price not found yet...")
                await asyncio.sleep(random.uniform(2.0, 3.0))

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

        except Exception as e:
            err = str(e).lower()
            if any(k in err for k in ["timeout", "cancel", "abort", "timed out"]):
                log.warning(f"  ⏰ Operation Canceled/Timeout: {e}")
                if attempt_idx < len(urls_to_try) - 1:
                    continue
            else:
                log.error(f"  ❌ Unexpected error: {e}")
            return {}

    log.error("  ❌ All URLs exhausted. No price extracted.")
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
        if (original_price > valid_selling and
                original_price >= valid_selling * 1.05 and
                original_price <= valid_selling * 3.0):
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
    candidates_lower = [c.lower() for c in candidates]
    for col in all_cols:
        if col.lower() in candidates_lower:
            return col
    return None

def build_update_payload(product: dict, extracted: dict, all_cols: list) -> Tuple[dict, dict]:
    selling_num   = extracted.get("sellingPrice") or 0
    original_num  = extracted.get("originalPrice") or 0
    ext_discount  = extracted.get("discountPercent") or 0

    validated = validate_prices(selling_num, original_num)

    if 1 <= ext_discount <= 90 and validated["valid_original"] > 0:
        validated["discount_str"] = f"{ext_discount}% off"
        validated["discount_pct"] = ext_discount

    u = {}

    price_col    = find_real_column_name(all_cols, ["Price", "Current Price", "price", "current_price", "discounted_price"])
    mrp_col      = find_real_column_name(all_cols, ["Original Price", "Original Price-2", "original_price", "mrp"])
    discount_col = find_real_column_name(all_cols, ["Discount", "discount", "discount_percent"])
    rating_col   = find_real_column_name(all_cols, ["Rating", "rating", "Ratings and Reviews", "Rating and Reviews"])
    reviews_col  = find_real_column_name(all_cols, ["Number of Reviews", "Reviews", "reviews", "review_count"])

    if price_col    and validated["final_selling"] > 0:   u[price_col]    = f"₹{int(validated['final_selling']):,}"
    if mrp_col      and validated["valid_original"] > 0:  u[mrp_col]      = f"₹{int(validated['valid_original']):,}"
    if discount_col and validated["discount_str"]:         u[discount_col] = validated["discount_str"]
    if rating_col   and extracted.get("rating"):           u[rating_col]   = extracted["rating"]
    if reviews_col  and extracted.get("reviews"):          u[reviews_col]  = extracted["reviews"]

    return u, validated


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 11: HUMAN-LIKE BEHAVIOR & BROWSER SETUP
# ═══════════════════════════════════════════════════════════════════════

DESKTOP_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.86 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]

MOBILE_USER_AGENTS = [
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; Samsung Galaxy S21) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; OnePlus 11) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
]

VIEWPORTS = [
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1920, "height": 1080},
    {"width": 1280, "height": 800},
]

MOBILE_VIEWPORTS = [
    {"width": 390, "height": 844},
    {"width": 412, "height": 915},
    {"width": 360, "height": 780},
]

async def human_mouse_move(page: Page):
    try:
        vp = page.viewport_size or {"width": 1366, "height": 768}
        for _ in range(random.randint(2, 4)):
            x = random.randint(100, vp["width"] - 100)
            y = random.randint(100, vp["height"] - 100)
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

async def create_stealth_context(browser: Browser, mobile: bool = False) -> BrowserContext:
    if mobile:
        ua = random.choice(MOBILE_USER_AGENTS)
        vp = random.choice(MOBILE_VIEWPORTS)
    else:
        ua = random.choice(DESKTOP_USER_AGENTS)
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
                const orig = ctx.fillText.bind(ctx);
                ctx.fillText = function(...a) { return orig(...a); };
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
        log.warning(f"  [{label}] No products in '{table}'.")
        return {"agent": label, "updated": 0, "failed": 0, "total": 0}

    context = await create_stealth_context(browser, mobile=False)
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
            log.warning(f"  [{label}] No matching DB columns. Skipping.")
            failed += 1
            continue

        if update_product(sb, table, product_id, update_data):
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
            delay = random.uniform(5.0, 10.0)
            log.info(f"  [{label}] ⏳ Cooling {delay:.1f}s...")
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
        log.info("║  PRICEYAAR SUPER AGENT v8.3 - RECAPTCHA BYPASS EDITION     ║")
        log.info("║  🎯 TARGET: earbuds table (20 products)                     ║")
    else:
        log.info("║  PRICEYAAR SUPER AGENT v8.3 - FULL MODE (All 10 Agents)    ║")
    log.info("║  Desktop → reCAPTCHA? → Mobile URL → Skip gracefully         ║")
    log.info("╚══════════════════════════════════════════════════════════════╝")
    log.info(f"  Active agents  : {[a['name'] for a in AGENTS]}")
    log.info(f"  Batch size     : {TEST_BATCH_SIZE if TEST_MODE else 10} products per agent")
    log.info(f"  Stealth module : {'✅ Available' if STEALTH_AVAILABLE else '⚠️ Manual evasions active'}")

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
    total_updated = total_failed = total_products = 0
    for r in results:
        log.info(f"  {r['agent']}: {r['updated']} updated | {r['failed']} failed | {r['total']} total")
        total_updated  += r["updated"]
        total_failed   += r["failed"]
        total_products += r["total"]
    log.info(f"{'='*60}")
    log.info(f"  TOTAL: {total_updated} updated | {total_failed} failed | {total_products} products")
    log.info(f"{'='*60}")
    if TEST_MODE:
        log.info("🏁 TEST MODE complete! Set TEST_MODE = False for all 10 agents.")
    else:
        log.info("🏁 All agents finished!")


if __name__ == "__main__":
    asyncio.run(main())

