'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Loader2, AlertCircle, Library, ExternalLink, FlaskConical } from 'lucide-react';
import { getLibrary, createSynthesis } from '@/lib/api';
import type { ExecutiveSummary, SynthesisResult } from '@/lib/types';
import SynthesisPanel from '@/components/synthesis/SynthesisPanel';

const MAX_SELECTION = 5;

export default function LibraryPage() {
  const [papers, setPapers] = useState<ExecutiveSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [synthesizing, setSynthesizing] = useState(false);
  const [synthesisError, setSynthesisError] = useState<string | null>(null);
  const [synthesisResult, setSynthesisResult] = useState<SynthesisResult | null>(null);

  useEffect(() => {
    getLibrary()
      .then(setPapers)
      .catch((err) => setError((err as Error).message))
      .finally(() => setLoading(false));
  }, []);

  function toggleSelect(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else if (next.size < MAX_SELECTION) {
        next.add(id);
      }
      return next;
    });
    setSynthesisResult(null);
    setSynthesisError(null);
  }

  async function handleSynthesize() {
    setSynthesizing(true);
    setSynthesisError(null);
    setSynthesisResult(null);
    try {
      const result = await createSynthesis(Array.from(selectedIds));
      setSynthesisResult(result);
    } catch (err) {
      setSynthesisError((err as Error).message);
    } finally {
      setSynthesizing(false);
    }
  }

  const canSynthesize = selectedIds.size >= 2 && selectedIds.size <= MAX_SELECTION;

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-10 space-y-8">
      {/* Page header */}
      <div className="flex items-center gap-3">
        <Library className="h-6 w-6 text-rice-navy" />
        <div>
          <h1 className="text-2xl font-bold text-rice-navy">Your Library</h1>
          <p className="text-sm text-rice-muted mt-0.5">
            Select 2–5 papers to generate a cross-paper synthesis.
          </p>
        </div>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-24 gap-3 text-rice-muted">
          <Loader2 className="h-6 w-6 animate-spin text-rice-blue" />
          <span className="text-sm">Loading library…</span>
        </div>
      )}

      {error && (
        <div className="flex items-start gap-3 p-4 rounded-xl bg-red-50 border border-red-200">
          <AlertCircle className="h-5 w-5 text-red-500 mt-0.5 shrink-0" />
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {!loading && !error && papers.length === 0 && (
        <div className="text-center py-20 space-y-3">
          <p className="text-rice-muted">Your library is empty.</p>
          <Link
            href="/"
            className="text-sm text-rice-blue hover:underline"
          >
            Search for papers and index them to get started.
          </Link>
        </div>
      )}

      {!loading && papers.length > 0 && (
        <>
          {/* Selection counter + action */}
          <div className="flex items-center justify-between bg-white rounded-xl border border-rice-border px-5 py-3 shadow-sm">
            <span className="text-sm text-rice-slate">
              <span className="font-semibold text-rice-navy">{selectedIds.size}</span>
              <span className="text-rice-muted"> / {MAX_SELECTION} selected</span>
            </span>
            <button
              onClick={handleSynthesize}
              disabled={!canSynthesize || synthesizing}
              className="
                flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium
                bg-rice-navy text-white
                hover:bg-rice-blue disabled:opacity-40 disabled:cursor-not-allowed
                transition-colors
              "
            >
              {synthesizing ? (
                <><Loader2 className="h-4 w-4 animate-spin" /> Generating…</>
              ) : (
                <><FlaskConical className="h-4 w-4" /> Generate Synthesis</>
              )}
            </button>
          </div>

          {/* Paper list */}
          <div className="bg-white rounded-xl border border-rice-border shadow-sm divide-y divide-rice-border">
            {papers.map((paper) => {
              const isSelected = selectedIds.has(paper.paper_id);
              const isDisabled = !isSelected && selectedIds.size >= MAX_SELECTION;
              return (
                <div
                  key={paper.paper_id}
                  className={`flex items-center gap-4 px-5 py-4 transition-colors ${
                    isSelected ? 'bg-rice-navy/5' : 'hover:bg-rice-surface'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    disabled={isDisabled}
                    onChange={() => toggleSelect(paper.paper_id)}
                    className="h-4 w-4 rounded border-rice-border text-rice-navy accent-rice-navy cursor-pointer disabled:cursor-not-allowed"
                  />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-rice-navy truncate">
                      {paper.title}
                    </p>
                    <p className="text-xs text-rice-muted mt-0.5">
                      {paper.reading_time_minutes} min read ·{' '}
                      {paper.source === 'abstract_only' ? 'Abstract only' : 'Full paper'}
                    </p>
                  </div>
                  <Link
                    href={`/summaries/${encodeURIComponent(paper.paper_id)}`}
                    className="flex-shrink-0 flex items-center gap-1 text-xs text-rice-blue hover:text-rice-navy transition-colors"
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                    View
                  </Link>
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* Synthesis error */}
      {synthesisError && (
        <div className="flex items-start gap-3 p-4 rounded-xl bg-red-50 border border-red-200">
          <AlertCircle className="h-5 w-5 text-red-500 mt-0.5 shrink-0" />
          <p className="text-sm text-red-700">{synthesisError}</p>
        </div>
      )}

      {/* Synthesis result */}
      {synthesisResult && (
        <div className="bg-rice-surface rounded-xl border border-rice-border p-6 shadow-sm">
          <SynthesisPanel result={synthesisResult} />
        </div>
      )}
    </div>
  );
}
