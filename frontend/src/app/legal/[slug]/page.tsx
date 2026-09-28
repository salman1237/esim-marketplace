import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { API_BASE } from "@/lib/api";
import LegalMarkdown from "@/components/LegalMarkdown";
import { formatDate } from "@/lib/datetime";

const LEGAL_LINKS = [
  { slug: "privacy", title: "Privacy Policy" },
  { slug: "data-policy", title: "Data Privacy" },
  { slug: "terms", title: "Terms & Conditions" },
  { slug: "declaration", title: "Declaration" },
  { slug: "refund-policy", title: "Refund Policy" },
  { slug: "payment-policy", title: "Payment Policy" },
];

type LegalDoc = { slug: string; title: string; body: string; updated_at: string | null };

// Revalidated like the layout's settings fetch, so an admin edit shows up
// within a few minutes without a rebuild.
async function fetchDoc(slug: string): Promise<LegalDoc | null | "error"> {
  if (!LEGAL_LINKS.some((l) => l.slug === slug)) return null;
  try {
    const res = await fetch(`${API_BASE}/api/v1/settings/legal/${slug}`, { next: { revalidate: 300 } });
    if (res.status === 404) return null;
    if (!res.ok) return "error";
    return await res.json();
  } catch {
    return "error";
  }
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const link = LEGAL_LINKS.find((l) => l.slug === slug);
  return { title: link ? link.title : "Legal" };
}

export default async function LegalPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const doc = await fetchDoc(slug);
  if (doc === null) notFound();

  const title = doc === "error" ? LEGAL_LINKS.find((l) => l.slug === slug)?.title : doc.title;

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-12 grid grid-cols-1 md:grid-cols-[200px_1fr] gap-8">
      <nav className="md:sticky md:top-24 self-start">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">Legal</div>
        <ul className="flex md:flex-col flex-wrap gap-1">
          {LEGAL_LINKS.map((l) => (
            <li key={l.slug}>
              <Link
                href={`/legal/${l.slug}`}
                className={`block px-3 py-2 rounded-lg text-xs font-semibold ${
                  l.slug === slug ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-gray-100"
                }`}
              >
                {l.title}
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      <article className="glass-panel rounded-2xl border border-gray-200 p-6 sm:p-10 min-w-0">
        <h1 className="text-3xl font-extrabold text-slate-900">{title}</h1>
        {doc !== "error" && doc.updated_at && (
          <p className="text-xs text-slate-500 mt-1">
            Last updated {formatDate(doc.updated_at)}
          </p>
        )}
        <div className="mt-6">
          {doc === "error" ? (
            <p className="text-sm text-slate-600">This page couldn&apos;t be loaded right now. Please try again in a moment.</p>
          ) : (
            <LegalMarkdown body={doc.body} />
          )}
        </div>
      </article>
    </div>
  );
}
