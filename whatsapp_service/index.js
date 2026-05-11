const express = require('express');
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const cors = require('cors');
const qrcode = require('qrcode');
const path = require('path');
const fs = require('fs');

const app = express();
app.use(express.json());
app.use(cors());

const PORT = process.env.PORT || 3000;
const QR_CODE_PATH = path.join(__dirname, 'qrcode.png');
const SESSION_PATH = path.join(__dirname, 'session');

// WhatsApp client
let client = null;
let isReady = false;
let lastQR = null;

// Initialize WhatsApp client
function initClient() {
    client = new Client({
        authStrategy: new LocalAuth({
            dataPath: SESSION_PATH
        }),
        puppeteer: {
            headless: true,
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--no-first-run',
                '--no-zygote',
                '--disable-gpu'
            ]
        }
    });

    client.on('qr', async (qr) => {
        console.log('[WA] QR Code received');
        try {
            await qrcode.toFile(QR_CODE_PATH, qr, { width: 300 });
            lastQR = qr;
            console.log('[WA] QR Code saved to', QR_CODE_PATH);
        } catch (err) {
            console.error('[WA] QR save error:', err.message);
        }
    });

    client.on('ready', () => {
        console.log('[WA] Client ready!');
        isReady = true;
    });

    client.on('authenticated', () => {
        console.log('[WA] Authenticated successfully');
    });

    client.on('auth_failure', (msg) => {
        console.error('[WA] Auth failure:', msg);
        isReady = false;
    });

    client.on('disconnected', (reason) => {
        console.log('[WA] Disconnected:', reason);
        isReady = false;
        // Reconnect after 3 seconds
        setTimeout(() => {
            console.log('[WA] Reconnecting...');
            client.initialize();
        }, 3000);
    });

    client.on('message', (msg) => {
        console.log(`[WA] Message from ${msg.from}:`, msg.body.substring(0, 50));
        // Handle incoming messages here if needed
    });

    console.log('[WA] Initializing client...');
    client.initialize();
}

// API Routes

// Health check
app.get('/health', (req, res) => {
    res.json({
        status: isReady ? 'ready' : 'not_ready',
        isReady: isReady,
        qr: lastQR ? 'available' : null
    });
});

// Get QR Code
app.get('/qr', async (req, res) => {
    if (fs.existsSync(QR_CODE_PATH)) {
        res.sendFile(QR_CODE_PATH);
    } else {
        res.status(404).json({ error: 'QR code not available yet' });
    }
});

// Send message
app.post('/send', async (req, res) => {
    const { phone, message } = req.body;
    
    if (!phone || !message) {
        return res.status(400).json({ error: 'Missing phone or message' });
    }

    if (!isReady) {
        return res.status(503).json({ error: 'WhatsApp not ready' });
    }

    try {
        // Format phone number
        let formattedPhone = phone.replace(/[^0-9]/g, '');
        if (!formattedPhone.startsWith('7') && !formattedPhone.startsWith('+')) {
            formattedPhone = '+' + formattedPhone;
        }
        
        console.log(`[WA] Sending to ${formattedPhone}:`, message.substring(0, 30));
        
        const result = await client.sendMessage(formattedPhone, message);
        
        res.json({
            success: true,
            messageId: result.id._serialized,
            to: formattedPhone
        });
    } catch (error) {
        console.error('[WA] Send error:', error.message);
        res.status(500).json({ error: error.message });
    }
});

// Send media
app.post('/send-media', async (req, res) => {
    const { phone, caption, url } = req.body;
    
    if (!phone || !url) {
        return res.status(400).json({ error: 'Missing phone or url' });
    }

    if (!isReady) {
        return res.status(503).json({ error: 'WhatsApp not ready' });
    }

    try {
        let formattedPhone = phone.replace(/[^0-9]/g, '');
        if (!formattedPhone.startsWith('+')) {
            formattedPhone = '+' + formattedPhone;
        }
        
        const media = await MessageMedia.fromUrl(url);
        const result = await client.sendMessage(formattedPhone, media, { caption });
        
        res.json({
            success: true,
            messageId: result.id._serialized
        });
    } catch (error) {
        console.error('[WA] Send media error:', error.message);
        res.status(500).json({ error: error.message });
    }
});

// Get contact info
app.get('/contact/:phone', async (req, res) => {
    const { phone } = req.params;
    
    if (!isReady) {
        return res.status(503).json({ error: 'WhatsApp not ready' });
    }

    try {
        let formattedPhone = phone.replace(/[^0-9]/g, '');
        if (!formattedPhone.startsWith('+')) {
            formattedPhone = '+' + formattedPhone;
        }
        
        const contact = await client.getContactById(formattedPhone);
        
        res.json({
            exists: true,
            name: contact.pushname || contact.shortName || 'Unknown',
            number: contact.number
        });
    } catch (error) {
        res.json({ exists: false });
    }
});

// Restart client
app.post('/restart', async (req, res) => {
    try {
        if (client) {
            await client.destroy();
        }
        initClient();
        res.json({ status: 'restarting' });
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

// Start server
app.listen(PORT, () => {
    console.log(`🚀 WhatsApp service running on port ${PORT}`);
    initClient();
});

module.exports = app;