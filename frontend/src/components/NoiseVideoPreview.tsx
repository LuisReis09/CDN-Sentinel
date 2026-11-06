import { useState } from "react";

interface NoiseVideoPreviewProps {
  videoUrl: string;
  label: string;
  variant: "original" | "watermarked" | "difference";
  description: string;
}

/** Plays the exact MP4 variant returned by the backend media catalog. */
export function NoiseVideoPreview({
  videoUrl,
  label,
  variant,
  description,
}: NoiseVideoPreviewProps) {
  const [unavailable, setUnavailable] = useState(false);

  return (
    <div className={`noise-video noise-video--${variant}`}>
      <div className="noise-video__frame">
        {unavailable ? (
          <div className="noise-video__fallback">
            <strong>MÍDIA INDISPONÍVEL</strong>
            <span>O backend não entregou um MP4 válido.</span>
          </div>
        ) : (
          <video
            className="noise-video__source"
            src={videoUrl}
            muted
            loop
            autoPlay
            playsInline
            controls
            aria-label={label}
            onError={() => setUnavailable(true)}
          />
        )}
        <span className="noise-video__source-badge">
          MP4 real · {variant === "original" ? "fonte" : "transformação de pixels"}
        </span>
      </div>
      <div className="noise-video__caption">
        <span>{label}</span>
        <small>{description}</small>
      </div>
    </div>
  );
}
