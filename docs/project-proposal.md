# Proposta de projeto — CDN-Sentinel

O CDN-Sentinel é um protótipo acadêmico local para tornar observáveis conceitos de Engenharia de Sistemas Distribuídos e Segurança Computacional: roteamento por distância, processos CDN independentes, watermarking forense HMAC, monitores de evidência, blacklist idempotente, gossip HTTP e tolerância a falhas.

## Escopo da Entrega 2

O controlador Flask coordena processos `node_app.py`; cada nó mantém estado local em memória. O frontend React/TypeScript visualiza estado real retornado pela API. Coordenadas e atraso de propagação são um modelo didático, não presença geográfica real.

## Fora do escopo

Não há Supabase/PostgreSQL, dataset Hugging Face, broker, Kubernetes, cloud ou API paga. O fallback de conteúdo é determinístico e local. A integração futura deve respeitar licença, armazenamento e reprodução de vídeos.

## Critério de honestidade

Dados observados vêm de processos e requisições reais. Valores de capacidade, custo e latência geográfica são explicitamente estimativas/modelos. HMAC protege integridade/autenticidade do claim; não cifra vídeo, não é watermark visual robusto e um token pode ser reapresentado fora do protocolo interno anti-replay.
