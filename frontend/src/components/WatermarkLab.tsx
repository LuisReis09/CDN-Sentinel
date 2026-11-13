import {
  ArrowRight,
  Binary,
  Check,
  Code2,
  Database,
  Eye,
  FileKey2,
  Fingerprint,
  KeyRound,
  LockKeyhole,
  Pause,
  Play,
  RotateCcw,
  ScanSearch,
  ShieldCheck,
  UnlockKeyhole,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api";
import { NoiseVideoPreview } from "./NoiseVideoPreview";
import type { WatermarkDemo } from "../types";

export function WatermarkLab({
  onError,
}: {
  onError: (message: string) => void;
}) {
  const [demo, setDemo] = useState<WatermarkDemo | null>(null);
  const videoVariants = demo?.video_variants;
  const [busy, setBusy] = useState(false);
  const videoRefs = useRef<Record<string, HTMLVideoElement | null>>({});
  const [playbackTime, setPlaybackTime] = useState(0);
  const [duration, setDuration] = useState(1);
  const [syncWarning, setSyncWarning] = useState("");
  const durations = useRef<Record<string, number>>({});
  const [zoom, setZoom] = useState(false);
  const lastClockUpdate = useRef(0);

  useEffect(() => {
    let frame = 0;
    const synchronize = () => {
      const master = videoRefs.current.original;
      if (master && !master.paused) {
        let drift = 0;
        for (const key of ["watermarked", "difference"]) {
          const follower = videoRefs.current[key];
          if (!follower || follower.readyState < 2) continue;
          const delta = Math.abs(follower.currentTime - master.currentTime);
          drift = Math.max(drift, delta);
          if (delta > 0.07) follower.currentTime = master.currentTime;
          if (follower.paused) void follower.play().catch(() => undefined);
        }
        if (performance.now() - lastClockUpdate.current > 200) {
          setPlaybackTime(master.currentTime);
          lastClockUpdate.current = performance.now();
        }
        setSyncWarning(drift > 0.25 ? `Diferença temporal corrigida: ${drift.toFixed(2)} s` : "");
      }
      frame = requestAnimationFrame(synchronize);
    };
    frame = requestAnimationFrame(synchronize);
    return () => cancelAnimationFrame(frame);
  }, [videoVariants?.original, videoVariants?.watermarked, videoVariants?.difference]);

  function metadata(variant: string, value: number) {
    if (!Number.isFinite(value)) return;
    durations.current[variant] = value;
    if (variant === "original") setDuration(value);
    const known = Object.values(durations.current);
    if (known.length >= 2 && Math.max(...known) - Math.min(...known) > 0.1) {
      setSyncWarning("As variantes têm durações diferentes; a comparação pode perder correspondência temporal.");
    }
  }

  function eachVideo(callback: (video: HTMLVideoElement) => void) {
    Object.values(videoRefs.current).forEach((video) => {
      if (video) callback(video);
    });
  }

  function playAll() {
    const master = videoRefs.current.original;
    const target = master?.currentTime ?? playbackTime;
    eachVideo((video) => {
      video.currentTime = target;
      void video.play().catch(() => undefined);
    });
  }

  function pauseAll() {
    eachVideo((video) => video.pause());
  }

  function restartAll() {
    eachVideo((video) => {
      video.currentTime = 0;
    });
    setPlaybackTime(0);
  }

  function seekAll(value: number) {
    eachVideo((video) => {
      if (Number.isFinite(video.duration)) video.currentTime = value;
    });
    setPlaybackTime(value);
  }

  function stepFrame(direction: number) {
    pauseAll();
    const fps = demo?.video_metadata?.fps && Number(demo.video_metadata.fps) > 0 ? Number(demo.video_metadata.fps) : 30;
    seekAll(Math.max(0, Math.min(duration, (videoRefs.current.original?.currentTime ?? playbackTime) + direction / fps)));
  }

  async function simulate() {
    setBusy(true);
    pauseAll();
    durations.current = {};
    setSyncWarning("");
    try {
      setDemo(
        await api.watermarkDemo({
          chunk: demo ? demo.chunk_number + 1 : 0,
          exclude_video_id: demo?.video_id,
        }),
      );
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Falha no laboratório");
    } finally {
      setBusy(false);
    }
  }

  const process = demo?.cryptographic_process;
  const claim = demo?.claim_before_encoding ?? {};

  return (
    <section className="panel watermark-lab">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">LEGACY CDNWM3 / ADAPTIVE SPREAD</p>
          <h2>Estúdio de watermark</h2>
        </div>
        <Fingerprint size={20} className="accent" />
      </div>
      <p className="panel-subtitle">
        Siga a geração do claim e a marca visual em frames reais. O claim fica
        no registro; o MP4 carrega somente o sinal visual. As transformações
        medem se o marcador de 48 bits foi recuperado exatamente.
      </p>
      <div className="lab-toolbar">
        <span className="standalone-badge">
          <KeyRound size={13} /> AES-256-GCM + HMAC · chave protegida
        </span>
        <button
          className="button button-primary"
          disabled={busy}
          onClick={() => void simulate()}
        >
          <Play size={15} /> {busy ? "Processando…" : "Executar demonstração"}
        </button>
      </div>
      {videoVariants ? (
        <>
          <div className="watermark-sync-toolbar" aria-label="Controles sincronizados dos vídeos">
            <button className="button button-secondary" type="button" onClick={playAll}>
              <Play size={14} /> Reproduzir os três
            </button>
            <button className="button button-secondary" type="button" onClick={pauseAll}>
              <Pause size={14} /> Pausar
            </button>
            <button className="button button-secondary" type="button" onClick={restartAll}>
              <RotateCcw size={14} /> Reiniciar
            </button>
            <button className="button button-secondary" type="button" onClick={() => stepFrame(-1)} aria-label="Frame anterior">−1 frame</button>
            <button className="button button-secondary" type="button" onClick={() => stepFrame(1)} aria-label="Próximo frame">+1 frame</button>
            <button className="button button-secondary" type="button" onClick={() => setZoom((value) => !value)}>{zoom ? "Zoom 1×" : "Zoom 2×"}</button>
            <label>
              <span>posição sincronizada {playbackTime.toFixed(1)}s</span>
              <input
                type="range"
                min={0}
                max={Math.max(1, duration)}
                step={0.1}
                value={playbackTime}
                onChange={(event) => seekAll(Number(event.target.value))}
              />
            </label>
          </div>
          {syncWarning && <p role="alert" className="panel-subtitle">{syncWarning}</p>}
          <div className={`noise-preview-grid noise-preview-grid--triple ${zoom ? "watermark-preview-zoom" : ""}`}>
          <NoiseVideoPreview
            videoUrl={videoVariants.original}
            variant="original"
            videoRef={(node) => {
              videoRefs.current.original = node;
            }}
            onTimeUpdate={setPlaybackTime}
            onLoadedMetadata={(value) => metadata("original", value)}
            onPlay={playAll}
            onPause={pauseAll}
            label="1 · Vídeo original"
            description="MP4 local versionado; mesmo vídeo de referência"
          />
          <NoiseVideoPreview
            videoUrl={videoVariants.watermarked}
            variant="watermarked"
            videoRef={(node) => {
              videoRefs.current.watermarked = node;
            }}
            onLoadedMetadata={(value) => metadata("watermarked", value)}
            label="2 · Sinal sutil"
            description="vídeo entregue ao cliente; sinal de luminância imperceptível"
          />
          <NoiseVideoPreview
            videoUrl={videoVariants.difference}
            variant="difference"
            videoRef={(node) => {
              videoRefs.current.difference = node;
            }}
            onLoadedMetadata={(value) => metadata("difference", value)}
            label="3 · Sinal destacado"
            description="diferença amplificada para auditoria; não é o vídeo entregue ao cliente"
          />
          </div>
        </>
      ) : (
        <div className="watermark-empty-state">
          <Play size={20} />
          <strong>Nenhuma demonstração executada</strong>
          <span>Os vídeos aparecerão aqui depois que você iniciar uma demonstração.</span>
        </div>
      )}
      {demo && (
        <div className="demo-result">
          <Check size={16} />
          <strong>
            {demo.verification?.forensic_status === "VALID"
              ? "Marca legada recuperada; sem autenticacao forense CDNWM4"
              : "Watermark visual pendente ou inconclusiva"}
          </strong>
          <span>
            {demo.video_label} · ensaio {demo.chunk_number} · SHA-256{" "}
            {demo.payload_sha256.slice(0, 18)}…
          </span>
          <small>
            Token de transporte: {demo.verification?.transport_token ?? "—"} ·{" "}
            inserção visual: {demo.verification?.visual_embedded ? "confirmada" : "pendente"} ·{" "}
            detecção: {demo.verification?.visual_detection ?? "—"}
          </small>
        </div>
      )}

      <div className="crypto-overview">
        <InfoCard
          icon={<Database size={17} />}
          title="1. O que foi identificado"
          tone="cyan"
        >
          <p>
            Este claim didático aparece apenas na tela do laboratório. Na entrega
            normal, o vídeo não contém o JSON ou o token cifrado.
          </p>
          <CodeBlock
            value={
              demo ? JSON.stringify(claim, null, 2) : "execute para ver o claim"
            }
          />
        </InfoCard>
        <InfoCard
          icon={<FileKey2 size={17} />}
          title="2. Como foi cifrado e assinado"
          tone="orange"
        >
          <p>
            O claim é serializado em JSON compacto, cifrado com AES-256-GCM e
            o envelope recebe uma assinatura HMAC-SHA256.
          </p>
          <code>AESGCM(key, claim_json, AAD) + HMAC(ciphertext)</code>
          <small>
            {demo
              ? `Fingerprint da chave: ${demo.key_fingerprint} · valor nunca enviado ao navegador`
              : "A chave real nunca é exibida."}
          </small>
        </InfoCard>
        <InfoCard
          icon={<ShieldCheck size={17} />}
          title="3. Como o monitor valida"
          tone="green"
        >
          <p>
            Valida o claim no registro com HMAC e GCM e, separadamente, recupera o
            marcador visual do vídeo. Só uma associação exata no registro atribui
            cliente, servidor e horário.
          </p>
          <code>compare_digest + AESGCM.decrypt</code>
          <small>
            AES-GCM fornece confidencialidade; HMAC acrescenta a assinatura do envelope.
          </small>
        </InfoCard>
      </div>

      {demo && (
        <>
          <div className="lab-flow">
            <Step
              icon={<LockKeyhole size={17} />}
              title="1. Emitir"
              value={`${String(claim.client_id)} · ${String(claim.server_id)}`}
            />
            <ArrowRight className="flow-arrow" size={17} />
            <Step
              icon={<Code2 size={17} />}
              title="2. Cifrar + autenticar"
              value={`${demo.encoded_claim.length} chars Base64URL`}
              mono
            />
            <ArrowRight className="flow-arrow" size={17} />
            <Step
              icon={<Eye size={17} />}
              title="3. Inserir visualmente no vídeo"
              value={`${demo.noise_hex.length * 4} bits visuais no MP4`}
            />
            <ArrowRight className="flow-arrow" size={17} />
            <Step
              icon={<UnlockKeyhole size={17} />}
              title="4. Descriptografar + validar"
              value={demo.verification?.forensic_status === "VALID" ? "claim e marcador exatos" : "evidência inconclusiva"}
              valid
            />
          </div>
          <div className="token-box">
            <span>claim cifrado (Base64URL)</span>
            <code>{demo.encoded_claim}</code>
            <span>assinatura HMAC</span>
            <code>{demo.signature}</code>
            <span>transporte físico</span>
            <code>{demo.payload_prefix}</code>
            <span>chave usada</span>
            <code>secreta · fingerprint SHA-256 {demo.key_fingerprint}</code>
          </div>
          <div className="payload-compare">
            <div>
              <span>payload original (Base64, início)</span>
              <code>{demo.original_payload_base64.slice(0, 120)}…</code>
            </div>
            <div>
              <span>payload após watermark (Base64, início)</span>
              <code>{demo.watermarked_payload_base64.slice(0, 120)}…</code>
            </div>
          </div>
          <div className="crypto-details crypto-decryption">
            <div className="crypto-details__heading">
              <UnlockKeyhole size={16} />
              <strong>Descriptografia passo a passo</strong>
              <span>{demo.decryption_process.algorithm}</span>
            </div>
            <div className="decryption-steps">
              {demo.decryption_process.steps.map((step, index) => (
                <div key={step}>
                  <b>{index + 1}</b>
                  <span>{step}</span>
                </div>
              ))}
            </div>
            <div className="crypto-detail-grid">
              <Detail label="AAD" value={demo.decryption_process.aad} />
              <Detail label="Nonce" value={demo.decryption_process.nonce_base64url} />
              <Detail label="Tag de autenticação" value={demo.decryption_process.authentication_tag_base64url} />
              <Detail label="Ciphertext" value={demo.decryption_process.ciphertext_base64url} />
            </div>
            <span className="crypto-output-label">Payload final após descriptografar</span>
            <CodeBlock value={JSON.stringify(demo.decryption_process.decrypted_payload, null, 2)} />
          </div>
          <div className="crypto-details">
            <div className="crypto-details__heading">
              <Binary size={16} />
              <strong>Telemetria criptográfica desta execução</strong>
              <span>{demo.video_source}</span>
            </div>
            <div className="crypto-detail-grid">
              <Detail label="Algoritmo" value={process?.algorithm} />
              <Detail label="Parâmetros da cifra" value={process?.encryption_parameters} />
              <Detail label="Derivação da chave" value={process?.key_derivation} />
              <Detail
                label="Payload assinado"
                value={process?.signed_payload}
              />
              <Detail label="Formato" value={process?.token_format} />
              <Detail label="Inserção" value={process?.embedding} />
              <Detail label="Transporte" value={process?.transport_encoding} />
              <Detail label="Verificação" value={process?.verification} />
              <Detail label="Canal robusto" value={process?.robust_channel} />
              <Detail label="Parâmetros visuais" value={process?.visual_parameters} />
              <Detail label="Limitação" value={process?.robustness_limit} />
              <Detail
                label="Fonte dos frames"
                value={`${demo.video_metadata.resolution} · ${demo.video_metadata.size_bytes} bytes`}
              />
            </div>
          </div>
          <RobustnessTable checks={demo.robustness_checks} />
        </>
      )}
    </section>
  );
}

function RobustnessTable({
  checks,
}: {
  checks: WatermarkDemo["robustness_checks"];
}) {
  return (
    <div className="robustness-panel">
      <div className="crypto-details__heading">
        <ScanSearch size={16} />
        <strong>Teste de resistência do sinal</strong>
        <span>amostras MP4 H.264 + detector visual</span>
      </div>
      <p>
        HMAC/AES continua sendo a prova criptográfica do payload. A métrica
        abaixo mostra duas grandezas distintas: consistência do detector e bits
        corretos contra o marcador conhecido neste experimento. A recuperação
        só é exata quando todos os 48 bits coincidem; autenticação exige ainda
        consulta ao registro. A diferença amplificada é apenas diagnóstico.
      </p>
      <div className="robustness-table">
        {checks.map((check) => (
          <div className="robustness-row" key={check.filter_id}>
            <span>
              {check.filter}
              {check.intensity && <small>{check.intensity}</small>}
            </span>
            <code>
              consistência {(check.confidence * 100).toFixed(1)}% ·{" "}
              {check.bits_correct ?? "—"}/{check.bits_total ?? "—"} bits conhecidos
            </code>
            <strong className={check.survives ? "robust-ok" : "robust-fail"}>
              {check.survives ? "marcador exato" : "não recuperado exatamente"}
            </strong>
            {check.sample_generated && <em>amostra real</em>}
          </div>
        ))}
      </div>
    </div>
  );
}
function CodeBlock({ value }: { value: string }) {
  return (
    <pre className="code-block">
      <code>{value}</code>
    </pre>
  );
}
function InfoCard({
  icon,
  title,
  tone,
  children,
}: {
  icon: ReactNode;
  title: string;
  tone: "cyan" | "orange" | "green";
  children: ReactNode;
}) {
  return (
    <article className={`crypto-card crypto-card--${tone}`}>
      <div className="crypto-card__title">
        <span>{icon}</span>
        <strong>{title}</strong>
      </div>
      {children}
    </article>
  );
}
function Detail({ label, value }: { label: string; value?: string }) {
  return (
    <div>
      <span>{label}</span>
      <code>{value ?? "—"}</code>
    </div>
  );
}
function Step({
  icon,
  title,
  value,
  mono = false,
  valid = false,
}: {
  icon: ReactNode;
  title: string;
  value: string;
  mono?: boolean;
  valid?: boolean;
}) {
  return (
    <div className={`lab-step ${valid ? "lab-step-valid" : ""}`}>
      <div className="lab-step__icon">{valid ? <Check size={17} /> : icon}</div>
      <span>{title}</span>
      <strong className={mono ? "mono" : ""}>{value}</strong>
    </div>
  );
}
