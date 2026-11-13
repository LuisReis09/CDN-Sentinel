# Refinamento visual e Studio CDNWM4 — 13/11/2026

## Implementação

- **QIM3 versionado:** marcador de 48 bits codificado por Hamming estendido SECDED(55,48), com oito bits de sincronismo. Corrige um bit do codeword e detecta dois; não aumenta a identidade de 48 bits nem torna o detector imune a múltiplos erros. A distribuição keyed usa blocos DCT 8×8 na geometria canônica de 640 px. Uma máscara deixa de inserir sinal em blocos uniformes, muito escuros ou claros e com aresta local muito forte. O decoder usa máscara suave recalculada da mídia recebida e agrega correlações de até 24 quadros. O gate de correlação 0,15 não foi reduzido.
- **Padrão selecionado:** QIM3, passo 28, em fontes de pelo menos 640×360; Adaptive Spread permanece para fontes menores. QIM2, DCT anterior e Adaptive Spread continuam disponíveis para detecção de claims históricos. O claim novo declara `dct-qim-v3` e `visual-marker-48-secded-hamming-55-48-v1`.
- **Studio principal:** `POST /api/security/watermark/demo/forensic` usa a emissão CDNWM4 real, cifra e autentica o claim, escreve no ledger, insere o marcador no MP4, executa a extração *sem token esperado*, consulta o ledger e roda a comparação de conteúdo da investigação. O Studio apresenta separadamente extração visual, ledger, comparação de conteúdo e decisão `PENDING_REVIEW`. O laboratório CDNWM3 permanece acessível como opção legada.
- **Comparação visual:** clipe original normalizado para FPS constante, controle H.264 CRF24, marcado H.264 CRF24, resíduo capturado antes da codificação, diferença RGB absoluta entre controle e marcado já codificados, e mapa de correlação DCT do primeiro quadro com a palavra emitida. Resíduo e diferença são diagnósticos com ganho de exibição 8×. O mapa usa o marcador emitido para colorir os blocos; não é o resultado do detector cego. O serviço mede número de quadros, FPS, duração e desvio máximo dos timestamps; a interface controla reprodução e busca de tempo em conjunto.

As seis amostras reais de Big Buck Bunny geradas no workspace estão relacionadas com hash SHA-256 em [studio-sample-manifest.json](benchmarks/studio-sample-manifest.json). Os MP4/PNG ficam em `data/media/generated/`, ignorados pelo Git; execute o Studio para regenerar amostras após um checkout limpo. A inspeção local confirmou 120 quadros e desvio de timestamp 0 ms entre as cinco variantes de vídeo. A primeira versão do filtro de diferença produzia uma visualização quase preta apesar de uma diferença RGB média de 2,79 níveis; ela foi corrigida e o E2E exige diferença visível.

## Rodada de detector QIM3 — 13/11/2026

Esta rodada usou somente três clipes locais de `kishan51/youtube_clipped_videos` (`tmp008xheyw`, `tmp00up6ls4`, `tmp00ytz800`), pois o dataset estava disponível. Cada clipe foi limitado a 2 s, o controle foi H.264 CRF24/veryfast/yuv420p e o token visual determinístico foi igual entre as alternativas. A matriz inclui clean, H.264 CRF23/28, resize 75%/50%, blur leve, ruído leve, grayscale, crop moderado e resize+blur+reencode. Os JSONs locais reproduzíveis são `data/runtime/qim3-detector-baseline.json`, `qim3-detector-soft.json` e `qim3-step30.json`.

| Alternativa | Inserção | Exatos (clean + 9 ataques) | Blur leve | Resize + blur + reencode | Negativos sem marca | PSNR médio | SSIM janelado médio | Decisão |
|---|---|---:|---:|---:|---:|---:|---:|---|
| Baseline QIM3 | passo 28 | 14/30 | 0/3 | 0/3 | 0/3 candidatos | 38,569 dB | 0,98591 | manter padrão |
| ECC soft experimental | passo 28, mesma mídia | 15/30 | 0/3 | 0/3 | 0/3 candidatos | 38,569 dB | 0,98591 | não promover |
| Passo 30 experimental | passo 30 | 16/30 | 0/3 | 0/3 | 0/3 candidatos | 38,510 dB | 0,98533 | não promover |

O decoder soft aplica uma busca Chase limitada aos oito bits menos confiáveis apenas depois de `UNCORRECTABLE`; sincronismo e gate de correlação 0,15 permanecem iguais. Ele recuperou um H.264 CRF28 adicional, mas não melhorou blur ou resize combinado e criou um candidato não exato em um resize 75%. O passo 30 trouxe dois acertos adicionais fora dos ataques prioritários, mas reduziu PSNR e SSIM em todos os clipes. Logo, nenhuma alternativa foi incorporada ao fluxo padrão: QIM3 passo 28, inserção atual e thresholds atuais permanecem intactos. Isso preserva 48/48 nos clean já aprovados e evita trocar imperceptibilidade ou confiabilidade por um resultado seletivo.

