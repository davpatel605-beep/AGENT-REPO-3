#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║  PRICEYAAR SUPER AGENT v8.1 - FULL LENGTH & ANTI-BOT EDITION         ║
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
import json
import re
import random
import logging
from datetime import datetime
from typing import Optional, Dict, List, Tuple

from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from supabase import create_client, Client

# -----------------------------------------------------------------------
# FIX 1: SAFE STEALTH IMPORT FOR GITHUB ACTIONS
# अगर stealth_async इम्पोर्ट फेल होता है, तो कोड क्रैश नहीं होगा।
# -----------------------------------------------------------------------
try:
    from playwright_stealth import stealth_async
    STEALTH_AVAILABLE = True
except ImportError:
    stealth_async = None
    STEALTH_AVAILABLE = False
    print("⚠️ WARNING: playwright-stealth module not found or import failed. Using manual evasions only.")


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
PAGE_LOAD_TIMEOUT = 120000  # 120 seconds
MAX_SCRAPE_RETRIES = 3
MIN_URL_LENGTH = 60

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s", datefmt="%H:%M:%S")
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

def update_product_url(sb: Client, table: str, product_id, url_col: str, new_url: str) -> bool:
    try:
        sb.table(table).update({url_col: new_url}).eq("id", product_id).execute()
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 2: TRUNCATED URL DETECTION & FLIPKART SEARCH FALLBACK
# ═══════════════════════════════════════════════════════════════════════

def is_url_truncated(url: str) -> bool:
    if not url: return True
    url = url.strip()
    if url.endswith("...") or url.endswith("-...") or url.endswith("…"): return True
    if len(url) < MIN_URL_LENGTH: return True
    if not url.startswith("http"): return True
    if "flipkart.com" not in url: return True
    if "/p/" not in url: return True
    if " " in url: return True
    return False

