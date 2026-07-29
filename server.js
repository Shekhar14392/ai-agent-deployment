// server.js — the entire backend-for-the-frontend in one file:
// static site + admin panel + PayPal payments + backend proxy.
// (Consolidated from server.js + api/_paypal.js + create-paypal-order.js +
//  capture-paypal-order.js + paypal-return.js)

import express from 'express';
import bodyParser from 'body-parser';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();
app.use(bodyParser.json());

// ---------------------------------------------------------- PayPal helpers --

const PAYPAL_BASE = process.env.PAYPAL_ENV === 'live'
  ? 'https://api-m.paypal.com'
  : 'https://api-m.sandbox.paypal.com';

const PLAN_PRICES_USD = { growth: '49.00', enterprise: '249.00' };

async function getPayPalAccessToken() {
  const clientId = process.env.PAYPAL_CLIENT_ID;
  const clientSecret = process.env.PAYPAL_CLIENT_SECRET;
  if (!clientId || !clientSecret) {
    throw new Error('PayPal is not configured on the server (missing client ID/secret).');
  }
  const auth = Buffer.from(`${clientId}:${clientSecret}`).toString('base64');
  const res = await fetch(`${PAYPAL_BASE}/v1/oauth2/token`, {
    method: 'POST',
    headers: { Authorization: `Basic ${auth}`, 'Content-Type': 'application/x-www-form-urlencoded' },
    body: 'grant_type=client_credentials',
  });
  if (!res.ok) throw new Error(`PayPal auth failed: ${res.status}`);
  const data = await res.json();
  return data.access_token;
}

// ------------------------------------------------------------ PayPal routes --

app.post('/api/create-paypal-order', async (req, res) => {
  try {
    const { plan } = req.body;
    const amount = PLAN_PRICES_USD[plan];
    if (!amount) return res.status(400).json({ error: 'Unknown plan.' });

    const accessToken = await getPayPalAccessToken();
    const origin = req.headers.origin || `https://${req.headers.host}`;

    const orderRes = await fetch(`${PAYPAL_BASE}/v2/checkout/orders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({
        intent: 'CAPTURE',
        purchase_units: [{
          reference_id: plan,
          description: `Global AI Solutions — ${plan} plan (monthly)`,
          amount: { currency_code: 'USD', value: amount },
        }],
        application_context: {
          brand_name: 'Global AI Solutions',
          user_action: 'PAY_NOW',
          return_url: `${origin}/api/paypal-return?plan=${plan}`,
          cancel_url: `${origin}/#pricing`,
        },
      }),
    });

    const order = await orderRes.json();
    if (!orderRes.ok) {
      console.error('PayPal order creation failed:', order);
      return res.status(502).json({ error: 'Could not create PayPal order.' });
    }
    const approveLink = order.links?.find((l) => l.rel === 'approve')?.href;
    res.status(200).json({ orderId: order.id, approveUrl: approveLink });
  } catch (err) {
    console.error('create-paypal-order error:', err);
    res.status(500).json({ error: err.message || 'Could not start PayPal checkout.' });
  }
});

app.post('/api/capture-paypal-order', async (req, res) => {
  try {
    const { orderId } = req.body;
    if (!orderId) return res.status(400).json({ error: 'orderId is required.' });

    const accessToken = await getPayPalAccessToken();
    const captureRes = await fetch(`${PAYPAL_BASE}/v2/checkout/orders/${orderId}/capture`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}` },
    });
    const capture = await captureRes.json();
    if (!captureRes.ok) {
      console.error('PayPal capture failed:', capture);
      return res.status(502).json({ error: 'Payment could not be captured.' });
    }

    const status = capture.status; // "COMPLETED" on success
    const plan = capture.purchase_units?.[0]?.reference_id;
    const payerEmail = capture.payer?.email_address;

    // TODO: call your backend to activate the subscription for this payer, e.g.
    // await fetch(`${process.env.BACKEND_URL}/api/v1/subscriptions/activate`, { ... });

    res.status(200).json({ status, plan, payerEmail });
  } catch (err) {
    console.error('capture-paypal-order error:', err);
    res.status(500).json({ error: err.message || 'Could not capture payment.' });
  }
});

app.get('/api/paypal-return', (req, res) => {
  const { token, PayerID, plan, source } = req.query;

  if (source === 'app') {
    const deepLink = `globalaisolutions://paypal-return?token=${token}&payerId=${PayerID}&plan=${plan || ''}`;
    res.set('Content-Type', 'text/html');
    return res.send(`
      <!DOCTYPE html><html><head><meta http-equiv="refresh" content="0;url=${deepLink}"></head>
      <body><p>Returning to Global AI Solutions app…</p>
      <script>window.location.href = "${deepLink}";</script></body></html>
    `);
  }

  res.set('Content-Type', 'text/html');
  res.send(`
    <!DOCTYPE html><html><head><title>Payment approved</title></head>
    <body style="font-family:sans-serif; text-align:center; padding:60px;">
      <h2>Payment approved — finishing up…</h2>
      <p>You can close this tab if it doesn't redirect automatically.</p>
      <script>
        fetch('/api/capture-paypal-order', {
          method: 'POST', headers: {'Content-Type':'application/json'},
          body: JSON.stringify({ orderId: '${token}' })
        }).then(() => window.location.href = '/success?plan=${plan || ''}');
      </script>
    </body></html>
  `);
});

app.get('/healthz', (req, res) => res.json({ status: 'ok' }));

// ------------------------------------------------------ backend API proxy --
// Keeps auth/wallet/agents reachable from the SAME url as the site — one
// address to remember, whether you're on a phone or a desktop.

const BACKEND_URL = process.env.BACKEND_URL;

app.use('/api/v1', async (req, res) => {
  if (!BACKEND_URL) return res.status(503).json({ error: 'Backend not configured yet — set BACKEND_URL.' });
  try {
    const response = await fetch(`${BACKEND_URL}/api/v1${req.url}`, {
      method: req.method,
      headers: {
        'Content-Type': 'application/json',
        ...(req.headers.authorization ? { Authorization: req.headers.authorization } : {}),
      },
      body: ['GET', 'HEAD'].includes(req.method) ? undefined : JSON.stringify(req.body),
    });
    const data = await response.json().catch(() => ({}));
    res.status(response.status).json(data);
  } catch (err) {
    console.error('Backend proxy error:', err);
    res.status(502).json({ error: 'Could not reach backend.' });
  }
});

// --------------------------------------------------- static site + admin --

app.use(express.static(path.join(__dirname), { extensions: ['html'] }));
app.get('/admin', (req, res) => res.sendFile(path.join(__dirname, 'admin', 'index.html')));
app.get('*', (req, res) => res.sendFile(path.join(__dirname, 'index.html')));

const PORT = process.env.PORT || 4000;
app.listen(PORT, () => console.log(`Global AI Solutions site+API listening on :${PORT}`));
