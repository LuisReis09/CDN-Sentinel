import { MapPin, ServerCog, UserPlus, X } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import type { MapEditMode } from "./MapBrushToolbar";

interface MapPlacementDialogProps {
  mode: Exclude<MapEditMode, null>;
  latitude: number;
  longitude: number;
  busy: boolean;
  onClose: () => void;
  onSubmit: (payload: Record<string, unknown>) => Promise<void>;
}

export function MapPlacementDialog({
  mode,
  latitude,
  longitude,
  busy,
  onClose,
  onSubmit,
}: MapPlacementDialogProps) {
  const [malicious, setMalicious] = useState(false);

  useEffect(() => setMalicious(false), [latitude, longitude, mode]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    await onSubmit({
      latitude,
      longitude,
      ...(mode === "client" ? { malicious } : {}),
    });
  }

  const isClient = mode === "client";
  return (
    <div
      className="dialog-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="placement-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="placement-title"
      >
        <header>
          <div
            className={`placement-icon ${isClient ? "placement-icon-client" : "placement-icon-server"}`}
          >
            {isClient ? <UserPlus size={18} /> : <ServerCog size={18} />}
          </div>
          <div>
            <p className="eyebrow">MAP PLACEMENT</p>
            <h2 id="placement-title">
              Adicionar {isClient ? "usuário" : "servidor CDN"}
            </h2>
          </div>
          <button
            type="button"
            className="icon-button"
            onClick={onClose}
            aria-label="Fechar"
          >
            <X size={17} />
          </button>
        </header>
        <div className="coordinate-readout">
          <MapPin size={14} />
          <span>
            {latitude.toFixed(4)}, {longitude.toFixed(4)}
          </span>
          <small>posição selecionada</small>
        </div>
        <form onSubmit={(event) => void submit(event)}>
          <div className="auto-assignment">
            <strong>Cadastro automático</strong>
            <span>ID, porta e cidade serão atribuídos pelo backend.</span>
          </div>
          {isClient ? (
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={malicious}
                onChange={(event) => setMalicious(event.target.checked)}
              />{" "}
              marcar como cliente malicioso
            </label>
          ) : (
            <div className="auto-assignment">
              <strong>Processo CDN dedicado</strong>
              <span>Um novo nó HTTP entrará no gossip com porta livre.</span>
            </div>
          )}
          <div className="dialog-actions">
            <button
              type="button"
              className="button button-ghost"
              onClick={onClose}
            >
              Cancelar
            </button>
            <button
              type="submit"
              className="button button-primary"
              disabled={busy}
            >
              {busy ? "Criando…" : `Criar ${isClient ? "usuário" : "servidor"}`}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
