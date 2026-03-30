import { CheckCircle2, AlertTriangle, Lightbulb, BarChart2, Zap, Clock } from 'lucide-react';
import type { SynthesisResult } from '@/lib/types';

interface Props {
  result: SynthesisResult;
}

function evidenceBadge(strength: string) {
  const s = strength.toLowerCase();
  if (s.startsWith('strong')) {
    return 'bg-green-100 text-green-800 border-green-200';
  }
  if (s.startsWith('moderate')) {
    return 'bg-amber-100 text-amber-800 border-amber-200';
  }
  return 'bg-red-100 text-red-800 border-red-200';
}

function formatTimestamp(iso: string) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    });
  } catch {
    return iso;
  }
}

export default function SynthesisPanel({ result }: Props) {
  const [strengthLabel, ...strengthRest] = result.evidence_strength.split(':');
  const strengthDetail = strengthRest.join(':').trim();

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-rice-navy">Cross-Paper Analysis</h2>
        {result.cached && (
          <span className="flex items-center gap-1 text-xs text-rice-muted">
            <Zap className="h-3 w-3" /> Cached result
          </span>
        )}
      </div>

      {/* 2×2 grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Consensus */}
        <section className="bg-green-50 rounded-xl border border-green-200 p-5">
          <div className="flex items-center gap-2 mb-3">
            <CheckCircle2 className="h-4 w-4 text-green-600" />
            <h3 className="text-sm font-semibold text-green-800">Consensus Findings</h3>
          </div>
          <ul className="space-y-2">
            {result.consensus_findings.map((f, i) => (
              <li key={i} className="flex gap-2 text-sm text-green-900">
                <span className="text-green-400 mt-1">•</span>
                <span className="leading-snug">{f}</span>
              </li>
            ))}
          </ul>
        </section>

        {/* Conflicts */}
        <section className="bg-amber-50 rounded-xl border border-amber-200 p-5">
          <div className="flex items-center gap-2 mb-3">
            <AlertTriangle className="h-4 w-4 text-amber-600" />
            <h3 className="text-sm font-semibold text-amber-800">Conflicting Evidence</h3>
          </div>
          <ul className="space-y-2">
            {result.conflicting_evidence.map((f, i) => (
              <li key={i} className="flex gap-2 text-sm text-amber-900">
                <span className="text-amber-400 mt-1">•</span>
                <span className="leading-snug">{f}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      {/* Recommendation — full width */}
      <section className="bg-white rounded-xl border-l-4 border-rice-gold border border-rice-border p-5 shadow-sm">
        <div className="flex items-center gap-2 mb-3">
          <Lightbulb className="h-4 w-4 text-rice-gold" />
          <h3 className="text-sm font-semibold text-rice-navy">Combined Recommendation</h3>
        </div>
        <p className="text-rice-slate leading-relaxed">{result.combined_recommendation}</p>
      </section>

      {/* Evidence Strength */}
      <section className="bg-white rounded-xl border border-rice-border p-5 shadow-sm">
        <div className="flex items-start gap-3">
          <BarChart2 className="h-4 w-4 text-rice-muted mt-0.5 shrink-0" />
          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-rice-navy">Evidence Strength</h3>
              <span
                className={`px-2 py-0.5 rounded-full text-xs font-semibold border ${evidenceBadge(
                  result.evidence_strength,
                )}`}
              >
                {strengthLabel.trim()}
              </span>
            </div>
            {strengthDetail && (
              <p className="text-sm text-rice-muted leading-snug">{strengthDetail}</p>
            )}
          </div>
        </div>
      </section>

      {/* Footer */}
      <p className="flex items-center gap-1.5 text-xs text-rice-muted">
        <Clock className="h-3 w-3" />
        Generated {formatTimestamp(result.created_at)}
        {result.cached && ' · served from cache'}
      </p>
    </div>
  );
}
