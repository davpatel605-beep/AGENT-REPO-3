const { createClient } = require('@supabase/supabase-js');
const puppeteer = require('puppeteer');

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_KEY);

async function runAgent() {
    console.log("Starting Price Yaar Agent...");
    try {
        const browser = await puppeteer.launch({ 
            headless: "new",
            executablePath: '/usr/bin/google-chrome',
            args: ['--no-sandbox', '--disable-setuid-sandbox'] 
        });
        const page = await browser.newPage();

        const { data: products, error: fetchError } = await supabase
            .from('earbuds')
            .select('*')
            .limit(20);
        
        if (fetchError) {
            console.error("Supabase Error:", fetchError);
            return;
        }

        for (let product of products) {
            const url = product['Product link'];
            if (url && url.includes('flipkart.com')) {
                console.log(`Processing ID: ${product.id}`);
                try {
                    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
                    
                    const details = await page.evaluate(() => {
                        const price = document.querySelector('.Nx9bqj')?.innerText.replace(/[₹,]/g, '');
                        const mrp = document.querySelector('.yRaY8j')?.innerText.replace(/[₹,]/g, '');
                        const rating = document.querySelector('.X1_N6m')?.innerText;
                        const reviews = document.querySelector('.Wphh3N')?.innerText.replace(/[^0-9]/g, '');
                        const discount = document.querySelector('.Uk_O9r')?.innerText.replace(/[^0-9]/g, '');
                        return { price, mrp, rating, reviews, discount };
                    });

                    await supabase.from('earbuds').update({
                        'Current Price': details.price,
                        'Original Price': details.mrp,
                        'Rating': details.rating,
                        'Number of Reviews': details.reviews,
                        'Discount': details.discount
                    }).eq('id', product.id);

                    console.log(`ID ${product.id} updated successfully.`);
                } catch (e) {
                    console.log(`Failed on ID ${product.id}: ${e.message}`);
                }
                await new Promise(r => setTimeout(r, 2000)); 
            }
        }
        await browser.close();
        console.log("Task finished.");
    } catch (err) {
        console.error("Fatal Error:", err.message);
    }
}

runAgent();
