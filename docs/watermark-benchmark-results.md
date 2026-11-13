# Benchmark forense reproduzível

> **Atualização de 12/11/2026:** estes números pertencem à rodada histórica indicada abaixo e não são uma avaliação final independente. A matriz, os intervalos de confiança e o estudo humano exigidos continuam pendentes; veja [o checklist de fechamento](watermark-finalization-status.md).

Data: 2026-11-11. Base auditada: `761e64a89d2d63ea2334566ff852a5da27b8c2be`; medições feitas na árvore de trabalho da branch `codex/forensic-watermark-reengineering` antes dos commits finais. Ambiente: Windows 11, Python 3.12.10, FFmpeg 8.1.2, NumPy 2.5.1, SciPy 1.18.0, CPU local. O script grava versão do ambiente e hash SHA-256 de cada fonte no JSON. Os arquivos sob `data/runtime/` são ignorados pelo Git; os comandos abaixo os recriam.

## Fontes e licença

Três primeiros clipes MP4 ordenados do dataset local `data/datasets/youtube_clipped_videos/data/`: `tmp008xheyw.mp4` (SHA-256 `753d63d3ee47d17f0ddac40cccef183072f774003c759db1efaa565febb00cdb`), `tmp00up6ls4.mp4` (`3a14cff9ef7fcaa02e0c8821985f3aa1d856484010a2309e9a9516373431d56e`) e `tmp00ytz800.mp4` (`3a753874ea34abee9e74ec568ab416513c26f915e63d314704617772b4dff17d`). A licença desses clipes **não foi verificada**; não redistribua artefatos derivados sem verificar os direitos. Big Buck Bunny local é usado para um ensaio adicional; é atribuído à Blender Foundation sob CC BY 3.0 no projeto.

## Protocolo executado

Cada fonte foi cortada em 2 s, codificada em H.264 CRF24/veryfast/yuv420p; um controle sem marca foi reencodado nas mesmas condições que os marcados. Mesmo token de 48 bits por clipe para spread força 24 e QIM2 passo 20. Medidas de PSNR e SSIM/MS-SSIM **aproximados globais** em até oito frames, contra o controle. Extração em até 24 frames. Ataques executados: H.264 CRF23, resize 75% com retorno e H.264 CRF23, blur `boxblur=1:1` com H.264 CRF23. “Exato” significa 48/48 bits e gate visual `CANDIDATE`; proximidade Hamming não conta. Os resultados são dos três clipes de desenvolvimento, sem seleção aleatória ou intervalo de confiança.

```powershell
python tools/forensic_benchmark.py --dataset-root data/datasets/youtube_clipped_videos --max-files 3 --seconds 2 --mode quick --algorithms adaptive-spread qim2 --qim-step 20 --output data/runtime/forensic-benchmark-dataset-3.json --artifact-dir data/runtime/benchmark-dataset-3
python tools/qim_threshold_calibration.py --dataset-root data/datasets/youtube_clipped_videos --count 128 --offset 0 --output data/runtime/qim-calibration-128-step20.json
python tools/qim_threshold_calibration.py --dataset-root data/datasets/youtube_clipped_videos --count 128 --offset 128 --output data/runtime/qim-final-negatives-128-step20.json
python tools/forensic_benchmark.py --input data/media/bigbuckbunny.mp4 --seconds 10 --mode quick --algorithms qim2 --qim-step 20 --output data/runtime/forensic-benchmark-qim2-final.json --artifact-dir data/runtime/benchmark-qim2-final
```

O script gera original cortado, controle, marcados e atacados, além de `sha256.json` no diretório de artefatos. A variante de diferença amplificada pode ser reproduzida com os utilitários existentes de experimentos perceptuais; a suíte forense não a gera automaticamente. O script `tools/human_blind_study.py` produz pares randomizados e CSV para um piloto cego, mas não houve participantes. A matriz `--mode full` contém ataques adicionais, porém **não foi executada integralmente** nesta rodada; artefatos adicionais requerem tempo/custo de processamento.

