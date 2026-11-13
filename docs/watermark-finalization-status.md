# Fechamento da auditoria forense — 12/11/2026

Base remota conferida com `git fetch origin --prune`: `codex/forensic-watermark-reengineering` em `11d213a913099138c89e00bfd96cec17e6d83ff7` e `main` em `1bf2b8aabd574cf67f0031b478544a20ca66873e`. A `main` é ancestral da branch auditada. Esta etapa usa `codex/forensic-watermark-finalization`; nenhuma alteração foi feita diretamente na `main`.

## Contrato implementado nesta etapa

- O detector retorna `VALID`, `CANDIDATE`, `INCONCLUSIVE`, `NOT_FOUND` ou `ERROR`. Resultados desconhecidos não se convertem em ausência. A investigação promove somente um `VALID` com claim autenticado e conteúdo compatível a `PENDING_REVIEW`; `CANDIDATE`, `INCONCLUSIVE`, `NOT_FOUND` e `ERROR` permanecem distintos. O resultado bruto vai para o evento assinado e para a resposta. A revisão registrada retorna estado `REVIEWED` sem blacklist.
- `CDN_AUTH_MODE=secure` exige `CDN_SECRET_KEY`, `CDN_VIEWER_SESSION_SECRET` e `CDN_OPERATOR_ACCOUNTS` no backend. Contas têm papel `operator`, `investigator` ou `reviewer` e senha PBKDF2-SHA256. O login cria cookie opaco HttpOnly, Secure e SameSite Strict por 15 minutos, vinculado ao User-Agent, com revogação no logout. Mutações exigem CSRF. GETs administrativos e forenses exigem sessão. Rotas de mídia exigem o bearer temporário de espectador, vinculado a cliente, conteúdo e simulação. Há limites em memória para login e processamento. A UI não contém `VITE_CONTROL_TOKEN`.
- `CDN_AUTH_MODE=local` é o modo acadêmico. O processo Python escuta apenas em `127.0.0.1` por padrão e recusa bind em todas as interfaces sem `CDN_LOCAL_BIND_ACK` explícito; o Compose fornece essa confirmação dentro do contêiner, mas publica backend e frontend apenas em `127.0.0.1` no host. O antigo `CDN_CONTROL_TOKEN` permanece para clientes de teste e scripts locais, mas não é inserido no frontend.
- Novos claims QIM2 declaram `visual-marker-48-uncoded-v1`; o spread declara `visual-marker-48-secded-hamming-13-8-v1`. Claims históricos com o rótulo incorreto continuam verificáveis. O QIM2 continua **sem correção ECC**. A classe Reed-Solomon existente detecta corrupção, mas ainda não corrige símbolos.
- O Studio identifica explicitamente a demonstração CDNWM3 como legada. `VALID` ali não comprova atribuição CDNWM4. O avanço de quadro usa FPS sondado do arquivo, sem assumir 30 FPS. O helper legado `get_video_chunk` rejeita números acima de zero; o Studio lê um asset integral por uma função com nome correspondente.
- O CI instala FFmpeg e confere FFprobe e codecs antes da suíte.

## Checklist da auditoria

| Item | Estado | Evidência ou bloqueio |
|---|---|---|
| P0.1 estados forenses | Corrigido nesta etapa | Testes de ausência, inconclusão, candidato, resultado desconhecido, falha, autenticação e revisão |
| P0.2 credencial e RBAC | Parcial | Bundle sem token; sessão, papéis, CSRF e rate limit locais. Falta provedor de identidade de espectadores e armazenamento compartilhado de sessões/limites |
| P0.3 ECC | Parcial | Metadados agora honestos; QIM2 e RS continuam sem correção efetiva |
| P0.4 Studio | Parcial | Rótulo legado corrigido; emissão CDNWM4/QIM2, VideoSeal e PixelSeal não foram integrados ao Studio |
| P0.5 tempo e diferença | Parcial | Avanço usa FPS real; normalização CFR/VFR e residual puro ainda ausentes |
| P0.6 robustez visual | Pendente | Sem nova calibração multigênero ou melhoria comprovada de crop/blur/resize |
| P1.1 VideoSeal e PixelSeal | Pendente | Nenhum checkpoint carregado nem modelo executado neste ambiente |
| P1.2 contrato de chunk | Corrigido nesta etapa | `get_video_chunk(n>0)` falha explicitamente; entrega temporal permanece no HLS |
| P1.3 atribuição e entrega HLS A/B | Pendente | Playlists e segmentos existem, mas não há recuperação forense confiável de sequência curta |
| P1.4 anti-colusão | Pendente | Simulador Tardos isolado, sem atribuição real |
| P1.5 busca de conteúdo sem claim | Pendente | Comparação atual usa conteúdo declarado pelo claim |
| P1.6 cadeia de custódia | Pendente | Upload original não é preservado em repositório controlado |
| P1.7 ledger distribuído | Pendente | SQLite local, sem backend compartilhado e ancoragem externa |
| P1.8 revisão | Parcial | Identidade vem da sessão; concorrência entre processos e histórico de reanálises seguem pendentes |
| P1.9 identificador longo | Pendente | 48 bits mantidos, sem medição que justifique ampliação |
| P1.10 codecs e desempenho | Pendente | Sem matriz temporal e de codecs completa |
| P1.11 compatibilidade | Parcial | Testes de simulação, gestão, rede e E2E continuam passando; sem auditoria completa de todos os contratos |
| 2.1 CI | Parcial | Correção FFmpeg preparada; aprovação do GitHub Actions ainda obrigatória |
| 2.2 benchmark e estudo humano | Pendente | Sem dataset separado para desenvolvimento, calibração e teste final; sem participantes humanos |
| 2.3 E2E completo | Parcial | Teste existente cobre dois clientes, MP4 recodificado, investigação e revisão; busca independente, HLS A/B e negativos exigidos faltam |
| 3.1–3.4 PR e merge | Bloqueado | P0 e critérios experimentais pendentes impedem merge seguro |

