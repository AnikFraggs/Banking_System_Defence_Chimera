const express = require('express');
const cors = require('cors');
const axios = require('axios');
const http = require('http');
const https = require('https');

const app = express();
const apiBase = (process.env.JAVA_API_URL || 'http://localhost:8080').replace(/\/$/, '');
const allowedOrigins = (process.env.CORS_ORIGINS || 'http://localhost:5173,http://127.0.0.1:5173')
  .split(',').map(value => value.trim()).filter(Boolean);
const client = axios.create({
  baseURL: apiBase,
  timeout: Number(process.env.API_TIMEOUT_MS || 10000),
  httpAgent: new http.Agent({ keepAlive: true, maxSockets: 128, maxFreeSockets: 32 }),
  httpsAgent: new https.Agent({ keepAlive: true, maxSockets: 128, maxFreeSockets: 32 }),
  validateStatus: () => true,
});

app.disable('x-powered-by');
app.use(cors({ origin: allowedOrigins, credentials: false, methods: ['GET', 'POST', 'OPTIONS'],
  allowedHeaders: ['Authorization', 'Content-Type', 'Idempotency-Key'] }));
app.use(express.json({ limit: '10mb', strict: true }));

let inFlight = 0;
const maxInFlight = Math.max(8, Number(process.env.BFF_MAX_IN_FLIGHT || 32));
app.use((req, res, next) => {
  if (inFlight >= maxInFlight) {
    res.set('Retry-After', '1');
    return res.status(503).json({ error: 'Gateway is at capacity; retry shortly' });
  }
  inFlight += 1;
  let released = false;
  const release = () => {
    if (!released) {
      released = true;
      inFlight -= 1;
    }
  };
  res.once('finish', release);
  res.once('close', release);
  return next();
});

async function forward(req, res, path, method = req.method) {
  // express.json() leaves non-JSON bodies (multipart dataset uploads) unread, so
  // stream them through untouched with their original boundary-bearing headers.
  const streamed = Boolean(req.headers['content-type']) && !req.is('application/json');
  try {
    const result = await client.request({
      url: path,
      method,
      data: streamed ? req : req.body,
      headers: {
        ...(req.headers.authorization ? { Authorization: req.headers.authorization } : {}),
        ...(req.headers['idempotency-key'] ? { 'Idempotency-Key': req.headers['idempotency-key'] } : {}),
        ...(streamed ? { 'Content-Type': req.headers['content-type'] } : {}),
        ...(streamed && req.headers['content-length'] ? { 'Content-Length': req.headers['content-length'] } : {}),
        'X-Forwarded-For': req.headers['x-forwarded-for'] || req.socket.remoteAddress,
      },
    });
    res.status(result.status);
    if (result.headers['content-type']) res.type(result.headers['content-type']);
    return res.send(result.data);
  } catch (error) {
    const timeout = error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT';
    return res.status(timeout ? 504 : 502).json({ error: timeout ? 'Upstream API timed out' : 'Upstream API unavailable' });
  }
}

app.get('/health', (_req, res) => res.json({ status: 'UP', upstream: apiBase }));
app.get('/api/market/overview', (req, res) => forward(req, res, '/api/market/overview'));
app.get('/api/banking/dashboard', (req, res) => forward(req, res, '/api/banking/dashboard'));
app.get('/api/banking/transactions', async (req, res) => {
  try {
    const result = await client.get('/api/banking/dashboard', {
      headers: req.headers.authorization ? { Authorization: req.headers.authorization } : {},
    });
    if (result.status < 200 || result.status >= 300) return res.status(result.status).send(result.data);
    return res.json({ transactions: result.data.recentTransactions || [] });
  } catch (error) {
    return res.status(error.code === 'ECONNABORTED' ? 504 : 502).json({ error: 'Upstream API unavailable' });
  }
});
app.post('/api/banking/secure-transfer/validate', (req, res) =>
  forward(req, res, '/api/banking/secure-transfer/validate'));
app.post('/api/banking/secure-transfer/execute', (req, res) =>
  forward(req, res, '/api/banking/secure-transfer/execute'));
app.use('/api', (req, res) => forward(req, res, req.originalUrl));

app.use((error, _req, res, _next) => {
  if (error instanceof SyntaxError && error.status === 400) return res.status(400).json({ error: 'Invalid JSON body' });
  if (error.type === 'entity.too.large') return res.status(413).json({ error: 'Request body exceeds 10 MB' });
  return res.status(500).json({ error: 'Request could not be processed' });
});

const port = Number(process.env.PORT || 5000);
app.listen(port, () => console.log(`CHIMERA BFF listening on port ${port}; upstream=${apiBase}`));