## Resultado dos três clipes

| Fonte | Método | PSNR dB | SSIM aprox. | Clean exato | H.264 exato | Resize exato | Blur exato |
|---|---|---:|---:|---|---|---|---|
| `tmp008xheyw` | Spread | 31,9503 | 0,991403 | sim | não (46/48) | não (46/48) | não (44/48) |
| `tmp008xheyw` | QIM2 | 39,2752 | 0,998905 | sim | não (46/48) | não (46/48) | não (30/48) |
| `tmp00up6ls4` | Spread | 30,6404 | 0,990203 | sim | sim | não (46/48) | não (45/48) |
| `tmp00up6ls4` | QIM2 | 35,1193 | 0,998119 | sim | sim | não (47/48) | não (36/48) |
| `tmp00ytz800` | Spread | 30,9831 | 0,994773 | sim | sim | sim | sim |
| `tmp00ytz800` | QIM2 | 40,6623 | 0,999527 | sim | não (40/48) | não (35/48) | não (28/48) |

QIM2 preservou mais qualidade objetiva nos três, mas sua recuperação exata pós-ataque foi inferior à do spread em um clipe. Em Big Buck Bunny de 2 s, DCT v1 teve 38,9225 dB/0,998698 e falhou até no clean; spread teve 28,4577 dB/0,978998 e também falhou no clean. Esses dois resultados não devem ser misturados diretamente com o dataset de três clipes. O ensaio anterior de QIM2 em Big Buck Bunny de 10 s usou o limiar antigo 0,22 e está descrito como histórico em [comparação](watermark-algorithm-comparison.md).

Um novo ensaio de Big Buck Bunny de 10 s, com o código/limiar 0,15, obteve QIM2 PSNR **37,9342 dB**, SSIM global aproximado **0,99827**, MS-SSIM aproximado **0,998786**; clean, H.264 CRF23 e resize 75% recuperaram marcador exato (48/48), enquanto blur teve 48/48 bits brutos, porém ficou **INCONCLUSIVE** pelo limiar visual. O diretório de artefatos contém seis arquivos com SHA-256 em `sha256.json`. O erro médio de luminância em regiões uniformes foi 1,588 nível e em regiões escuras 1,7868; sem estudo humano, esses números não autorizam afirmar invisibilidade.

Ensaios de diagnóstico adicionais mostraram uma **falha dependente da fonte**: Big Buck Bunny pré-reencodado para 640×360 por 10 s produziu QIM2 PSNR 37,0845 dB/SSIM 0,997782, mas o clean ficou `INCONCLUSIVE` com 48/48 bits brutos e correlação 0,1273 (<0,15); todos os ataques também ficaram inconclusivos. Um recorte de seis segundos do original 1280×720 produziu PSNR 37,8271 dB/SSIM 0,998217, clean/H.264/resize exatos e blur inconclusivo. Portanto, nenhum limiar ou resolução deve ser tratado como universal. JSONs locais: `data/runtime/e2e-bbb-640-10-benchmark.json` e `data/runtime/e2e-bbb-1280-6-benchmark.json`.

O limiar 0,15 de QIM2 foi escolhido após 128 vídeos locais sem marca: maior correlação observada 0,1127 e 0 candidatos. Em **outros** 128 negativos, maior correlação 0,1043 e 0 candidatos. Isso mede somente falso candidato visual nessas amostras e segredo. O limite superior aproximado de 95% para uma proporção com 0/128 ocorrências ainda é cerca de 2,3%; não prova taxa de falso positivo de produção. Não houve ROC/PR, várias chaves, milhares de títulos ou ataque de transplante calibrado.

PSNR/SSIM não provam imperceptibilidade. VMAF, LPIPS, flicker quantificado, avaliação HDR, estudo ITU-T P.910 com pessoas, custo p50/p95 sob concorrência, robustez por gênero e colusão real continuam pendentes. O teste E2E valida um vazamento recodificado específico e não altera essas limitações.
