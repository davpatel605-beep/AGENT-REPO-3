const { createClient } = require('@supabase/supabase-js');
const puppeteer = require('puppeteer');

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_KEY);

async function runAgent() {
    console.log("Agent starting task for first 20 earbuds...");
    const browser = await puppeteer.launch({ 
        headless: "new",
        args: ['--no-sandbox', '--disable-setuid-sandbox'] 
    });
    const page = await browser.newPage();
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36');

    // Fetching first 20 rows from 'earbuds' table
    const { data: products, error } = await supabase
        .from('earbuds')
        .select('*')
        .limit(20);
    
    if (error) {
        console.error("Supabase Connection Error:", error);
        return;
    }

    for (let product of products) {
        const url = product['Product link']; // Using your column name
        
        if (url && url.includes('flipkart.com')) {
            try {
                console.log(`Checking URL: ${url}`);
                await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
                
                const details = await page.evaluate(() => {
                    const price = document.querySelector('.Nx9bqj')?.innerText.replace(/[₹,]/g, '');
                    const mrp = document.querySelector('.yRaY8j')?.innerText.replace(/[₹,]/g, '');
                    const rating = document.querySelector('.X1_N6m')?.innerText;
                    const reviews = document.querySelector('.Wphh3N')?.innerText.replace(/[^0-9]/g, '');
                    const discount = document.querySelector('.Uk_O9r')?.innerText.replace(/[^0-9]/g, '');
                    
                    return { price, mrp, rating, reviews, discount };
                });

                // Updating the 'earbuds' table with your specific column names
                await supabase.from('earbuds').update({
                    'Current Price': details.price,
                    'Original Price': details.mrp,
                    'Rating': details.rating,
                    'Number of Reviews': details.reviews,
                    'Discount': details.discount
                }).eq('id', product.id);

                console.log(`Success: Updated earbuds ID ${product.id}`);
                await new Promise(r => setTimeout(r, 5000)); 
            } catch (e) {
                console.log(`Failed to process: ${url}`);
            }
        }
    }
    await browser.close();
    console.log("Task Completed Successfully!");
}

runAgent();

