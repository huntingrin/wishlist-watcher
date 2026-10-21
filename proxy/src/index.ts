/**
 * Wishlist Watcher proxy for a small internal test.
 *
 * The Haina API key lives only in this Worker's secret store.  Clients receive
 * an invite token and call /v1/product/search or /v1/discount/search.
 *
 * Deliberately boring: no database, no user accounts, no product quota.
 * A single Durable Object provides an atomic global daily cap and QPS guard.
 */

interface Env {
  HAINA_API_KEY: string;
  PROXY_TOKENS: string;
  DAILY_LIMIT?: string;
  GLOBAL_QPS?: string;
  CACHE_TTL_SECONDS?: string;
  LIMITER: DurableObjectNamespace;
}

type TokenInfo = { token: string; label: string };

const PRODUCT_PATH = "/v1/product/search";
const DISCOUNT_PATH = "/v1/discount/search";
const PRODUCT_UPSTREAM = "https://gw-openapi.zhidemai.com/product/v1";
const DISCOUNT_UPSTREAM = "https://gw-openapi.zhidemai.com/hj-search/discount/v2";
const MAX_BODY_BYTES = 8192;
const CACHE_MAX_ENTRIES = 200;

type CacheEntry = {
  expiresAt: number;
  body: unknown;
  status: number;
};

const responseCache = new Map<string, CacheEntry>();

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const requestId = crypto.randomUUID();
    const startedAt = Date.now();

    if (request.method === "GET" && url.pathname === "/healthz") {
      return json({
        ok: true,
        service: "wishlist-watcher-proxy",
        mode: "internal-test",
        time: new Date().toISOString(),
      });
    }

    if (request.method !== "POST") {
      return json({ error: "method_not_allowed" }, 405);
    }

    if (url.pathname !== PRODUCT_PATH && url.pathname !== DISCOUNT_PATH) {
      return json({ error: "not_found" }, 404);
    }

    const auth = authenticate(request, env);
    if (!auth) {
      return json({ error: "unauthorized", message: "邀请 token 缺失或无效" }, 401);
    }

    const rawBody = await request.text();
    if (rawBody.length > MAX_BODY_BYTES) {
      return json({ error: "payload_too_large" }, 413);
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(rawBody);
    } catch {
      return json({ error: "invalid_json" }, 400);
    }

    const validated = validatePayload(parsed, url.pathname);
    if (!validated.ok) {
      return json({ error: "invalid_payload", message: validated.error }, 422);
    }

    const dailyLimit = intFromEnv(env.DAILY_LIMIT, 2000);
    const globalQps = intFromEnv(env.GLOBAL_QPS, 4);
    const limiter = env.LIMITER.get(env.LIMITER.idFromName("global"));
    const limiterResponse = await limiter.fetch("https://limiter/check", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ dailyLimit, qps: globalQps }),
    });
    const limit = (await limiterResponse.json()) as {
      ok: boolean;
      reason?: string;
      remaining?: number;
      retry_after?: number;
    };

    if (!limit.ok) {
      const status = limit.reason === "daily" ? 429 : 429;
      const error = limit.reason === "daily" ? "daily_limit_reached" : "rate_limited";
      return json(
        {
          error,
          message:
            limit.reason === "daily"
              ? "今天的代理调用上限已到，请明天再试"
              : "请求太快，请稍后再试",
          remaining: limit.remaining ?? 0,
          retry_after: limit.retry_after ?? 1,
        },
        status,
        { "retry-after": String(limit.retry_after ?? 1) },
      );
    }

    const cacheKey = await sha256(`${url.pathname}|${JSON.stringify(validated.value)}`);
    const cached = responseCache.get(cacheKey);
    if (cached && cached.expiresAt > Date.now()) {
      logRequest(requestId, url.pathname, auth.label, 200, Date.now() - startedAt, true, 200);
      return json(withMeta(cached.body, requestId, true, limit.remaining ?? 0), cached.status);
    }

    const upstreamUrl = url.pathname === PRODUCT_PATH ? PRODUCT_UPSTREAM : DISCOUNT_UPSTREAM;
    let upstream: Response;
    try {
      upstream = await fetch(upstreamUrl, {
        method: "POST",
        headers: {
          "x-api-key": env.HAINA_API_KEY,
          "content-type": "application/json",
          accept: "application/json",
          "user-agent": "wishlist-watcher-proxy/0.1",
        },
        body: JSON.stringify(validated.value),
        signal: AbortSignal.timeout(30_000),
      });
    } catch {
      logRequest(requestId, url.pathname, auth.label, 502, Date.now() - startedAt, false, 0);
      return json({ error: "upstream_unreachable", message: "上游数据源暂时不可用" }, 502);
    }

    const upstreamText = await upstream.text();
    let upstreamJson: unknown;
    try {
      upstreamJson = JSON.parse(upstreamText);
    } catch {
      logRequest(requestId, url.pathname, auth.label, 502, Date.now() - startedAt, false, upstream.status);
      return json({ error: "upstream_invalid_response", message: "上游返回格式异常" }, 502);
    }

    if (!upstream.ok) {
      const status = upstream.status === 429 ? 429 : upstream.status === 401 || upstream.status === 403 ? 502 : 502;
      const error =
        upstream.status === 429
          ? "upstream_rate_limited"
          : upstream.status === 401 || upstream.status === 403
            ? "upstream_auth"
            : "upstream_error";
      logRequest(requestId, url.pathname, auth.label, status, Date.now() - startedAt, false, upstream.status);
      return json(
        {
          error,
          message:
            upstream.status === 429
              ? "上游限流，请稍后再试"
              : upstream.status === 401 || upstream.status === 403
                ? "代理暂时无法访问上游数据源"
                : "上游数据源返回错误",
          retry_after: upstream.status === 429 ? 1 : undefined,
        },
        status,
        upstream.status === 429 ? { "retry-after": "1" } : {},
      );
    }

    const ttl = Math.max(0, Math.min(intFromEnv(env.CACHE_TTL_SECONDS, 300), 600));
    if (ttl > 0) {
      if (responseCache.size >= CACHE_MAX_ENTRIES) {
        const oldest = responseCache.keys().next().value;
        if (oldest) responseCache.delete(oldest);
      }
      responseCache.set(cacheKey, {
        expiresAt: Date.now() + ttl * 1000,
        body: upstreamJson,
        status: 200,
      });
    }

    logRequest(requestId, url.pathname, auth.label, 200, Date.now() - startedAt, false, upstream.status);
    return json(withMeta(upstreamJson, requestId, false, limit.remaining ?? 0), 200);
  },
};

