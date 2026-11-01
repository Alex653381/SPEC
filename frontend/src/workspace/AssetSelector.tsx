import { useCallback, useEffect, useRef, useState } from "react";
import { getAssets } from "../api/client";
import type { Asset, AssetType } from "../types";
import { TYPE_LABELS } from "./labels";

interface AssetSelectorProps {
  onAdd: (asset: Asset) => void;
  disabled: boolean;
}

export default function AssetSelector({ onAdd, disabled }: AssetSelectorProps) {
  const [query, setQuery] = useState("");
  const [assetType, setAssetType] = useState<AssetType | null>(null);
  const [results, setResults] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);

  const load = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const data = await getAssets({
        asset_type: assetType ?? undefined,
        q: query || undefined,
        limit: 50,
      });
      if (id === requestId.current) setResults(data.items);
    } catch (err) {
      if (id === requestId.current) setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [assetType, query]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="selector">
      <div className="toolbar">
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="按代码或名称搜索" />
        <button className={`filter-button ${assetType === null ? "active" : ""}`} onClick={() => setAssetType(null)}>
          全部
        </button>
        {(["stock", "index", "etf", "open_fund"] as AssetType[]).map((type) => (
          <button
            key={type}
            className={`filter-button ${assetType === type ? "active" : ""}`}
            onClick={() => setAssetType(type)}
          >
            {TYPE_LABELS[type]}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="status">加载中…</div>
      ) : error ? (
        <div className="status">
          {error}
          <button className="asset-button" onClick={() => void load()}>
            重试
          </button>
        </div>
      ) : results.length === 0 ? (
        <div className="status">无匹配资产</div>
      ) : (
        <div className="selector-results">
          {results.map((asset) => (
            <div className="result-row" key={asset.id}>
              <div>
                <div className="asset-name">
                  {asset.name} · {TYPE_LABELS[asset.asset_type]}
                </div>
                <div className="asset-meta">
                  {asset.symbol} · {asset.market} · {asset.provider}
                </div>
              </div>
              <button className="asset-button" disabled={disabled} onClick={() => onAdd(asset)}>
                添加
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
