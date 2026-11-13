import { BookOpenCheck, FlaskConical, KeyRound } from "lucide-react";
import { ForensicStudio } from "../components/ForensicStudio";
import type { Overview } from "../types";

export function WatermarkPage({
  overview: _overview,
  onError,
}: {
  overview: Overview;
  onError: (message: string) => void;
}) {
  return (
    <main className="page-content watermark-page">
      <header className="watermark-page__hero">
        <div>
          <p className="eyebrow">WATERMARKING · AMBIENTE DE ESTUDO</p>
          <h1>Watermark Lab</h1>
          <p className="page-lead">
            Um espaço independente para observar como uma marca visual é criada,
            recuperada e verificada em um clipe real, sem representar a interface da CDN.
          </p>
        </div>
        <div className="watermark-page__hero-notes" aria-label="Escopo do laboratório">
          <span><FlaskConical size={15} /> sessão local controlada</span>
          <span><BookOpenCheck size={15} /> roteiro e métricas explicados</span>
          <span><KeyRound size={15} /> parâmetros de teste visíveis</span>
        </div>
      </header>

      <ForensicStudio onError={onError} />

    </main>
  );
}
