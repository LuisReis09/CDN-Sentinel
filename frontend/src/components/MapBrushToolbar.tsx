import { Brush, ServerCog, UserPlus } from "lucide-react";

export type MapEditMode = "client" | "server" | null;

export function MapBrushToolbar({
  mode,
  onChange,
}: {
  mode: MapEditMode;
  onChange: (mode: MapEditMode) => void;
}) {
  return (
    <div className="map-tools" aria-label="Ferramentas de edição do mapa">
      <span className="map-tools__label">
        <Brush size={14} /> pincel
      </span>
      <button
        type="button"
        className={`map-tool ${mode === "client" ? "map-tool-active map-tool-client" : ""}`}
        onClick={() => onChange(mode === "client" ? null : "client")}
        title="Adicionar usuário no mapa"
      >
        <UserPlus size={14} /> usuário
      </button>
      <button
        type="button"
        className={`map-tool ${mode === "server" ? "map-tool-active map-tool-server" : ""}`}
        onClick={() => onChange(mode === "server" ? null : "server")}
        title="Adicionar servidor CDN no mapa"
      >
        <ServerCog size={14} /> servidor
      </button>
    </div>
  );
}
