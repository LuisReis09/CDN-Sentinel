import { ArrowRight, Binary, Check, Code2, Database, Eye, FileKey2, Fingerprint, KeyRound, LockKeyhole, Play, ScanSearch, ShieldCheck, UnlockKeyhole } from "lucide-react";
import { useState, type ReactNode } from "react";
import { api } from "../api";
import { NoiseVideoPreview } from "./NoiseVideoPreview";
import type { WatermarkDemo } from "../types";

export function WatermarkLab({ onError }: { onError: (message: string) => void }) {
  const [demo, setDemo] = useState<WatermarkDemo | null>(null);
  const [busy, setBusy] = useState(false);

  async function simulate() {
    setBusy(true);
    try {
      setDemo(await api.watermarkDemo({ chunk: demo ? demo.chunk_number + 1 : 0, exclude_video_id: demo?.video_id }));
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Falha no laboratório independente");
    } finally {
      setBusy(false);
    }
  }

  const videoUrl = api.watermarkVideoUrl(demo?.video_id);
  const process = demo?.cryptographic_process;

  return (
    <section className="panel watermark-lab">
      <div className="panel-heading"><div><p className="eyebrow">FORENSIC WATERMARK LAB / STANDALONE</p><h2>Estúdio de watermark</h2></div><Fingerprint size={20} className="accent" /></div>
      <p className="panel-subtitle">Cada geração escolhe outro vídeo real do dataset do backend. Compare o conteúdo limpo, a assinatura quase invisível e a mesma assinatura destacada para inspeção.</p>
      <div className="lab-toolbar"><span className="standalone-badge"><KeyRound size={13} /> HMAC-SHA256 independente</span><button className="button button-primary" disabled={busy} onClick={() => void simulate()}><Play size={15} /> {busy ? "Processando…" : "Gerar outro vídeo"}</button></div>
      <div className="noise-preview-grid noise-preview-grid--triple">
        <NoiseVideoPreview videoUrl={videoUrl} noiseHex={demo?.noise_hex ?? "c0ffee42"} strength={0} showNoise={false} label="1 · Vídeo original" />
        <NoiseVideoPreview videoUrl={videoUrl} noiseHex={demo?.noise_hex ?? "c0ffee42"} strength={0.8} label="2 · Vídeo + ruído sutil" />
        <NoiseVideoPreview videoUrl={videoUrl} noiseHex={demo?.noise_hex ?? "c0ffee42"} strength={2.4} amplified label="3 · Ruído destacado" />
      </div>
      {demo && <div className="demo-result"><Check size={16} /><strong>{demo.round_trip_verified ? "Extração e validação confirmadas" : "Validação pendente"}</strong><span>{demo.video_label} · {demo.content_type} · chunk {demo.chunk_number} · SHA-256 {demo.payload_sha256.slice(0, 18)}…</span></div>}

      <div className="crypto-overview">
        <InfoCard icon={<Database size={17} />} title="O que foi colocado no vídeo" tone="cyan"><p>Um prefixo forense é anexado aos bytes do chunk antes do conteúdo original:</p><code>CDNWM1.&lt;claim-base64url&gt;.&lt;HMAC&gt;\n + chunk</code><small>Claim: client_id, server_id, issued_at e chunk_id.</small></InfoCard>
        <InfoCard icon={<FileKey2 size={17} />} title="Como foi criptografado" tone="orange"><p>O claim é serializado e assinado com HMAC-SHA256 usando a secret_key da CDN. A chave nunca vai para o navegador.</p><code>signature = HMAC-SHA256(secret_key, claim)</code><small>HMAC garante autenticidade e integridade; não é cifragem reversível.</small></InfoCard>
        <InfoCard icon={<ShieldCheck size={17} />} title="Como é descriptografado" tone="green"><p>O monitor decodifica o Base64, separa o prefixo, lê o claim e recalcula o HMAC.</p><code>compare_digest(received, recalculated)</code><small>Se coincidir, o vazamento é atribuído ao cliente e ao momento exatos.</small></InfoCard>
      </div>

      {demo && <>
        <div className="lab-flow"><Step icon={<LockKeyhole size={17} />} title="1. Emitir" value={`demo-viewer · ${demo.claim.server_id}`} /><ArrowRight className="flow-arrow" size={17} /><Step icon={<Code2 size={17} />} title="2. Encapsular" value={`${demo.watermarked_payload_base64.length} bytes Base64`} mono /><ArrowRight className="flow-arrow" size={17} /><Step icon={<Eye size={17} />} title="3. Extrair" value={`${String(demo.claim.client_id)} · ${String(demo.claim.issued_at)}`} /><ArrowRight className="flow-arrow" size={17} /><Step icon={<UnlockKeyhole size={17} />} title="4. Validar" value="HMAC válido · round trip OK" valid /></div>
        <div className="token-box"><span>assinatura HMAC</span><code>{demo.noise_hex}</code><span>token extraído</span><code>{demo.extracted_token}</code></div>
        <div className="crypto-details"><div className="crypto-details__heading"><Binary size={16} /><strong>Telemetria criptográfica desta execução</strong><span>{demo.video_source}</span></div><div className="crypto-detail-grid"><Detail label="Algoritmo" value={process?.algorithm} /><Detail label="Payload assinado" value={process?.signed_payload} /><Detail label="Formato" value={process?.token_format} /><Detail label="Inserção" value={process?.embedding} /><Detail label="Transporte" value={process?.transport_encoding} /><Detail label="Verificação" value={process?.verification} /></div></div>
      </>}
    </section>
  );
}

function InfoCard({ icon, title, tone, children }: { icon: ReactNode; title: string; tone: "cyan" | "orange" | "green"; children: ReactNode }) {
  return <article className={`crypto-card crypto-card--${tone}`}><div className="crypto-card__title"><span>{icon}</span><strong>{title}</strong></div>{children}</article>;
}

function Detail({ label, value }: { label: string; value?: string }) {
  return <div><span>{label}</span><code>{value ?? "—"}</code></div>;
}

function Step({ icon, title, value, mono = false, valid = false }: { icon: ReactNode; title: string; value: string; mono?: boolean; valid?: boolean }) {
  return <div className={`lab-step ${valid ? "lab-step-valid" : ""}`}><div className="lab-step__icon">{valid ? <Check size={17} /> : icon}</div><span>{title}</span><strong className={mono ? "mono" : ""}>{value}</strong></div>;
}