/**
 * Global limiter.  One Durable Object instance serializes all checks, so the
 * daily counter and per-second QPS guard are atomic enough for a 3–5 person
 * test without a database.
 */
export class RateLimiter {
  private state: DurableObjectState;

  constructor(state: DurableObjectState) {
    this.state = state;
  }

  async fetch(request: Request): Promise<Response> {
    if (request.method !== "POST") return json({ ok: false, error: "method_not_allowed" }, 405);

    let body: { dailyLimit?: number; qps?: number };
    try {
      body = (await request.json()) as { dailyLimit?: number; qps?: number };
    } catch {
      return json({ ok: false, error: "invalid_json" }, 400);
    }

    const dailyLimit = Math.max(1, Math.min(Number(body.dailyLimit) || 2000, 100_000));
    const qps = Math.max(1, Math.min(Number(body.qps) || 4, 50));
    const now = Date.now();
    const dayKey = new Date(now).toISOString().slice(0, 10);
    const secondKey = Math.floor(now / 1000);

    const stored = (await this.state.storage.get<{
      dayKey?: string;
      dayCount?: number;
      secondKey?: number;
      secondCount?: number;
    }>("counter")) ?? {};

    let dayCount = stored.dayKey === dayKey ? stored.dayCount ?? 0 : 0;
    let secondCount = stored.secondKey === secondKey ? stored.secondCount ?? 0 : 0;

    if (dayCount >= dailyLimit) {
      return json({
        ok: false,
        reason: "daily",
        remaining: 0,
        retry_after: secondsUntilUtcMidnight(now),
      });
    }

    if (secondCount >= qps) {
      return json({
        ok: false,
        reason: "qps",
        remaining: Math.max(0, dailyLimit - dayCount),
        retry_after: 1,
      });
    }

    dayCount += 1;
    secondCount += 1;
    await this.state.storage.put("counter", {
      dayKey,
      dayCount,
      secondKey,
      secondCount,
    });

    return json({
      ok: true,
      remaining: Math.max(0, dailyLimit - dayCount),
      day: dayKey,
    });
  }
}

