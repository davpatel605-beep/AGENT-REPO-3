const { createClient } = require('@supabase/supabase-js');
const puppeteer = require('puppeteer');

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_KEY);

async function runAgent() {
    console.log("Starting Debug Run for 'earbuds' table...");
    const browser = await puppeteer.launch({ 
        headless: "new",
        args: ['--no-sandbox', '--disable-setuid-sandbox'] 
    });
    const page = await browser.newPage();

    const { data: products, error: fetchError } = await supabase
        .from('earbuds')
        .select('*')
        .limit(20);
    
    if (fetchError) {
        console.error("Fetch Error:", fetchError);
        return;
    }

    for (let product of products) {
        const url = product['Product link'];
        if (url && url.includes('flipkart.com')) {
            try {
                console.log(`Processing ID: ${product.id} | URL: ${url}`);
                await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
                
                const details = await page.evaluate(() => {
                    const price = document.querySelector('.Nx9bqj')?.innerText.replace(/[₹,]/g, '');
                    const mrp = document.querySelector('.yRaY8j')?.innerText.replace(/[₹,]/g, '');
                    const rating = document.querySelector('.X1_N6m')?.innerText;
                    const reviews = document.querySelector('.Wphh3N')?.innerText.replace(/[^0-9]/g, '');
                    const discount = document.querySelector('.Uk_O9r')?.innerText.replace(/[^0-9]/g, '');
                    return { price, mrp, rating, reviews, discount };
                });

                // यहाँ हम अपडेट की कोशिश कर रहे हैं और रिजल्ट को रिकॉर्ड कर रहे हैं
                const { data, error: updateError } = await supabase
                    .from('earbuds')
                    .update({
                        'Current Price': details.price,
                        'Original Price': details.mrp,
                        'Rating': details.rating,
                        'Number of Reviews': details.reviews,
                        'Discount': details.discount
                    })
                    .eq('id', product.id)
                    .select(); // यह देखने के लिए कि क्या बदलाव हुआ

                if (updateError) {
                    console.error(`❌ Update Failed for ID ${product.id}:`, updateError.message);
                } else if (data && data.length > 0) {
                    console.log(`✅ Update Success for ID ${product.id}:`, data[0]);
                } else {
                    console.log(`⚠️ ID ${product.id} found but no data changed (Check RLS or if values were same)`);
                }

                await new Promise(r => setTimeout(r, 3000)); 
            } catch (e) {
                console.log(`Error on ${url}: ${e.message}`);
            }
        }
    }
    await browser.close();
}

runAgent();

