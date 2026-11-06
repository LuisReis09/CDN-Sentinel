import { useEffect, useRef, useState } from "react";

interface NoiseVideoPreviewProps {
  videoUrl: string;
  noiseHex: string;
  strength: number;
  label: string;
  amplified?: boolean;
  showNoise?: boolean;
}

/** Plays the real backend asset and overlays a deterministic forensic-noise inspection layer. */
export function NoiseVideoPreview({ videoUrl, noiseHex, strength, label, amplified, showNoise = true }: NoiseVideoPreviewProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [videoUnavailable, setVideoUnavailable] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;
    const width = 640;
    const height = 360;
    canvas.width = width;
    canvas.height = height;
    context.clearRect(0, 0, width, height);

    if (!showNoise) return;
    let seed = Number.parseInt(noiseHex.slice(0, 8), 16) || 7;
    for (let index = 0; index < 850; index += 1) {
      seed = (seed * 1664525 + 1013904223) >>> 0;
      const x = seed % width;
      seed = (seed * 1664525 + 1013904223) >>> 0;
      const y = seed % height;
      const alpha = (0.12 + ((seed >>> 8) % 100) / 100 * 0.2) * strength;
      const channel = seed % 3 === 0 ? "69,217,255" : seed % 3 === 1 ? "158,255,108" : "255,184,107";
      context.fillStyle = `rgba(${channel}, ${alpha})`;
      context.fillRect(x, y, amplified ? 2 : 1, amplified ? 2 : 1);
    }
  }, [noiseHex, strength, amplified, showNoise]);

  return (
    <div className={`noise-video noise-video--real ${amplified ? "noise-video--amplified" : ""}`}>
      <div className="noise-video__frame">
        {videoUnavailable ? <div className="noise-video__fallback"><strong>FALLBACK LOCAL</strong><span>conteúdo demonstrativo</span><small>nenhum frame real foi watermarkado</small></div> : <video className="noise-video__source" src={videoUrl} muted loop autoPlay playsInline controls aria-label={label} onError={() => setVideoUnavailable(true)} />}
        <canvas ref={canvasRef} className="noise-video__noise" aria-hidden="true" />
        <span className="noise-video__source-badge">overlay demonstrativo · fonte local/opt-in</span>
      </div>
      <div className="noise-video__caption"><span>{label}</span><small>{amplified ? "overlay amplificado para inspeção" : "overlay didático; não é frame watermarkado"}</small></div>
    </div>
  );
}
