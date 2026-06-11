// A small typed client over the central server's OPEN read endpoints (E-06: reads
// need no auth). `fetch` is injectable so tests run with a fake — NO real network.
import type {
  ApplyFixResponse,
  ConfigDocumentTree,
  ConfigEdit,
  CoverageSnapshot,
  EditableConfigTree,
  GenerateRequest,
  GenerateResponse,
  RegisteredRepo,
  RepoHealth,
  RepoStatus,
  ResolutionRecord,
  ReviewRecord,
  StoredConfigEdit,
  SyncMode,
  SyncRun,
} from "../types";

/** Server-side query filters for `GET /repos/{id}/records` (all optional). */
export interface RecordFilters {
  verdict?: string;
  drift_kind?: string;
  audience?: string;
  doc_id?: string;
  limit?: number;
  offset?: number;
}

/** Build a `?a=b&...` query string, dropping empty/undefined values. */
function buildQuery(params: Record<string, string | number | undefined>): string {
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    const str = String(value);
    if (str === "") continue;
    usp.set(key, str);
  }
  const qs = usp.toString();
  return qs ? `?${qs}` : "";
}

type FetchImpl = typeof fetch;

export interface ApiClientOptions {
  /** API base URL. Default: `import.meta.env.VITE_API_BASE` ?? "/api". */
  baseUrl?: string;
  /** Injectable fetch (tests pass a fake to capture requests). Default: global. */
  fetchImpl?: FetchImpl;
}

