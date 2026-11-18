import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { fetchDestination } from "@/lib/destinations";
import PackageDetail from "@/components/explore/PackageDetail";

// A single package's own shareable page: /explore/<slug>/<productId>.
// Rendered on the server (same destination fetch the listing page uses,
// no new endpoint) so the link preview on WhatsApp/Messenger and search
// results both show THIS package's own title/description, not the
// country's generic listing.
export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string; productId: string }>;
}): Promise<Metadata> {
  const { slug, productId } = await params;
  const data = await fetchDestination(slug);
  const product = data?.products.find((p: any) => p.id === productId);
  if (!data || !product) return { title: "Package not found" };

  const name = data.country.name_en;
  const label = product.is_unlimited ? "Unlimited data" : `${Number(product.data_amount_gb)} GB`;
  const title = `${name} eSIM — ${label}, ${product.validity_days} days`;
  const description = `${label} for ${product.validity_days} days in ${name}, from €${Number(product.retail_price).toFixed(2)}. Instant QR delivery, no roaming bills.`;
  return {
    title,
    description,
    openGraph: { title, description },
  };
}

export default async function PackagePage({
  params,
}: {
  params: Promise<{ slug: string; productId: string }>;
}) {
  const { slug, productId } = await params;
  const data = await fetchDestination(slug);
  const product = data?.products.find((p: any) => p.id === productId);
  if (!data || !product) notFound();

  return <PackageDetail country={data.country} product={product} />;
}
