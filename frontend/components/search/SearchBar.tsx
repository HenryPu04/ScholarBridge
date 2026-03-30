'use client';

import { Search } from 'lucide-react';
import { FormEvent, useState } from 'react';

interface Props {
  onSearch: (query: string) => void;
  loading?: boolean;
}

export default function SearchBar({ onSearch, loading }: Props) {
  const [value, setValue] = useState('');

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = value.trim();
    if (trimmed.length >= 3) onSearch(trimmed);
  }

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-2xl mx-auto">
      <div className="relative flex items-center">
        <Search className="absolute left-4 h-5 w-5 text-rice-muted pointer-events-none" />
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Search academic research in plain English…"
          minLength={3}
          className="
            w-full pl-12 pr-32 py-4 rounded-xl border-2 border-rice-border
            bg-white text-rice-slate placeholder:text-rice-muted
            focus:outline-none focus:border-rice-blue focus:ring-4 focus:ring-rice-blue/10
            text-base shadow-sm transition-all
          "
        />
        <button
          type="submit"
          disabled={loading || value.trim().length < 3}
          className="
            absolute right-2 px-5 py-2.5 rounded-lg
            bg-rice-navy text-white text-sm font-medium
            hover:bg-rice-blue disabled:opacity-40 disabled:cursor-not-allowed
            transition-colors
          "
        >
          {loading ? 'Searching…' : 'Search'}
        </button>
      </div>
    </form>
  );
}
