import {
  Ban,
  Eye,
  ExternalLink,
  Fingerprint,
  Globe2,
  Radar,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import type { ForensicInvestigation, LeakRecord, Overview, WatermarkDetection } from "../types";

export function SecurityPage({
  overview,
  onError,
}: {
  overview: Overview;
  onRefresh: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const monitor = overview.monitor;
  const monitorRows = Object.values(monitor.per_server ?? {});
  const platforms = new Set(overview.leaks.map((leak) => leak.platform)).size;
  const processedLeaks = overview.leaks.filter((leak) => leak.processed).length;
  const [detection, setDetection] = useState<WatermarkDetection | null>(null);
  const [detectionBusy, setDetectionBusy] = useState(false);
  const [investigation, setInvestigation] = useState<ForensicInvestigation | null>(null);
  const [reviewStatus, setReviewStatus] = useState("");
  const [investigationBusy, setInvestigationBusy] = useState(false);

  async function investigate(file: File | undefined) {
    if (!file) return;
    setInvestigationBusy(true);
    setInvestigation(null);
    setReviewStatus("");
    try {
      setInvestigation(await api.investigateVideo(file));
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Falha na investigação");
    } finally {
      setInvestigationBusy(false);
    }
  }

  async function review(decision: "ACCEPT" | "REJECT" | "INCONCLUSIVE") {
    if (!investigation) return;
    try {
      const result = await api.reviewInvestigation(investigation.investigation_id, decision);
      setReviewStatus(`Revisão registrada: ${String(result.decision)}. Nenhuma blacklist foi alterada.`);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Falha ao registrar revisão");
    }
  }

  async function detect(file: File | undefined) {
    if (!file) return;
    setDetectionBusy(true);
    try {
      setDetection(await api.detectWatermark(file));
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Falha ao detectar watermark");
    } finally {
      setDetectionBusy(false);
    }
  }

  return (
    <main className="page-content">
      <header className="page-header">
        <div>
          <p className="eyebrow">THREAT INTELLIGENCE / FORENSICS</p>
          <h1>Security observatory</h1>
          <p className="page-lead">
            Cada servidor possui seu próprio monitor. Um vazamento nasce em uma
            CDN, aparece numa plataforma externa simulada e vira uma investigação
            pendente de revisão. A conta associada não é automaticamente bloqueada.
          </p>
        </div>
        <div className="header-signal">
          <span
            className={`status-dot ${monitor.automatic ? "status-live" : "status-offline"}`}
          />
          {monitor.automatic
            ? `${monitorRows.length} monitores online · tick ${monitor.interval_seconds}s`
            : "monitores aguardando"}
        </div>
      </header>
      <section className="security-grid">
        <div className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">BLACKLIST GOVERNANCE</p>
              <h2>Identidades bloqueadas</h2>
            </div>
            <Ban size={18} className="danger" />
          </div>
          <div className="blacklist-list">
            {overview.blacklist.map((entry) => (
              <div className="blacklist-row" key={entry.client_id}>
                <span className="blacklist-avatar">
                  <Fingerprint size={16} />
                </span>
                <div>
                  <strong>{entry.client_id}</strong>
                  <small>
                    detectado por {entry.server_id} · watermark emitida por{" "}
                    {entry.watermark_server_id ?? "origem desconhecida"}
                  </small>
                </div>
                <span className="propagation">
                  {entry.propagated_to.length} nós sincronizados
                </span>
              </div>
            ))}
            {overview.blacklist.length === 0 && (
              <div className="empty-state">
                <Eye size={24} />
                <span>Nenhuma identidade bloqueada ainda.</span>
              </div>
            )}
          </div>
        </div>
        <div className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">MONITOR MESH</p>
              <h2>Um monitor por servidor</h2>
            </div>
            <Radar size={18} className="accent" />
          </div>
          <div className="server-monitor-list">
            {monitorRows.map((item) => (
              <div className="server-monitor-row" key={item.server_id}>
                <span
                  className={`status-dot ${item.automatic ? "status-live" : "status-offline"}`}
                />
                <div>
                  <strong>{item.server_id}</strong>
                  <small>
                    {item.last_scan_at
                      ? `último ciclo ${new Date(item.last_scan_at * 1000).toLocaleTimeString("pt-BR")}`
                      : "ainda sem ciclo"}{" "}
                    · intervalo {item.interval_seconds}s
                  </small>
                </div>
                <span>
                  <b>{item.last_detected}</b> detectados ·{" "}
                  <b>{item.pending_leaks}</b> pendentes
                </span>
              </div>
            ))}
            {monitorRows.length === 0 && (
              <div className="empty-state">
                <Radar size={22} />
                <span>Inicialize servidores para criar seus monitores.</span>
              </div>
            )}
          </div>
          <div className="security-monitor-summary">
            <div>
              <strong>{monitor.pending_leaks}</strong>
              <span>evidências aguardando</span>
            </div>
            <div>
              <strong>{monitor.last_detected}</strong>
              <span>detectadas no último ciclo</span>
            </div>
            <div>
              <strong>{monitor.last_rejected}</strong>
              <span>rejeitadas por prova inválida</span>
            </div>
          </div>
          <div className="leak-list">
            <div className="leak-row">
              <span className="scan-pulse" />
              <div>
                <strong>Varredura distribuída e automática</strong>
                <small>
                  cada monitor observa vazamentos emitidos pelo seu servidor e
                  registra evidência para revisão humana
                </small>
              </div>
            </div>
            <div className="leak-row">
              <ShieldCheck size={15} className="accent" />
              <div>
                <strong>Fluxo de acordo</strong>
                <small>
                  detectar → confirmar marcador → verificar claim →
                  conferir conteúdo → encaminhar para revisão
                </small>
              </div>
            </div>
          </div>
        </div>
      </section>
      <section className="panel watermark-detection-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">AUTHORIZED FORENSIC INGESTION</p>
            <h2>Investigar vídeo externo</h2>
            <p className="panel-subtitle">O arquivo é analisado por seus bytes, sem informar o cliente esperado. O resultado registra hash, correspondência de conteúdo, sessão e estado de revisão.</p>
          </div>
          <Fingerprint size={18} className="accent" />
        </div>
        <label className="watermark-file-input">
          <span>{investigationBusy ? "Analisando vídeo…" : "Selecionar vídeo suspeito"}</span>
          <input type="file" accept="video/*,.mp4,.mkv,.webm,.mov" disabled={investigationBusy} onChange={(event) => void investigate(event.target.files?.[0])} />
        </label>
        {investigation && (
          <div className="watermark-detection-result">
            <strong>{investigation.decision}</strong>
            <span>Estado forense: {investigation.forensic_status} · associação: {investigation.attribution}</span>
            <code>SHA-256: {investigation.media_sha256}</code>
            <span>Conteúdo: {investigation.content_id ?? "não confirmado"} · sessão: {investigation.session_id ?? "não atribuída"}</span>
            <span>Correspondência do conteúdo: {investigation.content_match?.status ?? "não avaliada"}</span>
            {investigation.decision === "PENDING_REVIEW" && !reviewStatus && (
              <div className="watermark-sync-toolbar">
                <button className="button button-secondary" type="button" onClick={() => void review("ACCEPT")}>Aceitar evidência</button>
                <button className="button button-secondary" type="button" onClick={() => void review("REJECT")}>Rejeitar</button>
                <button className="button button-secondary" type="button" onClick={() => void review("INCONCLUSIVE")}>Inconclusiva</button>
              </div>
            )}
            {reviewStatus && <span>{reviewStatus}</span>}
            <small>Revisão de evidência não determina autoria pessoal e não aplica sanção automaticamente.</small>
          </div>
        )}
      </section>
      <section className="panel watermark-detection-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">INDEPENDENT WATERMARK DETECTOR</p>
            <h2>Investigar imagem ou vídeo suspeito</h2>
            <p className="panel-subtitle">
              A análise não precisa do original nem do token esperado. A marca visual é recuperada primeiro; a autenticação só é confirmada contra um claim registrado na CDN.
            </p>
          </div>
          <Fingerprint size={18} className="accent" />
        </div>
        <label className="watermark-file-input">
          <span>{detectionBusy ? "Analisando mídia…" : "Selecionar imagem ou vídeo"}</span>
          <input type="file" accept="image/*,video/*" disabled={detectionBusy} onChange={(event) => void detect(event.target.files?.[0])} />
        </label>
        {detection && (
          <div className={`watermark-detection-result watermark-detection-result--${detection.status.toLowerCase()}`}>
            <strong>{detection.status}</strong>
            <span>{detection.reason ?? detection.error ?? detection.verification ?? "Nenhuma evidência adicional."}</span>
            {detection.marker && <code>marker: {detection.marker}</code>}
            {detection.claim && <code>{JSON.stringify(detection.claim)}</code>}
            {typeof detection.confidence === "number" && <small>confiança do sinal: {(detection.confidence * 100).toFixed(1)}%</small>}
          </div>
        )}
      </section>
      <ExternalLeakPanel
        leaks={overview.leaks}
        platforms={platforms}
        processed={processedLeaks}
      />
    </main>
  );
}

function ExternalLeakPanel({
  leaks,
  platforms,
  processed,
}: {
  leaks: LeakRecord[];
  platforms: number;
  processed: number;
}) {
  return (
    <section className="panel external-leak-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">EXTERNAL PLATFORM EXPOSURE</p>
          <h2>O cliente que vaza aparece fora da CDN</h2>
          <p className="panel-subtitle">
            O LeakService simula a cópia de um chunk watermarkado para
            plataformas externas. A prova mantém a origem da CDN mesmo depois da
            redistribuição; nenhuma plataforma real é acessada.
          </p>
        </div>
        <ExternalLink size={18} className="danger" />
      </div>
      <div className="external-leak-summary">
        <div>
          <strong>{leaks.length}</strong>
          <span>vazamentos externos</span>
        </div>
        <div>
          <strong>{platforms}</strong>
          <span>plataformas simuladas</span>
        </div>
        <div>
          <strong>{processed}</strong>
          <span>já investigados</span>
        </div>
      </div>
      <div className="external-leak-flow">
        <span className="external-flow-step">
          <ShieldAlert size={15} /> cliente malicioso
        </span>
        <span>→</span>
        <span className="external-flow-step">
          <Fingerprint size={15} /> chunk com watermark
        </span>
        <span>→</span>
        <span className="external-flow-step">
          <Globe2 size={15} /> plataforma externa
        </span>
        <span>→</span>
        <span className="external-flow-step">
          <Radar size={15} /> monitor da CDN
        </span>
      </div>
      <div className="external-leak-list">
        {leaks
          .slice(-8)
          .reverse()
          .map((leak) => (
            <div className="external-leak-row" key={leak.leak_id}>
              <span className="external-leak-icon">
                <Globe2 size={14} />
              </span>
              <div>
                <strong>
                  {leak.client_id} · {leak.platform}
                </strong>
                <small>
                  {leak.platform_kind ?? "plataforma externa"} · origem{" "}
                  {leak.origin_server_id ?? leak.server_id} · monitor{" "}
                  {leak.detected_by_server_id ?? "aguardando"}
                </small>
              </div>
              <span
                className={`leak-state ${leak.processed ? "leak-state-processed" : ""}`}
              >
                {leak.processed ? "prova processada" : "pendente"}
              </span>
            </div>
          ))}
        {leaks.length === 0 && (
          <div className="empty-state">
            <Globe2 size={22} />
            <span>
              Ainda não houve cópia para uma plataforma externa simulada.
            </span>
          </div>
        )}
      </div>
    </section>
  );
}
