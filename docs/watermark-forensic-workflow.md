# Fluxo de investigação forense

1. Um operador autorizado envia um vídeo em `POST /api/monitor/investigations` com `multipart/form-data`, campo `file`. Com `CDN_CONTROL_TOKEN` configurado, envie `X-CDN-Control-Token`. São aceitos contêineres de vídeo usuais até 64 MiB, 180 s, 4K e 60 fps. O upload temporário é excluído após a análise.
2. O serviço calcula SHA-256 do arquivo recebido, cria `investigation_id` e chama o detector visual keyed sem fornecer cliente, token ou original esperado.
3. Um `CANDIDATE` visual só avança se o marcador de 48 bits corresponder **exatamente** a uma entrada no ledger para a chave usada. O token CDNWM4 é autenticado e o claim é validado quanto a versão, `kid`, janela histórica, `watermark_id` e algoritmo. Recuperação parcial de bits não escolhe a conta mais próxima.
4. O `content_id` do claim é resolvido no catálogo local. `watermark/content_match.py` compara hashes ordenados de 1 fps, médias de luminância e contraste, com deslocamento inteiro, para impedir transplante simples para outro vídeo. Essa etapa ocorre **depois** da recuperação do marcador; não identifica um título arbitrário de maneira independente. Títulos ausentes, clipes com menos de três frames úteis e comparações fracas ficam inconclusivos.
5. Se as três provas concordam, a resposta contém `PENDING_REVIEW` e `AUTHENTICATED_SESSION`, junto a hashes, IDs, claim verificado e métricas de comparação. Caso contrário, a resposta contém `INCONCLUSIVE` ou `NO_WATERMARK`, sem atribuição. `NO_WATERMARK` não prova ausência de marca em ataques fora do alcance do detector.
6. O ledger grava `INVESTIGATION_COMPLETED` em cadeia HMAC. A rota `POST /api/monitor/investigations/{id}/review` aceita `ACCEPT`, `REJECT` ou `INCONCLUSIVE` e grava `INVESTIGATION_REVIEWED`. `ACCEPT` só é aceito após `PENDING_REVIEW`, não pode ser repetido e não modifica blacklist. O frontend Security Observatory oferece upload e revisão.

Exemplo local (PowerShell):

```powershell
$headers = @{}
if ($env:CDN_CONTROL_TOKEN) { $headers['X-CDN-Control-Token'] = $env:CDN_CONTROL_TOKEN }
curl.exe -X POST -H "X-CDN-Control-Token: $env:CDN_CONTROL_TOKEN" -F "file=@suspeito.mp4" http://127.0.0.1:5000/api/monitor/investigations
```

O exemplo pressupõe arquivo autorizado e serviço local. Em modo demo com token vazio, omita o header. Para preservar cadeia de custódia fora do protótipo, arquive o original recebido e seus hashes em armazenamento controlado; o serviço atual guarda só o digest e metadados, não os bytes.
