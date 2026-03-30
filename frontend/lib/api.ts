import type {
  SearchResult,
  SummaryStatusResponse,
  ExecutiveSummary,
  SynthesisResult,
} from './types';

const BASE = 'http://localhost:8000/api/v1';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) {
        detail = typeof body.detail === 'string'
          ? body.detail
          : JSON.stringify(body.detail);
      }
    } catch {
      // ignore parse error — use status text
    }
    const err = new Error(detail) as Error & { status: number };
    err.status = res.status;
    throw err;
  }

  return res.json() as Promise<T>;
}

// ── Papers ─────────────────────────────────────────────────────────────────

export interface SearchParams {
  limit?: number;
  year_min?: number;
  year_max?: number;
  fields_of_study?: string[];
  open_access_only?: boolean;
}

export function searchPapers(
  query: string,
  params: SearchParams = {},
): Promise<SearchResult[]> {
  const qs = new URLSearchParams({ query });
  if (params.limit)           qs.set('limit', String(params.limit));
  if (params.year_min)        qs.set('year_min', String(params.year_min));
  if (params.year_max)        qs.set('year_max', String(params.year_max));
  if (params.open_access_only) qs.set('open_access_only', 'true');
  params.fields_of_study?.forEach((f) => qs.append('fields_of_study', f));
  return request<SearchResult[]>(`/papers/search?${qs}`);
}

// ── Summaries ──────────────────────────────────────────────────────────────

export function requestSummary(paper_id: string): Promise<SummaryStatusResponse> {
  return request<SummaryStatusResponse>('/summaries/request', {
    method: 'POST',
    body: JSON.stringify({ paper_id }),
  });
}

export function getSummaryStatus(paper_id: string): Promise<SummaryStatusResponse> {
  return request<SummaryStatusResponse>(
    `/summaries/${encodeURIComponent(paper_id)}/status`,
  );
}

export function getSummary(paper_id: string): Promise<ExecutiveSummary> {
  return request<ExecutiveSummary>(
    `/summaries/${encodeURIComponent(paper_id)}`,
  );
}

export function getLibrary(): Promise<ExecutiveSummary[]> {
  return request<ExecutiveSummary[]>('/summaries/');
}

// ── Synthesis ──────────────────────────────────────────────────────────────

export async function createSynthesis(
  paper_ids: string[],
): Promise<SynthesisResult> {
  try {
    return await request<SynthesisResult>('/synthesis/', {
      method: 'POST',
      body: JSON.stringify({ paper_ids }),
    });
  } catch (err) {
    // Re-throw with the 422 detail message intact
    throw err;
  }
}
