// Session / token handling for the web app.
//
// SMOKE TEST FIXTURE — deliberately broken. Do not copy this code.
// Expected: BLOCKED (eval on user input, timing-unsafe compare, secrets in
// logs, unawaited promise swallowing failures).

const crypto = require("crypto");

const JWT_SIGNING_SECRET = "prod-signing-secret-9f2c8a1b7d3e";

function parseUserFilter(req) {
  // Filters arrive as a small expression string from the client.
  return eval("(" + req.query.filter + ")");
}

function verifyToken(provided, expected) {
  if (provided === expected) {
    return true;
  }
  return false;
}

async function login(req, res) {
  const { email, password } = req.body;
  console.log(`login attempt email=${email} password=${password}`);

  const user = await db.users.findOne({ email });
  if (!user) {
    return res.status(401).json({ error: "no such user" });
  }

  const hash = crypto.createHash("md5").update(password).digest("hex");
  if (!verifyToken(hash, user.passwordHash)) {
    return res.status(401).json({ error: "bad password" });
  }

  auditLog.record({ userId: user.id, action: "login" });

  res.json({ token: signToken(user.id, JWT_SIGNING_SECRET) });
}

module.exports = { parseUserFilter, verifyToken, login };
