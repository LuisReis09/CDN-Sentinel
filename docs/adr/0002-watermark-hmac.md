# ADR-0002: watermark forense baseada em HMAC-SHA256

- Status: aceito
- Data: 2026-11-05
- Decisores: equipe do projeto

## Contexto

O monitor precisa identificar cliente, servidor, instante e chunk de uma cópia vazada, além de detectar adulteração da prova. O projeto não precisa cifrar o vídeo para demonstrar autenticidade do claim.

## Decisão

Emitir tokens `CDNWM1.<payload-base64url>.<assinatura-hex>`. O payload contém `client_id`, `server_id`, `issued_at` e `chunk_id`; a assinatura é HMAC-SHA256 calculada com uma chave mantida no backend. O token é prefixado ao chunk para extração durante a simulação. O Watermark Studio usa o digest do mesmo claim para gerar 64 bits de sinal de luminância em frames reais do Big Buck Bunny e mede a recuperação após transformações.

## Consequências

- O monitor consegue validar integridade e atribuir a origem sem expor a chave ao navegador.
- HMAC não cifra o vídeo e o canal visual experimental não é uma garantia de robustez contra re-encode de produção; a tela mede explicitamente `bits_correct / bits_total` no primeiro frame após blur, ruído determinístico e quantização.
- Rotação de chaves, KMS/Vault e watermark de produção ficam como evolução; o protótipo mantém uma chave configurável por variável de ambiente.
