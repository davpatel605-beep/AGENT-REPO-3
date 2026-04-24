const { createClient } = require('@supabase/supabase-js');
const puppeteer = require('puppeteer');

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_KEY);

async function runAgent() {
    console.log("Agent starting task...");
    const browser = await puppeteer.launch({ 
        headless: "new",
        args: ['--no-sandbox', '--disable-setuid-sandbox'] 
    });
    const page = await browser.newPage();

    // Set User Agent to avoid immediate bot detection
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36');

    // 1. Fetching products from Supabase
    const { data: products, error } = await supabase.from('products').select('id, product_url');
    
    if (error) {
        console.error("Supabase Connection Error:", error);
        return;
    }

    for (let product of products) {
        if (product.product_url && product.product_url.includes('flipkart.com')) {
            try {
                console.log(`Checking URL: ${product.product_url}`);
                await page.goto(product.product_url, { waitUntil: 'domcontentloaded', timeout: 60000 });
                
                // Scraping logic using selectors
                const details = await page.evaluate(() => {
                    const price = document.querySelector('.Nx9bqj')?.innerText.replace(/[₹,]/g, '');
                    const mrp = document.querySelector('.yRaY8j')?.innerText.replace(/[₹,]/g, '');
                    const rating = document.querySelector('.X1_N6m')?.innerText;
                    const discount = document.querySelector('.Uk_O9r')?.innerText.replace(/[^0-9]/g, '');
                    
                    return { price, mrp, rating, discount };
                });

                // 2. Updating Supabase table
                await supabase.from('products').update({
                    current_price: details.price,
                    original_price: details.mrp,
                    rating: details.rating,
                    discount_percent: details.discount
                }).eq('id', product.id);

                console.log(`Success: Price updated to ${details.price}`);
                
                // Adding a 5-second delay to mimic human behavior
                await new Promise(r => setTimeout(r, 5000)); 
            } catch (e) {
                console.log(`Failed to process: ${product.product_url}`);
            }
        }
    }
    await browser.close();
    console.log("Task Completed Successfully!");
}

runAgent();
