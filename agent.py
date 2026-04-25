import os
import time
import re
import logging
from supabase import create_client, Client
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# Configure Logging for Detailed Output
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize Supabase Client
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    logging.error("Supabase Credentials are missing in environment variables.")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def setup_driver():
    """Configures and returns a headless Chrome WebDriver."""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

def clean_price(price_text):
    """Extracts numeric value from price string."""
    if not price_text:
        return None
    cleaned = re.sub(r'[^\d]', '', price_text)
    return int(cleaned) if cleaned else None

def parse_reviews_count(review_text):
    """Converts text like '28k' or '1.5k' into absolute integers."""
    if not review_text:
        return None
    
    text = review_text.lower().replace(',', '')
    match = re.search(r'([\d.]+)([k]?)', text)
    
    if match:
        number_part = float(match.group(1))
        multiplier_part = match.group(2)
        
        if multiplier_part == 'k':
            return int(number_part * 1000)
        return int(number_part)
    return None

def extract_rating(rating_text):
    """Extracts the rating float value."""
    if not rating_text:
        return None
    match = re.search(r'[\d.]+', rating_text)
    return float(match.group(0)) if match else None

def get_url_from_product(product_data):
    """Safely extracts URL handling possible case differences in column names."""
    for key, value in product_data.items():
        if key.lower() == 'product link':
            return value
    return None

def main():
    logging.info("Starting Detailed Price Yaar Intelligent Agent...")
    driver = setup_driver()
    
    try:
        # Fetch up to 20 products from 'earbuds' table, strictly ordered by ID (1 to 20)
        response = supabase.table("earbuds").select("*").order("id").limit(20).execute()
        products = response.data
        
        if not products:
            logging.warning("No products found in the database.")
            return

        logging.info(f"Successfully fetched {len(products)} products from Supabase.")

        for product in products:
            product_id = product.get("id")
            
            # Use the robust URL extraction function
            url = get_url_from_product(product)
            
            if not url or "flipkart.com" not in str(url):
                logging.info(f"Skipping ID {product_id} - Invalid or missing Flipkart URL. Value found: {url}")
                continue

            logging.info(f"--- Processing Product ID: {product_id} ---")
            driver.get(url)
            
            # Wait for the main price element to load (Maximum 15 seconds)
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".Nx9bqj"))
                )
                time.sleep(2) # Small buffer for dynamic elements like ratings to render
            except Exception:
                logging.error(f"Timeout waiting for page to load for ID {product_id}. URL: {url}")
                continue

            # Initialize variables
            current_price = None
            original_price = None
            discount_percent = None
            rating = None
            reviews = None

            # 1. Extract Current Price (Always present)
            try:
                cp_element = driver.find_element(By.CSS_SELECTOR, ".Nx9bqj")
                current_price = clean_price(cp_element.text)
            except Exception:
                logging.warning(f"Could not find Current Price for ID {product_id}")

            # 2. Extract Original Price and Discount Percent
            try:
                op_element = driver.find_element(By.CSS_SELECTOR, ".yRaY8j")
                disc_element = driver.find_element(By.CSS_SELECTOR, ".Uk_O9r")
                
                original_price = clean_price(op_element.text)
                # Extract only numbers from discount (e.g., "87% off" -> 87)
                disc_text = disc_element.text
                disc_match = re.search(r'\d+', disc_text)
                discount_percent = int(disc_match.group(0)) if disc_match else None
                
            except Exception:
                # If no discount is found (as per user instruction: Image 2 logic)
                logging.info(f"No discount found for ID {product_id}. Setting original price and discount to NULL.")
                original_price = None
                discount_percent = None

            # 3. Extract Rating
            try:
                rating_element = driver.find_element(By.CSS_SELECTOR, "div.X1_N6m")
                rating = extract_rating(rating_element.text)
            except Exception:
                pass

            # 4. Extract Reviews Count (with 'k' conversion)
            try:
                reviews_element = driver.find_element(By.CSS_SELECTOR, "span.Wphh3N")
                reviews = parse_reviews_count(reviews_element.text)
            except Exception:
                pass

            logging.info(f"Extracted Data -> CP: {current_price}, OP: {original_price}, Disc: {discount_percent}%, Rating: {rating}, Reviews: {reviews}")

            # 5. Update Supabase
            update_payload = {
                "Current Price": current_price,
                "Original Price": original_price,
                "Discount": discount_percent,
                "Rating": rating,
                "Number of Reviews": reviews
            }

            try:
                supabase.table("earbuds").update(update_payload).eq("id", product_id).execute()
                logging.info(f"Successfully updated Supabase for ID {product_id}")
            except Exception as e:
                logging.error(f"Failed to update Supabase for ID {product_id}. Error: {str(e)}")

            # Small delay between requests to avoid IP Ban
            time.sleep(3)

    except Exception as main_err:
        logging.critical(f"Critical error in Agent execution: {str(main_err)}")
    finally:
        driver.quit()
        logging.info("Detailed Price Yaar Intelligent Agent execution completed.")

if __name__ == "__main__":
    main()