async def search_flipkart_for_url(page: Page, product_name: str) -> Optional[str]:
    if not product_name or product_name == "Unknown":
        return None
    search_query = product_name.strip().replace(" ", "+")
    search_url = f"https://www.flipkart.com/search?q={search_query}"
    log.info(f"  🔍 Searching Flipkart for: '{product_name}'")

    try:
        await page.goto(search_url, referer="https://www.google.com/", wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(random.uniform(2.5, 5.0))

        product_link_selectors = ["a[href*='/p/itm']", "a._1fQZEK", "a.s1Q9rs", "div._1AtVbE a"]
        for sel in product_link_selectors:
            try:
                links = page.locator(sel)
                if await links.count() > 0:
                    href = await links.first.get_attribute("href")
                    if href:
                        if href.startswith("/"): href = "https://www.flipkart.com" + href
                        if "flipkart.com" in href and "/p/" in href:
                            return href
            except:
                continue
    except Exception as e:
        log.error(f"  ❌ Search failed: {e}")
    return None

async def resolve_product_url(page: Page, product: dict, sb: Client, table: str, product_id) -> Optional[str]:
    url_col_candidates = ["Product Link", "product_url", "link", "Product URL", "url"]
    url = None
    url_col = None
    for key, value in product.items():
        if key.lower() in [c.lower() for c in url_col_candidates] and value:
            url = str(value)
            url_col = key
            break

    if is_url_truncated(url):
        log.warning(f"  ⚠️ URL Invalid. Attempting Search fallback...")
        name = product.get("Product Name-2") or product.get("Product Name") or product.get("name")
        recovered_url = await search_flipkart_for_url(page, name)
        if recovered_url:
            log.info(f"  🔧 URL recovered: {recovered_url[:80]}...")
            if url_col and product_id:
                update_product_url(sb, table, product_id, url_col, recovered_url)
            return recovered_url
        return None
    return url


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 3: EXTRACTION LOGIC (DOM, CSS, TEXT)
# ═══════════════════════════════════════════════════════════════════════

async def extract_with_dom_strikethrough(page: Page) -> dict:
    return await page.evaluate("""
        () => {
            const result = { sellingPrice: null, originalPrice: null };
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

                    let isOriginal = style.textDecoration.includes('line-through') || el.closest('[style*="line-through"]') !== null;
                    let parent = el.parentElement;
                    for (let i = 0; i < 3 && parent; i++) {
                        if (window.getComputedStyle(parent).textDecoration.includes('line-through')) {
                            isOriginal = true; break;
                        }
                        parent = parent.parentElement;
                    }
                    rupeeElements.push({ num, isOriginal });
                }
            }

            if (rupeeElements.length > 0) {
                const originals = rupeeElements.filter(e => e.isOriginal).map(e => e.num);
                const sellings = rupeeElements.filter(e => !e.isOriginal).map(e => e.num);
                if (sellings.length > 0) result.sellingPrice = Math.min(...sellings);
                if (originals.length > 0) result.originalPrice = Math.max(...originals);
            }
            return result;
        }
    """)

async def extract_with_css_selectors(page: Page) -> dict:
    result = {"sellingPrice": None, "originalPrice": None}
    sell_sels = ["div._30jeq3._16Jk6d", "div.Nx9bqj", "div._30jeq3"]
    mrp_sels = ["div._3I9_wc._2p6lqe", "div.yRaY8j", "div._3I9_wc"]
    
    for sel in sell_sels:
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                text = await el.inner_text()
                result["sellingPrice"] = int(re.sub(r'[^0-9]', '', text))
                break
        except: pass
        
    for sel in mrp_sels:
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                text = await el.inner_text()
                result["originalPrice"] = int(re.sub(r'[^0-9]', '', text))
                break
        except: pass
        
    return result


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 4: MASTER EXTRACTION WITH 404 & CANCELLATION PROTECTION
# ═══════════════════════════════════════════════════════════════════════

async def extract_product_data(page: Page, url: str) -> dict:
    log.info(f"  🌐 Opening: {url[:80]}...")
    
    # FIX 2: ROBUST NAVIGATION TRY-CATCH
    nav_success = False
    for wait_strategy in ["domcontentloaded", "load"]:
        try:
            response = await page.goto(
                url, 
                referer="https://www.google.com/", 
                wait_until=wait_strategy, 
                timeout=PAGE_LOAD_TIMEOUT
            )
            
            # Check for 404 Not Found Page Deleted
            if response and response.status in [404, 410]:
                log.error(f"  ❌ Page not found (404 Error) on Flipkart. Skipping.")
                return {}
                
            nav_success = True
            break
        except Exception as nav_err:
            err_msg = str(nav_err).lower()
            if "timeout" in err_msg or "cancel" in err_msg or "abort" in err_msg:
                log.warning(f"  ⏰ Nav error '{wait_strategy}': {err_msg[:40]}. Checking if page loaded anyway...")
                try:
                    # Check if body is there despite the error
                    body_text = await page.inner_text("body")
                    if len(body_text) > 500:
                        nav_success = True
                        break
                except:
                    pass

    if not nav_success:
        log.error(f"  ❌ All navigation failed (Operation Canceled/Timeout). Skipping.")
        return {}

    await asyncio.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    data = {}
    for attempt in range(1, 4):
        await page.evaluate("window.scrollBy(0, 500)")
        await asyncio.sleep(1)

        # 1. Try DOM Strikethrough
        data = await extract_with_dom_strikethrough(page)
        if data.get("sellingPrice"): break

        # 2. Try CSS Selectors
        css_data = await extract_with_css_selectors(page)
        if css_data.get("sellingPrice"):
            data = css_data
            break

        await asyncio.sleep(2)

    if data.get("sellingPrice"):
        log.info(f"  ✅ Extracted: ₹{data['sellingPrice']} | MRP: ₹{data.get('originalPrice') or 0}")
        return data
    else:
        log.error(f"  ❌ Failed to extract price data.")
        return {}


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 5: HUMAN-LIKE BEHAVIOR & BROWSER SETUP
# ═══════════════════════════════════════════════════════════════════════

async def create_stealth_context(browser: Browser) -> BrowserContext:
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        viewport={"width": 1366, "height": 768},
        locale="en-IN",
        extra_http_headers={"Accept-Language": "en-IN,en;q=0.9"}
    )
    
    # MANUAL EVASIONS (Will save us if stealth_async fails)
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        window.chrome = { runtime: {} };
    """)
    return context


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 6: MINI AGENT RUNNER
# ═══════════════════════════════════════════════════════════════════════

async def run_mini_agent(agent_config: dict, sb: Client, browser: Browser):
    table = agent_config["table"]
    label = f"Agent-[{agent_config['name'].upper()}]"

    products = fetch_category_products(sb, table, limit=10)
    if not products: return

    context = await create_stealth_context(browser)
    page = await context.new_page()
    
    # APPLY STEALTH ONLY IF AVAILABLE
    if STEALTH_AVAILABLE and stealth_async:
        try:
            await stealth_async(page)
        except Exception as e:
            log.warning(f"  ⚠️ Stealth apply failed: {e}")

    updated = 0
    for i, product in enumerate(products, 1):
        product_id = product.get("id")
        name = product.get("Product Name-2") or product.get("name") or "Unknown"
        log.info(f"\n  [{label}] ({i}/{len(products)}) {name[:50]}...")

        url = await resolve_product_url(page, product, sb, table, product_id)
        if not url: continue

        extracted = await extract_product_data(page, url)
        if not extracted or not extracted.get("sellingPrice"): continue

        # Simple DB Update Payload
        u = {}
        selling = extracted["sellingPrice"]
        original = extracted.get("originalPrice") or 0
        
        for k in product.keys():
            kl = k.lower()
            if kl in ["price", "current price"]: u[k] = f"₹{selling:,}"
            if kl in ["original price", "mrp"] and original > 0: u[k] = f"₹{original:,}"

        if u:
            if update_product(sb, table, product_id, u):
                updated += 1
                log.info(f"  💾 Saved to DB: {u}")
                
        await asyncio.sleep(random.uniform(3.0, 5.0))

    await context.close()
    log.info(f"  ✅ DONE: {updated} updated out of {len(products)}")


# ═══════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════

async def main():
    log.info("╔══════════════════════════════════════════════════════════════╗")
    log.info("║  PRICEYAAR SUPER AGENT v8.1 - GITHUB ACTIONS SAFE EDITION  ║")
    log.info("╚══════════════════════════════════════════════════════════════╝")

    sb = get_supabase()
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        
        for agent in AGENTS:
            await run_mini_agent(agent, sb, browser)

        await browser.close()
    log.info("🏁 ALL TASKS FINISHED!")

if __name__ == "__main__":
    asyncio.run(main())

