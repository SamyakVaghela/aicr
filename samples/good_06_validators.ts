// Request validation helpers for the public API.
//
// SMOKE TEST FIXTURE — clean TypeScript.
// Expected: PASS with no critical or high findings.

export type ValidationError = {
  field: string;
  message: string;
};

export type Validated<T> =
  | { ok: true; value: T }
  | { ok: false; errors: ValidationError[] };

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const MAX_EMAIL_LENGTH = 254;
const MAX_PAGE_SIZE = 100;

export interface CreateUserInput {
  email: string;
  displayName: string;
  marketingOptIn: boolean;
}

export function validateCreateUser(raw: unknown): Validated<CreateUserInput> {
  const errors: ValidationError[] = [];

  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return { ok: false, errors: [{ field: "_root", message: "body must be an object" }] };
  }

  const body = raw as Record<string, unknown>;

  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  if (!email) {
    errors.push({ field: "email", message: "email is required" });
  } else if (email.length > MAX_EMAIL_LENGTH) {
    errors.push({ field: "email", message: `email must be at most ${MAX_EMAIL_LENGTH} characters` });
  } else if (!EMAIL_RE.test(email)) {
    errors.push({ field: "email", message: "email is not a valid address" });
  }

  const displayName = typeof body.displayName === "string" ? body.displayName.trim() : "";
  if (displayName.length < 1 || displayName.length > 80) {
    errors.push({ field: "displayName", message: "displayName must be 1-80 characters" });
  }

  const marketingOptIn = body.marketingOptIn;
  if (typeof marketingOptIn !== "boolean") {
    errors.push({ field: "marketingOptIn", message: "marketingOptIn must be a boolean" });
  }

  if (errors.length > 0) {
    return { ok: false, errors };
  }

  return {
    ok: true,
    value: { email, displayName, marketingOptIn: marketingOptIn as boolean },
  };
}

export interface Pagination {
  limit: number;
  offset: number;
}

/** Clamp caller-supplied paging into a bounded range so queries stay cheap. */
export function parsePagination(query: Record<string, unknown>): Pagination {
  const rawLimit = Number(query.limit);
  const rawOffset = Number(query.offset);

  const limit = Number.isFinite(rawLimit)
    ? Math.min(Math.max(Math.trunc(rawLimit), 1), MAX_PAGE_SIZE)
    : 25;

  const offset = Number.isFinite(rawOffset) ? Math.max(Math.trunc(rawOffset), 0) : 0;

  return { limit, offset };
}
