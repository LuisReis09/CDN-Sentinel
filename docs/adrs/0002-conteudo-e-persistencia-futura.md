# ADR 0002 — conteúdo e persistência fora da Entrega 2

## Decisão

Manter o estado do protótipo em memória e o conteúdo em fallback determinístico. Expor `ContentProvider` e `VideoCatalog` como pontos de substituição. A instalação não baixa nem consulta o dataset Hugging Face.

## Motivo

Isso mantém a demonstração reproduzível, barata e independente de contas externas. O custo é perder durabilidade e realismo de catálogo, que serão tratados em uma etapa própria.

## Próxima etapa

Um adaptador Supabase/PostgreSQL deverá definir schema, migrações, concorrência, retenção e recuperação. Um adaptador de dataset deverá registrar licença, origem, cache, tamanho e política de reprodução. Nenhum desses adaptadores é considerado implementado agora.
