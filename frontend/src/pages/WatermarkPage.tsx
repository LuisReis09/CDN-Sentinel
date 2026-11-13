import {
  Fingerprint,
  LockKeyhole,
  ScanSearch,
  ShieldCheck,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { WatermarkLab } from "../components/WatermarkLab";
import { ForensicStudio } from "../components/ForensicStudio";
import type { Overview } from "../types";

export function WatermarkPage({
  overview,
  onError,
}: {
  overview: Overview;
  onError: (message: string) => void;
}) {
  const [showLegacy, setShowLegacy] = useState(false);
  return (
    <main className="page-content">
      <header className="page-header">
        <div>
          <p className="eyebrow">CRYPTOGRAPHIC CONTENT PROTECTION</p>
          <h1>Watermark studio</h1>
          <p className="page-lead">
            Compare os mesmos instantes do vídeo original, marcado e da diferença
            diagnóstica. A marca visual é experimental; atribuição exige claim autenticado e revisão.
          </p>
        </div>
      </header>
      <section className="watermark-story">
        <StoryCard
          icon={<LockKeyhole />}
          title="Emitir"
          text="A CDN registra uma sessão e um claim cifrado; o vídeo carrega apenas um marcador visual curto."
        />
        <StoryCard
          icon={<Fingerprint />}
          title="Assinar"
          text="AES-256-GCM cifra o claim e HMAC-SHA256 autentica o envelope no ledger."
        />
        <StoryCard
          icon={<ScanSearch />}
          title="Extrair"
          text="O monitor extrai o marcador dos frames e consulta a associação exata no ledger."
        />
        <StoryCard
          icon={<ShieldCheck />}
          title="Governar"
          text="Uma sessão associada vira evidência para revisão; não determina automaticamente a autoria da cópia."
        />
      </section>
      <ForensicStudio onError={onError} />
      <section className="forensic-studio__legacy">
        <button type="button" onClick={() => setShowLegacy((current) => !current)}>
          {showLegacy ? "Fechar laboratório legado CDNWM3" : "Abrir laboratório legado CDNWM3"}
        </button>
        {showLegacy && <><p role="note" className="panel-subtitle">Este laboratório usa CDNWM3 / Adaptive Spread. O resultado não autentica uma sessão CDNWM4.</p><WatermarkLab onError={onError} /></>}
      </section>
    </main>
  );
}

function StoryCard({
  icon,
  title,
  text,
}: {
  icon: ReactNode;
  title: string;
  text: string;
}) {
  return (
    <article className="story-card">
      <span>{icon}</span>
      <h3>{title}</h3>
      <p>{text}</p>
    </article>
  );
}
