# Auditoria e validação do núcleo de watermarking

Data da auditoria: 2026-11-11  
Branch de trabalho: `feat/watermark-security-core`

## Resultado executivo

O núcleo anterior misturava dois mecanismos diferentes:

- o claim transportado no chunk já tinha confidencialidade e autenticação, mas não vinculava explicitamente o conteúdo;
- a marca visual dependia da imagem original e de um marcador esperado, portanto não era uma detecção independente.

O fluxo foi separado e validado:

```text
claim CDNWM3
  ├─ AES-256-GCM: confidencialidade + tag de autenticidade
  ├─ HMAC-SHA256: assinatura do envelope
  └─ content_id: vínculo do claim ao conteúdo

imagem/vídeo
  └─ localizador visual keyed de 40 bits
       ├─ sincronização de 16 bits
       ├─ repetição 3x
       ├─ mascaramento perceptual adaptativo
       ├─ portadora de baixa frequência em blocos de 6×6
       └─ detector sem original e sem token esperado

marcador visual → registro backend → verificação do token → VALID
```

A variante visual agora é gerada quadro a quadro. Em vídeo, as evidências são agregadas entre os quadros antes da decisão; um quadro isolado não decide o resultado. A terceira variante do Watermark Studio continua sendo uma diferença amplificada, mas agora é rejeitada se estiver saturada ou praticamente uniforme.

## Contrato de detecção

| Status | Significado |
|---|---|
| `NOT_FOUND` | A sincronização não atingiu o limiar mínimo. Não há evidência suficiente de marca. |
| `INCONCLUSIVE` | O arquivo é pequeno demais, a sincronização é parcial ou as repetições discordam. Não deve ser tratado como presença nem ausência definitiva. |
| `CANDIDATE` | A marca visual é coerente, mas ainda não foi ligada a um claim autenticado no registro da CDN. |
| `VALID` | O marcador foi associado a um token registrado (exato ou por associação única de até 5 bits), e HMAC, AES-GCM, tag e campos do claim foram verificados. |
| `INVALID` | Houve candidato, mas não há claim registrado ou o claim não corresponde ao marcador recuperado. |

O detector visual não usa a imagem original, uma imagem de referência ou um token esperado. A confiança visual localiza uma possível marca; a decisão de segurança é feita pelo token autenticado no backend.

Para absorver erros pontuais de H.264, o backend procura uma associação única a até 5 bits de distância Hamming entre os marcadores registrados. Se houver empate, nenhum claim é escolhido. Essa aproximação é somente uma etapa de associação; o token ainda precisa passar integralmente por HMAC e AES-GCM. O limite é deliberadamente finito: não é uma correção arbitrária do marcador.

## Alterações criptográficas

### Envelope de watermark

- `CDNWM1` continua aceito somente para compatibilidade legada HMAC.
- `CDNWM2` continua aceito para claims antigos cifrados.
- `CDNWM3` é usado quando existe `content_id`, como nos chunks reais e na demonstração.
- O payload autenticado contém `client_id`, `server_id`, `issued_at`, `chunk_id` e `content_id`.
- A cifra é AES-256-GCM, com nonce aleatório de 96 bits e tag de 128 bits.
- A versão (`CDNWM2` ou `CDNWM3`) entra como AAD, impedindo que o envelope seja reinterpretado em outro formato.
- O HMAC cobre a representação Base64URL do nonce, ciphertext e tag. No `CDNWM3`, a chave de assinatura é derivada em contexto separado (`watermark-signing-v3`), sem reutilizar diretamente a chave bruta.
- A chave de cifra também é derivada por contexto (`watermark-v3`) e nunca é enviada ao front-end.

O registro visual em memória é deliberado para o protótipo. Ele permite transformar `CANDIDATE` em `VALID`, mas é apagado quando o processo reinicia. Isso é uma limitação operacional, não um mecanismo de segurança permanente.

### Canal visual

O marcador é `SHA-256(token)[:10]`, ou 40 bits. Ele não substitui HMAC/AES-GCM e não carrega o claim completo.

Para cada imagem com pelo menos 128×128 pixels:

1. a imagem é convertida para luminância;
2. uma grade 16×16 é endereçada por uma permutação determinística derivada do segredo;
3. 16 bits de sincronização e 40 bits de dados são repetidos três vezes, ocupando 168 das 256 células;
4. cada célula recebe uma portadora pseudoaleatória em blocos de 6×6, com sinal positivo ou negativo conforme o bit;
5. a amplitude é reduzida em regiões uniformes, escuras e visualmente sensíveis por uma máscara derivada da própria luminância recebida;
6. a alteração é aplicada proporcionalmente aos canais RGB, preservando o alpha;
7. o detector reproduz as portadoras com o segredo, calcula a correlação e vota nas repetições;
8. no vídeo, a mesma evidência é agregada em até 24 frames, explorando redundância temporal antes da associação criptográfica.

