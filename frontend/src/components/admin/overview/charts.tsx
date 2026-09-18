"use client";

import React, { useEffect, useRef, useState } from "react";

// Chart tokens. Categorical slots 1-3 are the validated reference palette
// (checked against the white card surface: all gates pass; aqua is 2.82:1,
// so wherever it appears its values are also printed as text and the card
// has a table view). Status colours are reserved for good/bad meaning and
// always ship with an icon + label. The admin console is light-only, so the
// charts are too.
export const VIZ = {
  surface: "#ffffff",
  grid: "#e1e0d9",
  baseline: "#c3c2b7",
  muted: "#898781",
  secondary: "#52514e",
  primary: "#0b0b0b",
  deemph: "#c3c2b7",
  series: ["#2a78d6", "#eb6834", "#1baf7a"],
  track: "#cde2fb", // sequential blue step 100 - meter track
  status: { good: "#0ca30c", warning: "#fab219", serious: "#ec835a", critical: "#d03b3b" },
  upGoodText: "#006300",
  downBadText: "#d03b3b",
};

export function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(Math.floor(el.getBoundingClientRect().width));
    const ro = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

// Clean axis ticks: 0 / 1 / 2 / 5 × 10^n steps, about four of them.
export function niceScale(max: number, ticks = 4) {
  if (!(max > 0)) return { max: 1, step: 0.25, values: [0, 0.25, 0.5, 0.75, 1] };
  const raw = max / ticks;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const n = raw / pow;
  const step = (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * pow;
  const top = Math.ceil(max / step) * step;
  const values: number[] = [];
  for (let v = 0; v <= top + step / 2; v += step) values.push(Number(v.toFixed(10)));
  return { max: top, step, values };
}

// Which x labels to draw: at least `minGap` px apart, always the last one,
// and a regular tick that would crowd the last label is dropped - fixed
// every-Nth spacing let the final two dates collide on narrow screens.
export function tickIndices(n: number, stepPx: number, minGap = 64): number[] {
  if (n <= 1) return [0];
  const every = Math.max(1, Math.ceil(minGap / Math.max(1, stepPx)));
  const idx: number[] = [];
  for (let i = 0; i < n - 1; i += every) idx.push(i);
  if (idx.length && (n - 1 - idx[idx.length - 1]) * stepPx < minGap) idx.pop();
  idx.push(n - 1);
  return idx;
}

const anchorFor = (i: number, n: number) => (i === 0 ? "start" : i === n - 1 ? "end" : "middle");

export const shortDate = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

// ---------------------------------------------------------------------------
// Tooltip - values lead, labels follow, keyed with a short line.
// ---------------------------------------------------------------------------
export type TipRow = { color?: string; value: string; label: string };

function Tooltip({ x, y, containerWidth, title, rows }: { x: number; y: number; containerWidth: number; title: string; rows: TipRow[] }) {
  const width = 176;
  const left = Math.max(4, Math.min(x + 12, containerWidth - width - 4));
  return (
    <div
      role="status"
      className="pointer-events-none absolute z-10 rounded-lg bg-white shadow-lg ring-1 ring-black/10 px-3 py-2"
      style={{ left, top: Math.max(0, y), width }}
    >
      <div className="text-[11px] mb-1" style={{ color: VIZ.muted }}>{title}</div>
      {rows.map((r) => (
        <div key={r.label} className="flex items-center gap-2 text-xs leading-5">
          {r.color && <span className="inline-block w-3 h-[2px] rounded-full shrink-0" style={{ background: r.color }} />}
          <span className="font-semibold tabular-nums" style={{ color: VIZ.primary }}>{r.value}</span>
          <span className="truncate" style={{ color: VIZ.secondary }}>{r.label}</span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Card with the table-view twin every chart needs.
// ---------------------------------------------------------------------------
export type TableSpec = { columns: string[]; rows: (string | number)[][] };

export function ChartCard({
  title, subtitle, legend, table, children, className = "",
}: {
  title: string; subtitle?: string; legend?: React.ReactNode; table?: TableSpec; children: React.ReactNode; className?: string;
}) {
  const [asTable, setAsTable] = useState(false);
  return (
    <figure className={`glass-panel rounded-2xl border border-gray-200 p-5 bg-white min-w-0 ${className}`}>
      <figcaption className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <div className="text-sm font-bold" style={{ color: VIZ.primary }}>{title}</div>
          {subtitle && <div className="text-[11px] mt-0.5" style={{ color: VIZ.muted }}>{subtitle}</div>}
        </div>
        {table && (
          <button
            type="button"
            onClick={() => setAsTable(!asTable)}
            className="text-[11px] font-semibold px-2 py-1 rounded-md border border-gray-200 hover:bg-gray-50 shrink-0"
            style={{ color: VIZ.secondary }}
            aria-pressed={asTable}
          >
            {asTable ? "Chart" : "Table"}
          </button>
        )}
      </figcaption>
      {legend && !asTable && <div className="mb-3">{legend}</div>}
      {asTable && table ? <DataTable spec={table} /> : children}
    </figure>
  );
}

export function DataTable({ spec }: { spec: TableSpec }) {
  return (
    <div className="max-h-72 overflow-auto">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-white">
          <tr>
            {spec.columns.map((c, i) => (
              <th key={c} className={`py-1.5 pe-3 font-semibold border-b border-gray-200 ${i === 0 ? "text-start" : "text-end"}`} style={{ color: VIZ.secondary }}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {spec.rows.map((r, ri) => (
            <tr key={ri} className="border-b border-gray-100">
              {r.map((cell, ci) => (
                <td key={ci} className={`py-1.5 pe-3 ${ci === 0 ? "text-start" : "text-end tabular-nums"}`} style={{ color: ci === 0 ? VIZ.secondary : VIZ.primary }}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Legend({ items, shape = "line" }: { items: { label: string; color: string; value?: string }[]; shape?: "line" | "rect" }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1">
      {items.map((it) => (
        <span key={it.label} className="flex items-center gap-1.5 text-[11px]" style={{ color: VIZ.secondary }}>
          {shape === "line" ? (
            <span className="inline-block w-3.5 h-[2px] rounded-full" style={{ background: it.color }} />
          ) : (
            <span className="inline-block w-2.5 h-2.5 rounded-[3px]" style={{ background: it.color }} />
          )}
          {it.label}
          {it.value && <span className="font-semibold tabular-nums" style={{ color: VIZ.primary }}>{it.value}</span>}
        </span>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Line chart - multi-series, one axis, crosshair + keyboard.
// ---------------------------------------------------------------------------
export function LineChart({
  labels, series, fmt, fmtAxis, height = 220, ariaLabel,
}: {
  labels: string[];
  series: { name: string; color: string; values: number[]; area?: boolean }[];
  fmt: (n: number) => string;
  fmtAxis?: (n: number) => string;
  height?: number;
  ariaLabel: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const m = { top: 10, right: 12, bottom: 26, left: 52 };
  const plotW = Math.max(0, width - m.left - m.right);
  const plotH = height - m.top - m.bottom;
  const n = labels.length;
  const scale = niceScale(Math.max(0, ...series.flatMap((s) => s.values)));
  const x = (i: number) => m.left + (n <= 1 ? plotW / 2 : (i * plotW) / (n - 1));
  const y = (v: number) => m.top + plotH * (1 - v / scale.max);
  const ticks = tickIndices(n, n > 1 ? plotW / (n - 1) : plotW);

  const pick = (clientX: number, rect: DOMRect) => {
    const px = clientX - rect.left - m.left;
    const i = Math.round((px / Math.max(1, plotW)) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  };

  return (
    <div ref={ref} className="relative w-full" style={{ height }}>
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={ariaLabel}
          tabIndex={0}
          className="outline-none focus-visible:ring-2 focus-visible:ring-brand-500 rounded-md"
          onPointerMove={(e) => pick(e.clientX, (e.currentTarget as SVGSVGElement).getBoundingClientRect())}
          onPointerLeave={() => setHover(null)}
          onFocus={() => setHover(n - 1)}
          onBlur={() => setHover(null)}
          onKeyDown={(e) => {
            if (e.key === "ArrowLeft") setHover((h) => Math.max(0, (h ?? n - 1) - 1));
            if (e.key === "ArrowRight") setHover((h) => Math.min(n - 1, (h ?? 0) + 1));
          }}
        >
          {scale.values.map((v) => (
            <g key={v}>
              <line x1={m.left} x2={m.left + plotW} y1={y(v)} y2={y(v)} stroke={v === 0 ? VIZ.baseline : VIZ.grid} strokeWidth={1} />
              <text x={m.left - 8} y={y(v)} dy="0.32em" textAnchor="end" fontSize={11} fill={VIZ.muted} style={{ fontVariantNumeric: "tabular-nums" }}>
                {(fmtAxis || fmt)(v)}
              </text>
            </g>
          ))}
          {ticks.map((i) => (
            <text key={labels[i]} x={x(i)} y={height - 8} textAnchor={anchorFor(i, n)} fontSize={11} fill={VIZ.muted}>
              {shortDate(labels[i])}
            </text>
          ))}
          {series.map((s) => {
            const pts = s.values.map((v, i) => `${x(i)},${y(v)}`);
            return (
              <g key={s.name}>
                {s.area && n > 1 && (
                  <path d={`M${x(0)},${y(0)} L${pts.join(" L")} L${x(n - 1)},${y(0)} Z`} fill={s.color} fillOpacity={0.1} />
                )}
                <polyline points={pts.join(" ")} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                <circle cx={x(n - 1)} cy={y(s.values[n - 1] ?? 0)} r={4} fill={s.color} stroke={VIZ.surface} strokeWidth={2} />
              </g>
            );
          })}
          {hover !== null && (
            <g>
              <line x1={x(hover)} x2={x(hover)} y1={m.top} y2={m.top + plotH} stroke={VIZ.baseline} strokeWidth={1} />
              {series.map((s) => (
                <circle key={s.name} cx={x(hover)} cy={y(s.values[hover] ?? 0)} r={4} fill={s.color} stroke={VIZ.surface} strokeWidth={2} />
              ))}
            </g>
          )}
        </svg>
      )}
      {hover !== null && width > 0 && (
        <Tooltip
          x={x(hover)}
          y={m.top}
          containerWidth={width}
          title={shortDate(labels[hover])}
          rows={series.map((s) => ({ color: s.color, value: fmt(s.values[hover] ?? 0), label: s.name }))}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Column chart - one series, per-bar hover, thin rounded columns.
// ---------------------------------------------------------------------------
function roundedTop(x: number, y: number, w: number, h: number, r = 4) {
  if (h <= 0) return "";
  const rr = Math.min(r, h, w / 2);
  return `M${x},${y + h} V${y + rr} Q${x},${y} ${x + rr},${y} H${x + w - rr} Q${x + w},${y} ${x + w},${y + rr} V${y + h} Z`;
}

export function ColumnChart({
  labels, values, color, fmt, height = 200, ariaLabel, seriesName,
}: {
  labels: string[]; values: number[]; color: string; fmt: (n: number) => string; height?: number; ariaLabel: string; seriesName: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const m = { top: 16, right: 8, bottom: 26, left: 36 };
  const plotW = Math.max(0, width - m.left - m.right);
  const plotH = height - m.top - m.bottom;
  const n = labels.length;
  const band = plotW / Math.max(1, n);
  const barW = Math.max(2, Math.min(24, band - 2));
  const scale = niceScale(Math.max(0, ...values));
  const y = (v: number) => m.top + plotH * (1 - v / scale.max);
  const ticks = tickIndices(n, band);
  const maxIdx = values.reduce((best, v, i) => (v > values[best] ? i : best), 0);

  return (
    <div ref={ref} className="relative w-full" style={{ height }}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={ariaLabel}>
          {scale.values.map((v) => (
            <g key={v}>
              <line x1={m.left} x2={m.left + plotW} y1={y(v)} y2={y(v)} stroke={v === 0 ? VIZ.baseline : VIZ.grid} strokeWidth={1} />
              <text x={m.left - 8} y={y(v)} dy="0.32em" textAnchor="end" fontSize={11} fill={VIZ.muted} style={{ fontVariantNumeric: "tabular-nums" }}>{fmt(v)}</text>
            </g>
          ))}
          {values.map((v, i) => {
            const cx = m.left + band * i + band / 2;
            const top = y(v);
            return (
              <g
                key={labels[i]}
                tabIndex={0}
                aria-label={`${shortDate(labels[i])}: ${fmt(v)} ${seriesName}`}
                onPointerEnter={() => setHover(i)}
                onPointerLeave={() => setHover(null)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
                className="outline-none"
              >
                {/* hit target: the whole band, not just the painted column */}
                <rect x={m.left + band * i} y={m.top} width={band} height={plotH} fill="transparent" />
                <path d={roundedTop(cx - barW / 2, top, barW, m.top + plotH - top)} fill={color} fillOpacity={hover === i ? 0.75 : 1} />
              </g>
            );
          })}
          {values[maxIdx] > 0 && (
            <text x={m.left + band * maxIdx + band / 2} y={y(values[maxIdx]) - 6} textAnchor="middle" fontSize={11} fontWeight={600} fill={VIZ.secondary}>
              {fmt(values[maxIdx])}
            </text>
          )}
          {ticks.map((i) => (
            // Edge labels anchor to the plot edge so they can't be clipped.
            <text
              key={labels[i]}
              x={i === 0 ? m.left : i === n - 1 ? m.left + plotW : m.left + band * i + band / 2}
              y={height - 8}
              textAnchor={anchorFor(i, n)}
              fontSize={11}
              fill={VIZ.muted}
            >
              {shortDate(labels[i])}
            </text>
          ))}
        </svg>
      )}
      {hover !== null && width > 0 && (
        <Tooltip
          x={m.left + band * hover + band / 2}
          y={m.top}
          containerWidth={width}
          title={shortDate(labels[hover])}
          rows={[{ color, value: fmt(values[hover]), label: seriesName }]}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Horizontal bars - ranked nominal categories, one hue, value at the tip.
// ---------------------------------------------------------------------------
export function HBarChart({
  items, color, fmt, ariaLabel, seriesName,
}: {
  items: { label: string; value: number; detail?: string }[]; color: string; fmt: (n: number) => string; ariaLabel: string; seriesName: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const rowH = 30;
  const barH = 14;
  const labelW = Math.min(150, Math.max(90, width * 0.34));
  const valueW = 64;
  const plotW = Math.max(0, width - labelW - valueW);
  const max = Math.max(0, ...items.map((i) => i.value)) || 1;
  const height = rowH * items.length;

  if (items.length === 0) {
    return <p className="text-xs py-8 text-center" style={{ color: VIZ.muted }}>No sales in this period yet.</p>;
  }

  return (
    <div ref={ref} className="relative w-full" style={{ height }}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={ariaLabel}>
          <line x1={labelW} x2={labelW} y1={0} y2={height} stroke={VIZ.baseline} strokeWidth={1} />
          {items.map((it, i) => {
            const w = (it.value / max) * plotW;
            const cy = i * rowH + rowH / 2;
            const rr = Math.min(4, w);
            return (
              <g
                key={it.label}
                tabIndex={0}
                aria-label={`${it.label}: ${fmt(it.value)}`}
                onPointerEnter={() => setHover(i)}
                onPointerLeave={() => setHover(null)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
                className="outline-none"
              >
                <rect x={0} y={i * rowH} width={width} height={rowH} fill="transparent" />
                <text x={labelW - 8} y={cy} dy="0.32em" textAnchor="end" fontSize={12} fill={VIZ.secondary}>
                  {it.label.length > 18 ? `${it.label.slice(0, 17)}…` : it.label}
                </text>
                {w > 0 && (
                  <path
                    d={`M${labelW},${cy - barH / 2} H${labelW + w - rr} Q${labelW + w},${cy - barH / 2} ${labelW + w},${cy - barH / 2 + rr} V${cy + barH / 2 - rr} Q${labelW + w},${cy + barH / 2} ${labelW + w - rr},${cy + barH / 2} H${labelW} Z`}
                    fill={color}
                    fillOpacity={hover === i ? 0.75 : 1}
                  />
                )}
                <text x={labelW + w + 6} y={cy} dy="0.32em" fontSize={11} fontWeight={600} fill={VIZ.secondary} style={{ fontVariantNumeric: "tabular-nums" }}>
                  {fmt(it.value)}
                </text>
              </g>
            );
          })}
        </svg>
      )}
      {hover !== null && width > 0 && (
        <Tooltip
          x={labelW + 8}
          y={hover * rowH + rowH}
          containerWidth={width}
          title={items[hover].label}
          rows={[{ color, value: fmt(items[hover].value), label: seriesName }, ...(items[hover].detail ? [{ value: items[hover].detail!, label: "" }] : [])]}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Part-to-whole: one 100% bar, 2px surface gaps, legend with values.
// ---------------------------------------------------------------------------
export function ShareBar({ parts, fmt, ariaLabel }: { parts: { name: string; value: number; color: string }[]; fmt: (n: number) => string; ariaLabel: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const total = parts.reduce((s, p) => s + p.value, 0);
  const h = 18;
  const gap = 2;
  const visible = parts.filter((p) => p.value > 0);
  const usable = Math.max(0, width - gap * Math.max(0, visible.length - 1));
  let cursor = 0;

  return (
    <div className="space-y-3">
      <div ref={ref} className="relative w-full" style={{ height: h }}>
        {width > 0 && total > 0 && (
          <svg width={width} height={h} role="img" aria-label={ariaLabel}>
            <defs>
              <clipPath id="sharebar-clip">
                <rect x={0} y={0} width={width} height={h} rx={4} />
              </clipPath>
            </defs>
            <g clipPath="url(#sharebar-clip)">
              {visible.map((p, i) => {
                const w = (p.value / total) * usable;
                const x = cursor;
                cursor += w + gap;
                return (
                  <rect
                    key={p.name}
                    x={x}
                    y={0}
                    width={Math.max(0, w)}
                    height={h}
                    fill={p.color}
                    fillOpacity={hover === i ? 0.75 : 1}
                    tabIndex={0}
                    aria-label={`${p.name}: ${fmt(p.value)}`}
                    onPointerEnter={() => setHover(i)}
                    onPointerLeave={() => setHover(null)}
                    onFocus={() => setHover(i)}
                    onBlur={() => setHover(null)}
                    className="outline-none"
                  />
                );
              })}
            </g>
          </svg>
        )}
        {total === 0 && <div className="h-full rounded bg-gray-100" />}
      </div>
      {/* The legend prints every value - the relief channel for the low-contrast aqua slot. */}
      <div className="space-y-1.5">
        {parts.map((p) => (
          <div key={p.name} className="flex items-center justify-between text-xs">
            <span className="flex items-center gap-2" style={{ color: VIZ.secondary }}>
              <span className="inline-block w-2.5 h-2.5 rounded-[3px]" style={{ background: p.color }} />
              {p.name}
            </span>
            <span className="tabular-nums" style={{ color: VIZ.primary }}>
              <span className="font-semibold">{fmt(p.value)}</span>
              <span className="ms-2" style={{ color: VIZ.muted }}>{total > 0 ? `${Math.round((p.value / total) * 100)}%` : "—"}</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Meter - a single ratio against its whole, same-ramp track.
// ---------------------------------------------------------------------------
export function Meter({ ratio, label, detail }: { ratio: number; label: string; detail: string }) {
  const pct = Math.max(0, Math.min(1, ratio));
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1.5">
        <span className="text-xs" style={{ color: VIZ.secondary }}>{label}</span>
        <span className="text-sm font-bold" style={{ color: VIZ.primary }}>{Math.round(pct * 100)}%</span>
      </div>
      <div className="h-2 rounded-full overflow-hidden" style={{ background: VIZ.track }} role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct * 100)} aria-label={label}>
        <div className="h-full rounded-full" style={{ width: `${pct * 100}%`, background: VIZ.series[0] }} />
      </div>
      <div className="text-[11px] mt-1" style={{ color: VIZ.muted }}>{detail}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stat tile - label · value · delta vs previous period · sparkline.
// ---------------------------------------------------------------------------
function Sparkline({ values }: { values: number[] }) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const h = 28;
  if (values.length < 2) return null;
  return (
    <div ref={ref} className="w-full mt-2" style={{ height: h }}>
      {w > 0 && <SparklineSvg values={values} w={w} h={h} />}
    </div>
  );
}

function SparklineSvg({ values, w, h }: { values: number[]; w: number; h: number }) {
  const max = Math.max(...values);
  const min = Math.min(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => [(i / (values.length - 1)) * (w - 6) + 3, h - 3 - ((v - min) / span) * (h - 6)]);
  const last = pts[pts.length - 1];
  return (
    <svg width={w} height={h} aria-hidden="true">
      <polyline points={pts.map((p) => p.join(",")).join(" ")} fill="none" stroke={VIZ.deemph} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r={3} fill={VIZ.series[0]} stroke={VIZ.surface} strokeWidth={1.5} />
    </svg>
  );
}

export function StatTile({
  label, value, current, previous, upIsGood = true, periodLabel, spark, note,
}: {
  label: string; value: string; current?: number; previous?: number; upIsGood?: boolean; periodLabel?: string; spark?: number[]; note?: string;
}) {
  let delta: React.ReactNode = null;
  if (current !== undefined && previous !== undefined) {
    if (previous === 0) {
      delta = <span style={{ color: VIZ.muted }}>{current > 0 ? `new vs ${periodLabel}` : `flat vs ${periodLabel}`}</span>;
    } else {
      const pct = ((current - previous) / Math.abs(previous)) * 100;
      const up = pct >= 0;
      const good = up === upIsGood;
      delta = (
        <span style={{ color: Math.abs(pct) < 0.05 ? VIZ.muted : good ? VIZ.upGoodText : VIZ.downBadText }} className="font-semibold">
          {up ? "▲" : "▼"} {Math.abs(pct).toFixed(Math.abs(pct) >= 10 ? 0 : 1)}%
          <span className="font-normal ms-1" style={{ color: VIZ.muted }}>vs {periodLabel}</span>
        </span>
      );
    }
  }
  return (
    // Value gets the full width; the sparkline sits under it, so a narrow
    // tile never truncates the number.
    <div className="glass-panel rounded-2xl border border-gray-200 p-4 bg-white min-w-0">
      <div className="text-xs" style={{ color: VIZ.secondary }}>{label}</div>
      <div className="text-2xl font-semibold mt-1 whitespace-nowrap" style={{ color: VIZ.primary }}>{value}</div>
      <div className="text-[11px] mt-0.5 truncate">{delta ?? <span style={{ color: VIZ.muted }}>{note}</span>}</div>
      {spark && <Sparkline values={spark} />}
    </div>
  );
}