Como controle de falso positivo, 32 clipes sem watermark (índices 32–63 do mesmo dataset, chave independente de calibração e até oito frames por clipe) produziram **0/32 candidatos** tanto no baseline quanto no soft decoder; a maior confiança negativa foi 0,1245, abaixo do gate 0,15. É uma calibração limitada, não uma taxa de produção, e não compensa a ausência de ganho nos ataques prioritários.

Reprodução da comparação:

```powershell
python tools/forensic_benchmark.py --dataset-root data/datasets/youtube_clipped_videos --max-files 3 --seconds 2 --mode refinement --algorithms qim3 --qim3-step 28 --token-seed detector-ab-20261113 --output data/runtime/qim3-detector-baseline.json
python tools/forensic_benchmark.py --dataset-root data/datasets/youtube_clipped_videos --max-files 3 --seconds 2 --mode refinement --algorithms qim3 --qim3-step 28 --qim3-soft-decode --token-seed detector-ab-20261113 --output data/runtime/qim3-detector-soft.json
python tools/forensic_benchmark.py --dataset-root data/datasets/youtube_clipped_videos --max-files 3 --seconds 2 --mode refinement --algorithms qim3 --qim3-step 30 --token-seed detector-ab-20261113 --output data/runtime/qim3-step30.json
python tools/qim_threshold_calibration.py --dataset-root data/datasets/youtube_clipped_videos --count 32 --offset 32 --algorithm qim3 --qim-step 28 --output data/runtime/qim3-negative-baseline-32.json
python tools/qim_threshold_calibration.py --dataset-root data/datasets/youtube_clipped_videos --count 32 --offset 32 --algorithm qim3 --qim-step 28 --qim3-soft-decode --output data/runtime/qim3-negative-soft-32.json
```

## Protocolo e resultados locais

Foram usados os três clipes da rodada anterior (`tmp008xheyw`, `tmp00up6ls4`, `tmp00ytz800`) e Big Buck Bunny. Cada fonte foi cortada em 2 s, codificada em H.264 CRF24/veryfast/yuv420p; o controle foi recodificado com os mesmos parâmetros. Um mesmo marcador por fonte foi inserido por Adaptive Spread força 24, QIM2 passo 20 e QIM3 passo 28. Qualidade usa até oito quadros contra o controle. **SSIM** agora usa janelas Gaussianas 11×11, σ=1,5, na luminância, faixa 255. O MS-SSIM continua aproximação em três escalas. Extração usa até 24 quadros. Exato significa marcador de 48/48 bits e gate visual `CANDIDATE`. Os JSONs incluem hashes SHA-256, ambiente, tempos, estados, BER bruto do canal QIM e correções ECC. Não houve análise perceptual com participantes.

| Algoritmo | PSNR médio vs controle | SSIM janelado médio | Limpo exato | Ataques exatos (9×4) | Negativos com marcador esperado |
|---|---:|---:|---:|---:|---:|
| Adaptive Spread | 30,5180 dB | 0,936538 | 2/4 | 13/36 | 0/4 |
| QIM2 passo 20 | 38,3510 dB | 0,976888 | 3/4 | 12/36 | 0/4 |
| QIM3 passo 28 | 38,2854 dB | 0,982499 | 4/4 | 21/36 | 0/4 |

| Transformação | Adaptive Spread | QIM2 | QIM3 |
|---|---:|---:|---:|
| H.264 CRF23 | 2/4 | 2/4 | 4/4 |
| Resize 75% e retorno | 2/4 | 2/4 | 3/4 |
| Blur leve | 2/4 | 1/4 | 1/4 |
| H.264 CRF28 | 1/4 | 1/4 | 3/4 |
| Resize 50% e retorno | 2/4 | 1/4 | 1/4 |
| Ruído leve | 1/4 | 2/4 | 4/4 |
| Grayscale | 2/4 | 2/4 | 4/4 |
| Crop moderado | 0/4 | 0/4 | 0/4 |
| Resize + blur + reencode | 1/4 | 1/4 | 1/4 |