O limite de 128×128 é intencional: uma matriz 20×20 ou 64×64 não fornece células suficientemente grandes para uma marca visual confiável. Esses arquivos retornam `INCONCLUSIVE`, em vez de um falso `VALID`.

`utils/robust_watermark.py` foi mantido como helper legado dos testes de transformação de bytes. O caminho ativo do Watermark Studio é `utils/image_watermark.py` + `utils/video_watermark.py` e não depende da imagem original.

## Interface e auditoria da Watermark Studio

Foi adicionada a rota `POST /api/security/watermark/detect` para upload multipart ou Base64 de imagem/vídeo. A tela Security adiciona um painel de detecção independente e exibe status, confiança, marcador recuperado e claim somente quando a associação criptográfica é válida.

O fluxo da demonstração agora:

1. escolhe o asset local disponível, priorizando o dataset baixado;
2. emite um `CDNWM3` vinculado ao `video_id`;
3. gera o MP4 marcado quadro a quadro;
4. extrai e verifica o claim de transporte;
5. mede a detecção visual independente no original, no controle marcado e nas transformações;
6. só disponibiliza a variante de diferença se ela não estiver branca/saturada.

O bug de serialização da nova rota também foi coberto: o layout interno do detector é convertido para um objeto JSON simples antes da resposta.

## Experimentos executados

### Benchmark de imagem

Comando:

```powershell
python -m tools.watermark_benchmark --size 256 --negatives 32
```

Fixture determinística: gradiente RGB com ruído, 256×256, seed 2026. Resultado medido:

| Medida | Resultado |
|---|---:|
| PSNR da imagem marcada | 44.4083 dB |
| SSIM global simplificado | 0.996804 |
| Detecção marcada | `VALID`, marcador correto |
| JPEG qualidade 80 | `VALID`, marcador correto |
| Blur raio 1 | `VALID`, marcador correto |
| Redimensionar para metade e voltar | `VALID`, marcador correto |
| Candidatos falsos em 32 imagens aleatórias | 3 (todos `INVALID`) |
| Taxa de candidato falso visual | 9.375% |
| `VALID` falso após registro criptográfico | 0 |
| Tempo de embedding medido | 26.403 ms |

O fixture original sem marca retornou `INCONCLUSIVE`, não `VALID`: a correlação parcial não foi aceita como claim. Nos 32 negativos aleatórios, 3 produziram candidato visual, mas todos foram `INVALID` por não haver claim correspondente; 17 foram `INCONCLUSIVE` e 12 `NOT_FOUND`. Nenhum foi validado criptograficamente. A taxa de falso candidato visual é uma limitação conhecida dos limiares mais permissivos; o critério de segurança é o falso `VALID`, que permaneceu em 0/32.

### Análise de imperceptibilidade

Esta foi a validação decisiva da correção do ruído visual. O vídeo usado foi o mesmo `cdn_sentinel_demo`, em 320×180, com 24 frames analisados. O controle sem marca foi reencodado com exatamente as mesmas condições do marcado: `libx264`, `veryfast`, `CRF 24`, `yuv420p`. PSNR, SSIM e MS-SSIM foram calculados contra esse controle; também foram medidas regiões uniformes, regiões escuras e a fração de pixels com alteração de luminância absoluta ≥2.

| Configuração | PSNR (dB) | SSIM | MS-SSIM | Uniforme ΔY | Escura ΔY | ΔY≥2 | Detecção normal |
|---|---:|---:|---:|---:|---:|---:|---|
| baseline legado: luminância fixa, força 16 | 26,51 | 0,99046 | 0,99209 | 6,65 | 6,81 | 82,2% | marcador recuperado, mas visível |
| spread adaptativo, força 24 | 31,26 | 0,99765 | 0,99823 | 0,83 | 0,94 | 21,4% | `VALID`, distância 1/40 |
| spread adaptativo, força 28 — comparação | 30,60 | 0,99699 | 0,99770 | 0,90 | 1,04 | 22,9% | `VALID`, mas sem vantagem robusta consistente |
| DCT intermediário, passo 22 | 34,34 | 0,99948 | 0,99968 | 0,64 | 0,56 | 11,5% | `VALID` no controle, falha em transformações |

O baseline legado reproduz o problema observado: SSIM global aparentemente alto não impediu alteração média de aproximadamente 6–7 níveis de luminância nas áreas uniformes. O spread adaptativo reduz essa alteração para aproximadamente 0,8–0,9 nível; a inspeção visual dos frames reais não mostrou granulação comparável à versão anterior. A configuração escolhida foi a força 24, por oferecer melhor invisibilidade com detecção autenticada normal; a força 28 foi mantida como comparação real, mas não apresentou vantagem consistente suficiente para justificar a maior alteração. Ambas superam a meta inicial SSIM ≥0,98 e a preferência ≥0,99.

