import { Fingerprint, LockKeyhole, ScanSearch, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import { WatermarkLab } from "../components/WatermarkLab";
import type { Overview } from "../types";

export function WatermarkPage({ overview, onError }: { overview: Overview; onError: (message: string) => void }) {
  return <main className="page-content"><header className="page-header"><div><p className="eyebrow">CRYPTOGRAPHIC CONTENT PROTECTION</p><h1>Watermark studio</h1><p className="page-lead">Uma visão didática do ciclo de vida da assinatura forense sem expor a chave secreta.</p></div></header><section className="watermark-story"><StoryCard icon={<LockKeyhole />} title="Emitir" text="A CDN cria um token único usando cliente, servidor, timestamp e chunk." /><StoryCard icon={<Fingerprint />} title="Assinar" text="HMAC-SHA256 torna a prova resistente a adulteração e replay simples." /><StoryCard icon={<ScanSearch />} title="Extrair" text="O monitor lê o prefixo CDNWM1 diretamente dos bytes redistribuídos." /><StoryCard icon={<ShieldCheck />} title="Governar" text="A prova válida identifica o assinante e dispara o gossip de blacklist." /></section><WatermarkLab onError={onError} /></main>;
}

function StoryCard({ icon, title, text }: { icon: ReactNode; title: string; text: string }) { return <article className="story-card"><span>{icon}</span><h3>{title}</h3><p>{text}</p></article>; }

