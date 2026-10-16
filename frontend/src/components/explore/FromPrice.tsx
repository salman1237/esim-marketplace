"use client";

import { useAppSettings } from "@/lib/AppSettingsContext";

/**
 * The "from <price>" line on a destination header.
 *
 * Its own component because the page around it is server-rendered and so has
 * no idea what currency the visitor reads in. Left on the server it printed a
 * euro figure directly above a grid of taka prices, which reads as two
 * different prices for the same package.
 */
export default function FromPrice({ amount }: { amount: number }) {
  const { formatPrice } = useAppSettings();
  return <> · from {formatPrice(amount)}</>;
}
