const puppeteer = require('puppeteer-core');

async function check() {
    const browser = await puppeteer.connect({
        browserURL: 'http://localhost:9222',
        defaultViewport: null
    });

    const pages = await browser.pages();
    const waPage = pages.find(p => p.url().includes('web.whatsapp.com'));

    if (!waPage) {
        console.log('No WhatsApp page found');
        await browser.disconnect();
        return;
    }

    console.log('URL:', waPage.url());

    // Get visible text
    const text = await waPage.evaluate(() => document.body.innerText.slice(0, 500));
    console.log('Page text:', text.slice(0, 300));

    await browser.disconnect();
}

check().catch(e => console.error(e.message));