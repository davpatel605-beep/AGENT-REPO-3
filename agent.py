#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║  PRICEYAAR SUPER AGENT v7.0 - MERGED EDITION                       ║
║  Python + Playwright + DOM Strikethrough + 10 Mini Agents           ║
╚══════════════════════════════════════════════════════════════════════╝

MERGED FROM:
- Anthropic Agent: Python Playwright base, CSS selectors, stealth
- PriceYaar Agent: DOM strikethrough detection, 10 mini agents, strict validation

EXTRACTION LOGIC (from user screenshots):
1. ₹ symbol = price indicator
2. text-decoration: line-through = ORIGINAL PRICE (MRP)
3. Normal ₹ without strikethrough = SELLING PRICE
4. ↓XX% or XX% off = DISCOUNT PERCENT (1-99 max)
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

# SECURITY FIX: Use environment variable strictly, do not hardcode your private key here
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not SUPABASE_KEY:
    logging.error("CRITICAL ERROR: SUPABASE_KEY is missing. Please set it in your environment/GitHub Secrets.")
    sys.exit(1)

# 10 MINI AGENTS - one per category
AGENTS = [
    {"id": 1,  "name": "smart phone", "table": "smart phone"},
    {"id": 2,  "name": "laptop",      "table": "laptop"},
    {"id": 3,  "name": "earbuds",     "table": "earbuds"},
    {"id": 4,  "name": "iphone",      "table": "iphone"},
    {"id": 5,  "name": "smart+tv",    "table": "smart+tv"},
    {"id": 6,  "name": "smartwatch",  "table": "smartwatch"},
    {"id": 7,  "name": "induction",   "table": "induction"},
    {"id": 8,  "name": "keyboard",    "table": "keybord"},  # as in DB
    {"id": 9,  "name": "mouse",       "table": "mouse"},
    {"id": 10, "name": "monitor",     "table": "monitar"},  # as in DB
]

HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
DELAY_MIN = 2.0
DELAY_MAX = 5.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("PriceYaarSuperAgent")


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 1: SUPABASE HELPERS (from PriceYaar)
# ═══════════════════════════════════════════════════════════════════════

def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_category_products(sb: Client, table: str) -> list[dict]:
    """Fetch 10 products from a category table (as requested: 10-10 agent)."""
    try:
        # We limit to 10 to reduce load and process in small batches
        res = sb.table(table).select("*").limit(10).execute()
        products = res.data or []
        log.info(f"📦 {len(products)} products in '{table}' (Batch size: 10)")
        return products
    except Exception as e:
        log.error(f"❌ Fetch error for '{table}': {e}")
        return []

