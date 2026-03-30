'use client';

import { useState, useCallback } from 'react';
import Link from 'next/link';
import { BookMarked, Globe, Quote, Calendar, ExternalLink } from 'lucide-react';
import { requestSummary } from '@/lib/api';
import type { SearchResult } from '@/lib/types';
import PipelinePoller from '@/components/pipeline/PipelinePoller';

interface Props {
  result: SearchResult;
  onIndexed?: (paperId: string) => void;
}

export default function PaperCard({ result, onIndexed }: Props) {
  const [indexing, setIndexing] = useState(false);
  const [indexed, setIndexed] = useState(result.search_source === 'pinecone');
  const [error, setError] = useState<string | null>(null);

  const isLibrary = indexed;
  const displayAuthors = result.authors.slice(0, 3);
  const hasMoreAuthors = result.authors.length > 3;

  async function handleSummarize() {
    setError(null);
    setIndexing(true);
    try {
      await requestSummary(result.paper_id);
    } catch (err) {
      setError((err as Error).message);
      setIndexing(false);
    }
  }

  const handleComplete = useCallback(() => {
    setIndexing(false);
    setIndexed(true);
    onIndexed?.(result.paper_id);
  }, [result.paper_id, onIndexed]);

  return (
    <div className="bg-white rounded-xl border border-rice-border shadow-sm hover:shadow-md transition-shadow p-5 flex flex-col gap-3">
      {/* Source badge */}
      <div className="flex items-center justify-between gap-2">
        <span
          className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ${
            isLibrary
              ? 'bg-rice-navy/10 text-rice-navy'
              : 'bg-slate-100 text-rice-slate'
          }`}
        >
          {isLibrary ? (
            <><BookMarked className="h-3 w-3" /> In Library</>
          ) : (
            <><Globe className="h-3 w-3" /> Global Web</>
          )}
        </span>

        {result.relevance_score > 0 && (
          <span className="text-xs text-rice-muted">
            {Math.round(result.relevance_score * 100)}% match
          </span>
        )}
      </div>

      {/* Title */}
      <h3 className="text-rice-navy font-semibold text-sm leading-snug line-clamp-3">
        {result.title}
      </h3>

      {/* Authors */}
      {displayAuthors.length > 0 && (
        <p className="text-xs text-rice-muted truncate">
          {displayAuthors.map((a) => a.name).join(', ')}
          {hasMoreAuthors && ` +${result.authors.length - 3} more`}
        </p>
      )}

      {/* Meta row */}
      <div className="flex flex-wrap items-center gap-3 text-xs text-rice-muted">
        {result.year && (
          <span className="flex items-center gap-1">
            <Calendar className="h-3 w-3" />
            {result.year}
          </span>
        )}
        {result.citation_count != null && (
          <span className="flex items-center gap-1">
            <Quote className="h-3 w-3" />
            {result.citation_count.toLocaleString()} citations
          </span>
        )}
        {result.venue && (
          <span className="truncate max-w-[180px]">{result.venue}</span>
        )}
      </div>

      {/* Field tags */}
      {result.fields_of_study.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {result.fields_of_study.slice(0, 2).map((f) => (
            <span
              key={f}
              className="px-2 py-0.5 bg-rice-blue/10 text-rice-blue text-xs rounded-md"
            >
              {f}
            </span>
          ))}
        </div>
      )}

      {/* Action */}
      <div className="mt-auto pt-2 border-t border-rice-border">
        {isLibrary ? (
          <Link
            href={`/summaries/${encodeURIComponent(result.paper_id)}`}
            className="flex items-center gap-1.5 text-sm font-medium text-rice-blue hover:text-rice-navy transition-colors"
          >
            <ExternalLink className="h-4 w-4" />
            View Summary
          </Link>
        ) : indexing ? (
          <PipelinePoller paperId={result.paper_id} onComplete={handleComplete} />
        ) : (
          <>
            <button
              onClick={handleSummarize}
              className="w-full py-2 px-4 bg-rice-navy text-white text-sm font-medium rounded-lg hover:bg-rice-blue transition-colors"
            >
              Summarize &amp; Index
            </button>
            {error && (
              <p className="mt-1.5 text-xs text-red-600">{error}</p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
