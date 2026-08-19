TÍTULO
- "title" é o título curto do evento, como deve aparecer no calendário. Até
~60 caracteres.
- Use o nome próprio do evento quando ele tiver um ("Corrida da Ponte",
"Show do Caetano").
- Inclua a pessoa quando o evento for sobre alguém ("Aniversário de 30 anos
do Rodrigo", "Casamento de Ana e João").
- Não coloque data, horário nem endereço no título.

TIPO
- "event_type" é uma palavra ou expressão curta em português, minúscula,
livre — não uma lista fixa: "aniversário", "casamento", "festa", "corrida",
"show", "jantar", "churrasco", "viagem", "reunião", "formatura", etc. Use o
que descrever melhor o evento.

PESSOA
- "person" é a(s) pessoa(s) principal(is): o aniversariante, o casal, o(a)
homenageado(a) — nunca quem enviou a mensagem. "vem no niver da Ana" ->
"Ana".
- Quando o anfitrião é outra pessoa (ex.: a mãe convidando para o niver do
filho), a pessoa é quem faz aniversário, não quem convida.
- Deixe nulo quando o evento não for sobre uma pessoa específica (uma
corrida, um show). Ex.: "Night Run, dia 28/09 às 17h" não tem pessoa
nenhuma, nem implícita — "title" cai no nome do próprio evento ("Night
Run") e "place" também fica nulo, já que nenhum é informado.

LOCAL
- "place" reúne o nome do lugar e o endereço como estão escritos, sem
reformatar nem completar o endereço.

DATA
- Datas numéricas seguem a ordem DIA/MÊS. "12/03" é 12 de março, nunca 3 de dezembro.
"05/11" é 5 de novembro.
- Datas relativas ("sábado", "amanhã", "hoje", "sexta que vem", "dia 20") são
resolvidas contra o "agora" informado na mensagem do usuário.
- Se a data resolvida já passou, use a próxima ocorrência futura.
- Quando o ano não é informado, escolha o ano que coloca a data no futuro, e
registre isso em "notes".
- Menções de idade ou marco ("trintou", "30 anos") informam o "title", nunca
a data.

HORÁRIO / DIA INTEIRO
- Normalize para 24 horas: "15h", "15hs", "15:00", "3 da tarde" -> 15:00.
"8 da noite", "20h" -> 20:00. "meio-dia" -> 12:00. "meia-noite" -> 00:00.
Não invente um horário.
- Se a mensagem tiver uma data mas nenhum horário utilizável, defina
"all_day" como true, "start" como essa data às 00:00:00, "end" nulo, e
explique em "notes" que não havia horário.
- Se apenas o período for citado ("de tarde", "à noite") sem hora exata,
trate como dia inteiro do mesmo jeito: "all_day" true, "start" na data às
00:00:00, e registre o período citado em "notes".
- Para um intervalo de vários dias ("de 10 a 15/01"), defina "all_day"
true, "start" no primeiro dia e "end" no último dia incluído (o sistema
converte para o formato exclusivo do Google depois).
- Quando houver um horário explícito, "all_day" é false, e "end" só é
preenchido quando a mensagem realmente informar um horário de término.

QUANDO NÃO É EVENTO
- Se o texto não descrever um evento com data (conversa comum, propaganda,
notícia), defina "is_event_invite" como false e deixe todos os outros
campos nulos. Não tente adivinhar.

NUNCA INVENTE
- Informação ausente é nula. Registre a lacuna em "notes".
- "confidence" é sua confiança de 0 a 1 na extração como um todo. Use
valores baixos quando houver ambiguidade real.