QIM3 é a melhor opção **neste conjunto**, com recuperação limpa em 4/4 e melhora agregada de 12/36 para 21/36 ataques em relação a QIM2. O SSIM médio subiu 0,005611; o PSNR médio caiu 0,0656 dB. A vantagem não é uniforme: Adaptive Spread recuperou um caso adicional de blur e resize 50%. Um crop de 10% em largura e altura zerou todos os métodos. Blur e resize 50% continuam fracos. Ensaios exploratórios de passo 20 e 28 usaram tokens diferentes, então a diferença entre passos não é uma estimativa causal isolada. Não houve ajuste do limiar de detecção para mudar resultados inconclusivos.

Entre os 40 resultados QIM3 (quatro limpos e 36 ataques), o decoder registrou 18 codewords `CLEAN`, 13 `CORRECTED` e nove `UNCORRECTABLE`. Seis das 25 recuperações exatas (limpos e ataques) exigiram correção de um bit. Um status `CORRECTED` não garante marcador verdadeiro quando há três ou mais erros; o ledger só aceita associação exata e a investigação exige correspondência do conteúdo. A BER bruta é medida frente ao marcador conhecido **apenas no benchmark**; o detector operacional não o recebe.

Os quatro vídeos sem marca dos ensaios não produziram o marcador esperado. O conjunto de 128 negativos de calibração QIM3 (arquivos de índices 256–383, sem sobreposição com os quatro positivos) produziu zero candidatos visuais, maior correlação média 0,1683; ela excedeu 0,15, mas não passou o sincronismo. Outros 128 negativos independentes (índices 384–511) também deram zero candidatos, maior correlação 0,1710. Os intervalos de índices são disjuntos, mas vêm do mesmo dataset; isso não é uma taxa de falsa atribuição de produção. O limite superior unilateral aproximado de 95% para 0/128 candidatos é 2,3%. A atribuição no sistema ainda exige associação exata de 48 bits ao ledger, assinatura válida e correspondência do conteúdo.

Em Big Buck Bunny de 4 s, QIM2 teve PSNR 37,9217 dB, SSIM 0,976069 e 6/9 ataques exatos; QIM3 teve PSNR 37,4698 dB, SSIM 0,972292 e 8/9 ataques exatos. Ambos recuperaram o marcador no arquivo limpo, e o crop continuou falhando. Esse ensaio confirma o custo visual local de mais intensidade e o benefício de robustez no clipe mais longo; não substitui a matriz de quatro fontes de 2 s.

Em `tmp008xheyw` de 5 s, QIM2 teve 39,2188 dB / SSIM 0,982384 e QIM3 39,2904 dB / 0,986316; ambos recuperaram 3/9 ataques, incluindo H.264 CRF23, resize 75% e grayscale. Blur, resize 50% e crop falharam. Os recortes de 2, 4 e 5 s demonstram que a duração e o conteúdo amostrado mudam a recuperação; os tokens também são novos em cada execução. A comparação causal entre algoritmos é **dentro de cada ensaio**, onde eles usam o mesmo token.

Reprodução da matriz principal:

```powershell
python tools/forensic_benchmark.py --input data/datasets/youtube_clipped_videos/data/tmp008xheyw.mp4 --input data/datasets/youtube_clipped_videos/data/tmp00up6ls4.mp4 --input data/datasets/youtube_clipped_videos/data/tmp00ytz800.mp4 --input data/media/bigbuckbunny.mp4 --seconds 2 --mode refinement --algorithms adaptive-spread qim2 qim3 --qim3-step 28 --output docs/benchmarks/refinement-2s-4clips.json
python tools/qim_threshold_calibration.py --dataset-root data/datasets/youtube_clipped_videos --count 128 --offset 256 --algorithm qim3 --qim-step 28 --output docs/benchmarks/qim3-calibration-128.json
python tools/qim_threshold_calibration.py --dataset-root data/datasets/youtube_clipped_videos --count 128 --offset 384 --algorithm qim3 --qim-step 28 --output docs/benchmarks/qim3-independent-negatives-128.json
```

## Validação e limites

O E2E da CDN em `tests/test_watermark_e2e_forensics.py` cobre dois clientes, sessão autorizada, MP4 marcado, reencode, upload suspeito, extração e identificação da sessão correta; o outro cliente não é atribuído. `tests/test_forensic_studio_e2e.py` verifica o Studio real e seus seis ativos. O SECDED foi testado para cada erro simples e cada par de erros duplos. Os resultados de testes, build, Docker e CI estão no checklist final da tarefa.

Não há estudo com espectadores, medida de cintilação temporal, VMAF/LPIPS ou calibração por gênero de vídeo. A máscara é heurística e pode variar entre quadros. Crop, blur e resize seguem limitações. Os clipes do dataset têm licença ainda não verificada; os JSONs de resultados não redistribuem a mídia. Não use o status visual sozinho para punição ou declaração de autoria humana.
