// Session / token handling for the web app.
//
// SMOKE TEST FIXTURE — clean counterpart to bad_02_auth.js.
// Expected: PASS with no critical or high findings.

const crypto = require("crypto");
const argon2 = require("argon2");

const JWT_SIGNING_SECRET = process.env.JWT_SIGNING_SECRET;
if (!JWT_SIGNING_SECRET) {
  throw new Error("JWT_SIGNING_SECRET must be set");
}

const ALLOWED_FILTER_FIELDS = new Set(["status", "createdAt", "ownerId"]);

/**
 * Parse a client-supplied filter into a safe query object.
 * Only known fields are accepted; everything else is rejected.
 */
function parseUserFilter(rawFilter) {
  let parsed;
  try {
    parsed = JSON.parse(rawFilter ?? "{}");
  } catch {
    throw new Error("filter must be valid JSON");
  }

  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("filter must be a JSON object");
  }

  const filter = {};
  for (const [key, value] of Object.entries(parsed)) {
    if (!ALLOWED_FILTER_FIELDS.has(key)) {
      throw new Error(`unsupported filter field: ${key}`);
    }
    if (typeof value !== "string" && typeof value !== "number") {
      throw new Error(`filter value for ${key} must be a string or number`);
    }
    filter[key] = value;
  }
  return filter;
}

/** Constant-time comparison so token checks do not leak length or content. */
function tokensMatch(provided, expected) {
  const a = Buffer.from(String(provided));
  const b = Buffer.from(String(expected));
  if (a.length !== b.length) {
    return false;
  }
  return crypto.timingSafeEqual(a, b);
}

async function login(req, res, next) {
  try {
    const { email, password } = req.body ?? {};
    if (typeof email !== "string" || typeof password !== "string") {
      return res.status(400).json({ error: "email and password are required" });
    }

    const user = await db.users.findOne({ email });

    // Same response and comparable timing whether or not the user exists.
    const passwordOk = user
      ? await argon2.verify(user.passwordHash, password)
      : await argon2.verify(DUMMY_HASH, password).catch(() => false);

    if (!user || !passwordOk) {
      logger.info("failed login", { email });
      return res.status(401).json({ error: "invalid credentials" });
    }

    await auditLog.record({ userId: user.id, action: "login" });

    return res.json({ token: signToken(user.id, JWT_SIGNING_SECRET) });
  } catch (err) {
    return next(err);
  }
}

module.exports = { parseUserFilter, tokensMatch, login };
