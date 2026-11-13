# Ferramentas de IA utilizadas

## Revisão de 12/11/2026

Codex auxiliou na implementação de estados forenses, autenticação, testes, CI e inspeção crítica. A decisão sobre uso operacional, a avaliação científica com datasets independentes, a revisão do PR e a validação humana permanecem responsabilidades humanas. Nenhuma resposta humana foi simulada para o estudo perceptual. O estado técnico verificável está no [checklist de fechamento](watermark-finalization-status.md).

## Ferramenta

- **ChatGPT/Codex (OpenAI):** usado nesta revisão da Entrega 2.

## Onde atuou

- leitura e síntese das especificações do professor;
- auditoria do repositório contra os itens da Entrega 2;
- redação dos C4, ADRs, justificativas de stack, padrões, checklist e roteiro;
- criação dos artefatos Docker Compose, Dockerfiles, Nginx e workflow de CI;
- sugestão de comandos de validação e execução dos testes/builds.

## Como foi orientada

A ferramenta recebeu o PDF fornecido pelo grupo, o código existente no repositório e a instrução de conferir cada exigência da Entrega 2, dockerizar o projeto e validar com terminais até obter um resultado funcional. As decisões foram limitadas ao escopo de documentação inicial, setup e correções necessárias para a execução.

## Avaliação honesta

O uso foi útil para transformar os requisitos em uma matriz verificável e preencher a documentação ausente. A implementação existente foi preservada quando os testes e o build já passavam. A configuração Docker, o Makefile e os smoke tests são a fonte de verdade para a execução. Nenhum artefato gerado automaticamente deve ser tratado como prova de que a apresentação, a divisão nominal do grupo ou o histórico de commits já estão completos: esses pontos precisam ser confirmados pela equipe.

## Reengenharia forense de 2026-11-11

Codex auxiliou na auditoria da branch `feat/watermark-e2e-forensics`, implementação dos módulos de claim/ledger, QIM2, HLS A/B e investigação, alterações de interface, scripts de benchmark, testes e documentos científicos. Os resultados numéricos citados nos relatórios vieram da execução local dos scripts e estão identificados por fonte, parâmetros e limitações. Codex não executou estudo de percepção com pessoas nem validou a licença dos clipes do dataset. A equipe deve revisar o código, repetir os experimentos e aprovar qualquer uso real ou decisão administrativa.
