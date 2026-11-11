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
  └─ localizador visual keyed de 48 bits
       ├─ sincronização de 32 bits
       ├─ repetição 3x
       ├─ portadora de baixa frequência
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
| `VALID` | O marcador foi associado a um token registrado (exato ou por correção única de até 2 bits), e HMAC, AES-GCM, tag e campos do claim foram verificados. |
| `INVALID` | Houve candidato, mas não há claim registrado ou o claim não corresponde ao marcador recuperado. |

O detector visual não usa a imagem original, uma imagem de referência ou um token esperado. A confiança visual localiza uma possível marca; a decisão de segurança é feita pelo token autenticado no backend.

Para absorver erros pontuais de H.264, o backend procura uma associação única a até 2 bits de distância Hamming entre os marcadores registrados. Se houver empate, nenhum claim é escolhido. Essa correção é somente uma etapa de associação; o token ainda precisa passar integralmente por HMAC e AES-GCM.

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

O marcador é `SHA-256(token)[:12]`, ou 48 bits. Ele não substitui HMAC/AES-GCM e não carrega o claim completo.

Para cada imagem com pelo menos 128×128 pixels:

1. a imagem é convertida para luminância;
2. uma grade 16×16 é endereçada por uma permutação determinística derivada do segredo;
3. 32 bits de sincronização e 48 bits de dados são repetidos três vezes, ocupando 240 das 256 células;
4. cada célula recebe uma portadora pseudoaleatória de baixa frequência, com sinal positivo ou negativo conforme o bit;
5. a alteração é aplicada proporcionalmente aos canais RGB, preservando o alpha;
6. o detector reproduz as portadoras com o segredo, calcula a correlação e vota nas repetições.

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
| PSNR da imagem marcada | 30.6236 dB |
| SSIM global simplificado | 0.928820 |
| Detecção marcada | `VALID`, marcador correto |
| JPEG qualidade 80 | `VALID`, marcador correto |
| Blur raio 1 | `VALID`, marcador correto |
| Redimensionar para metade e voltar | `VALID`, marcador correto |
| Candidatos falsos em 32 imagens aleatórias | 0 |
| Taxa de candidato falso | 0.0 |
| `VALID` falso após registro criptográfico | 0 |
| Tempo de embedding medido | 66.675 ms |

O fixture original sem marca retornou `INCONCLUSIVE`, não `VALID`: a correlação parcial não foi aceita como claim. Nos 32 negativos aleatórios, 18 foram `NOT_FOUND` e 14 `INCONCLUSIVE`; nenhum foi candidato visual, e nenhum foi validado criptograficamente.

### Benchmark de vídeo

Foi gerado um MP4 local de 320×180 com força visual de vídeo 16. A avaliação foi feita sobre amostras H.264 e não reutilizou a imagem original para detectar a marca:

| Transformação | Resultado | Bits corretos |
|---|---|---:|
| controle marcado | sobreviveu | 48/48 |
| original sem marca | não sobreviveu | — |
| blur leve | sobreviveu | 48/48 |
| ruído leve | sobreviveu | 48/48 |
| escala + reencode | sobreviveu | 48/48 |
| escala de cinza | sobreviveu | 48/48 |

Na função de robustez, os casos positivos aparecem como `CANDIDATE` porque ela mede o canal visual antes da associação ao registro; pela rota da CDN, o token emitido é registrado e o mesmo marcador pode resultar em `VALID`.

### Testes automatizados

O arquivo `tests/test_watermark_security.py` cobre:

- compatibilidade `CDNWM2` e emissão `CDNWM3` com `content_id`;
- alteração de token, segredo incorreto e versão desconhecida;
- detecção sem original e sem token esperado;
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