def update_product(sb: Client, table: str, product_id, data: dict):
    """Update a product in Supabase."""
    try:
        sb.table(table).update(data).eq("id", product_id).execute()
        return True
    except Exception as e:
        log.error(f"❌ Update error for id={product_id}: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 2: STRICT PRICE VALIDATION (from PriceYaar)
# ═══════════════════════════════════════════════════════════════════════

def validate_prices(selling_price: float, original_price: float) -> dict:
    """
    STRICT validation - only accept genuine prices.
    """
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
    """Convert '1,23,456' or '48.8k' to number."""
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
#  SECTION 3: FLIPKART CSS SELECTORS (from Anthropic)
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
#  SECTION 4: DOM STRIKETHROUGH DETECTION (from PriceYaar - KEY FEATURE)
# ═══════════════════════════════════════════════════════════════════════

async def extract_with_dom_strikethrough(page: Page) -> dict:
    """
    CRITICAL: Detect strikethrough via getComputedStyle.
    Strikethrough ₹ = Original Price, Normal ₹ = Selling Price.
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
           
            // ── 1. SCAN ALL ELEMENTS WITH ₹ ──
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
                    if (num < 500) continue;  // Skip small prices
                   
                    // Check strikethrough on element itself
                    const isStrike = style.textDecoration.includes('line-through') ||
                                     el.closest('[style*="line-through"]') !== null;
                   
                    // Check up to 3 parent levels
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
                   
                    // Skip EMI/accessory prices
                    const lowerText = text.toLowerCase();
                    const badKeywords = ['emi', '/m', 'per month', 'monthly',
                                        'warranty', 'protection', 'insurance',
                                        'case', 'cover', 'screen guard', 'charger'];
                    const isBad = badKeywords.some(k => lowerText.includes(k));
                    if (isBad) continue;
                   
                    rupeeElements.push({ match, num, isOriginal });
                }
            }
           
            // ── 2. CLASSIFY: Original vs Selling ──
            if (rupeeElements.length > 0) {
                const originals = rupeeElements.filter(e => e.isOriginal).map(e => e.num);
                const sellings = rupeeElements.filter(e => !e.isOriginal).map(e => e.num);
               
                const uniqueOriginals = [...new Set(originals)].sort((a, b) => b - a);
                const uniqueSellings = [...new Set(sellings)].sort((a, b) => a - b);
               
                if (uniqueSellings.length > 0) {
                    result.sellingPrice = uniqueSellings[0];  // Lowest = selling
                }
                if (uniqueOriginals.length > 0) {
                    result.originalPrice = uniqueOriginals[0];  // Highest = original
                }
            }
           
            // ── 3. DISCOUNT % ──
            const bodyText = document.body.innerText || '';
            const discMatch = bodyText.match(/[↓↓↓]\\s*(\\d{1,2})\\s*%/);
            if (discMatch) {
                result.discountPercent = parseInt(discMatch[1]);
            } else {
                const discMatch2 = bodyText.match(/(\\d{1,2})\\s*%\\s*(?:off|Off|OFF)/);
                if (discMatch2) result.discountPercent = parseInt(discMatch2[1]);
            }
           
            // ── 4. RATING (X.X ★) ──
            const ratingMatch = bodyText.match(/(\\d\\.\\d)\\s*★/);
            if (ratingMatch) {
                const val = parseFloat(ratingMatch[1]);
                if (val >= 1 && val <= 5) result.rating = val.toFixed(1);
            }
           
            // ── 5. REVIEWS (XX.XK+) ──
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
#  SECTION 5: CSS SELECTOR FALLBACK (from Anthropic)
# ═══════════════════════════════════════════════════════════════════════

async def extract_with_css_selectors(page: Page) -> dict:
    """Fallback: Use Flipkart's known CSS class selectors."""
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
#  SECTION 6: TEXT-BASED FALLBACK (from Anthropic)
# ═══════════════════════════════════════════════════════════════════════

async def extract_with_text_parsing(page: Page) -> dict:
    """Last resort: Parse innerText for price patterns."""
    page_text = await page.inner_text("body")
   
    result = {
        "sellingPrice": None,
        "originalPrice": None,
        "discountPercent": None,
        "rating": None,
        "reviews": None
    }
   
    # ── 1. Extract ₹ prices ──
    prices = []
    price_matches = re.findall(r'₹\s*([\d,]+)', page_text)
    for p in price_matches:
        val = parse_indian_number(p)
        if val and val > 500:
            prices.append(val)
   
    # ── 2. Filter out bad prices (EMI, accessories) ──
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
   
    # ── 3. Determine prices ──
    unique = sorted(set(clean_prices))
    if len(unique) >= 2:
        result["sellingPrice"] = unique[0]   # Lowest = selling
        result["originalPrice"] = unique[-1]  # Highest = MRP
    elif len(unique) == 1:
        result["sellingPrice"] = unique[0]
   
    # ── 4. Discount ──
    disc_match = re.search(r'(\d{1,2})\s*%\s*off', page_text, re.IGNORECASE)
    if disc_match:
        result["discountPercent"] = int(disc_match.group(1))
   
    # ── 5. Rating ──
    rating_match = re.search(r'(\d\.\d)\s*★', page_text)
    if rating_match:
        val = float(rating_match.group(1))
        if 1 <= val <= 5:
            result["rating"] = f"{val:.1f}"
   
    # ── 6. Reviews ──
    rev_match = re.search(r'(\d+\.?\d*)\s*K\+', page_text)
    if rev_match:
        result["reviews"] = str(int(float(rev_match.group(1)) * 1000))
    else:
        rev_match2 = re.search(r'([\d,]+)\s*(?:Ratings?\s*[&+]\s*)?Reviews?', page_text, re.IGNORECASE)
        if rev_match2:
            result["reviews"] = rev_match2.group(1).replace(',', '')
   
    return result


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 7: MASTER EXTRACTION - Try all 3 methods
# ═══════════════════════════════════════════════════════════════════════

async def extract_product_data(page: Page, url: str) -> dict:
    """
    FIERCE RETRY MECHANISM: Try extracting multiple times!
    Wait as much as needed without hard timeouts.
    Try 3 methods in order:
    1. DOM Strikethrough Detection (BEST)
    2. CSS Selectors (Fallback)
    3. Text Parsing (Last resort)
    """
    log.info(f"  🌐 Opening: {url[:80]}...")
   
    try:
        # No strict timeout, wait until dom is loaded properly
        await page.goto(url, wait_until="domcontentloaded", timeout=120000)
        await asyncio.sleep(random.uniform(1.5, 3.0))
       
        # Check redirect
        current_url = page.url
        if "login" in current_url or "error" in current_url.lower():
            log.warning(f"  ⚠️ Redirect: {current_url[:60]}")
            return {}
           
        data = {}
        method = ""
       
        # FIERCE RETRY LOOP (Wait up to ~50s+ if needed, pressuring the page to load)
        for attempt in range(1, 16):
            # Human-like scroll
            await human_scroll(page)
            await asyncio.sleep(random.uniform(1.0, 2.0))
           
            # ── METHOD 1: DOM Strikethrough (BEST) ──
            data_try = await extract_with_dom_strikethrough(page)
            if data_try.get("sellingPrice"):
                data = data_try
                method = "DOM_strikethrough"
                break
           
            # ── METHOD 2: CSS Selectors (if method 1 failed) ──
            css_data = await extract_with_css_selectors(page)
            if css_data.get("sellingPrice"):
                data["sellingPrice"] = css_data["sellingPrice"]
                if css_data.get("originalPrice"):
                    data["originalPrice"] = css_data["originalPrice"]
                # merge the rest safely
                data.update({k: v for k, v in css_data.items() if v and not data.get(k)})
                method = "CSS_selectors"
                break
           
            # ── METHOD 3: Text parsing (last resort) ──
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
        else:
            log.error(f"  ❌ Failed to extract data even after maximum attempts!")
           
        return data
       
    except Exception as e:
        log.error(f"  ❌ Scrape failed: {e}")
        return {}


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 8: HUMAN-LIKE BEHAVIOR (from both agents)
# ═══════════════════════════════════════════════════════════════════════

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.86 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

async def human_scroll(page: Page):
    """Slowly scroll like a human."""
    scroll_height = await page.evaluate("document.body.scrollHeight")
    current = 0
    while current < min(scroll_height * 0.6, 2000):
        scroll_amount = random.randint(100, 300)
        current += scroll_amount
        await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
        await asyncio.sleep(random.uniform(0.1, 0.4))

async def setup_browser(playwright):
    """Launch browser with anti-detection."""
    return await playwright.chromium.launch(
        headless=HEADLESS,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--disable-extensions",
            "--disable-dev-shm-usage",
        ]
    )