/** Thrown on a non-2xx response so callers can render an error state. */
export class ApiError extends Error {
  readonly status: number;
  readonly url: string;
  constructor(status: number, url: string) {
    super(`API request to ${url} failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.url = url;
  }
}

function defaultBaseUrl(): string {
  // EPIC ASTRO single-origin deploy: FastAPI serves BOTH the API and this site,
  // so the default base is "" (same-origin root) — fetches hit `/health`,
  // `/repos`, … directly. An explicit `PUBLIC_API_BASE` overrides verbatim (e.g.
  // "/api" for an `astro dev` proxy, or an absolute URL for a split deploy).
  const fromEnv = import.meta.env?.PUBLIC_API_BASE;
  return typeof fromEnv === "string" ? fromEnv : "";
}

/**
 * Encode a repo_id for a URL path WITHOUT escaping `/` — repo_ids may be the
 * `org/name` form and the server route is `{repo_id:path}` (slashes preserved).
 */
function encodeRepoId(repoId: string): string {
  return repoId
    .split("/")
    .map((seg) => encodeURIComponent(seg))
    .join("/");
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: FetchImpl;

  constructor(opts: ApiClientOptions = {}) {
    this.baseUrl = (opts.baseUrl ?? defaultBaseUrl()).replace(/\/$/, "");
    // Default to a LAZY global lookup (not a bound reference) so a test that
    // swaps `globalThis.fetch` (e.g. vi.stubGlobal) is honored by the shared
    // singleton too. An explicitly injected `fetchImpl` is used verbatim.
    this.fetchImpl =
      opts.fetchImpl ?? ((...args) => globalThis.fetch(...args));
  }

  private async getJson<T>(path: string): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const resp = await this.fetchImpl(url, {
      method: "GET",
      headers: { Accept: "application/json" },
    });
    if (!resp.ok) {
      throw new ApiError(resp.status, url);
    }
    return (await resp.json()) as T;
  }

  /**
   * POST a JSON body, optionally with a Bearer token (the WRITE path; F-04).
   * An EMPTY/absent token omits the `Authorization` header entirely — so an OPEN
   * (standalone, L-01) repo accepts the write, while a token-protected repo still
   * gets a 401/403 the caller can react to. A non-empty token sends the bearer.
   */
  private async postJson<T>(path: string, body: unknown, token: string): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const headers: Record<string, string> = {
      Accept: "application/json",
      "Content-Type": "application/json",
    };
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
    const resp = await this.fetchImpl(url, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      throw new ApiError(resp.status, url);
    }
    return (await resp.json()) as T;
  }

  /** GET {base}/health → liveness probe ({status:"ok"}); drives the shell's
   *  connection indicator. Any 2xx means the central server is reachable. */
  ping(): Promise<{ status: string }> {
    return this.getJson<{ status: string }>("/health");
  }

  /** GET {base}/repos → RegisteredRepo[]. */
  listRepos(): Promise<RegisteredRepo[]> {
    return this.getJson<RegisteredRepo[]>("/repos");
  }

  /** GET {base}/repos/{repoId}/status → RepoStatus. */
  repoStatus(repoId: string): Promise<RepoStatus> {
    return this.getJson<RepoStatus>(`/repos/${encodeRepoId(repoId)}/status`);
  }

  /**
   * GET {base}/repos/{repoId}/records[?verdict&drift_kind&audience&doc_id&limit&offset]
   * → ReviewRecord[]. Filters map 1:1 to the E-05 query params (reads are OPEN).
   */
  recordsFor(repoId: string, filters: RecordFilters = {}): Promise<ReviewRecord[]> {
    const query = buildQuery({ ...filters });
    return this.getJson<ReviewRecord[]>(
      `/repos/${encodeRepoId(repoId)}/records${query}`,
    );
  }

  /** GET {base}/repos/{repoId}/resolutions → ResolutionRecord[]. */
  resolutionsFor(repoId: string): Promise<ResolutionRecord[]> {
    return this.getJson<ResolutionRecord[]>(
      `/repos/${encodeRepoId(repoId)}/resolutions`,
    );
  }

  /** GET {base}/repos/{repoId}/coverage → CoverageSnapshot[] (latest last). */
  coverageFor(repoId: string): Promise<CoverageSnapshot[]> {
    return this.getJson<CoverageSnapshot[]>(
      `/repos/${encodeRepoId(repoId)}/coverage`,
    );
  }

  /**
   * POST {base}/repos/{repoId}/resolutions — the FIRST write path (F-04). Sends the
   * SHARED `ResolutionRecord` with `Authorization: Bearer <token>`; returns the
   * server's `{ record_id }`. A non-2xx (401/403/404) → a thrown `ApiError`.
   */
  resolve(
    repoId: string,
    rec: ResolutionRecord,
    token: string,
  ): Promise<{ record_id: string }> {
    return this.postJson<{ record_id: string }>(
      `/repos/${encodeRepoId(repoId)}/resolutions`,
      rec,
      token,
    );
  }

  /** GET {base}/repos/{repoId}/health → RepoHealth (an OPEN computed view, F-05). */
  healthFor(repoId: string): Promise<RepoHealth> {
    return this.getJson<RepoHealth>(`/repos/${encodeRepoId(repoId)}/health`);
  }

  /**
   * GET {base}/config/templates → the canonical config/cdmon/ template strings
   * (W-02). A GLOBAL, public reference (no auth, no repo): the four template
   * bodies the Config page renders so adopters can copy the v2 format.
   */
  configTemplates(): Promise<{
    unit: string;
    index: string;
    ignore: string;
    doc_style: string;
  }> {
    return this.getJson<{
      unit: string;
      index: string;
      ignore: string;
      doc_style: string;
    }>("/config/templates");
  }

  /**
   * GET {base}/repos/{repoId}/documents?sync_kind=... → ConfigDocumentTree[] (W-01).
   * ALWAYS sends `sync_kind` (default "git") — the unfiltered endpoint mixes the
   * git + local rows. Each tree is a document plus the code_refs it owns.
   */
  documentsFor(
    repoId: string,
    syncKind = "git",
  ): Promise<ConfigDocumentTree[]> {
    const query = buildQuery({ sync_kind: syncKind });
    // W-03 fix: use the SAME slash-preserving `encodeRepoId` as every other method
    // (the server route is `{repo_id:path}`). Previously this lone method used
    // `encodeURIComponent` (slash → %2F) — an inconsistency from W-01.
    return this.getJson<ConfigDocumentTree[]>(
      `/repos/${encodeRepoId(repoId)}/documents${query}`,
    );
  }

  /**
   * POST {base}/repos/{repoId}/sync — trigger a sync (Y-02; the WRITE path).
   * Sends `{mode}` with `Authorization: Bearer <token>` (mirrors {@link resolve});
   * returns the SyncRun summary. A non-2xx (401/403/404/400) → a thrown `ApiError`.
   */
  syncRepo(repoId: string, mode: SyncMode, token: string): Promise<SyncRun> {
    return this.postJson<SyncRun>(
      `/repos/${encodeRepoId(repoId)}/sync`,
      { mode },
      token,
    );
  }

  /**
   * GET {base}/repos/{repoId}/sync-state[?sync_kind=...] → the latest SyncRun, or
   * `null` when the repo has never been synced (Y-02; an OPEN read). Passes
   * `sync_kind` only when given (otherwise the server picks the latest run).
   */
  syncState(repoId: string, syncKind?: SyncMode): Promise<SyncRun | null> {
    const query = buildQuery({ sync_kind: syncKind });
    return this.getJson<SyncRun | null>(
      `/repos/${encodeRepoId(repoId)}/sync-state${query}`,
    );
  }

  /**
   * GET {base}/repos/{repoId}/config/editable[?sync_kind=...] → EditableConfigTree
   * (EDITOR E-04; an OPEN read). The editable document↔code mapping plus the
   * working-tree-derived gap + selectable doc-style options the Mapping page renders.
   * Passes `sync_kind` only when given (the server defaults to "local").
   */
  configEditable(repoId: string, syncKind?: SyncMode): Promise<EditableConfigTree> {
    const query = buildQuery({ sync_kind: syncKind });
    return this.getJson<EditableConfigTree>(
      `/repos/${encodeRepoId(repoId)}/config/editable${query}`,
    );
  }

  /**
   * POST {base}/repos/{repoId}/config/edits — stage one mapping "ticket" (EDITOR
   * E-05; the WRITE path). Sends the typed {@link ConfigEdit} with
   * `Authorization: Bearer <token>` (mirrors {@link syncRepo}); returns the
   * server's `{ edit_id }`. A non-2xx (401/403/404/422) → a thrown `ApiError`.
   */
  stageConfigEdit(
    repoId: string,
    edit: ConfigEdit,
    token: string,
  ): Promise<{ edit_id: string }> {
    return this.postJson<{ edit_id: string }>(
      `/repos/${encodeRepoId(repoId)}/config/edits`,
      edit,
      token,
    );
  }

  /**
   * GET {base}/repos/{repoId}/config/edits[?status=...] → StoredConfigEdit[]
   * (EDITOR E-05; an OPEN read). The staged edits in insertion order, optionally
   * filtered by `status` ("pending"/"applied"/"discarded").
   */
  listConfigEdits(repoId: string, status?: string): Promise<StoredConfigEdit[]> {
    const query = buildQuery({ status });
    return this.getJson<StoredConfigEdit[]>(
      `/repos/${encodeRepoId(repoId)}/config/edits${query}`,
    );
  }

  /**
   * POST {base}/repos/{repoId}/config/generate — make staged edits live (EDITOR
   * E-06; the WRITE path). Sends the {@link GenerateRequest} body with
   * `Authorization: Bearer <token>` (mirrors {@link syncRepo}); returns the
   * {@link GenerateResponse} (applied ids + fresh sync_run + recomputed gap).
   */
  generateConfig(
    repoId: string,
    body: GenerateRequest,
    token: string,
  ): Promise<GenerateResponse> {
    return this.postJson<GenerateResponse>(
      `/repos/${encodeRepoId(repoId)}/config/generate`,
      body,
      token,
    );
  }

  /**
   * POST {base}/repos/{repoId}/records/{recordId}/apply-fix — apply the record's
   * LLM-proposed fix to the doc on disk (EDITOR E-07; the WRITE path). Sends an
   * empty body `{}` with `Authorization: Bearer <token>` (mirrors {@link syncRepo});
   * returns the {@link ApplyFixResponse}. The `recordId` is encoded with the same
   * slash-preserving helper as the repo id (record ids may carry path-like chars).
   */
  applyRecordFix(
    repoId: string,
    recordId: string,
    token: string,
  ): Promise<ApplyFixResponse> {
    return this.postJson<ApplyFixResponse>(
      `/repos/${encodeRepoId(repoId)}/records/${encodeRepoId(recordId)}/apply-fix`,
      {},
      token,
    );
  }
}

/** A shared default client (prod uses VITE_API_BASE; tests inject their own). */
export const apiClient = new ApiClient();
