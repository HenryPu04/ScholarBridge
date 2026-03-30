'use client';

import { useState } from 'react';
import { Microscope } from 'lucide-react';
import SearchBar from '@/components/search/SearchBar';
import PaperCard from '@/components/search/PaperCard';
import { searchPapers } from '@/lib/api';
import type { SearchResult } from '@/lib/types';

export default function HomePage() {
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  async function handleSearch(query: string) {
    setLoading(true);
    setError(null);
    try {
      const data = await searchPapers(query);
      setResults(data);
      setHasSearched(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  function handleIndexed(paperId: string) {
    setResults((prev) =>
      prev.map((r) =>
        r.paper_id === paperId ? { ...r, search_source: 'pinecone' as const } : r,
      ),
    );
  }

  return (
    <div className="min-h-[calc(100vh-4rem)]">
      {/* Hero */}
      <section className="bg-gradient-to-b from-rice-navy to-rice-navy/90 py-16 px-4">
        <div className="max-w-3xl mx-auto text-center space-y-6">
          <div className="flex justify-center">
            <Microscope className="h-12 w-12 text-rice-gold" />
          </div>
          <h1 className="text-3xl sm:text-4xl font-bold text-white leading-tight">
            Academic research,<br />
            <span className="text-rice-gold">translated for impact.</span>
          </h1>
          <p className="text-blue-200 text-base max-w-xl mx-auto">
            Search 200M+ papers. Index the ones that matter to your programs.
            Get plain-English summaries and cross-paper analysis — in minutes.
          </p>
          <SearchBar onSearch={handleSearch} loading={loading} />
        </div>
      </section>

      {/* Results */}
      <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
        {error && (
          <div className="mb-6 p-4 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
            {error}
          </div>
        )}

        {loading && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {Array.from({ length: 6 }).map((_, i) => (
              <div
                key={i}
                className="bg-white rounded-xl border border-rice-border h-56 animate-pulse"
              />
            ))}
          </div>
        )}

        {!loading && hasSearched && results.length === 0 && (
          <div className="text-center py-16 text-rice-muted">
            <p className="text-lg font-medium">No results found.</p>
            <p className="text-sm mt-1">Try a different query or broader terms.</p>
          </div>
        )}

        {!loading && results.length > 0 && (
          <>
            <div className="flex items-center justify-between mb-5">
              <p className="text-sm text-rice-muted">
                {results.length} result{results.length !== 1 ? 's' : ''}
              </p>
              <div className="flex items-center gap-4 text-xs text-rice-muted">
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-rice-navy inline-block" />
                  In Library
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-slate-400 inline-block" />
                  Global Web
                </span>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
              {results.map((r) => (
                <PaperCard
                  key={r.paper_id}
                  result={r}
                  onIndexed={handleIndexed}
                />
              ))}
            </div>
          </>
        )}

        {!hasSearched && (
          <div className="text-center py-20 text-rice-muted">
            <p className="text-sm">Enter a query above to begin.</p>
          </div>
        )}
      </section>
    </div>
  );
}
