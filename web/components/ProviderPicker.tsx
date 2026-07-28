"use client";

/**
 * Provider + model selector.
 *
 * The list is fetched live from the backend, which in turn asks Ollama, so
 * pulling a new model makes it appear here without restarting anything. A
 * provider that is present but unusable (no API key, server down) is shown
 * disabled with the reason rather than hidden.
 */

import type { ProvidersPayload } from "@/lib/types";

interface Props {
  providers: ProvidersPayload | null;
  provider: string;
  model: string;
  onProviderChange: (name: string) => void;
  onModelChange: (name: string) => void;
  disabled?: boolean;
}

export default function ProviderPicker({
  providers,
  provider,
  model,
  onProviderChange,
  onModelChange,
  disabled,
}: Props) {
  if (!providers) {
    return (
      <div className="panel">
        <h2>Provider</h2>
        <p className="empty">Loading providers…</p>
      </div>
    );
  }

  const selected = providers.data.find((p) => p.name === provider);

  return (
    <div className="panel">
      <h2>Provider</h2>

      <div style={{ marginBottom: 12 }}>
        <label htmlFor="provider">Answering model comes from</label>
        <select
          id="provider"
          value={provider}
          disabled={disabled}
          onChange={(e) => {
            const next = e.target.value;
            onProviderChange(next);
            const p = providers.data.find((x) => x.name === next);
            onModelChange(p?.default_model ?? "");
          }}
        >
          {providers.data.map((p) => (
            <option key={p.name} value={p.name} disabled={!p.available}>
              {p.name}
              {p.available ? "" : " — unavailable"}
            </option>
          ))}
        </select>
      </div>

      {selected && !selected.available && (
        <p className="hint" style={{ marginTop: -6, marginBottom: 12 }}>
          {selected.detail}
        </p>
      )}

      <div>
        <label htmlFor="model">Model</label>
        <select
          id="model"
          value={model}
          disabled={disabled || !selected?.available}
          onChange={(e) => onModelChange(e.target.value)}
        >
          {selected?.models.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name}
            </option>
          ))}
        </select>
      </div>

      <p className="hint" style={{ marginTop: 12 }}>
        Embeddings always run locally via{" "}
        <span className="mono">{providers.embedding_model}</span> (
        {providers.embedding_dimensions}-dim). Anthropic has no embeddings API,
        so only generation is switchable.
      </p>
    </div>
  );
}
