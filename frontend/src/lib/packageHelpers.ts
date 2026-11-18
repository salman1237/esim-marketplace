export type Product = {
  id: string;
  title_en: string;
  data_amount_gb: string | number;
  validity_days: number;
  retail_price: string | number;
  is_unlimited: boolean;
  is_featured?: boolean;
  currency?: string;
  // Set only for a Day Pass duration variant (see catalog_parsing.py's
  // DAY_PASS_VARIANT_DAYS) - null/undefined for an ordinary fixed-data plan.
  supplier_period_num?: number | null;
  // Resolved country names for a regional/multi-country package - null
  // for a single-country plan.
  coverage_countries?: string[] | null;
};

export const priceOf = (p: Product) => parseFloat(String(p.retail_price));

// A Day Pass's data_amount_gb is the TOTAL over the whole validity period
// (daily rate x days, see catalog_parsing.py), but the allowance actually
// resets every day and never carries over - showing that total the same
// way a Fixed-data plan's pooled allowance is shown wrongly implies the
// customer can use it all on day one. Showing the per-day rate instead
// matches what they actually get.
export const dataLabel = (p: Product) => {
  if (p.is_unlimited) return "Unlimited";
  if (p.supplier_period_num && p.validity_days) {
    const perDay = Number(p.data_amount_gb) / p.validity_days;
    const rounded = Math.round(perDay * 100) / 100;
    return `${rounded} GB/day`;
  }
  return `${Number(p.data_amount_gb)} GB`;
};

// A rough, client-side estimate from the public (pre-login) code check -
// just enough to show "you'll save about this much" on a card. The real
// amount is always recomputed per-product, authoritatively, by
// api.previewDiscount once the customer actually buys.
export function estimateDiscount(
  price: number,
  generic: { discount_type: string; value: string; max_discount_amount: string | null },
) {
  if (generic.discount_type === "PERCENT") {
    let amount = (price * parseFloat(generic.value)) / 100;
    if (generic.max_discount_amount) amount = Math.min(amount, parseFloat(generic.max_discount_amount));
    return Math.min(amount, price);
  }
  return Math.min(parseFloat(generic.value), price);
}