O teste DCT foi implementado e medido. Ele apresentou a melhor qualidade numérica, mas não atingiu detecção autenticada consistente após H.264, blur, JPEG e redimensionamento; portanto não foi selecionado automaticamente apenas por ter maior SSIM.

#### Robustez e falsos positivos da configuração escolhida

Com força 24, mascaramento adaptativo, portadora em blocos 6×6 e agregação temporal em até 24 frames, o controle normal foi `VALID`. No experimento de ataques com H.264 CRF 34, ruído leve, blur `boxblur=1:1` e redução/retorno de escala:

| Cenário | Resultado observado | Decisão |
|---|---|---|
| reencode H.264 CRF 34 | recuperação variável; `INVALID` no ensaio final | não aprovado como garantia consistente |
| ruído leve | recuperação variável; `INVALID` no ensaio final | não aprovado como garantia consistente |
| blur leve | candidato visual, distância chegou a 9/40 | não aprovado como robustez autenticada |
| redimensionamento | candidato visual, distância chegou a 7/40 | não aprovado como robustez autenticada |
| original sem marca | sem `VALID` | nenhum falso positivo autenticado observado |
| JPEG qualidade 80 em frame isolado | recuperação parcial, não sempre exata | não aprovado como garantia isolada |

Assim, não declaro a configuração como robusta contra todos os ataques, nem como aprovada para a matriz completa de transformações. Declaro corrigido o objetivo principal de entrega normal: vídeo visualmente indistinguível ou extremamente difícil de distinguir, com detecção autenticada no vídeo entregue. A recuperação após reencode H.264, ruído, blur, resize agressivo e JPEG em frame único precisa de uma etapa adicional de robustez antes de ser tratada como garantia.

Os vídeos reais comparativos ficaram em `data/media/generated/perceptual-experiments/`, incluindo `baseline-current-strength16.mp4`, `adaptive-spread-strength24.mp4`, `adaptive-spread-strength28.mp4` e as variantes DCT. A terceira visualização do Studio (`difference`) não é essa marca entregue: ela é gerada por um controle sem marca reencodado nas mesmas condições, recebe apenas um filtro de diferença/amplificação e é validada contra saturação antes de ser servida.

#### Cache das variantes

O identificador da variante agora incorpora a versão do algoritmo, algoritmo, força, piso da máscara, tamanho da portadora, número de bits/repetições, versão do filtro diagnóstico, caminho do asset, `mtime` da fonte e token. A mudança de qualquer parâmetro produz outro ID; arquivos antigos não são reutilizados. A variante de diferença também é revalidada pelo backend e rejeitada se estiver branca, saturada ou sem amplitude suficiente.

### Testes automatizados

O arquivo `tests/test_watermark_security.py` cobre:

- compatibilidade `CDNWM2` e emissão `CDNWM3` com `content_id`;
- alteração de token, segredo incorreto e versão desconhecida;
- detecção sem original e sem token esperado;
- redução de energia em região uniforme com a máscara perceptual, mantendo `VALID`;
- imagem marcada, blur e imagem sem marca;
- dimensões 20×20 e 64×64 como `INCONCLUSIVE`;
- PNG multipart e Base64 na rota pública de detecção.

O teste existente da demonstração também valida que a diferença gerada não é saturada em branco.

## Pontos de melhoria para aprovação

Estes itens não foram tratados como concluídos sem sua aprovação:

1. Persistir o registro marcador → claim em banco/arquivo de auditoria, com expiração e recuperação após restart.
2. Introduzir `kid`/keyring e rotação de chaves sem invalidar imediatamente claims em voo.
3. Trocar o sincronismo apenas por grade fixa por sincronização geométrica para crop, rotação e pequenas translações.
4. Expandir a matriz de ataques: JPEG de qualidade 20–95, H.264/H.265 em bitrates variados, crop, aspect ratio, frame drop, overlay e regravação de tela.
5. Gerar ROC/precision-recall com milhares de negativos e calibrar os limiares de `NOT_FOUND`/`INCONCLUSIVE`/`CANDIDATE` por família de mídia.
6. Criar detector assíncrono em lote para vídeos longos, com limite de custo e progresso no front-end.
7. Separar segredos por tenant/ambiente e adicionar política de retenção/anonimização para `client_id` e histórico de detecção.
8. Adicionar métricas perceptuais locais (SSIM por janela e, opcionalmente, LPIPS) além do SSIM global simplificado do benchmark.
9. Implementar uma trilha de auditoria assinada para cada detecção, transformação testada e decisão final.

## Limitações declaradas

Este resultado valida o núcleo e os cenários testados; não é uma certificação de robustez contra todos os ataques. O detector depende do segredo backend, o registro é volátil, imagens menores que 128×128 são inconclusivas e ataques geométricos fortes ainda precisam do item 3 da lista de melhorias. O canal visual serve para localizar e associar evidência; a autenticidade continua dependendo do envelope criptográfico.
