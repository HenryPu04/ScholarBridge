'use client';

import { useEffect, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2 } from 'lucide-react';
import { getSummaryStatus } from '@/lib/api';
import type { PipelineStatus } from '@/lib/types';

const STATUS_LABELS: Record<PipelineStatus, string> = {
  pending:      'Queued…',
  downloading:  'Downloading PDF…',
  extracting:   'Reading pages…',
  chunking:     'Splitting into sections…',
  embedding:    'Teaching AI the content…',
  indexed:      'Saved to library…',
  summarizing:  'Writing plain-English summary…',
  complete:     'Complete',
  abstract_only: 'Complete (abstract only)',
  failed:       'Failed',
};

const STATUS_PROGRESS: Record<PipelineStatus, number> = {
  pending:      5,
  downloading:  20,
  extracting:   35,
  chunking:     50,
  embedding:    65,
  indexed:      75,
  summarizing:  90,
  complete:     100,
  abstract_only: 100,
  failed:       100,
};

interface Props {
  paperId: string;
  onComplete: () => void;
}

export default function PipelinePoller({ paperId, onComplete }: Props) {
  const [status, setStatus] = useState<PipelineStatus>('pending');
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    async function poll() {
      try {
        const res = await getSummaryStatus(paperId);
        setStatus(res.status);

        if (res.status === 'complete' || res.status === 'abstract_only') {
          clearInterval(intervalRef.current!);
          onComplete();
        } else if (res.status === 'failed') {
          clearInterval(intervalRef.current!);
          setError(res.message ?? 'Indexing failed. Please try again.');
        }
      } catch (err) {
        clearInterval(intervalRef.current!);
        setError((err as Error).message);
      }
    }

    poll(); // immediate first check
    intervalRef.current = setInterval(poll, 3000);
    return () => clearInterval(intervalRef.current!);
  }, [paperId, onComplete]);

  const progress = STATUS_PROGRESS[status];
  const isDone = status === 'complete' || status === 'abstract_only';
  const isFailed = status === 'failed' || error;

  if (isFailed) {
    return (
      <div className="flex items-start gap-2 mt-3 p-3 rounded-lg bg-red-50 border border-red-200">
        <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 shrink-0" />
        <p className="text-xs text-red-700">{error ?? 'Indexing failed.'}</p>
      </div>
    );
  }

  return (
    <div className="mt-3 space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-xs text-rice-muted">{STATUS_LABELS[status]}</span>
        {isDone && <CheckCircle2 className="h-4 w-4 text-green-500" />}
      </div>
      <div className="w-full h-1.5 bg-rice-border rounded-full overflow-hidden">
        <div
          className="h-full bg-rice-blue rounded-full transition-all duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}
