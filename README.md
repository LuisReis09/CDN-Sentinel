# Proposta de Projeto 

**Tema**: Rede Distribuída para Distribuição e Rastreabilidade de Conteúdo Digital
**Repositório**: 

**Equipe:** 
- [Josué Guedes Ferreira](https://github.com/JosueGuedes)
- [Lael Gustavo Batista Ribeiro de Lima](https://github.com/sunny-fellow)
- [Luis Gustavo Lacerda Reis](https://github.com/LuisReis09)

**Disciplina:** Engenharia de Sistemas Distribuídos  

O projeto propõe o desenvolvimento de uma rede de distribuição de conteúdo digital baseada no conceito de *Content Delivery Network* (CDN), voltada à distribuição de imagens e vídeos com mecanismos de rastreabilidade e proteção contra redistribuição não autorizada. Para isso, serão incorporadas marcas d’água digitais imperceptíveis (*watermarks*), inseridas por meio de pequenas perturbações no conteúdo, contendo identificadores que permitam associar cada cópia distribuída a um cliente e a uma sessão de acesso. A proposta busca explorar conceitos de sistemas distribuídos, como comunicação entre serviços, distribuição de conteúdo, processamento descentralizado e monitoramento, avaliando a viabilidade de uma solução escalável para identificação de possíveis violações de direitos autorais.

A solução será dividida em três módulos principais: 
1. Uma rede de distribuição responsável por disponibilizar os conteúdos e inserir marcas d’água individualizadas; 
2. Um cliente simulador de ataque, que obtém o conteúdo e tenta redistribuí-lo em outras plataformas sem autorização; 
3. Um serviço observador, responsável por identificar conteúdos potencialmente correspondentes aos distribuídos pela rede, analisar a presença das marcas d’água e, quando possível, recuperar os identificadores de rastreamento. Ao detectar uma possível redistribuição indevida, o observador notificará a rede de origem, que poderá registrar o incidente e identificar o cliente associado à cópia. 

Dessa forma, o projeto permitirá demonstrar e avaliar um mecanismo distribuído de rastreabilidade de conteúdo, considerando aspectos como eficiência da detecção, resistência das marcas d’água a alterações e capacidade de operação em diferentes componentes e serviços.