import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  CheckCircle2,
  ChevronRight,
  CirclePlay,
  Database,
  Eye,
  FileKey2,
  FlaskConical,
  KeyRound,
  Pause,
  RotateCcw,
  ScanSearch,
  ShieldCheck,
  SlidersHorizontal,
  Video,
} from "lucide-react";
import { api } from "../api";
import type { ForensicStudio as StudioResult } from "../types";

const videoKeys = ["original", "control", "watermarked", "residual", "difference"] as const;
type VideoKey = (typeof videoKeys)[number];

const variants: Record<VideoKey, { label: string; description: string }> = {
  original: { label: "Original", description: "Referência do clipe de teste." },
  control: { label: "Controle", description: "Mesmo codec, sem watermark." },
  watermarked: { label: "Marcado", description: "Versão entregue pelo laboratório." },
  residual: { label: "Resíduo", description: "Sinal antes da compressão, ampliado 8×." },
  difference: { label: "Diferença", description: "Diferença após codec, ampliada 8×." },
};

export function ForensicStudio({ onError }: { onError: (message: string) => void }) {
  const [algorithm, setAlgorithm] = useState<"qim2" | "qim3">("qim3");
  const [result, setResult] = useState<StudioResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(4);
  const [selectedVariant, setSelectedVariant] = useState<VideoKey>("watermarked");
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
    setSelectedVariant("watermarked");
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

  function restart() {
    for (const player of Object.values(players.current)) {
      if (player) player.currentTime = 0;
    }
    setTime(0);
  }

  function seek(value: number) {
    for (const player of Object.values(players.current)) {
      if (player) player.currentTime = value;
    }
    setTime(value);
  }

  const detection = result?.visual_detection;
  const selected = variants[selectedVariant];

  return (
    <section className="forensic-studio" aria-label="Laboratório de watermark CDNWM4">
      <header className="forensic-studio__intro">
        <div>
          <p className="eyebrow">AMBIENTE ISOLADO DE DEMONSTRAÇÃO</p>
          <h2>Laboratório de watermark</h2>
          <p>
            Este ensaio é independente da entrega da CDN. Ele cria uma sessão local,
            marca um clipe curto e mostra a evidência visual e criptográfica em etapas.
          </p>
        </div>
        <span className="forensic-studio__independent"><FlaskConical size={15} /> demonstração local</span>
      </header>

      <div className="forensic-studio__setup">
        <div className="forensic-studio__algorithm">
          <span className="forensic-studio__section-label"><SlidersHorizontal size={14} /> Método do ensaio</span>
          <div className="forensic-studio__algorithm-options" role="radiogroup" aria-label="Método de watermark">
            <label className={algorithm === "qim3" ? "is-selected" : ""}>
              <input type="radio" name="algorithm" value="qim3" checked={algorithm === "qim3"} disabled={busy} onChange={() => setAlgorithm("qim3")} />
              <strong>QIM3</strong><small>Máscara perceptual + ECC SECDED</small>
            </label>
            <label className={algorithm === "qim2" ? "is-selected" : ""}>
              <input type="radio" name="algorithm" value="qim2" checked={algorithm === "qim2"} disabled={busy} onChange={() => setAlgorithm("qim2")} />
              <strong>QIM2</strong><small>Base histórica sem ECC</small>
            </label>
          </div>
        </div>
        <button className="button button-primary forensic-studio__run" type="button" onClick={() => void run()} disabled={busy}>
          <CirclePlay size={16} /> {busy ? "Gerando e verificando…" : "Executar demonstração"}
        </button>
      </div>

      <section className="forensic-studio__guide" aria-label="Roteiro da demonstração">
        <GuideStep number="1" title="Emitir" text="Cria um claim CDNWM4 para uma sessão local." />
        <ChevronRight aria-hidden="true" />
        <GuideStep number="2" title="Marcar" text="Insere o identificador visual no clipe." />
        <ChevronRight aria-hidden="true" />
        <GuideStep number="3" title="Extrair" text="Lê os frames sem receber o token esperado." />
        <ChevronRight aria-hidden="true" />
        <GuideStep number="4" title="Conferir" text="Valida ledger e conteúdo para revisão." />
      </section>

      <details className="forensic-studio__method" open={!result}>
        <summary>O que este teste usa <ChevronRight size={15} /></summary>
        <div className="forensic-studio__method-grid">
          <MethodItem icon={<Video size={16} />} label="Mídia" value="Youtube Clipped Videos quando disponível; Big Buck Bunny como fallback" />
          <MethodItem icon={<Eye size={16} />} label="Comparação" value="Original, controle CRF24, marcado e dois diagnósticos 8×" />
          <MethodItem icon={<ScanSearch size={16} />} label="Verificação" value="Até 24 frames, marcador exato, ledger e conteúdo" />
          <MethodItem icon={<KeyRound size={16} />} label="Chave padrão local" value="local-development-secret" sensitive />
        </div>
        <p className="forensic-studio__method-note">
          A chave é exibida aqui porque este é um laboratório independente. Ela corresponde ao valor padrão local;
          uma instalação que defina <code>CDN_SECRET_KEY</code> usa seu próprio segredo no backend.
        </p>
      </details>

      {!result && !busy && <div className="forensic-studio__empty"><FlaskConical size={20} /><strong>Pronto para um ensaio controlado</strong><span>Escolha o método e execute para gerar as evidências desta sessão.</span></div>}

      {result && <>
        <section className="forensic-studio__result-heading" aria-live="polite">
          <div>
            <p className="eyebrow">RESULTADO DA SESSÃO</p>
            <h3>{result.video_label}</h3>
            <p>{result.algorithm_id} · {result.fingerprint_scheme}</p>
          </div>
          <span className={result.ledger_status === "VALID" ? "forensic-studio__result-ok" : "forensic-studio__result-pending"}>
            <CheckCircle2 size={16} /> {result.investigation.decision}
          </span>
        </section>

        <div className="forensic-studio__status" aria-label="Etapas verificadas">
          <StatusCard icon={<Eye size={16} />} label="Sinal visual" value={detection?.status ?? "INCONCLUSIVE"} detail={detection?.marker ? `Marcador ${detection.marker}` : "Marcador não recuperado"} />
          <StatusCard icon={<Database size={16} />} label="Ledger" value={result.ledger_status ?? "INCONCLUSIVE"} detail="Associação exata do claim" />
          <StatusCard icon={<ShieldCheck size={16} />} label="Conteúdo" value={result.investigation.content_match?.status ?? "INCONCLUSIVE"} detail={`${result.investigation.content_match?.matched_frames ?? 0} frames compatíveis`} />
          <StatusCard icon={<FileKey2 size={16} />} label="Decisão" value={result.investigation.decision} detail="Ação humana continua necessária" />
        </div>

        <section className="forensic-studio__comparison" aria-label="Comparação visual sincronizada">
          <div className="forensic-studio__comparison-heading">
            <div><p className="eyebrow">COMPARAÇÃO SINCRONIZADA</p><h3>{selected.label}</h3><p>{selected.description}</p></div>
            <span>instante {time.toFixed(2)} s</span>
          </div>
          <div className="forensic-studio__variant-tabs" role="tablist" aria-label="Variantes do vídeo">
            {videoKeys.map((key) => <button key={key} type="button" role="tab" aria-selected={selectedVariant === key} className={selectedVariant === key ? "is-active" : ""} onClick={() => setSelectedVariant(key)}>{variants[key].label}</button>)}
          </div>
          <div className="forensic-studio__media-stage">
            {videoKeys.map((key) => <video key={key} ref={(node) => { players.current[key] = node; }} className={selectedVariant === key ? "is-active" : ""} src={result.video_variants[key]} muted playsInline preload="metadata" onLoadedMetadata={(event) => { if (key === "original") setDuration(event.currentTarget.duration); }} />)}
          </div>
          <div className="forensic-studio__playback">
            <button className="button button-secondary" type="button" onClick={togglePlayback}>{playing ? <><Pause size={14} /> Pausar</> : <><CirclePlay size={14} /> Reproduzir</>}</button>
            <button className="button button-secondary" type="button" onClick={restart}><RotateCcw size={14} /> Reiniciar</button>
            <label>Posição
              <input type="range" min="0" max={duration || 4} step="0.01" value={Math.min(time, duration || 4)} onChange={(event) => seek(Number(event.target.value))} />
            </label>
          </div>
          <div className="forensic-studio__detection-map">
            <div><p className="eyebrow">MAPA DE DETECÇÃO</p><h4>Primeiro quadro analisado</h4><p>Verde concorda com o marcador emitido; vermelho diverge; cinza foi mascarado.</p></div>
            <img src={result.video_variants.detection_map} alt="Mapa de correlação dos blocos QIM" />
          </div>
        </section>

        <details className="forensic-studio__details">
          <summary>Métricas, resistência e dados técnicos <ChevronRight size={15} /></summary>
          <div className="forensic-studio__metrics">
            <Metric label="PSNR" value={`${result.quality_vs_control.psnr_db.toFixed(2)} dB`} />
            <Metric label="SSIM janelado" value={result.quality_vs_control.ssim_windowed.toFixed(4)} />
            <Metric label="MS-SSIM (3 escalas)" value={result.quality_vs_control.ms_ssim_3scale_approx.toFixed(4)} />
            <Metric label="Alinhamento" value={result.video_alignment.aligned ? "confirmado" : "não confirmado"} />
            <Metric label="ECC" value={`${detection?.ecc_status ?? "não aplicável"} · ${detection?.ecc_corrected_bits ?? 0} bit`} />
            <Metric label="Frames analisados" value={String(detection?.frames_sampled ?? 0)} />
          </div>
          <div className="forensic-studio__checks" aria-label="Resultados dos testes de resistência">
            {result.robustness_checks.map((check) => <div key={check.filter_id}><strong>{check.filter}</strong><span>{check.bits_correct}/{check.bits_total} bits · {check.survives ? "marcador exato" : "sem recuperação exata"}</span></div>)}
          </div>
          <dl className="forensic-studio__session-data">
            <div><dt>Sessão</dt><dd>{String(result.claim.session_id)}</dd></div>
            <div><dt>Marcador emitido</dt><dd>{result.issued_marker}</dd></div>
            <div><dt>Diagnóstico</dt><dd>{result.diagnostics.residual}</dd></div>
          </dl>
        </details>
      </>}
    </section>
  );
}

function GuideStep({ number, title, text }: { number: string; title: string; text: string }) {
  return <div><span>{number}</span><strong>{title}</strong><p>{text}</p></div>;
}

function MethodItem({ icon, label, value, sensitive = false }: { icon: ReactNode; label: string; value: string; sensitive?: boolean }) {
  return <div className={sensitive ? "is-sensitive" : ""}><span>{icon}</span><small>{label}</small>{sensitive ? <code>{value}</code> : <strong>{value}</strong>}</div>;
}

function StatusCard({ icon, label, value, detail }: { icon: ReactNode; label: string; value: string; detail: string }) {
  return <article><span>{icon}</span><small>{label}</small><strong>{value}</strong><p>{detail}</p></article>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}
