# Mídia demonstrativa local

O Watermark Studio usa `bigbuckbunny.mp4`, um sample real de 10 segundos do
curta-metragem Big Buck Bunny, em 1280×720. O filme foi produzido pela Blender
Foundation e o material é distribuído sob CC-BY-3.0; a interface exibe essa
atribuição na origem do vídeo.

Os arquivos `cdn-sentinel-demo-*.mp4` continuam disponíveis como fallback local
pequeno e reproduzível:

- `cdn-sentinel-demo-original.mp4`: fonte `testsrc2` de controle.
- `cdn-sentinel-demo-watermarked.mp4`: luminância alterada para testes legados.
- `cdn-sentinel-demo-difference.mp4`: diferença amplificada do fallback.

Durante uma execução do laboratório, o backend usa FFmpeg para gerar em
`data/media/generated/` duas variantes temporárias/cacheadas do Big Buck Bunny:

- `watermarked`: 64 bits do digest HMAC distribuídos em uma grade 8×8 de regiões
  de luminância em cada frame;
- `difference`: blend real entre o frame original e o frame transformado, com
  contraste aumentado para inspeção.

O token HMAC prefixado ao chunk é uma prova de transporte separada do sinal
visual. O detector do laboratório lê o primeiro frame real de ambos os MP4s e
calcula `bits_correct / bits_total`; os filtros blur, ruído determinístico e
quantização são aplicados antes da comparação. A pasta `generated/` é cache
local de runtime e não faz parte do conjunto versionado.
