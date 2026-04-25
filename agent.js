
const { createClient } = require('@supabase/supabase-js');
const puppeteer = require('puppeteer');

// Initialize Supabase
const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_KEY);

async function runAgent() {
    console.log("🚀 Starting Price Yaar Agent...");
    
    let browser;
    try {
        browser = await puppeteer.launch({ 
            headless: "new",
            executablePath: '/usr/bin/google-chrome',
            args: ['--no-sandbox', '--disable-setuid-sandbox'] 
        });
        const page = await browser.newPage();

        // 1. Fetch products from Supabase
        const { data: products, error: fetchError } = await supabase
            .from('earbuds')
            .select('*')
            .limit(10);
        
        if (fetchError) {
            console.error("❌ Supabase Fetch Error:", fetchError.message);
            return;
        }

        console.log(`(Fetched ${products.length} products to process)`);

        for (let product of products) {
            const url = product['Product link'];
            if (url && url.includes('flipkart.com')) {
                console.log(`\n🔍 Checking Product ID: ${product.id}`);
                
                try {
                    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
                    
                    const details = await page.evaluate(() => {
                        const getTxt = (sel) => document.querySelector(sel)?.innerText || "";
                        const price = getTxt('.Nx9bqj').replace(/[₹,]/g, '');
                        const mrp = getTxt('.yRaY8j').replace(/[₹,]/g, '');
                        const rating = getTxt('.X1_N6m');
                        const reviews = getTxt('.Wphh3N').replace(/[^0-9]/g, '');
                        const discount = getTxt('.Uk_O9r').replace(/[^0-9]/g, '');
                        return { price, mrp, rating, reviews, discount };
                    });

                    console.log(`📊 Scraped Data: Price=${details.price}, MRP=${details.mrp}`);

                    // 2. Update Data in Supabase with Verification
                    const { data: updateData, error: updateError } = await supabase
                        .from('earbuds')
                        .update({
                            'Current Price': details.price,
                            'Original Price': details.mrp,
                            'Rating': details.rating,
                            'Number of Reviews': details.reviews,
                            'Discount': details.discount
                        })
                        .eq('id', product.id)
                        .select(); // This checks if the row was actually changed

                    if (updateError) {
                        console.error(`❌ Update Failed for ID ${product.id}:`, updateError.message);
                    } else if (updateData && updateData.length > 0) {
                        console.log(`✅ Success! ID ${product.id} updated in Supabase.`);
                    } else {
                        console.warn(`⚠️ ID ${product.id} matched but NO data was changed. (Check RLS Policies or Column Names)`);
                    }

                } catch (e) {
                    console.error(`❌ Error scraping URL: ${e.message}`);
                }
                
                // Small delay to avoid blocking
                await new Promise(r => setTimeout(r, 2000)); 
            }
        }
    } catch (err) {
        console.error("🔥 Fatal Agent Error:", err.message);
    } finally {
        if (browser) await browser.close();
        console.log("\n🏁 Agent Task Finished.");
    }
}

runAgent();

