"use client";

import React, { useEffect, useState } from "react";
import { FileText, ExternalLink, RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import LegalMarkdown from "@/components/LegalMarkdown";
import ConfirmDialog from "@/components/ConfirmDialog";
import { formatDateTime } from "@/lib/datetime";

type LegalDoc = { slug: string; title: string; body: string; updated_at: string | null; is_default: boolean };

function getToken() {
  try {
    return localStorage.getItem("esim_token");
  } catch {
    return null;
  }
}

export default function LegalContentCard({ isSuperAdmin }: { isSuperAdmin: boolean }) {
  const [docs, setDocs] = useState<LegalDoc[]>([]);
  const [active, setActive] = useState("terms");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState(false);
  const [saving, setSaving] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    api
      .getAdminLegalDocuments(token)
      .then((res: { documents: LegalDoc[] }) => {
        setDocs(res.documents);
        setDrafts(Object.fromEntries(res.documents.map((d) => [d.slug, d.body])));
      })
      .catch((err: any) => setNotice({ kind: "error", text: err.message || "Couldn't load legal pages" }));
  }, []);

  const doc = docs.find((d) => d.slug === active);
  const draft = drafts[active] ?? "";
  const dirty = !!doc && draft !== doc.body;

  const save = async (body: string) => {
    const token = getToken();
    if (!token || !doc) return;
    setSaving(true);
    setNotice(null);
    try {
      const saved: LegalDoc = await api.updateAdminLegalDocument(token, doc.slug, body);
      setDocs((all) => all.map((d) => (d.slug === saved.slug ? saved : d)));
      setDrafts((all) => ({ ...all, [saved.slug]: saved.body }));
      setNotice({
        kind: "ok",
        text: saved.is_default ? `${saved.title} reset to the built-in draft.` : `${saved.title} saved — live within 5 minutes.`,
      });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't save" });
    } finally {
      setSaving(false);
      setResetOpen(false);
    }
  };

  return (
    <div className="glass-panel rounded-2xl p-6 border border-gray-200">
      <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
        <FileText className="w-4 h-4 text-admin-600" /> Legal pages
      </h3>
      <p className="text-xs text-slate-500 mt-1 max-w-3xl">
        Shown at /legal/… and linked from the footer and sign-up page. Formatting: <code>## Heading</code>,{" "}
        <code>- bullet</code>, <code>**bold**</code>, blank line between paragraphs. <code>{"{platform_name}"}</code> and{" "}
        <code>{"{support_email}"}</code> are filled in from branding.
      </p>

      <div className="flex flex-wrap items-center gap-1 mt-4 border-b border-gray-200">
        {docs.map((d) => (
          <button
            key={d.slug}
            type="button"
            onClick={() => {
              setActive(d.slug);
              setNotice(null);
            }}
            className={`px-3 py-2 text-xs font-semibold border-b-2 -mb-px ${
              d.slug === active ? "border-admin-600 text-admin-700" : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
          >
            {d.title}
            {drafts[d.slug] !== d.body && <span className="ms-1 text-amber-500">•</span>}
          </button>
        ))}
      </div>

      {doc && (
        <div className="mt-4">
          <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
            <div className="text-[11px]">
              {doc.is_default ? (
                <span className="px-2 py-0.5 rounded bg-amber-50 text-amber-700 font-semibold">
                  Built-in draft — have it reviewed before launch
                </span>
              ) : (
                <span className="text-slate-500">
                  Last saved {formatDateTime(doc.updated_at, "")}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 text-xs">
              <label className="flex items-center gap-1.5 text-slate-700">
                <input type="checkbox" checked={preview} onChange={(e) => setPreview(e.target.checked)} className="accent-admin-500" />
                Preview
              </label>
              <a href={`/legal/${doc.slug}`} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-admin-600 hover:underline">
                Live page <ExternalLink className="w-3 h-3" />
              </a>
            </div>
          </div>

          {preview ? (
            <div className="rounded-xl border border-gray-200 bg-white p-5 max-h-[520px] overflow-y-auto">
              <LegalMarkdown body={draft} />
            </div>
          ) : (
            <textarea
              value={draft}
              readOnly={!isSuperAdmin}
              onChange={(e) => setDrafts((all) => ({ ...all, [active]: e.target.value }))}
              rows={22}
              maxLength={60000}
              className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs leading-relaxed font-mono text-slate-900"
            />
          )}

          {isSuperAdmin && (
            <div className="flex flex-wrap items-center gap-3 mt-3">
              <button
                type="button"
                onClick={() => save(draft)}
                disabled={!dirty || saving || !draft.trim()}
                className="bg-admin-600 hover:bg-admin-500 disabled:opacity-50 text-white text-xs font-bold px-4 py-2.5 rounded-xl"
              >
                {saving ? "Saving…" : `Save ${doc.title}`}
              </button>
              {!doc.is_default && (
                <button
                  type="button"
                  onClick={() => setResetOpen(true)}
                  className="flex items-center gap-1 text-xs text-slate-600 hover:text-rose-600"
                >
                  <RotateCcw className="w-3.5 h-3.5" /> Reset to built-in draft
                </button>
              )}
              <span className="text-[11px] text-slate-500">{draft.length.toLocaleString()} / 60,000</span>
            </div>
          )}
        </div>
      )}
      {notice && <p className={`text-xs font-medium mt-3 ${notice.kind === "ok" ? "text-emerald-600" : "text-rose-600"}`}>{notice.text}</p>}

      <ConfirmDialog
        open={resetOpen && !!doc}
        title={`Reset ${doc?.title ?? ""}?`}
        tone="danger"
        icon={<RotateCcw className="w-5 h-5" />}
        confirmLabel="Reset to draft"
        busy={saving}
        onConfirm={() => save("")}
        onCancel={() => setResetOpen(false)}
      >
        <p>Your saved text is replaced by the built-in draft on the live page. This can&apos;t be undone.</p>
      </ConfirmDialog>
    </div>
  );
}
