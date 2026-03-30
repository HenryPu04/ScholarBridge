// ── Paper ──────────────────────────────────────────────────────────────────

export interface Author {
  author_id?: string | null;
  name: string;
}

export interface OpenAccessPdf {
  url: string;
  status: string;
}

export interface PaperResult {
  paper_id: string;
  title: string;
  abstract?: string | null;
  authors: Author[];
  year?: number | null;
  citation_count?: number | null;
  fields_of_study: string[];
  open_access_pdf?: OpenAccessPdf | null;
  venue?: string | null;
  external_ids?: Record<string, string> | null;
}

export interface PaperDetail extends PaperResult {
  tldr?: string | null;
  reference_count?: number | null;
  influential_citation_count?: number | null;
}

// ── Search ─────────────────────────────────────────────────────────────────

export interface SearchResult extends PaperResult {
  relevance_score: number;
  matched_chunk_text?: string | null;
  search_source: 'pinecone' | 'semantic_scholar';
}

// ── Summary ────────────────────────────────────────────────────────────────

export type PipelineStatus =
  | 'pending'
  | 'downloading'
  | 'extracting'
  | 'chunking'
  | 'embedding'
  | 'indexed'
  | 'summarizing'
  | 'complete'
  | 'failed'
  | 'abstract_only';

export interface SummaryStatusResponse {
  paper_id: string;
  status: PipelineStatus;
  message?: string | null;
}

export interface ExecutiveSummary {
  paper_id: string;
  title: string;
  problem_statement: string;
  key_findings: string[];
  practical_implications: string;
  methodology_note: string;
  confidence_note: string;
  jargon_glossary: Record<string, string>;
  reading_time_minutes: number;
  source: string;
}

// ── Synthesis ──────────────────────────────────────────────────────────────

export interface SynthesisResult {
  paper_ids: string[];
  consensus_findings: string[];
  conflicting_evidence: string[];
  combined_recommendation: string;
  evidence_strength: string;
  created_at: string;
  cached: boolean;
}
