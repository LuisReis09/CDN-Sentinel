# ADR-0002: watermark forense baseada em HMAC-SHA256

- Status: aceito
- Data: 2026-11-05
- Decisores: equipe do projeto

## Contexto

O monitor precisa identificar cliente, servidor, instante e chunk de uma cópia vazada, detectar adulteração da prova e manter o claim confidencial enquanto ele viaja junto ao conteúdo.

## Decisão

Emitir tokens `CDNWM2.<nonce+ciphertext+tag-base64url>.<assinatura-hex>`. O claim contém `client_id`, `server_id`, `issued_at` e `chunk_id`; ele é cifrado com AES-256-GCM e o envelope é assinado com HMAC-SHA256 por uma chave mantida no backend. O token é prefixado ao chunk para extração e descriptografia durante a simulação. O Watermark Studio usa o digest do mesmo claim para gerar 64 bits de sinal de luminância em frames reais do Big Buck Bunny e mede a recuperação em amostras MP4 H.264 transformadas.

## Consequências

- O monitor consegue validar integridade e atribuir a origem sem expor a chave ao navegador.
- A cifra protege o claim, não transforma todo o vídeo em um canal secreto; o canal visual experimental também não é uma garantia de robustez contra re-encode de produção. A tela mede explicitamente `bits_correct / bits_total` em amostras reais de blur, ruído, resize e diferentes CRFs.
- Rotação de chaves, KMS/Vault e watermark de produção ficam como evolução; o protótipo mantém uma chave configurável por variável de ambiente.
