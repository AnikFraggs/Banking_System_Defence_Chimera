const express = require('express');
const { Pool } = require('pg');
const { createClient } = require('redis');
const cors = require('cors');
const axios = require('axios');

const app = express();
app.use(cors());
app.use(express.json());

// --- INFRASTRUCTURE CONNECTIONS ---
// SSD Layer: PostgreSQL (Permanent cold storage)
const pg = new Pool({ connectionString: process.env.DATABASE_URL });

// Cache Layer: Redis (L1/L2 Hot Data)
const redis = createClient({ url: process.env.REDIS_URL });
redis.connect().catch(console.error);

// --- MEMORY HIERARCHY SIMULATION ---
// VRAM / Register (Ultra-fast Node.js memory for active threats/RL states)
const VRAM = new Map(); 

// RAM (Active session buffers)
const RAM = new Map(); 


// --- TRIE & BLOOM FILTER ROUTING ---
class RouteNode {
    constructor() {
        this.children = {};
        this.bloom = new Set(); // Simplified Bloom Filter
        this.targetLayer = null;
    }
}

const rootTrie = new RouteNode();

function insertRoute(path, layer) {
    let node = rootTrie;
    for (const char of path) {
        if (!node.children[char]) node.children[char] = new RouteNode();
        node = node.children[char];
        node.bloom.add(path); // Add to bloom filter at each step
    }
    node.targetLayer = layer;
}

function routeRequest(path) {
    let node = rootTrie;
    for (const char of path) {
        if (!node.children[char] || !node.bloom.has(path)) return 'SSD'; // Prune early
        node = node.children[char];
    }
    return node.targetLayer;
}

// Register API routes to specific memory layers
insertRoute('/api/market/overview', 'VRAM');      // Live stocks -> VRAM
insertRoute('/api/banking/dashboard', 'CACHE');   // User balance -> Redis
insertRoute('/api/banking/transactions', 'SSD');  // History -> Postgres


// --- MIDDLEWARE: The Processor Engine ---
app.use(async (req, res, next) => {
    const targetLayer = routeRequest(req.path);
    req.targetLayer = targetLayer; // Attach to request
    
    // Quantization logic: If under attack, strip payload to integers
    if (req.body.threatLevel === 'HIGH') {
        req.body = { amount: Number(req.body.amount), flag: 1 }; // Strip metadata
    }
    
    next();
});


// --- ENDPOINTS ---

// 1. VRAM Layer Endpoint (Live Market)
app.get('/api/market/overview', async (req, res) => {
    // In VRAM, data updates in microseconds. We serve from local memory.
    if (VRAM.has('market')) {
        return res.json({ ...VRAM.get('market'), layer: 'VRAM (GPU/Register)', latency: '0.1ms' });
    }
    // Fallback to Java API if not in VRAM
    const response = await axios.get(`${process.env.JAVA_API_URL}/api/market/overview`, { headers: { Authorization: req.headers.authorization } });
    VRAM.set('market', response.data);
    res.json({ ...response.data, layer: 'SSD -> VRAM (Loaded)', latency: '12ms' });
});

// 2. CACHE Layer Endpoint (Dashboard)
app.get('/api/banking/dashboard', async (req, res) => {
    const cacheKey = `dashboard:${req.headers.authorization}`;
    
    // Check Redis (L1/L2 Cache)
    const cached = await redis.get(cacheKey);
    if (cached) {
        return res.json({ ...JSON.parse(cached), layer: 'L1/L2 Cache (Redis)', latency: '1ms' });
    }
    
    // Cache miss -> Fetch from Java API
    const response = await axios.get(`${process.env.JAVA_API_URL}/api/banking/dashboard`, { headers: { Authorization: req.headers.authorization } });
    await redis.setEx(cacheKey, 60, JSON.stringify(response.data)); // Cache for 60 seconds
    res.json({ ...response.data, layer: 'RAM -> Cache (Loaded)', latency: '45ms' });
});

// 3. SSD Layer Endpoint (Transaction History - Permanent Storage)
app.get('/api/banking/transactions', async (req, res) => {
    // Directly query PostgreSQL (SSD)
    try {
        const result = await pg.query('SELECT * FROM transactions ORDER BY timestamp DESC LIMIT 10');
        res.json({ transactions: result.rows, layer: 'SSD (PostgreSQL)', latency: '15ms' });
    } catch (err) {
        res.status(500).json({ error: 'Database query failed' });
    }
});

// 4. Secure Transfer (Write-through cache to SSD)
app.post('/api/banking/secure-transfer/execute', async (req, res) => {
    const { amount, beneficiary, method } = req.body;
    
    // 1. Write to SSD (Postgres) - Immutable Ledger
    await pg.query(
        'INSERT INTO transactions (type, amount, counterparty, status) VALUES ($1, $2, $3, $4)',
        ['TRANSFER', parseFloat(amount), beneficiary, 'COMPLETED']
    );
    
    // 2. Invalidate Cache (Redis)
    await redis.del(`dashboard:${req.headers.authorization}`);
    
    // 3. Return success
    res.json({ status: 'SUCCESS', message: `Transferred ₹${amount} to ${beneficiary} via ${method}. Written to SSD.` });
});

app.listen(5000, () => console.log('⚡ CHIMERA Express Processor Engine running on port 5000'));