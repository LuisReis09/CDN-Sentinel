# Modelo de ameaças do watermark forense

## Ativos, atores e confiança

Ativos: mídia original, segredo de emissão, ledger com tokens/claims e dados de cliente, evidências de investigação e histórico de decisões. O cliente recebe a mídia e controla a cópia; um adversário pode reencodar, editar, gravar tela, combinar cópias ou enviar arquivos falsos. Operadores e nós possuem privilégios distintos na arquitetura pretendida, mas o simulador ainda os executa em uma aplicação/control plane e SQLite local. O investigador conhece a chave e o ledger; o espectador não deve conhecer o token.

| Ameaça | Controle implementado | Limite restante |
|---|---|---|
| Recuperação de identidade pelo data plane | MP4/JSON sem token e sem claim; marcador pseudônimo | API didática de verificação e segredo demo exigem deployment isolado e controle de acesso |
| Falsificação de claim | CDNWM4 AES-GCM + HMAC com subchaves HKDF, `kid`, nonce aleatório | Chaves em configuração/processo, sem KMS ou rotação distribuída |
| Colisão de marcador | Unicidade SQLite e rejeição de colisão | 48 bits insuficientes para grande escala; probabilidades de aniversário crescem rapidamente |
| Transplante do sinal para outro título | Comparação ordenada com título alegado antes de `PENDING_REVIEW` | Matcher simples de 1 fps, sem identificação independente do catálogo ou limiares calibrados |
| Reencode, resize, blur | QIM2 e extração de múltiplos frames | Exatidão variou nos três clipes; crop, rotação, HDR, screen recording real não aprovados |
| Corte temporal, troca de FPS | Até 24 frames agregados e matcher com deslocamento inteiro | Sem alinhamento temporal geral; trechos muito curtos ficam inconclusivos |
| Colusão de duas ou mais sessões | Protótipo de simulação Tardos | Não integrado, sem acusação estatisticamente defensável |
| Falsa atribuição por candidato visual | Exige marcador exato, registro, claim válido e conteúdo compatível | Há risco residual de coincidência, erro de matcher e acesso indevido ao ledger |
| Alteração do ledger | Hash do claim, HMAC de sessão e cadeia HMAC de eventos | Administrador com banco e chave pode reescrever a história; sem âncora externa imutável |
| Acesso indevido ao upload e revisão | `CDN_CONTROL_TOKEN` protege POST quando configurado; upload limitado; revisão não bane | Sem RBAC, rate limiting, retenção e política de privacidade; sem token o modo é demo local |

O watermark vincula uma cópia a uma **entrega**, não prova que o titular da conta publicou o vídeo. O relatório mostra `AUTHENTICATED_SESSION` somente quando marcador, claim e conteúdo alegado concordam. Uma revisão `ACCEPT` apenas registra decisão; ações punitivas exigem processo externo explícito. A palavra “autenticado” não afirma certeza estatística universal do detector visual ou da comparação de conteúdo.

Para uso real, separar segredos por ambiente e finalidade, isolar ledger, autenticar papéis, limitar requisições, ancorar eventos em armazenamento imutável, criar retenção/backup, calibrar falsos positivos e conduzir teste adversarial e revisão jurídica.
