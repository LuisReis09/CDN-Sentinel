# Mídia demonstrativa local

Os três arquivos `cdn-sentinel-demo-*.mp4` são um asset pequeno, versionado e
reproduzível do projeto. O original foi gerado com `ffmpeg` a partir do filtro
`testsrc2`, em 320×180, 12 fps e aproximadamente dois segundos. Não contém
material de terceiros nem exige download externo.

- `original`: fonte de referência.
- `watermarked`: o mesmo vídeo com uma alteração sutil de luminância e uma
  região de sinal visual aplicada aos frames.
- `difference`: `blend=difference` entre os dois arquivos, com contraste
  amplificado para inspeção.

O endpoint expõe todos como `video/mp4` com suporte condicional/range do Flask.
O `HMAC-SHA256` mostrado no laboratório continua sendo um claim de
autenticidade inserido no transporte; ele não é confundido com o watermark
visual dos frames.

O dataset `scikit-video`/Big Buck Bunny permanece opcional (`USE_BIGBUCKBUNNY_DATASET=1`)
e não é baixado automaticamente.