function authenticate(request: Request, env: Env): TokenInfo | null {
  const authorization = request.headers.get("authorization") ?? "";
  const token = authorization.toLowerCase().startsWith("bearer ")
    ? authorization.slice(7).trim()
    : (request.headers.get("x-proxy-token") ?? "").trim();
  if (!token) return null;

  const tokens = parseTokens(env.PROXY_TOKENS ?? "");
  const label = tokens.get(token);
  return label ? { token, label } : null;
}

function parseTokens(raw: string): Map<string, string> {
  const map = new Map<string, string>();
  const trimmed = raw.trim();
  if (!trimmed) return map;

  try {
    const parsed = JSON.parse(trimmed);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      for (const [token, label] of Object.entries(parsed)) {
        if (typeof label === "string" && label.trim()) {
          map.set(token, label.trim().slice(0, 40));
        }
      }
      return map;
    }
  } catch {
    // Fall back to comma-separated tokens.
  }

  for (const part of trimmed.split(",")) {
    const token = part.trim();
    if (token) map.set(token, "tester");
  }
  return map;
}

function validatePayload(
  input: unknown,
  route: string,
): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    return { ok: false, error: "body 必须是 JSON 对象" };
  }
  const body = input as Record<string, unknown>;
  const query = body.product_query;
  if (typeof query !== "string" || !query.trim()) {
    return { ok: false, error: "product_query 必填" };
  }
  if (query.trim().length > 100) {
    return { ok: false, error: "product_query 不能超过 100 字" };
  }

  const rawSize = body.size ?? 5;
  const size = Number(rawSize);
  if (!Number.isInteger(size) || size < 1 || size > 10) {
    return { ok: false, error: "size 必须是 1–10 的整数" };
  }

  const allowed = [
    "product_query",
    "request_from",
    "question_id",
    "query_process",
    "size",
    "mall_id",
    "brand_name",
    "category_name",
    "min_price",
    "max_price",
    "sort",
    "fields",
  ];
  const value: Record<string, unknown> = {};
  for (const key of allowed) {
    if (key in body) value[key] = body[key];
  }

  value.product_query = query.trim();
  value.request_from =
    typeof body.request_from === "string" && body.request_from.trim()
      ? body.request_from.trim().slice(0, 50)
      : "wishlist-watcher-proxy";
  value.question_id =
    typeof body.question_id === "string" && body.question_id.trim()
      ? body.question_id.trim().slice(0, 80)
      : crypto.randomUUID();
  value.query_process = 1;
  value.size = route === PRODUCT_PATH ? Math.min(size, 10) : Math.min(size, 10);

  if (typeof value.fields === "string" && value.fields.length > 500) {
    return { ok: false, error: "fields 太长" };
  }

  return { ok: true, value };
}

function withMeta(body: unknown, requestId: string, cached: boolean, remaining: number): unknown {
  if (body && typeof body === "object" && !Array.isArray(body)) {
    return {
      ...(body as Record<string, unknown>),
      _meta: { request_id: requestId, cached, remaining },
    };
  }
  return { data: body, _meta: { request_id: requestId, cached, remaining } };
}

function logRequest(
  requestId: string,
  route: string,
  tester: string,
  status: number,
  ms: number,
  cached: boolean,
  upstreamStatus: number,
): void {
  console.log(
    JSON.stringify({
      event: "proxy_request",
      request_id: requestId,
      route,
      tester,
      status,
      ms,
      cached,
      upstream_status: upstreamStatus,
    }),
  );
}

function intFromEnv(value: string | undefined, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
}

function secondsUntilUtcMidnight(now: number): number {
  const date = new Date(now);
  const midnight = Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate() + 1);
  return Math.max(1, Math.ceil((midnight - now) / 1000));
}

function json(data: unknown, status = 200, extraHeaders: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      ...extraHeaders,
    },
  });
}

async function sha256(input: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}
