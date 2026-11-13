import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { ForensicStudio as StudioResult } from "../types";

const videoKeys = ["original", "control", "watermarked", "residual", "difference"] as const;
const labels: Record<(typeof videoKeys)[number], string> = {
  original: "Original recortado",
  control: "Controle sem marca (mesmo codec)",
  watermarked: "Marca CDNWM4 entregue",
  residual: "Resíduo antes do codec · 8×",
  difference: "Diferença após codec · 8×",
};

export function ForensicStudio({ onError }: { onError: (message: string) => void }) {
  const [algorithm, setAlgorithm] = useState<"qim2" | "qim3">("qim3");
  const [result, setResult] = useState<StudioResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(4);
  const players = useRef<Record<string, HTMLVideoElement | null>>({});

  useEffect(() => {
    if (!result) return;
    const timer = window.setInterval(() => {
      const master = players.current.original;
      if (!master) return;
      setTime(master.currentTime);
      for (const key of videoKeys) {
        if (key === "original") continue;
        const player = players.current[key];
        if (player && player.readyState >= 2 && Math.abs(player.currentTime - master.currentTime) > 0.08) {
          player.currentTime = master.currentTime;
        }
      }
    }, 180);
    return () => window.clearInterval(timer);
  }, [result]);

  async function run() {
    setBusy(true);
    setResult(null);
    setPlaying(false);
    try {
      setResult(await api.forensicStudio({ algorithm }));
      setTime(0);
    } catch (error) {
      onError(error instanceof Error ? error.message : "Falha no Studio CDNWM4.");
    } finally {
      setBusy(false);
    }
  }

  function togglePlayback() {
    const next = !playing;
    for (const player of Object.values(players.current)) {
      if (!player) continue;
      if (next) void player.play().catch(() => undefined);
      else player.pause();
    }
    setPlaying(next);
  }

  function seek(value: number) {
    for (const player of Object.values(players.current)) {
      if (player) player.currentTime = value;
    }
    setTime(value);
  }

  const detection = result?.visual_detection;
  return (
    <section className="watermark-lab forensic-studio" aria-label="Studio forense CDNWM4">
      <div className="forensic-studio__heading">
        <div>
          <p className="eyebrow">PIPELINE FORENSE REAL</p>
          <h2>CDNWM4 · Watermark Studio</h2>
          <p>Emite um claim de sessão, marca um clipe local e testa extração, ledger e correspondência do conteúdo.</p>
        </div>
        <div className="forensic-studio__actions">
          <label>Algoritmo
            <select value={algorithm} disabled={busy} onChange={(event) => setAlgorithm(event.target.value as "qim2" | "qim3")}>
              <option value="qim3">QIM3 · máscara + ECC</option>
              <option value="qim2">QIM2 · base</option>
            </select>
          </label>
          <button type="button" onClick={() => void run()} disabled={busy}>{busy ? "Processando clipe e investigando…" : "Executar demonstração"}</button>
        </div>
      </div>
      {!result && !busy && <p role="note">Use Big Buck Bunny, 4 s. A geração pode levar alguns segundos.</p>}
      {result && <>
        <div className="forensic-studio__status" aria-live="polite">
          <article><strong>Extração visual</strong><span>{detection?.status ?? "INCONCLUSIVE"}</span><small>Marcador: {detection?.marker ?? "não recuperado"}</small></article>
          <article><strong>Claim no ledger</strong><span>{result.ledger_status ?? "INCONCLUSIVE"}</span><small>Associação exata e assinatura criptográfica</small></article>
          <article><strong>Correspondência do conteúdo</strong><span>{result.investigation.content_match?.status ?? "INCONCLUSIVE"}</span><small>{result.investigation.content_match?.matched_frames ?? 0} quadros de 1 s correspondentes</small></article>
          <article><strong>Investigação</strong><span>{result.investigation.decision}</span><small>Sem ação administrativa automática</small></article>
        </div>
        <p className="panel-subtitle">
          Sessão {String(result.claim.session_id)} · {result.algorithm_id} · {result.fingerprint_scheme} ·
          ECC {detection?.ecc_status ?? "não aplicável"} ({detection?.ecc_corrected_bits ?? 0} bit corrigido) ·
          {detection?.frames_sampled ?? 0} quadros analisados
        </p>
        <p className="panel-subtitle">PSNR {result.quality_vs_control.psnr_db.toFixed(2)} dB · SSIM janelado {result.quality_vs_control.ssim_windowed.toFixed(4)} · MS-SSIM aproximado em três escalas {result.quality_vs_control.ms_ssim_3scale_approx.toFixed(4)} · maior delta médio regional {result.quality_vs_control.region_mean_abs_luma_max.toFixed(2)} · alinhamento {result.video_alignment.aligned ? "confirmado" : "não confirmado"}</p>
        <div className="forensic-studio__checks" aria-label="Testes reais de resistência">
          {result.robustness_checks.map((check) => <span key={check.filter_id}>{check.filter}: <strong>{check.status}</strong> · {check.bits_correct}/{check.bits_total} bits · {check.survives ? "marcador exato" : "sem recuperação exata"}</span>)}
        </div>
        <div className="watermark-sync-toolbar">
          <button type="button" onClick={togglePlayback}>{playing ? "Pausar todos" : "Reproduzir todos"}</button>
          <label>Instante {time.toFixed(2)} s
            <input type="range" min="0" max={duration || 4} step="0.01" value={Math.min(time, duration || 4)} onChange={(event) => seek(Number(event.target.value))} />
          </label>
        </div>
        <div className="forensic-studio__grid">
          {videoKeys.map((key) => <figure key={key}>
            <figcaption>{labels[key]}</figcaption>
            <video ref={(node) => { players.current[key] = node; }} src={result.video_variants[key]} muted playsInline preload="metadata" onLoadedMetadata={(event) => { if (key === "original") setDuration(event.currentTarget.duration); }} />
          </figure>)}
          <figure><figcaption>Mapa de detecção · primeiro quadro</figcaption><img src={result.video_variants.detection_map} alt="Mapa dos blocos QIM: verde concorda com o marcador emitido, vermelho diverge e cinza foi mascarado" /></figure>
        </div>
        <p role="note" className="panel-subtitle">Resíduo e diferença usam ganho visual de 8×. O mapa usa o marcador emitido como referência diagnóstica; a extração acima é independente. Resultado PENDING_REVIEW exige revisão humana.</p>
      </>}
    </section>
  );
}
