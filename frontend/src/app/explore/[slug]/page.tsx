import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, ShieldCheck, Wifi, Zap } from "lucide-react";
import PackageBrowser from "@/components/explore/PackageBrowser";
import FromPrice from "@/components/explore/FromPrice";
import { fetchDestination } from "@/lib/destinations";

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const data = await fetchDestination(slug);
  if (!data) return { title: "Destination not found" };
  const name = data.country.name_en;
  const cheapest = data.products.length
    ? Math.min(...data.products.map((p: any) => parseFloat(p.retail_price)))
    : null;
  const description = cheapest
    ? `Travel eSIM for ${name} from €${cheapest.toFixed(2)}. Instant QR delivery, no roaming bills, ${data.products.length} packages to choose from.`
    : `Travel eSIM packages for ${name}. Instant QR delivery, no roaming bills.`;
  return {
    title: `${name} eSIM — instant mobile data`,
    description,
    openGraph: { title: `${name} eSIM`, description },
  };
}

export default async function ExploreDestinationPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const data = await fetchDestination(slug);
  if (!data) notFound();

  const { country, products } = data;
  const cheapest = products.length ? Math.min(...products.map((p: any) => parseFloat(p.retail_price))) : null;

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-10 space-y-6">
      <Link href="/destinations" className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-slate-900">
        <ArrowLeft className="w-3.5 h-3.5" /> All destinations
      </Link>

      <div className="glass-panel rounded-2xl border border-gray-200 p-6 sm:p-8">
        <div className="flex flex-wrap items-center gap-4">
          {country.flag_url && (
            <div className="w-16 h-11 rounded-lg overflow-hidden border border-gray-200 shadow-sm shrink-0">
              <img src={country.flag_url} alt={country.name_en} className="w-full h-full object-cover" />
            </div>
          )}
          <div className="min-w-0">
            <h1 className="text-3xl font-extrabold text-slate-900">{country.name_en} eSIM</h1>
            <p className="text-xs text-slate-500 mt-1">
              {products.length} package{products.length === 1 ? "" : "s"}
              {cheapest !== null ? <FromPrice amount={cheapest} /> : null}
              {country.region ? ` · ${country.region}` : ""}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap gap-4 mt-5 text-xs text-slate-600">
          <span className="flex items-center gap-1.5"><Zap className="w-4 h-4 text-brand-600" /> QR delivered in seconds</span>
          <span className="flex items-center gap-1.5"><Wifi className="w-4 h-4 text-brand-600" /> 4G / 5G data, no roaming bill</span>
          <span className="flex items-center gap-1.5"><ShieldCheck className="w-4 h-4 text-emerald-600" /> Keep your own number</span>
        </div>
      </div>

      {products.length === 0 ? (
        <div className="glass-panel rounded-2xl border border-dashed border-gray-300 p-10 text-center">
          <p className="text-sm font-semibold text-slate-900">No packages available for {country.name_en} right now</p>
          <p className="text-xs text-slate-500 mt-1">Please check another destination — our catalogue updates regularly.</p>
        </div>
      ) : (
        <PackageBrowser country={country} products={products} />
      )}
    </div>
  );
}
