import { Clock, FileText, AlertCircle } from 'lucide-react';
import type { ExecutiveSummary } from '@/lib/types';

interface Props {
  summary: ExecutiveSummary;
}

export default function SummaryViewer({ summary }: Props) {
  const isAbstractOnly = summary.source === 'abstract_only';

  return (
    <article className="max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-rice-navy/10 text-rice-navy">
            <Clock className="h-3 w-3" />
            {summary.reading_time_minutes} min read
          </span>
          <span
            className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ${
              isAbstractOnly
                ? 'bg-amber-50 text-amber-700 border border-amber-200'
                : 'bg-green-50 text-green-700 border border-green-200'
            }`}
          >
            <FileText className="h-3 w-3" />
            {isAbstractOnly ? 'Abstract Only' : 'Full Paper'}
          </span>
        </div>
        <h1 className="text-2xl font-bold text-rice-navy leading-snug">
          {summary.title}
        </h1>
        {isAbstractOnly && (
          <div className="flex items-start gap-2 p-3 rounded-lg bg-amber-50 border border-amber-200">
            <AlertCircle className="h-4 w-4 text-amber-600 mt-0.5 shrink-0" />
            <p className="text-xs text-amber-800">
              No open-access PDF was available. This summary is based on the
              abstract and TLDR provided by Semantic Scholar.
            </p>
          </div>
        )}
      </header>

      {/* Problem Statement */}
      <section className="bg-white rounded-xl border-l-4 border-rice-navy border border-rice-border p-5 shadow-sm">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-rice-muted mb-2">
          Problem Statement
        </h2>
        <p className="text-rice-slate leading-relaxed">{summary.problem_statement}</p>
      </section>

      {/* Key Findings */}
      <section className="bg-white rounded-xl border border-rice-border p-5 shadow-sm">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-rice-muted mb-4">
          Key Findings
        </h2>
        <ol className="space-y-3">
          {summary.key_findings.map((finding, i) => (
            <li key={i} className="flex gap-3">
              <span className="flex-shrink-0 w-6 h-6 rounded-full bg-rice-blue/10 text-rice-blue text-xs font-bold flex items-center justify-center mt-0.5">
                {i + 1}
              </span>
              <p className="text-rice-slate leading-relaxed">{finding}</p>
            </li>
          ))}
        </ol>
      </section>

      {/* Practical Implications */}
      <section className="bg-white rounded-xl border-l-4 border-rice-gold border border-rice-border p-5 shadow-sm">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-rice-muted mb-2">
          Practical Implications
        </h2>
        <p className="text-rice-slate leading-relaxed">{summary.practical_implications}</p>
      </section>

      {/* Methodology + Confidence */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <section className="bg-white rounded-xl border border-rice-border p-5 shadow-sm">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-rice-muted mb-2">
            Methodology
          </h2>
          <p className="text-sm text-rice-slate leading-relaxed">{summary.methodology_note}</p>
        </section>
        <section className="bg-white rounded-xl border border-rice-border p-5 shadow-sm">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-rice-muted mb-2">
            Confidence
          </h2>
          <p className="text-sm text-rice-slate leading-relaxed">{summary.confidence_note}</p>
        </section>
      </div>

      {/* Jargon Glossary */}
      {Object.keys(summary.jargon_glossary).length > 0 && (
        <section className="bg-white rounded-xl border border-rice-border p-5 shadow-sm">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-rice-muted mb-4">
            Jargon Glossary
          </h2>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
            {Object.entries(summary.jargon_glossary).map(([term, definition]) => (
              <div key={term}>
                <dt className="text-sm font-semibold text-rice-navy">{term}</dt>
                <dd className="text-sm text-rice-muted leading-snug mt-0.5">{definition}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}
    </article>
  );
}
