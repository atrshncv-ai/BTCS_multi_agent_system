const puppeteer = require('puppeteer-core');

async function main(phone, message) {
    const browser = await puppeteer.connect({
        browserURL: 'http://localhost:9222',
        defaultViewport: null
    });

    const pages = await browser.pages();
    let waPage = pages.find(p => p.url().includes('web.whatsapp.com'));

    if (!waPage) {
        waPage = await browser.newPage();
        await waPage.goto('https://web.whatsapp.com');
        await new Promise(r => setTimeout(r, 3000));
    }

    console.log('[WA] Searching for:', phone);

    // Open search
    await waPage.keyboard.down('Meta');
    await waPage.keyboard.down('Shift');
    await waPage.keyboard.press('K');
    await waPage.keyboard.up('Shift');
    await waPage.keyboard.up('Meta');
    await new Promise(r => setTimeout(r, 800));

    // Type phone
    await waPage.keyboard.type(phone);
    await new Promise(r => setTimeout(r, 1500));

    // Press Enter to open chat
    await waPage.keyboard.press('Enter');
    await new Promise(r => setTimeout(r, 2000));

    console.log('[WA] Chat opened');

    // Click on message input (the contenteditable div)
    await waPage.evaluate(() => {
        const inputs = document.querySelectorAll('div[contenteditable="true"][role="textbox"]');
        if (inputs.length) inputs[inputs.length - 1].click();
    });
    await new Promise(r => setTimeout(r, 300));

    // Type message
    await waPage.keyboard.type(message);
    await new Promise(r => setTimeout(r, 300));

    // Send
    await waPage.keyboard.press('Enter');
    console.log('[WA] Message sent:', message);

    await browser.disconnect();
    return true;
}

const phone = process.argv[2] || process.env.WA_PHONE;
if (!phone) {
  console.error('[WA] Pass the target number via argv or WA_PHONE.');
  process.exit(2);
}
const msg = process.argv.slice(3).join(' ') || 'Test from Chrome CDP!';
main(phone, msg).then(() => process.exit(0)).catch(e => { console.error(e); process.exit(1); });