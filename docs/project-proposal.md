# Proposta original do projeto

**Tema:** Rede Distribuída para Distribuição e Rastreabilidade de Conteúdo Digital  
**Repositório:** [LuisReis09/CDN-Sentinel](https://github.com/LuisReis09/CDN-Sentinel)  
**Disciplina:** Engenharia de Sistemas Distribuídos

## Equipe registrada no repositório de destino

- [Josué Guedes Ferreira](https://github.com/JosueGuedes)
- [Lael Gustavo Batista Ribeiro de Lima](https://github.com/sunny-fellow)
- [Luis Gustavo Lacerda Reis](https://github.com/LuisReis09)

## Resumo

O projeto propõe uma rede de distribuição de conteúdo digital baseada no conceito de *Content Delivery Network* (CDN), voltada à distribuição de imagens e vídeos com mecanismos de rastreabilidade e proteção contra redistribuição não autorizada. Para isso, são incorporadas marcas d’água digitais (*watermarks*) contendo identificadores que permitem associar cada cópia distribuída a um cliente e a uma sessão de acesso.

A solução é dividida em três módulos principais: uma rede de distribuição que disponibiliza conteúdos e insere marcas d’água individualizadas; um cliente simulador de ataque, que obtém o conteúdo e tenta redistribuí-lo; e um serviço observador, responsável por identificar conteúdos correspondentes, analisar a presença das marcas d’água e recuperar os identificadores de rastreamento.

Ao detectar uma redistribuição indevida, o observador notifica a rede de origem, que registra o incidente e identifica o cliente associado à cópia. A implementação atual evolui essa proposta com control plane, edge nodes HTTP independentes, monitoramento, gossip de blacklist, console React e setup Docker Compose.
