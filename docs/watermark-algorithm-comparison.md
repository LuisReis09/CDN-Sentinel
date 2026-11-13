# Comparação de algoritmos

> **Atualização de 12/11/2026:** os resultados abaixo são históricos e insuficientes para escolher um algoritmo de produção. VideoSeal e PixelSeal não foram executados neste ambiente; QIM2 permanece sem ECC corretor. Veja [o estado de fechamento](watermark-finalization-status.md).

## Escopo e decisão

Os números abaixo vêm do mesmo script `tools/forensic_benchmark.py`, usando o mesmo token por clipe, controle H.264 CRF24, primeiros 2 segundos e até 24 frames para extração. São três clipes locais de `youtube_clipped_videos`, escolhidos por ordem de arquivo; não constituem amostra representativa. Os resultados completos e comandos estão em [watermark-benchmark-results.md](watermark-benchmark-results.md). `CANDIDATE` visual não prova marcador exato.

| Método | Qualidade medida nos 3 clipes (PSNR; SSIM global aproximado) | Clean exato | H.264 CRF23 exato | Resize 75% exato | Blur leve exato | Estado |
|---|---|---:|---:|---:|---:|---|
| Spread adaptativo v5, força 24 | 30,64–31,95 dB; 0,9902–0,9948 | 3/3 | 2/3 | 1/3 | 1/3 | Baseline operacional para resolução baixa |
| DCT/QIM v1, passo 10 | 38,92 dB; 0,9987 no Big Buck Bunny de 2 s | 0/1 | 0/1 | 0/1 | 0/1 | Reprovado neste ensaio |
| QIM2 keyed, passo 20 | 35,12–40,66 dB; 0,9981–0,9995 | 3/3 | 1/3 | 0/3 | 0/3 | Padrão provisório para >=640×360 |
| VideoSeal | Não medido | — | — | — | — | Adaptador opcional, pesos/dependências não instalados |
| PixelSeal | Não medido | — | — | — | — | Pesquisa; integração real não executada |
| DWT/híbrido | Não medido | — | — | — | Alternativa a investigar |

No vídeo Big Buck Bunny de 10 s, uma rodada anterior de QIM2 com passo 20 produziu PSNR 37,90 dB e SSIM 0,99825, com 48/48 bits brutos em clean, H.264 CRF23, resize e blur. O JSON antigo foi gerado com limiar 0,22 e portanto classificou os quatro como inconclusivos; uma nova extração dos **artefatos salvos** com limiar 0,15 classificou clean, H.264 e resize como candidatos exatos, blur ainda inconclusivo. Não conte esses resultados como um novo benchmark de emissão. Os três clipes da tabela acima usam o código com limiar 0,15.

## Pesquisa e critérios

[VideoSeal, artigo](https://arxiv.org/abs/2412.09492) e [implementação](https://github.com/facebookresearch/videoseal) oferecem encoder/decoder aprendido com propagação temporal e modelos publicados. O custo de dependências e inferência, e a necessidade de medir qualidade e ataques no mesmo dataset, impediram escolher o modelo sem executá-lo. O adaptador em `watermark/algorithms.py` falha explicitamente se a biblioteca não está instalada. [PixelSeal](https://arxiv.org/abs/2512.16874) enfatiza limites perceptuais e treinamento adversarial; não foram obtidos resultados locais nem integração de pesos. A comparação numérica neural é, portanto, pendente.

O QIM2 distribui bits e escolhe dois coeficientes DCT de média frequência por bloco. A geometria canônica reduz diferenças por resize, ao custo de instabilidade em crop, rotação, barras e cenas difíceis. O spread usa máscara adaptativa e repetição espacial; custou mais qualidade no teste curto, mas foi mais robusto em um dos clipes. DWT não foi implementado por falta de evidência local de vantagem. A escolha atual prioriza qualidade objetiva e detecção no arquivo limpo; a baixa recuperação sob ataque impede alegar um vencedor robusto.

ECC e códigos de colusão são problemas diferentes. `watermark/ecc.py` implementa paridade Reed-Solomon/interleaving experimental, mas o decoder **não corrige** símbolos errados. O SECDED legado continua para o canal legado; QIM2 não usa RS corretor na atribuição. `watermark/anticollusion.py` simula uma matriz enviesada no estilo [Tardos](https://doi.org/10.1145/1346330.1346335), sem limiar estatístico nem integração à entrega. A arquitetura [DASH-IF/ETSI de A/B](https://dashif.org/guidelines/specifications/) orientou a preparação de segmentos; a extração e taxa de atribuição continuam pendentes.

Qualidade humana deve ser medida com protocolo cego inspirado em [ITU-T P.910](https://www.itu.int/rec/t-rec-p.910). `tools/human_blind_study.py` gera pares e formulário; não houve participantes nem revisão humana nesta entrega. PSNR/SSIM altos não demonstram invisibilidade.
