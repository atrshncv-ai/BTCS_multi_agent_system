const { Client, LocalAuth } = require('whatsapp-web.js');
const fs = require('fs');
const path = require('path');

const SESSION_PATH = path.join(__dirname, 'whatsapp_service/session_visible');

const client = new Client({
    authStrategy: new LocalAuth({
        dataPath: SESSION_PATH
    }),
    puppeteer: {
        headless: false,
        defaultViewport: null,
        args: [
            '--start-maximized',
            '--disable-setuid-sandbox'
        ]
    }
});

client.on('qr', (qr) => {
    console.log('[WA] Scan QR at: http://localhost:9222');
    fs.writeFileSync(path.join(__dirname, 'whatsapp_service/qrcode.png'), qr);
});

client.on('ready', () => {
    console.log('[WA] WhatsApp Web is ready!');
    console.log('[WA] To send: node whatsapp_web.js send <phone> <message>');
});

client.on('message', (msg) => {
    console.log(`[WA] ${msg.from}: ${msg.body}`);
});

async function sendMessage(phone, text) {
    const chatId = phone.includes('@c.us') ? phone : `${phone}@c.us`;
    try {
        await client.sendMessage(chatId, text);
        console.log(`[WA] Sent to ${phone}: ${text}`);
        return true;
    } catch (e) {
        console.error(`[WA] Error: ${e.message}`);
        return false;
    }
}

const args = process.argv.slice(2);
if (args[0] === 'send' && args[1] && args[2]) {
    client.once('ready', () => {
        sendMessage(args[1], args.slice(2).join(' '));
    });
} else {
    client.initialize();
}