import http from 'http';
import https from 'https';

const TARGET = 'http://localhost:11434';
const PORT = 4000;

const server = http.createServer((req, res) => {
  console.log(`[PROXY] ${req.method} ${req.url}`);
  
  // Collect request body
  const body = [];
  req.on('data', chunk => body.push(chunk));
  req.on('end', () => {
    const bodyStr = Buffer.concat(body).toString();
    
    const options = new URL(TARGET + req.url);
    options.method = req.method;
    options.headers = { ...req.headers, host: options.host };
    
    const proxyReq = http.request(options, (proxyRes) => {
      res.writeHead(proxyRes.statusCode, proxyRes.headers);
      proxyRes.pipe(res);
    });
    
    proxyReq.on('error', (e) => {
      console.error('[PROXY] Error:', e.message);
      res.writeHead(502);
      res.end(JSON.stringify({ error: e.message }));
    });
    
    if (bodyStr) proxyReq.write(bodyStr);
    proxyReq.end();
  });
});

server.listen(PORT, () => {
  console.log(`🚀 Ollama Proxy running!`);
  console.log(`   Paperclip → http://localhost:${PORT} → Ollama (${TARGET})`);
});
