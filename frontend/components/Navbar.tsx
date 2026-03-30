import Link from 'next/link';
import { BookOpen, Library } from 'lucide-react';

export default function Navbar() {
  return (
    <nav className="bg-rice-navy shadow-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <Link href="/" className="flex items-center gap-2.5 group">
            <BookOpen className="h-6 w-6 text-rice-gold" />
            <span className="text-white font-semibold text-lg tracking-tight">
              Scholar<span className="text-rice-gold">Bridge</span>
            </span>
          </Link>

          <div className="flex items-center gap-6">
            <Link
              href="/library"
              className="flex items-center gap-1.5 text-blue-200 hover:text-white text-sm font-medium transition-colors"
            >
              <Library className="h-4 w-4" />
              Library
            </Link>
          </div>
        </div>
      </div>
    </nav>
  );
}
