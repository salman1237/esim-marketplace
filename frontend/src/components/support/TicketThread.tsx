"use client";

import React, { useState } from "react";
import { FileText, Paperclip, Send, X } from "lucide-react";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/datetime";

export const STATUS_STYLE: Record<string, { badge: string; label: string }> = {
  OPEN: { badge: "bg-amber-50 text-amber-700 border-amber-200", label: "Waiting for support" },
  ANSWERED: { badge: "bg-brand-50 text-brand-700 border-brand-200", label: "Support replied" },
  RESOLVED: { badge: "bg-emerald-50 text-emerald-700 border-emerald-200", label: "Resolved" },
  CLOSED: { badge: "bg-gray-100 text-slate-600 border-gray-200", label: "Closed" },
};

// Staff read the same labels from the queue's point of view.
export const STAFF_STATUS_LABEL: Record<string, string> = {
  OPEN: "Needs a reply",
  ANSWERED: "Waiting on customer",
  RESOLVED: "Resolved",
  CLOSED: "Closed",
};

export function StatusBadge({ status, staff = false }: { status: string; staff?: boolean }) {
  const style = STATUS_STYLE[status] || STATUS_STYLE.OPEN;
  return (
    <span className={`text-[10px] font-bold px-2 py-0.5 rounded border whitespace-nowrap ${style.badge}`}>
      {staff ? STAFF_STATUS_LABEL[status] || status : style.label}
    </span>
  );
}

function AttachmentChip({ attachment }: { attachment: any }) {
  const [busy, setBusy] = useState(false);
  const open = async () => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setBusy(true);
    try {
      const { url } = await api.getSupportAttachmentUrl(token, attachment.url);
      window.open(url, "_blank", "noopener");
    } catch {
      // Nothing useful to say beyond the file not opening.
    } finally {
      setBusy(false);
    }
  };
  return (
    <button
      type="button"
      onClick={open}
      disabled={busy}
      className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-2 py-1 text-[11px] text-slate-700 hover:border-brand-500 disabled:opacity-60"
    >
      <FileText className="w-3 h-3 shrink-0" />
      <span className="max-w-[160px] truncate">{attachment.name}</span>
      <span className="text-slate-400">{Math.round(attachment.size_bytes / 1024)}KB</span>
    </button>
  );
}

/** The conversation, shown identically to the customer and to staff. */
export function Thread({ messages }: { messages: any[] }) {
  return (
    <div className="space-y-4">
      {messages.map((m) => (
        <div key={m.id} className={`flex ${m.is_staff ? "justify-start" : "justify-end"}`}>
          <div className={`max-w-[85%] rounded-2xl px-4 py-3 border ${
            m.is_staff ? "bg-white border-gray-200" : "bg-brand-50 border-brand-200"
          }`}>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[11px] font-bold text-slate-900">{m.author}</span>
              <span className="text-[10px] text-slate-400">{formatDateTime(m.created_at)}</span>
            </div>
            <p className="text-xs text-slate-700 whitespace-pre-wrap break-words">{m.body}</p>
            {m.attachments?.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {m.attachments.map((a: any) => <AttachmentChip key={a.id} attachment={a} />)}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Reply box with attachments, shared by both sides. */
export function ReplyBox({
  onSend, disabled, placeholder = "Write a reply…", sending,
}: {
  onSend: (body: string, files: File[]) => Promise<void>;
  disabled?: boolean;
  placeholder?: string;
  sending?: boolean;
}) {
  const [body, setBody] = useState("");
  const [files, setFiles] = useState<File[]>([]);

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!body.trim() && files.length === 0) return;
    await onSend(body, files);
    setBody("");
    setFiles([]);
  };

  if (disabled) {
    return (
      <p className="text-xs text-slate-500 rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
        This ticket is closed. Open a new one if you need more help.
      </p>
    );
  }

  return (
    <form onSubmit={send} className="space-y-2">
      <textarea
        rows={3}
        value={body}
        maxLength={5000}
        onChange={(e) => setBody(e.target.value)}
        placeholder={placeholder}
        className="w-full bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900"
      />
      {files.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {files.map((f, i) => (
            <span key={i} className="inline-flex items-center gap-1.5 rounded-lg bg-gray-100 border border-gray-200 px-2 py-1 text-[11px] text-slate-700">
              <span className="max-w-[160px] truncate">{f.name}</span>
              <button type="button" onClick={() => setFiles(files.filter((_, n) => n !== i))} aria-label={`Remove ${f.name}`}>
                <X className="w-3 h-3 text-slate-400 hover:text-rose-600" />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <label className="inline-flex items-center gap-1.5 cursor-pointer rounded-xl border border-gray-300 bg-white px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-gray-50">
          <Paperclip className="w-3.5 h-3.5" /> Attach
          <input
            type="file"
            multiple
            accept="image/png,image/jpeg,image/webp,image/heic,application/pdf,text/plain"
            className="hidden"
            onChange={(e) => setFiles([...files, ...Array.from(e.target.files || [])].slice(0, 5))}
          />
        </label>
        <span className="text-[11px] text-slate-400">Up to 5 files, 5MB each</span>
        <button
          type="submit"
          disabled={sending || (!body.trim() && files.length === 0)}
          className="ms-auto inline-flex items-center gap-1.5 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white text-xs font-bold px-4 py-2 rounded-xl"
        >
          <Send className="w-3.5 h-3.5" /> {sending ? "Sending…" : "Send"}
        </button>
      </div>
    </form>
  );
}
