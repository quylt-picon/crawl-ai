import { useEffect, useState, type FormEvent } from "react";
import { Search } from "lucide-react";
import type { SearchInput } from "@/lib/api";

interface Preset {
  label: string;
  website_url: string;
  product_name: string;
  product_code: string;
}

interface Props {
  onSubmit: (input: SearchInput) => void;
  disabled?: boolean;
  /** When true, show a "search without a specific site" toggle that makes the
   * website URL optional (web-search tab); the crawl tab always needs a site. */
  allowNoSite?: boolean;
}

export function SearchForm({ onSubmit, disabled, allowNoSite }: Props) {
  const [websiteUrl, setWebsiteUrl] = useState(
    ""
  );
  const [productName, setProductName] = useState("");
  const [productCode, setProductCode] = useState("");
  const [noSite, setNoSite] = useState(false);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selectedPreset, setSelectedPreset] = useState<string>("");

  useEffect(() => {
    fetch("/presets.json")
      .then((res) => (res.ok ? res.json() : []))
      .then((data: Preset[]) => setPresets(Array.isArray(data) ? data : []))
      .catch(() => setPresets([]));
  }, []);

  const onPresetChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const idx = e.target.value;
    setSelectedPreset(idx);
    if (idx === "") return;
    const preset = presets[Number(idx)];
    if (!preset) return;
    setWebsiteUrl(preset.website_url);
    setProductName(preset.product_name);
    setProductCode(preset.product_code);
  };

  const siteless = allowNoSite && noSite;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (disabled) return;
    onSubmit({
      // Omit the URL entirely when searching site-less so the backend treats it
      // as "no preferred site" rather than validating an empty string.
      website_url: siteless ? undefined : websiteUrl.trim(),
      product_name: productName.trim(),
      product_code: productCode.trim(),
    });
  };

  return (
    <form className="card" onSubmit={submit}>
      <div className="card-header flex items-center justify-between">
        <h2 className="text-base font-semibold text-slate-900">Search a product manual</h2>
      </div>
      <div className="card-body grid grid-cols-1 gap-4 md:grid-cols-3">
        {presets.length > 0 && (
          <div className="md:col-span-3">
            <label className="label" htmlFor="preset">Preset</label>
            <select
              id="preset"
              className="input"
              value={selectedPreset}
              onChange={onPresetChange}
            >
              <option value="">— Chọn preset có sẵn —</option>
              {presets.map((p, i) => (
                <option key={i} value={i}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="md:col-span-3">
          <div className="flex items-center justify-between">
            <label className="label" htmlFor="website_url">Website URL</label>
            {allowNoSite && (
              <label className="flex cursor-pointer items-center gap-1.5 text-xs font-medium text-slate-500">
                <input
                  type="checkbox"
                  className="h-3.5 w-3.5 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                  checked={noSite}
                  disabled={disabled}
                  onChange={(e) => setNoSite(e.target.checked)}
                />
                Không chỉ định site — tự tìm kiếm
              </label>
            )}
          </div>
          <input
            id="website_url"
            className="input"
            value={siteless ? "" : websiteUrl}
            onChange={(e) => setWebsiteUrl(e.target.value)}
            placeholder={siteless ? "Tự tìm trên web (không cần website)" : "https://www.example.com"}
            required={!siteless}
            disabled={disabled || siteless}
          />
        </div>
        <div className="md:col-span-2">
          <label className="label" htmlFor="product_name">Product name</label>
          <input
            id="product_name"
            className="input"
            value={productName}
            onChange={(e) => setProductName(e.target.value)}
            placeholder="Máy giặt cửa trên ..."
            required
          />
        </div>
        <div>
          <label className="label" htmlFor="product_code">Product code</label>
          <input
            id="product_code"
            className="input"
            value={productCode}
            onChange={(e) => setProductCode(e.target.value)}
            placeholder="NA-F85S11BRV"
            required
          />
        </div>
        <div className="md:col-span-3 flex justify-end">
          <button type="submit" className="btn-primary" disabled={disabled}>
            <Search className="h-4 w-4" />
            {disabled ? "Running…" : "Start search"}
          </button>
        </div>
      </div>
    </form>
  );
}
