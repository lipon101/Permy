/**
 * Permy Node/TypeScript SDK — typed client for the Permy Building Permit API.
 *
 * Designed for RapidAPI users: point `baseUrl` at the RapidAPI gateway and set
 * your RapidAPI key as `apiKey` (sent as `X-API-Key`). Runs on Node 18+ (uses
 * the built-in `fetch`) and in browsers.
 *
 *   import { Permy, PermyError } from "permy-sdk";
 *   const p = new Permy({ apiKey: "your-rapidapi-key", baseUrl: "https://permy-building-permit-construction-intelligence-api.p.rapidapi.com" });
 *   const permits = await p.searchPermits({ city: "Austin", trade: "roofing", limit: 25 });
 *   const cov = await p.coverage();
 *
 * All methods return parsed JSON. Non-2xx responses throw `PermyError` carrying
 * the upstream `code`, `message`, and HTTP `status` so callers can branch on
 * `quota_exceeded` / `rate_limited` / `not_found` etc.
 */

export class PermyError extends Error {
  readonly code: string;
  readonly status: number;
  readonly requestId?: string;
  readonly raw?: any;

  constructor(code: string, message: string, status: number, requestId?: string, raw?: any) {
    super(`[${status}] ${code}: ${message}`);
    this.name = "PermyError";
    this.code = code;
    this.status = status;
    this.requestId = requestId;
    this.raw = raw;
  }
}

export interface PermyOptions {
  apiKey?: string;
  baseUrl?: string;
  timeoutMs?: number;
}

export interface SearchPermitsParams {
  city?: string; state?: string; zip?: string; trade?: string;
  permit_type?: string; status?: string; contractor?: string; keyword?: string;
  min_valuation?: number; max_valuation?: number;
  issued_after?: string; issued_before?: string;
  sort?: "issued_date" | "valuation_usd" | "lead_score";
  sort_dir?: "asc" | "desc";
  page?: number; limit?: number;
}

export class Permy {
  private baseUrl: string;
  private headers: Record<string, string>;
  private timeoutMs: number;

  constructor(opts: PermyOptions = {}) {
    this.baseUrl = (opts.baseUrl ?? "https://permy-building-permit-construction-intelligence-api.p.rapidapi.com").replace(/\/+$/, "");
    this.timeoutMs = opts.timeoutMs ?? 30000;
    this.headers = { Accept: "application/json" };
    if (opts.apiKey) this.headers["X-API-Key"] = opts.apiKey;
  }

  private async request(path: string, params?: Record<string, any>, method = "GET", body?: any): Promise<any> {
    const url = new URL(this.baseUrl + path);
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
      }
    }
    const init: RequestInit = { method, headers: this.headers };
    if (body) {
      init.headers = { ...this.headers, "Content-Type": "application/json" };
      init.body = JSON.stringify(body);
    }
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), this.timeoutMs);
    let res: Response;
    try {
      res = await fetch(url.toString(), { ...init, signal: ctrl.signal });
    } catch (e: any) {
      clearTimeout(timer);
      throw new PermyError("network_error", e?.message ?? "fetch failed", 0);
    }
    clearTimeout(timer);
    const text = await res.text();
    let json: any = {};
    try { json = text ? JSON.parse(text) : {}; } catch { /* non-JSON body */ }
    if (!res.ok) {
      const err = json.error ?? {};
      throw new PermyError(err.code ?? "http_error", err.message ?? "request failed",
        res.status, json.request_id, json);
    }
    return json;
  }

  // ---- permits ----
  searchPermits(params: SearchPermitsParams = {}): Promise<any> {
    return this.request("/v1/permits/search", params as Record<string, any>);
  }
  getPermit(permitId: string): Promise<any> {
    return this.request(`/v1/permits/${encodeURIComponent(permitId)}`);
  }

  // ---- properties ----
  resolveProperty(address: string): Promise<any> {
    return this.request("/v1/properties/resolve", { address });
  }
  propertyTimeline(propertyId: string): Promise<any> {
    return this.request(`/v1/properties/${encodeURIComponent(propertyId)}/timeline`);
  }

  // ---- contractors ----
  searchContractors(params: { name?: string; trade?: string; license?: string; city?: string; page?: number; limit?: number } = {}): Promise<any> {
    return this.request("/v1/contractors/search", params as Record<string, any>);
  }
  contractorActivity(contractorId: string): Promise<any> {
    return this.request(`/v1/contractors/${encodeURIComponent(contractorId)}/activity`);
  }

  // ---- markets ----
  marketScore(zip: string): Promise<any> {
    return this.request(`/v1/markets/${encodeURIComponent(zip)}/development-score`);
  }

  // ---- leads + intelligence ----
  rankLeads(persona = "roofer", params: { trade?: string; city?: string; limit?: number } = {}): Promise<any> {
    return this.request("/v1/leads/ranked", { persona, ...params });
  }
  scoreIntelligence(opts: { address?: string; permit_id?: string; persona?: string; project_type?: string }): Promise<any> {
    return this.request("/v1/intelligence/score", undefined, "POST", opts);
  }

  // ---- alerts + webhooks ----
  createAlert(opts: { persona: string; query: Record<string, any>; webhook_url?: string }): Promise<any> {
    return this.request("/v1/alerts", undefined, "POST", opts);
  }
  listAlerts(): Promise<any> { return this.request("/v1/alerts"); }
  deleteAlert(alertId: string): Promise<any> {
    return this.request(`/v1/alerts/${encodeURIComponent(alertId)}`, undefined, "DELETE");
  }
  testWebhook(url: string, secret?: string): Promise<any> {
    return this.request("/v1/webhooks/test", undefined, "POST", secret ? { url, secret } : { url });
  }

  // ---- meta ----
  coverage(): Promise<any> { return this.request("/v1/coverage"); }
  health(): Promise<any> { return this.request("/v1/health"); }
  usage(): Promise<any> { return this.request("/v1/usage"); }

  // ---- sample mode (no key) ----
  sampleSearchPermits(params: SearchPermitsParams = {}): Promise<any> {
    return this.request("/v1/sample/permits/search", params as Record<string, any>);
  }
  sampleCoverage(): Promise<any> { return this.request("/v1/sample/coverage"); }
  sampleLeads(persona = "roofer"): Promise<any> {
    return this.request("/v1/sample/leads/ranked", { persona });
  }
}

export default Permy;