async def create_stealth_context(browser: Browser) -> BrowserContext:
    """Create stealth browser context."""
    ua = random.choice(USER_AGENTS)
    context = await browser.new_context(
        user_agent=ua,
        viewport={"width": 1366, "height": 768},
        locale="en-IN",
        timezone_id="Asia/Kolkata",
        extra_http_headers={
            "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
        }
    )
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en', 'hi'] });
        window.chrome = { runtime: {} };
    """)
    return context


# ═══════════════════════════════════════════════════════════════════════
#  SECTION 9: BUILD SUPABASE UPDATE (WITH CASE-INSENSITIVE FIX)
# ═══════════════════════════════════════════════════════════════════════

# --- NEW HELPER FUNCTIONS FOR CASE INSENSITIVITY ---
def get_dict_value_ignore_case(d: dict, target_keys: list) -> str:
    """Finds values in a dict ignoring case sensitivity for keys."""
    target_keys_lower = [k.lower() for k in target_keys]
    for key, value in d.items():
        if key.lower() in target_keys_lower and value:
            return str(value)
    return ""

def find_real_column_name(all_cols: list, candidates: list) -> Optional[str]:
    """Matches desired column names against DB columns, ignoring case."""
    candidates_lower = [c.lower() for c in candidates]
    for col in all_cols:
        if col.lower() in candidates_lower:
            return col
    return None
# ---------------------------------------------------

def build_update_payload(product: dict, extracted: dict, all_cols: list) -> Tuple[dict, dict]:
    """Build Supabase update payload with strict validation."""
    selling_num = extracted.get("sellingPrice") or 0
    original_num = extracted.get("originalPrice") or 0
    extracted_discount = extracted.get("discountPercent") or 0
   
    # Strict validation
    validated = validate_prices(selling_num, original_num)
   
    # Override discount with extracted if valid
    if 1 <= extracted_discount <= 90 and validated["valid_original"] > 0:
        validated["discount_str"] = f"{extracted_discount}% off"
        validated["discount_pct"] = extracted_discount
   
    u = {}
   
    # Price column mapping
    price_candidates = ["Price", "Current Price", "price", "current_price", "discounted_price"]
    mrp_candidates = ["Original Price", "Original Price-2", "original_price", "mrp"]
    discount_candidates = ["Discount", "discount", "discount_percent"]
    rating_candidates = ["Rating", "rating", "Ratings and Reviews", "Rating and Reviews"]
    reviews_candidates = ["Number of Reviews", "Reviews", "reviews", "review_count"]
   
    # Find matching columns using the NEW Case-Insensitive logic
    price_col = find_real_column_name(all_cols, price_candidates)
    mrp_col = find_real_column_name(all_cols, mrp_candidates)
    discount_col = find_real_column_name(all_cols, discount_candidates)
    rating_col = find_real_column_name(all_cols, rating_candidates)
    reviews_col = find_real_column_name(all_cols, reviews_candidates)
   
    # Build update
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
#  SECTION 10: MINI AGENT RUNNER (WITH CASE-INSENSITIVE FIX)
# ═══════════════════════════════════════════════════════════════════════

async def run_mini_agent(agent_config: dict, sb: Client, browser: Browser):
    """Run one mini agent for a category."""
    agent_id = agent_config["id"]
    agent_name = agent_config["name"]
    table = agent_config["table"]
    label = f"Agent-{agent_id:02d} [{agent_name.upper()}]"
   
    log.info(f"\n{'='*60}")
    log.info(f"  {label} STARTING")
    log.info(f"{'='*60}")
   
    # Fetch products
    products = fetch_category_products(sb, table)
    if not products:
        log.warning(f"  [{label}] No products found")
        return {"agent": label, "updated": 0, "failed": 0, "total": 0}
   
    # Create page
    context = await create_stealth_context(browser)
    page = await context.new_page()
   
    updated = 0
    failed = 0
   
    for i, product in enumerate(products, 1):
        # Get product URL using the NEW Case-Insensitive logic
        url = get_dict_value_ignore_case(product, ["Product Link", "product_url", "link", "Product URL"])
       
        if not url or "flipkart.com" not in url:
            continue
       
        # Get product name using the NEW Case-Insensitive logic
        product_name = get_dict_value_ignore_case(product, ["Product Name-2", "Product Name", "name", "Brand Name"])
        if not product_name:
            product_name = "Unknown"
       
        log.info(f"\n  [{label}] ({i}/{len(products)}) {product_name[:50]}...")
       
        # Scrape
        extracted = await extract_product_data(page, url)
       
        if not extracted or not extracted.get("sellingPrice"):
            log.warning(f"  [{label}] No price extracted, skipping")
            failed += 1
            continue
       
        # Build update
        all_cols = list(product.keys())
        update_data, validated = build_update_payload(product, extracted, all_cols)
       
        if not update_data:
            log.warning(f"  [{label}] No columns to update")
            failed += 1
            continue
       
        # Update Supabase
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
       
        # Delay between products
        if i < len(products):
            delay = random.uniform(3.0, 7.0)
            log.info(f"  [{label}] ⏳ Waiting {delay:.1f}s...")
            await asyncio.sleep(delay)
   
    await context.close()
   
    log.info(f"\n  [{label}] ✅ DONE: {updated} updated, {failed} failed, {len(products)} total")
    return {"agent": label, "updated": updated, "failed": failed, "total": len(products)}


# ═══════════════════════════════════════════════════════════════════════
#  MAIN - Run all 10 mini agents
# ═══════════════════════════════════════════════════════════════════════

async def main():
    log.info("╔══════════════════════════════════════════════════════════════╗")
    log.info("║  PRICEYAAR SUPER AGENT v7.0 - MERGED EDITION               ║")
    log.info("║  Python + Playwright + DOM Strikethrough + 10 Mini Agents    ║")
    log.info("╚══════════════════════════════════════════════════════════════╝")
   
    # Supabase connect
    sb = get_supabase()
    log.info(f"✅ Supabase connected")
   
    # Launch browser
    async with async_playwright() as playwright:
        browser = await setup_browser(playwright)
        log.info(f"🌐 Browser launched (headless={HEADLESS})")
       
        # Run all 10 mini agents
        results = []
        for agent in AGENTS:
            result = await run_mini_agent(agent, sb, browser)
            results.append(result)
           
            # Rest between agents
            if agent["id"] < len(AGENTS):
                rest = random.uniform(5.0, 10.0)
                log.info(f"\n💤 Resting {rest:.0f}s before next agent...")
                await asyncio.sleep(rest)
       
        await browser.close()
   
    # Final report
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
    log.info("🏁 All 10 agents finished!")


if __name__ == "__main__":
    asyncio.run(main())

