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
  Play,
  ScanSearch,
  ShieldCheck,
  UnlockKeyhole,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { api } from "../api";
import { NoiseVideoPreview } from "./NoiseVideoPreview";
import type { WatermarkDemo } from "../types";

export function WatermarkLab({
  onError,
}: {
  onError: (message: string) => void;
}) {
  const [demo, setDemo] = useState<WatermarkDemo | null>(null);
  const [busy, setBusy] = useState(false);

  async function simulate() {
    setBusy(true);
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

  const videoVariants = demo?.video_variants ?? {
    original: api.watermarkVideoUrl("bigbuckbunny"),
    watermarked: api.watermarkVideoUrl("bigbuckbunny"),
    difference: api.watermarkVideoUrl("bigbuckbunny"),
  };
  const process = demo?.cryptographic_process;
  const claim = demo?.claim_before_encoding ?? {};

  return (
    <section className="panel watermark-lab">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">FORENSIC WATERMARK LAB / STANDALONE</p>
          <h2>Estúdio de watermark</h2>
        </div>
        <Fingerprint size={20} className="accent" />
      </div>
      <p className="panel-subtitle">
        Siga uma execução completa. A prova criptográfica assina a origem do
        chunk; o canal robusto experimental testa se um sinal espalhado
        continuaria detectável após filtros visuais.
      </p>
      <div className="lab-toolbar">
        <span className="standalone-badge">
          <KeyRound size={13} /> HMAC-SHA256 · chave protegida
        </span>
        <button
          className="button button-primary"
          disabled={busy}
          onClick={() => void simulate()}
        >
          <Play size={15} /> {busy ? "Processando…" : "Executar demonstração"}
        </button>
      </div>
      <div className="noise-preview-grid noise-preview-grid--triple">
        <NoiseVideoPreview
          videoUrl={videoVariants.original}
          variant="original"
          label="1 · Vídeo original"
          description="MP4 local versionado; mesmo vídeo de referência"
        />
        <NoiseVideoPreview
          videoUrl={videoVariants.watermarked}
          variant="watermarked"
          label="2 · Sinal sutil"
          description="alteração real de luminância, aplicada aos frames"
        />
        <NoiseVideoPreview
          videoUrl={videoVariants.difference}
          variant="difference"
          label="3 · Sinal destacado"
          description="diferença real entre original e vídeo transformado"
        />
      </div>
      {demo && (
        <div className="demo-result">
          <Check size={16} />
          <strong>
            {demo.round_trip_verified
              ? "Extração e validação confirmadas"
              : "Validação pendente"}
          </strong>
          <span>
            {demo.video_label} · chunk {demo.chunk_number} · SHA-256{" "}
            {demo.payload_sha256.slice(0, 18)}…
          </span>
        </div>
      )}

      <div className="crypto-overview">
        <InfoCard
          icon={<Database size={17} />}
          title="1. O que foi identificado"
          tone="cyan"
        >
          <p>
            O claim didático carrega exatamente estes campos. Ele não é segredo:
            a integridade vem da assinatura. O vídeo acima é uma trilha visual separada.
          </p>
          <CodeBlock
            value={
              demo ? JSON.stringify(claim, null, 2) : "execute para ver o claim"
            }
          />
        </InfoCard>
        <InfoCard
          icon={<FileKey2 size={17} />}
          title="2. Como foi assinado"
          tone="orange"
        >
          <p>
            O claim é serializado em JSON compacto, codificado em Base64URL e
            assinado com HMAC-SHA256.
          </p>
          <code>HMAC(secret_key, claim_base64url)</code>
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
            Extrai o prefixo, recalcula o HMAC em tempo constante e só então
            atribui cliente, servidor e horário.
          </p>
          <code>compare_digest(received, recalculated)</code>
          <small>
            HMAC não é criptografia reversível; é autenticidade + integridade.
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
              title="2. Codificar + assinar"
              value={`${demo.encoded_claim.length} chars Base64URL`}
              mono
            />
            <ArrowRight className="flow-arrow" size={17} />
            <Step
              icon={<Eye size={17} />}
              title="3. Inserir no chunk"
              value={`${demo.watermarked_payload_base64.length} chars Base64`}
            />
            <ArrowRight className="flow-arrow" size={17} />
            <Step
              icon={<UnlockKeyhole size={17} />}
              title="4. Extrair + validar"
              value="HMAC válido · round trip OK"
              valid
            />
          </div>
          <div className="token-box">
            <span>claim codificado</span>
            <code>{demo.encoded_claim}</code>
            <span>assinatura HMAC</span>
            <code>{demo.signature}</code>
            <span>prefixo físico</span>
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
          <div className="crypto-details">
            <div className="crypto-details__heading">
              <Binary size={16} />
              <strong>Telemetria criptográfica desta execução</strong>
              <span>{demo.video_source}</span>
            </div>
            <div className="crypto-detail-grid">
              <Detail label="Algoritmo" value={process?.algorithm} />
              <Detail
                label="Payload assinado"
                value={process?.signed_payload}
              />
              <Detail label="Formato" value={process?.token_format} />
              <Detail label="Inserção" value={process?.embedding} />
              <Detail label="Transporte" value={process?.transport_encoding} />
              <Detail label="Verificação" value={process?.verification} />
              <Detail label="Canal robusto" value={process?.robust_channel} />
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
        <span>protótipo spread-spectrum/QIM</span>
      </div>
      <p>
        O HMAC continua sendo a prova criptográfica. A confiança não vem do
        HMAC: é a razão entre bits do marcador recuperados corretamente e bits
        totais, calculada comparando cada bloco 8×8 transformado com a linha de
        base. O limite didático de aprovação é 90%.
      </p>
      <div className="robustness-table">
        {checks.map((check) => (
          <div className="robustness-row" key={check.filter_id}>
            <span>{check.filter}</span>
            <code>
              {Math.round(check.confidence * 100)}% ·{" "}
              {check.bits_correct ?? "—"}/{check.bits_total ?? "—"} bits
            </code>
            <strong className={check.survives ? "robust-ok" : "robust-fail"}>
              {check.survives ? "detectável" : "perdeu sinal"}
            </strong>
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