## Arquitetura e limites

No fluxo MP4, o nó emite um claim CDNWM4 cifrado e autenticado, grava no ledger SQLite, insere um marcador visual de 48 bits por QIM2 em resolução adequada ou spread em vídeo menor, e entrega mídia sem token no cabeçalho. O detector tenta recuperar o marcador, consulta associação **exata** no ledger, verifica o claim e compara a mídia ao conteúdo indicado pelo claim. Uma correspondência produz `PENDING_REVIEW`, não sanção automática. Atribuição técnica não prova quem operava a conta. O HLS A/B é experimental e não deve gerar atribuição punitiva.

O backend seguro é apropriado apenas para **uma instância de API** atrás de HTTPS e de um proxy de mesma origem. Sessões e limites em memória se perdem em reinício e não são compartilhados entre workers. A sessão de espectador é emitida após autenticação da conta fora deste aplicativo. O cookie reduz replay por expiração, revogação e vínculo ao User-Agent, mas um cookie roubado ainda pode ser reutilizado no mesmo contexto até ser revogado ou expirar. O segredo do ledger e a base sob o mesmo administrador não produzem imutabilidade forte.

## Validação disponível

- `python -m compileall -q app.py controllers routes services tests utils watermark`: passou.
- `python -m unittest discover -s tests -v`: 60 testes passaram em 114,090 s na segunda execução completa. Depois dela, um teste adicional de resultado de comparação desconhecido foi incluído; `python -m unittest tests.test_forensic_states tests.test_operator_auth tests.test_video_contract -v` passou com 8 testes em 1,150 s. A suíte completa precisa ser reexecutada no CI do PR.
- `npm.cmd run build`: passou; aviso de bundle maior que 500 kB.
- `docker compose config --quiet`: passou; aviso local de leitura de configuração Docker, sem falha de validação.

Ensaio exploratório adicional: `python tools/forensic_benchmark.py --input data/media/bigbuckbunny.mp4 --seconds 2 --mode quick --algorithms adaptive-spread qim2 --output data/runtime/final-benchmark.json`. O JSON de esquema 2 registra `git_dirty=true`, hash SHA-256 da fonte e um controle H.264 com os mesmos parâmetros. Resultado de **um único clipe de 2 s**, sem inferência estatística:

| Algoritmo | PSNR vs. controle | Limpo | H.264 CRF23 | Resize 75% | Blur leve |
|---|---:|---:|---:|---:|---:|
| Adaptive Spread | 28,4475 dB | 0/1 exato | 0/1 | 0/1 | 0/1 |
| QIM2 | 37,8351 dB | 1/1 exato | 1/1 | 1/1 | 1/1 |

As colunas SSIM e MS-SSIM do experimento antigo eram aproximações globais; o esquema 2 usa os nomes `ssim_global_approx` e `ms_ssim_global_approx`. Não há SSIM de janela, MS-SSIM correto, VMAF, LPIPS ou estudo humano nesta etapa. Os resultados não alteram o estágio experimental dos algoritmos.

Os números de robustez de três clipes e 256 negativos em [watermark-benchmark-results.md](watermark-benchmark-results.md) são **históricos**. Eles não validam taxa de falso positivo de produção, imperceptibilidade humana ou superioridade de algoritmo. A [implementação oficial do VideoSeal](https://github.com/facebookresearch/videoseal) oferece VideoSeal e PixelSeal, mas a disponibilidade pública do código não constitui execução comparativa neste projeto.

## Decisão de integração

O merge permanece bloqueado enquanto ECC efetivo, Studio forense, robustez, E2E autenticado completo e CI do PR não estiverem aprovados. Nenhum resultado experimental deve ser promovido a atribuição automática para satisfazer um check. A branch e o PR podem ser mantidos em draft para revisão das correções concretas já feitas.
