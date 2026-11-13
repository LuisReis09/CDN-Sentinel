import { useEffect, useState, type Ref } from "react";

interface NoiseVideoPreviewProps {
  videoUrl: string;
  label: string;
  variant: "original" | "watermarked" | "difference";
  description: string;
  videoRef?: Ref<HTMLVideoElement>;
  onTimeUpdate?: (currentTime: number) => void;
  onLoadedMetadata?: (duration: number) => void;
  onPlay?: () => void;
  onPause?: () => void;
}

/** Plays the exact MP4 variant returned by the backend media catalog. */
export function NoiseVideoPreview({
  videoUrl,
  label,
  variant,
  description,
  videoRef,
  onTimeUpdate,
  onLoadedMetadata,
  onPlay,
  onPause,
}: NoiseVideoPreviewProps) {
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    setUnavailable(false);
  }, [videoUrl]);

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
            ref={videoRef}
            muted
            playsInline
            aria-label={label}
            onError={() => setUnavailable(true)}
            onTimeUpdate={(event) => onTimeUpdate?.(event.currentTarget.currentTime)}
            onLoadedMetadata={(event) => onLoadedMetadata?.(event.currentTarget.duration)}
            onPlay={onPlay}
            onPause={onPause}
          />
        )}
        <span className="noise-video__source-badge">
          MP4 real ·{" "}
          {variant === "original" ? "fonte" : "transformação de pixels"}
        </span>
      </div>
      <div className="noise-video__caption">
        <span>{label}</span>
        <small>{description}</small>
      </div>
    </div>
  );
}

