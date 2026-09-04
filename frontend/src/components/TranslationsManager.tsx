"use client";

import React, { useState, useEffect } from "react";
import { Languages, Plus, Save, Sparkles } from "lucide-react";
import { api } from "@/lib/api";

interface LanguageMeta {
  code: string;
  name: string;
  native_name: string;
  flag_emoji?: string;
  is_active: boolean;
  is_rtl: boolean;
}

const NAMESPACES = ["common", "nav", "hero", "catalog", "checkout", "esim", "reseller", "wallet", "admin"];

export default function TranslationsManager({ languages: initialLanguages }: { languages: LanguageMeta[] }) {
  const [languages, setLanguages] = useState<LanguageMeta[]>(initialLanguages);
  const [newCode, setNewCode] = useState("");
  const [newName, setNewName] = useState("");
  const [newNative, setNewNative] = useState("");
  const [newIsRTL, setNewIsRTL] = useState(false);
  const [creating, setCreating] = useState(false);

  const [editLang, setEditLang] = useState("en");
  const [editNamespace, setEditNamespace] = useState("common");
  const [editKey, setEditKey] = useState("site_name");
  const [editValue, setEditValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [autoTranslating, setAutoTranslating] = useState<string | null>(null);

  const refreshLanguages = () => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    api.getAllLanguages(token).then(setLanguages).catch(() => {});
  };

  useEffect(() => {
    refreshLanguages();
  }, []);

  useEffect(() => {
    if (languages.length && !languages.some((l) => l.code === editLang)) {
      setEditLang(languages[0].code);
    }
  }, [languages, editLang]);

  useEffect(() => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    api.getTranslations(editLang).then((data: any) => {
      const val = data?.namespaces?.[editNamespace]?.[editKey];
      if (val !== undefined) setEditValue(val);
    }).catch(() => {});
  }, [editLang, editNamespace, editKey]);

  const handleCreateLanguage = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setCreating(true);
    try {
      const res = await api.createLanguage(token, {
        code: newCode.trim().toLowerCase(),
        name: newName.trim(),
        native_name: newNative.trim() || newName.trim(),
        is_rtl: newIsRTL,
        seed_from_english: true,
      });
      alert(`Language "${newCode}" added and seeded with ${res.seeded_keys} placeholder strings.`);
      setNewCode(""); setNewName(""); setNewNative(""); setNewIsRTL(false);
      refreshLanguages();
    } catch (err: any) {
      alert(err.message || "Failed to create language");
    } finally {
      setCreating(false);
    }
  };

  const handleSaveTranslation = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setSaving(true);
    try {
      await api.upsertTranslation(token, {
        language_code: editLang,
        namespace: editNamespace,
        key: editKey,
        value: editValue,
      });
      alert("Translation saved.");
    } catch (err: any) {
      alert(err.message || "Failed to save translation");
    } finally {
      setSaving(false);
    }
  };

  const handleAutoTranslate = async (code: string) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setAutoTranslating(code);
    try {
      const res = await api.autoTranslateLanguage(token, code);
      alert(`Filled ${res.filled_keys} missing string(s) for "${code}" with English placeholder text, flagged for review. No live machine-translation provider is configured in this deployment.`);
    } catch (err: any) {
      alert(err.message || "Auto-translate failed");
    } finally {
      setAutoTranslating(null);
    }
  };

  const handleToggleLanguage = async (code: string, isActive: boolean) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    try {
      await api.toggleLanguage(token, code, !isActive);
      refreshLanguages();
    } catch (err: any) {
      alert(err.message || "Failed to toggle language");
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
      {/* Active Languages List */}
      <div className="glass-panel rounded-2xl p-6 border border-gray-200 lg:col-span-2">
        <h3 className="text-base font-bold text-slate-900 mb-1 flex items-center space-x-2">
          <Languages className="w-4 h-4 text-admin-600" />
          <span>Language Catalog</span>
        </h3>
        <p className="text-xs text-slate-500 mb-4">Activate/deactivate languages and trigger a bulk auto-translate pass (English placeholders, flagged for human review — no external MT provider is wired up in this deployment).</p>
        <div className="overflow-x-auto">
          <table className="w-full text-start text-xs">
            <thead className="text-slate-500 border-b border-gray-200">
              <tr>
                <th className="py-2">Language</th>
                <th className="py-2">Code</th>
                <th className="py-2">RTL</th>
                <th className="py-2">Status</th>
                <th className="py-2">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {languages.map((l) => (
                <tr key={l.code}>
                  <td className="py-2.5 text-slate-900 font-semibold">{l.flag_emoji} {l.native_name}</td>
                  <td className="py-2.5 font-mono text-slate-500">{l.code}</td>
                  <td className="py-2.5 text-slate-500">{l.is_rtl ? "Yes" : "No"}</td>
                  <td className="py-2.5">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${l.is_active ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-slate-500"}`}>
                      {l.is_active ? "ACTIVE" : "INACTIVE"}
                    </span>
                  </td>
                  <td className="py-2.5 space-x-2">
                    <button onClick={() => handleToggleLanguage(l.code, l.is_active)} className="bg-gray-100 hover:bg-gray-200 text-slate-700 px-2.5 py-1 rounded text-[11px] font-bold">
                      {l.is_active ? "Deactivate" : "Activate"}
                    </button>
                    {l.code !== "en" && (
                      <button
                        onClick={() => handleAutoTranslate(l.code)}
                        disabled={autoTranslating === l.code}
                        className="bg-admin-600 hover:bg-admin-500 px-2.5 py-1 rounded text-[11px] font-bold text-white inline-flex items-center space-x-1"
                      >
                        <Sparkles className="w-3 h-3" />
                        <span>{autoTranslating === l.code ? "Filling..." : "Auto-Translate"}</span>
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add New Language */}
      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        <h3 className="text-base font-bold text-slate-900 mb-1">Add a Language</h3>
        <p className="text-xs text-slate-500 mb-6">Any ISO code. Seeds with English placeholder strings so it's usable immediately.</p>
        <form onSubmit={handleCreateLanguage} className="space-y-3">
          <div>
            <label className="text-xs text-slate-700 font-semibold block mb-1">ISO Code (e.g. ko, vi, id)</label>
            <input required maxLength={10} value={newCode} onChange={(e) => setNewCode(e.target.value)} className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900" />
          </div>
          <div>
            <label className="text-xs text-slate-700 font-semibold block mb-1">English Name (e.g. Korean)</label>
            <input required value={newName} onChange={(e) => setNewName(e.target.value)} className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900" />
          </div>
          <div>
            <label className="text-xs text-slate-700 font-semibold block mb-1">Native Name (e.g. 한국어)</label>
            <input value={newNative} onChange={(e) => setNewNative(e.target.value)} className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900" />
          </div>
          <div className="flex items-center space-x-2">
            <input type="checkbox" id="newIsRTL" checked={newIsRTL} onChange={(e) => setNewIsRTL(e.target.checked)} className="rounded border-gray-300" />
            <label htmlFor="newIsRTL" className="text-xs text-slate-700">Right-to-left script</label>
          </div>
          <button type="submit" disabled={creating} className="bg-admin-600 hover:bg-admin-500 text-white text-xs font-bold px-4 py-2.5 rounded-xl inline-flex items-center space-x-2">
            <Plus className="w-3.5 h-3.5" />
            <span>{creating ? "Adding..." : "Add Language"}</span>
          </button>
        </form>
      </div>

      {/* Translation String Editor */}
      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        <h3 className="text-base font-bold text-slate-900 mb-1">Translation String Editor</h3>
        <p className="text-xs text-slate-500 mb-6">Edit any string per language and namespace — including English itself. Takes effect immediately, no redeploy.</p>
        <form onSubmit={handleSaveTranslation} className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Language</label>
              <select value={editLang} onChange={(e) => setEditLang(e.target.value)} className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900">
                {languages.map((l) => (<option key={l.code} value={l.code}>{l.native_name} ({l.code})</option>))}
              </select>
            </div>
            <div>
              <label className="text-xs text-slate-700 font-semibold block mb-1">Namespace</label>
              <select value={editNamespace} onChange={(e) => setEditNamespace(e.target.value)} className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900">
                {NAMESPACES.map((ns) => (<option key={ns} value={ns}>{ns}</option>))}
              </select>
            </div>
          </div>
          <div>
            <label className="text-xs text-slate-700 font-semibold block mb-1">Key (e.g. site_name, login, buy_now)</label>
            <input required value={editKey} onChange={(e) => setEditKey(e.target.value)} className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900 font-mono" />
          </div>
          <div>
            <label className="text-xs text-slate-700 font-semibold block mb-1">Value</label>
            <textarea required value={editValue} onChange={(e) => setEditValue(e.target.value)} rows={3} className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900" />
          </div>
          <button type="submit" disabled={saving} className="bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold px-4 py-2.5 rounded-xl inline-flex items-center space-x-2">
            <Save className="w-3.5 h-3.5" />
            <span>{saving ? "Saving..." : "Save Translation"}</span>
          </button>
        </form>
      </div>
    </div>
  );
}
