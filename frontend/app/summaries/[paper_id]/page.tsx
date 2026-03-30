'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeft, Loader2, AlertCircle } from 'lucide-react';
import { getSummary } from '@/lib/api';
import type { ExecutiveSummary } from '@/lib/types';
import SummaryViewer from '@/components/summary/SummaryViewer';

export default function SummaryPage() {
  const { paper_id } = useParams<{ paper_id: string }>();
  const decodedId = decodeURIComponent(paper_id);

  const [summary, setSummary] = useState<ExecutiveSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSummary(decodedId)
      .then(setSummary)
      .catch((err) => setError((err as Error).message))
      .finally(() => setLoading(false));
  }, [decodedId]);

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      <Link
        href="/"
        className="inline-flex items-center gap-1.5 text-sm text-rice-muted hover:text-rice-navy mb-8 transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Search
      </Link>

      {loading && (
        <div className="flex flex-col items-center justify-center py-32 gap-3 text-rice-muted">
          <Loader2 className="h-8 w-8 animate-spin text-rice-blue" />
          <p className="text-sm">Loading summary…</p>
        </div>
      )}

      {error && (
        <div className="flex items-start gap-3 p-5 rounded-xl bg-red-50 border border-red-200">
          <AlertCircle className="h-5 w-5 text-red-500 mt-0.5 shrink-0" />
          <div>
            <p className="font-medium text-red-800">Summary not available</p>
            <p className="text-sm text-red-700 mt-1">{error}</p>
            <Link href="/" className="text-sm text-rice-blue hover:underline mt-2 inline-block">
              Return to search
            </Link>
          </div>
        </div>
      )}

      {summary && <SummaryViewer summary={summary} />}
    </div>
  );
}
