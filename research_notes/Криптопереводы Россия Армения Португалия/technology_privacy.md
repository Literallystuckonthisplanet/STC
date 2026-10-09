# Технические свойства приватности и контроля: USDT/USDC, BTC, Lightning, XMR, Zcash, Liquid, ecash, Railgun — матрица и модель угроз (на октябрь 2026)

> Дата сбора: 2026-10-09 (все ссылки проверены через поиск в эту дату, если не указано иное). Многие материалы получены через выдачу поиска, а не через полное чтение страницы: при использовании цифр в итоговом отчёте сохраняйте оговорки.
> Метки надёжности: **[первичн.]** — регулятор/протокол/суд/сам эмитент; **[СМИ]** — отраслевые/деловые СМИ; **[вендор]** — коммерческая заинтересованная сторона (аналитика, кошелёк, биржа); **[блог]** — личный блог/агрегатор низкой надёжности; **[академ.]** — научная статья/препринт.
> Рамка: прозрачность публичного блокчейна в этом исследовании считается **недостатком**. Техническая приватность ≠ юридическая анонимность: KYC на входе/выходе, налоговые и AML-обязанности остаются в силе. Заметки не содержат операционных инструкций по обходу AML/санкционного скрининга.

---

## 1. Что демонстрируемо умеют аналитические фирмы (Chainalysis, Elliptic, TRM, Crystal) и Росфинмониторинг («Прозрачный блокчейн»)? Можно ли отследить Monero (включая статус FCMP++)?

### Takeaway
Для прозрачных сетей (BTC, ETH, TRON и др.) аналитика опирается на кластеризацию адресов (эвристика общего входа и др.) плюс атрибуцию бирж — и это рабочая, судебно используемая технология. Для Monero публичных доказательств «взлома» криптографии нет: задокументированные методы — это сетевой уровень (шпионские/вредоносные узлы, сбор IP и временных меток), вероятностные эвристики по приманкам (decoys) и ошибки кошельков; FCMP++, который устраняет атаки на основе выбора приманок, на 2026-10-09 **не активирован в mainnet** (только stressnet). Публичных доказательств того, что «Прозрачный блокчейн» отслеживает XMR, не найдено.

### Cited Findings
**Прозрачные сети — кластеризация**
- Эвристика общего владения входами (CIOH): если транзакция тратит несколько входов, они считаются принадлежащими одному лицу; Chainalysis Reactor использует её как «Heuristic 1» вместе с поведенческими паттернами и peel chains (по материалам судебного дела Sterlingov) — [criminaldefenseattorneytampa.com, обзор судебных материалов, блог юрфирмы](https://criminaldefenseattorneytampa.com/asset-seizure-asset-forfeiture/cryptocurrency/tracing/heuristic/); [Stout: judicial scrutiny of Chainalysis](https://www.stout.com/en/insights/article/judicial-scrutiny-chainalysis)
- Свидетель Chainalysis в суде заявил, что компания имеет «controls in place to detect CoinJoin» и «может пропускать CoinJoin co-spends» при кластеризации; это показание по конкретному делу, а не публичная методика — [criminaldefenseattorneytampa.com](https://criminaldefenseattorneytampa.com/?p=64195) [блог юрфирмы со ссылкой на суд]
- Академические работы по кластеризации BTC (USENIX Security 2022, Kappos/Meiklejohn и др.) — [UCL discovery, sec22-kappos.pdf](https://discovery.ucl.ac.uk/10206678/1/sec22-kappos.pdf) [академ.]
- Инфраструктура CoinJoin сокращается: zkSNACKs (Wasabi) прекратил работу координатора с 1 июня 2024 г. из‑за «правовой неопределённости»; Samourai Whirlpool закрыт ФБР в апреле 2024 г.; координатор zkSNACKs заменён мелкими координаторами — [блог Wasabi](https://blog.wasabiwallet.io/zksnacks-is-discontinuing-its-coinjoin-coordination-service-1st-of-june/) [первичн.]; [PoPETs 2026](https://www.petsymposium.org/popets/2026/popets-2026-0061.pdf) [академ.]
- Основатели Samourai Wallet приговорены к 5 (Rodriguez, 6 ноября 2025) и 4 (Hill, 19 ноября 2025) годам за сговор с целью ведения нелицензированного денежного перевода; прокуратура заявляла о >$237 млн незаконных средств — [IRS-CI](https://www.irs.gov/zh-hans/compliance/criminal-investigation/founders-of-samourai-wallet-cryptocurrency-mixing-service-sentenced-to-five-and-four-years-in-prison) [первичн.]; [The Block](https://www.theblock.co/post/377937/samourai-wallet-keonne-rodriguez-sentenced-maximum-five-year-term-crypto-mixing-service)
- OFAC исключил Tornado Cash из SDN 21 марта 2025 г. после решения Пятого округа (Van Loon, 26 ноября 2024: неизменяемые смарт‑контракты не являются «собственностью» по IEEPA); Роман Семёнов остался в SDN — [CoinDesk](https://www.coindesk.com/policy/2025/04/05/why-ofac-delisted-tornado-cash); [Steptoe](https://www.steptoe.com/en/news-publications/international-compliance-blog/treasury-department-delists-tornado-cash-following-the-fifth-circuits-decision.html)

**Monero — что известно публично**
- Утечка обучающего видео Chainalysis (опубликовано на Reddit и удалено в сентябре 2024 г.; по описанию записано в августе 2023 г.): компания разворачивает множество собственных узлов Monero в разных локациях/у разных провайдеров, чтобы фиксировать IP‑адреса и временные метки транзакций; Chainalysis отказалась от комментариев — [Cointelegraph](https://cointelegraph.com/news/chainalysis-leak-monero-traceability) [СМИ]; [ForkLog](https://forklog.com/en/?p=16826) [СМИ]; [Decrypt](https://decrypt.co/248728/monero-expert-fact-checks-chainalysis-video-claiming-xmr-transactions-can-be-traced?amp=1) [СМИ]
- Анализ digilol.net (10 сентября 2024): в видео показаны RPC‑логи, по‑видимому, с публичного узла node.moneroworld.com; домен около 2020 г. имел A‑записи на как минимум два узла Chainalysis (#003, #140) — [digilol.net](https://www.digilol.net/blog/chainanalysis-malicious-xmr) [блог, независимый анализ]
- Позиция сообщества: «отслеживание» в видео — корреляция IP с транзакциями через подконтрольные remote‑узлы, а не деанонимизация on‑chain; рекомендация — не доверять случайным remote‑узлам, использовать свой узел или Tor/VPN — [Decrypt](https://decrypt.co/248728/monero-expert-fact-checks-chainalysis-video-claiming-xmr-transactions-can-be-traced?amp=1); [Privacy Guides forum](https://discuss.privacyguides.net/t/leaked-chainalysis-video-about-deanonymizing-monero-users/20843)
- IRS (2020) выдало контракты Chainalysis и Integra FEC до $625 тыс. каждому ($500 тыс. на разработку + $125 тыс. при прохождении тестов) на инструменты трассировки Monero, срок 8 месяцев; публичных результатов не найдено — [Decrypt](https://decrypt.co/43451/irs-1-million-contracts-data-firms-crack-monero) [СМИ]
- CipherTrace (2020) заявлял об инструменте трассировки Monero для DHS; CEO называл это «вероятностной игрой»; сообщество оспаривало — [Decrypt](https://decrypt.co/40284/us-homeland-security-can-now-track-privacy-crypto-monero?amp=1) [СМИ]
- TRM Labs официально: поддержка Monero = **скрининг адресов** на риск (санкции, атрибутированные нелегальные акторы) через Wallet Screening API; «в определённых ситуациях» может помочь с demixing и дать следственные зацепки; исследование TRM о «10 Block Decoy Bug» — ошибке, позволявшей с высокой точностью определять реальный вход в части транзакций; вывод TRM: Monero остаётся одной из самых приватных криптовалют — [TRM coverage: Monero](https://www.trmlabs.com/blockchain-coverage/monero) [вендор]; [TRM blog](https://www.trmlabs.com/resources/blog/the-rise-of-monero-traceability-challenges-and-research-review) [вендор]
- Патент США на «системы трассировки цепочек Monero по порядку входов и выходов» существует (правообладатель в выдаче не указан) — [USPTO 12705622](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/12705622) [первичн., содержание не проверено]
- Möser et al., PoPETs 2018: ~62% входов с ≥1 mixin были вычислимы «цепной реакцией» (в эпоху до обязательных колец/RingCT; 64% входов вообще без mixin); эвристика «новейший вход = реальный» давала ~80% точности — [PoPETs 2018](https://petsymposium.org/popets/2018/popets-2018-0025.php) [академ.]; ответ проекта Monero — [getmonero.org](https://getmonero.org/2018/03/29/response-to-an-empirical-analysis-of-traceability.html) [первичн.]
- Последующая работа (данные до августа 2018): Monero «в основном невосприимчив к известным пассивным атакам» благодаря контрмерам — [arXiv 1812.02808](https://arxiv.org/pdf/1812.02808) [академ.]
- Сетевой уровень: Monero Research Lab (2024) рекомендовал бан‑лист IP предполагаемых шпионских узлов (подменяют peer ID, проксируют несколько узлов через множество IP, «насыщение подсетей»); многие IP совпадают с «LinkingLion», шпионившим за сетью BTC с 2020 г.; в конце 2025 г. узлы переехали из AS LionLink в AS Spruce Creek → бан‑лист v2; список не включается автоматически, ~50% честных узлов его используют — [gist Rucknium (MRL)](https://gist.github.com/Rucknium/76edd249c363b9ecf2517db4fab42e88) [первичн., исследователь MRL]
- ProbeLab (доклад 2026): из >16 тыс. рукопожатий с узлами Monero >81% показывают паттерн несовпадения peer ID, флагнутые узлы ведут к одному провайдеру — [probelab.io talks](https://probelab.io/talks/?year=2026) [доклад, не рецензирован]
- WWW 2024: атака на интеграцию Tor в Monero — внедрение вредоносных onion‑узлов позволяет деанонимизировать транзакции от Tor hidden service‑узлов на сетевом уровне — [ACM DOI 10.1145/3589335.3651487](https://unpaywall.org/10.1145%2F3589335.3651487) [академ.]
- Финское NBI (дело Vastaamo) заявляло о способе отследить Monero; сторонники Monero утверждают, что трассировки XMR не было — [bitcoin.com (ru)](https://news.bitcoin.com/ru/trassirovka-monero-storonniky-privatnoy-kriptovalyuty-otvergayut-utverzhdeniya-finskogo-pravookhranitelnogo-agentstva-o-proryve-v-otslezhivanii/) [СМИ]

**FCMP++ (статус на 2026-10-09)**
- 5 октября 2026 г. форк прошёл **только на stressnet** FCMP++/Carrot (высота 3102800), сборка v0.19.0.0‑beta.3.0 выпущена 25 сентября 2026; дата для mainnet **не назначена**; аудит Trail of Bits 11–22 мая 2026; beta stressnet запущен 6 мая 2026 — [cryptoticker.io (EN)](https://cryptoticker.io/en/monero-fcmp-stressnet-fork-october-2026/) [СМИ; страница не открылась при fetch, данные из выдачи]
- План разработчика (CCS): alpha stressnet → beta stressnet → завершение ревью/аудитов → testnet → mainnet — [CCS j-berman](https://ccs.getmonero.org/proposals/j-berman-4months-full-time-13.html) [первичн.]
- Противоречие: xgram.io и altFINS утверждают, что FCMP++ активирован в Q1/январе 2026 — это противоречит данным разработчиков; считать недостоверным — [xgram](https://xgram.io/en/blog/monero-fcmp) [вендор]; [altFINS](https://altfins.com/screener/xmr-monero) [вендор]

**Росфинмониторинг «Прозрачный блокчейн»**
- Глава РФМ Ю. Чиханчин (2023): система позволяет «двигаться по цепочке» и выходить на отправителя и получателя, мониторинг в 30 криптовалютах; разработана совместно с ВТБ по поручению президента — [The Moscow Times (ru)](https://ru.themoscowtimes.com/2023/11/01/glava-rosfinmonitoringa-zayavil-ob-otslezhivanii-operatsii-rossiyan-s-kriptovalyutoi-a111886) [СМИ]
- Пилот для банков завершён; доступ имеют 5 кредитных организаций; в 2026 г. РФМ с Банком России продолжает интеграцию в национальную антиотмывочную систему; цель — выявлять связи между фиатными и криптооперациями клиентов — [investfuture.ru](https://investfuture.ru/articles/rosfinmonitoring-zavershaet-pilotniy-proekt-prozrachniy-blokcheyn-dlya-bankov-74E254D1330E9D7943258D6F004F47A1) [СМИ]; [SecurityLab](https://www.securitylab.ru/news/556643.php) [СМИ]; [kod.ru, 13.07.2026](https://kod.ru/rosfinmonitoring-za-regulyaciyu-kripty/) [СМИ]
- РФМ называл BTC, ETH и Monero самыми популярными у преступников в РФ — но заявлений о трассировке XMR не найдено — [ForkLog](https://forklog.com/tag/rosfinmonitoring) [СМИ]
- Критика первой версии (2020): анализировала только Bitcoin, без обхода миксеров и идентификации пользователей — «графическая оболочка» над публичными данными о кошельках бирж (мнение автора) — [SecurityLab](https://www.securitylab.ru/blog/company/CABIS/350479.php) [блог]

### Inferences
- Реальная угроза для пользователя XMR сегодня — не on‑chain‑криптоанализ, а: (а) IP/время через remote‑узлы и шпионские P2P‑узлы; (б) KYC‑точки входа/выхода (биржи, обменники); (в) вероятностные эвристики по приманкам до активации FCMP++; (г) ошибки/баги кошельков (как «10 Block Decoy Bug»).
- Для прозрачных сетей (USDT‑TRON/ETH, BTC) аналитика — зрелая индустрия; любые переводы с KYC‑биржей на одном конце связывают личность с графом транзакций ретроспективно и навсегда.
- «Прозрачный блокчейн» по публичным данным — инструмент для банков РФ (скрининг клиентов и связь фиата с криптой), реалистично покрывающий прозрачные сети и атрибуцию бирж; вероятно использует те же эвристики, что и западные вендоры (вывод, не подтверждён).
- Crystal Blockchain: в рамках этого исследования первичных данных о её возможностях по Monero не найдено.

### Gaps
- Нет подтверждения, поставили ли Chainalysis/Integra FEC IRS рабочий инструмент по Monero.
- Нет публичного заявления Elliptic о поддержке/неподдержке трассировки Monero (найдены только общие маркетинговые страницы) — [Elliptic coverage](https://www.elliptic.co/blockchain-coverage.html).
- Нет официального перечня поддерживаемых «Прозрачным блокчейном» активов; нет данных о TRON/USDT‑покрытии (весьма вероятно, но не подтверждено).
- Точная дата активации FCMP++ в mainnet неизвестна.

---

## 2. Стейблкоины USDT/USDC: наблюдаемость, власть заморозки (Tether, Circle, T3 FCU, OFAC), Россия‑связанные блокировки, риск для обычных получателей, сети и комиссии

### Takeaway
USDT и USDC — полностью прозрачные токены на публичных блокчейнах с функцией административной заморозки (blacklist) у эмитента во всех сетях. Tether замораживает масштабно (≈9,6 тыс. адресов / $5,69 млрд по ETH+TRON на 26.07.2026 по BlockSec; >$4,4 млрд по данным самого Tether на апрель 2026), автоматически блокирует адреса из SDN OFAC, снимает заморозку редко (~3,6% адресов). Circle — на порядок реже (~370–500 адресов, ~$110 млн), но по судебным приказам США, включая запечатанные гражданские. TRON — главная сеть USDT‑заморозок и адресного «отравления»; комиссия в TRON после снижения цены энергии (авг. 2025) ≈6,5 TRX (получатель с USDT) / ≈13 TRX (новый получатель) при отсутствии энергии.

### Cited Findings
**Механизм и статистика заморозок Tether**
- BlockSec (на 26.07.2026): Tether внёс в чёрный список 9 597 адресов USDT в ETH и TRON, заморожено $5,69 млрд — [Cointelegraph со ссылкой на BlockSec](https://cointelegraph.com/news/tether-freezes-over-500m-usdt-30-days-blocksec-data-show?rand=351) [СМИ/вендор‑данные]
- BlockSec за 2025 г.: 4 163 уникальных адреса, $1,26 млрд; из них ~$698 млн затем уничтожено (destroyBlackFunds); лишь 3,6% адресов впоследствии исключены из чёрного списка — [BlockSec 2025](https://blocksec.com/blog/1-26-billion-frozen-usdt-blacklisting-on-ethereum-and-tron-in-2025) [вендор]
- 30‑дневный срез BlockSec: 370 адресов, из них 328 в TRON и 42 в Ethereum (дата среза не указана); за 30 дней мая 2026 заморожено >$144 млн — [Cointelegraph](https://regional-front.cointelegraph.com/news/tether-freezes-over-500m-usdt-30-days-blocksec-data-show) [СМИ]
- Tether (апрель 2026): сотрудничество с правоохранителями привело к заморозке >$4,4 млрд, из них >$2,1 млрд по запросам США; 2 300 дел, 340 ведомств, 65 стран — [сводка в выдаче, The Defiant/Pluang](https://pluang.com/en/news-feed/tether-bekukan-aset-lebih-450-juta-usdt) [СМИ; первоисточник Tether не открыт]
- Исследование 2023–2025: ~$3,3 млрд на 7 268 адресах, >2 800 заморозок в координации с DOJ/FBI/Secret Service — [Stablecoin Freezes 2023–2025, AMLBot](https://blog.amlbot.com/stablecoin-freezes-2023-2025-a-data-backed-analysis-of-usdt-usdc-by-amlbot/) [вендор]
- Апрель 2026: Tether в координации с OFAC и правоохранителями США заморозил >$344 млн — [The Defiant](https://thedefiant.io/news/defi/tether-freezes-usd344m-usdt-in-coordination-with-u-s-law-enforcement) [СМИ]
- Политика: Tether проактивно замораживает любой адрес из SDN OFAC без запроса (при запуске политики — все 161 адрес из SDN); для заморозки по запросу правоохранителей не всегда нужен судебный приказ — достаточно верифицированного запроса с официального домена ведомства — [BlockSec compliance guide](https://blocksec.com/blog/usdt-freeze-stablecoin-compliance-guide) [вендор; не удалось открыть страницу, данные из выдачи]; [EMM Legal](https://www.emmlegal.com/news/recover-frozen-usdt-a-guide-to-tether-wallet-freezes/) [юрфирма]
- Судебный иск: 10 адресов заморожены одним пакетом за 2,5 минуты 30.10.2025, а ордер на изъятие, на который ссылается иск, датирован 19.02.2026 (заморозка до ордера) — [The Defiant](https://thedefiant.io/news/regulation/tether-sued-42-million-usdt-freeze-before-seizure-warrant) [СМИ]
- Функция заморозки USDT есть во всех сетях, включая TON (по словам техлида TON Core, янв. 2025) — [ForkLog](https://forklog.com/en/?p=22176) [СМИ]

**T3 Financial Crime Unit (Tether + TRON + TRM Labs)**
- Запущен в авг./сент. 2024 (источники расходятся); на май 2026 заморожено >$450 млн USDT; работа с регуляторами в 23 юрисдикциях; в 2025 г. перехвачено на 43,9% больше, чем ранее — [Blockworks (спонсорский материал)](https://blockworks.com/news/t3-financial-crime-unit-marks-enforcement-victory-usdt-100-million-in-criminal-assets-frozen-across-five-continents); [Yahoo/Cointelegraph](https://www.yahoo.com/news/trons-t3-financial-crime-fighting-120000013.html) [СМИ]

**Circle (USDC)**
- Основания блэклиста (политика CENTRE): угроза безопасности сети; требования законов/приказов уполномоченных органов и судов США или иных государственных органов — [Medium: Circle USDC blacklist implementation](https://medium.com/@j2abro/circle-usdc-blacklist-implementation-8a7bab143a93) [блог‑разбор кода/политики]
- ~372 адреса и ~$109 млн (AMLBot) либо <500 адресов и ~$110 млн (Spark); USDT‑заморозки ≈в 30 раз больше и по числу адресов, и по сумме; у Circle нет механизма burn‑and‑reissue — средства лежат замороженными до юридического решения — [AMLBot](https://blog.amlbot.com/stablecoin-freezes-2023-2025-a-data-backed-analysis-of-usdt-usdc-by-amlbot/) [вендор]; [Spark research](https://www.spark.money/research/stablecoin-blacklisting-sanctions-mechanics) [вендор]
- 23.03.2026 Circle заблокировал 16 кошельков одним пакетом по **запечатанному гражданскому** приказу суда США, без уведомления; ни один не был санкционным/хакерским; среди них — смарт‑контракт моста, что остановило выводы USDC по этому маршруту; к 26.03 разблокирован 1 из 16 — [AMLBot](https://blog.amlbot.com/circle-froze-16-business-hot-wallets-including-a-blockchain-bridge-smart-contract/) [вендор]
- Май 2025: ~$57 млн USDC по гражданскому делу LIBRA; сентябрь 2025: президент Circle говорил об изучении «обратимых» транзакций USDC — [mexc news / сводка](https://www.mexc.com/news/983965) [агрегатор]

**Россия‑связанные заморозки и санкции**
- Март 2025: Tether заморозил ~$26–28 млн USDT на кошельках Garantex (>2,5 млрд руб.); Garantex остановил торги и выводы; домены изъяты США/Германией/Финляндией — [Benzinga](https://benzinga.com/content/44166906/tether-freezes-27-million-in-usdt-on-sanctioned-russian-garantex-crypto-exchange) [СМИ]; [TRM: Grinex](https://www.trmlabs.com/resources/blog/grinex-emerges-as-likely-garantex-rebrand) [вендор]
- Garantex перевёл ликвидность в Grinex (зарегистрирован в Киргизии в дек. 2024); бывшим клиентам начисляли A7A5 (рублёвый стейблкоин Old Vector, Киргизия; связан с платформой A7/Промсвязьбанк) в объёме замороженных балансов — [TRM deep dive](https://www.trmlabs.com/es/resources/blog/garantex-grinex-and-the-a7a5-token-a-deep-dive-into-sanctions-evasion-networks) [вендор]; [Global Ledger](https://blog.globalledger.io/blog/same-garantex-different-sauce.-new-russian-exchange-grinex-launched) [вендор]
- 14.08.2025 OFAC: санкции против основателя/совладельцев Garantex, Grinex, токена A7A5 и связанных структур (включая биржу Meer) — [Cointelegraph](https://cointelegraph.com/news/sanctioned-exchange-garantex-launches-reboot-exchange-grinex) [СМИ]; [The Insider](https://theins.ru/en/news/284078) [СМИ]
- Elliptic: совокупный объём переводов A7A5 превысил $41 млрд к концу июня 2025 — (цитируется в выдаче по [TRM/Elliptic сводке](https://www.trmlabs.com/es/resources/blog/garantex-grinex-and-the-a7a5-token-a-deep-dive-into-sanctions-evasion-networks)) [вендор]
- Апрель 2026: Grinex приостановил работу после взлома на ~$13,7–15 млн, обвинив «враждебные государства» — [The Block](https://www.theblock.co/post/397814/russia-linked-grinex-exchange-suspends-operations-15-million-hack-hostile-states) [СМИ]
- Отдельных публикаций 2026 г. о заморозке Tether адресов, связанных с A7A5/Grinex, не найдено (см. Gaps).
- Binance с 2022 г. ограничила россиян с балансом >€10 000 (режим только вывода) по 5‑му пакету санкций ЕС; 8‑й пакет ЕС (окт. 2022) запретил любые услуги криптокошельков/хранения для российских лиц — [FinanceFeeds](https://financefeeds.com/binance-blocks-russian-accounts-holding-crypto-worth-e10000/) [СМИ]; [Digital Policy Alert](https://digitalpolicyalert.org/change/3596-eighth-eu-sanctions-package-including-prohibition-on-russian-cross-border-crypto-payments) [первичн.‑агрегатор]
- Bybit (2025): реальное время блокировки выводов на адреса, связанные со скамом, + час «остывания»; заморожено $4,32 млн по 335 делам о мошенничестве; работает с TRM, Elliptic, Chainalysis — [пресс‑релиз Bybit](https://www.bybit.com/press/post/bybit-unveils-2025-security-milestone-intercepts-300m-in-impersonalization-scams-and-frauds-via-new-ai-driven-risk-framework-blta3f182b8bbda344e) [первичн./вендор]

**Сети USDT, вывод из обращения, комиссии**
- Tether прекратил погашение USDT на Omni, BCH SLP, Kusama, EOS, Algorand с 1.09.2025; оставшиеся токены подлежали заморозке (на Omni было ~$82,9 млн) — [The Block](https://www.theblock.co/post/362269/tether-to-sunset-usdt-on-five-legacy-blockchains-including-algorand-and-omni); [Cointelegraph](https://cointelegraph.com/news/tether-discontinue-usdt-redemptions-five-legacy-blockchains) [СМИ]
- TRON: Proposal #104 (с 29.08.2025) снизил цену энергии с 210 до 100 sun; перевод USDT на адрес, уже державший USDT, ≈65 000 энергии → ≈6,5 TRX сжигается при отсутствии энергии; на «новый» адрес ≈131 000 энергии → ≈13 TRX; можно арендовать/застейкать энергию — [CoinsDo](https://web.coinsdo.com/en/blog/trc20-fees-explained-energy-bandwidth-usdt-costs) [вендор]; [gasfeesnow](https://gasfeesnow.com/tron/) [агрегатор]. Противоречие: часть источников приписывает снижение Proposal #95.
- GasFree на TRON (оплата комиссии в USDT без TRX): у Klever ~1 USDT активация + ~1 USDT за перевод; CryptoQuant: пример $1,5 комиссии на перевод $16,3K, рекорд недельного объёма GasFree в мае 2026 — [Klever support](https://support.klever.org/hc/en-us/articles/38548067522836-How-to-Send-USDT-Without-TRX-Using-Klever-Wallet-s-GasFree-Feature) [вендор]; [CryptoQuant TRON research (PDF)](https://bucket.cryptoquant.com/applied-research/6a5ed4632cc8ea28f79e1b95/TRON_Research_Beyond_P2P.pdf) [вендор‑аналитика]
- Ethereum L1: перевод USDT ≈65 000 gas → ≈$2,3 при 10 gwei и ETH $3 500, ≈$7 при 30 gwei, >$20 при пиках; Arbitrum ≈$0,01–0,20; Base ≈$0,002–0,10 (нативного USDT на Base, по одному источнику, нет); Polygon PoS ≈$0,001–0,05; TON ≈$0,005–0,01 (после снижения в мае 2026 ~0,00104 TON; газ платится в TON) — [eco.com ERC‑20 guide](https://eco.com/support/en/articles/15210366-usdt-erc-20-network-guide-2026-fees-speed-use-cases) [вендор]; [Spark cost comparison](https://www.spark.money/tools/stablecoin-transfer-cost-comparison) [вендор]; [eco.com TON guide](https://eco.com/support/en/articles/14998909-usdt-on-ton-complete-guide-for-telegram-wallet-users) [вендор]
- Общий объём USDT (2026): оценки расходятся — ~$158–160 млрд (Q2 2026) против ~$190 млрд (апрель 2026) — [Stablecoin Insider Q2 2026](https://stablecoininsider.org/usdt-q2-2026-report-supply-regulation-and-the-two-tier-market/) [СМИ]; [eco.com](https://eco.com/support/en/articles/11819134-tether-usdt) [вендор]
- USDT на TON запущен в апреле 2024; >519 млн USDT на TON в 2024 г. — [The Block](https://www.theblock.co/amp/post/301957/usdt-ton-blockchain-crosses-500-million) [СМИ]

**Ошибки пользователя и мошенничество**
- USENIX Security (ETH и BSC, июль 2022 – июнь 2024): ~270 млн попыток address poisoning против ~17 млн кошельков, ≥6 633 успешных атак, потери >$83,8 млн (нижняя оценка) — [Kerberus со ссылкой на USENIX](https://www.kerberus.com/learn/address-poisoning-attacks-web3-guide/) [вендор, пересказ академ.]
- Декабрь 2025: ~$50 млн USDT потеряны после «пыльной» транзакции с похожего адреса (совпадали первые и последние символы); жертва сначала отправила тестовые 50 USDT — [Cointelegraph](https://cointelegraph.com/news/address-poisoning-copy-paste-mistake-50m-usdt-loss) [СМИ]
- Webacy, сентябрь 2025: 32 290 событий poisoning, 6 516 жертв (ETH ~91%, Polygon ~6,7%, Base ~1,9%; TRON не покрыт) — [Webacy](https://world.webacy.com/from-the-ctos-desk-september-2025) [вендор]
- TRON: 15 инвесторов потеряли $9,4 млн (USDD, не USDT) из‑за address poisoning — [CoinTurk](https://en.coin-turk.com/15-crypto-investors-lose-9-4-million-to-tron-address-poisoning-scam/) [СМИ, дата не установлена]
- Неверная сеть: USDT, отправленный в другую EVM‑сеть на тот же 0x‑адрес, часто восстановим (если ключи у вас или биржа поддерживает возврат); TRC‑20 ↔ ERC‑20 — обычно невосстановим; биржи могут не поддерживать возврат (пример: BEP20 не восстанавливается) — [Bright Side of News](https://brightsideofnews.com/payment/crypto/sent-crypto-to-wrong-network/) [СМИ]; [Bitbuy policy](https://support.bitbuy.ca/hc/en-us/articles/4408736697741) [первичн.]

### Inferences
- Для USDT/USDC «самостоятельное хранение» защищает от банкротства/блокировки посредника, но **не** от заморозки эмитентом: контроль над балансом в конечном счёте у Tether/Circle (и через T3 FCU — у правоохранителей многих стран).
- Риск «случайного» обычного пользователя: прямых данных о массовых заморозках «невиновных» получателей нет; однако (а) Tether замораживает по запросу без судебного приказа и редко снимает блок; (б) Circle замораживал несанкционные бизнес‑кошельки по запечатанному приказу; (в) биржи при депозите проводят скрининг (TRM/Elliptic/Chainalysis), и связь адреса с санкционными сущностями (Garantex/Grinex/A7A5/Meer) может привести к удержанию депозита/запросу источника средств. Это вывод о механизме, а не измеренная частота.
- TRON — сеть, где сосредоточены и рабочие USDT‑платежи из РФ/СНГ, и большинство блокировок Tether (328 из 370 в 30‑дневном срезе), и T3 FCU с участием самого TRON: для данного исследования TRON — сеть с максимальной концентрацией контроля и наблюдения.
- Комиссия TRON в долларах зависит от курса TRX: при 6,5 TRX и цене ~$0,3 — ~$2 (оценка вендора); на новый адрес — вдвое дороже.

### Gaps
- Нет первичного (Tether) документа с полной текущей политикой заморозки и числом адресов на октябрь 2026; BlockSec‑страницы не открылись.
- Не найдено публикаций 2026 г. о заморозке Tether адресов, связанных с A7A5/Grinex, и о судьбе Grinex после апреля 2026.
- Нет исследования address poisoning именно по TRON/USDT за 2025–2026.
- Нет методики, как Binance/Bybit/OKX превращают риск‑скор аналитики в удержание депозита.
- Курс TRX/ETH на 2026‑10‑09 не проверялся → долларовые комиссии приблизительны.

---

## 3. Bitcoin on-chain и Lightning: что видят наблюдатели, LSP, кастодиальные кошельки; комиссии; гео‑ограничения

### Takeaway
On‑chain Bitcoin полностью прозрачен (суммы, адреса, граф), кластеризуется эвристиками, а инфраструктура CoinJoin после 2024 г. резко сократилась под правовым давлением. Lightning скрывает платежи от публичного блокчейна, но открытие/закрытие каналов видно on‑chain, балансы каналов зондируются, а LSP (например, ACINQ для Phoenix) видит сумму и получателя BOLT11‑платежей; кастодиальные кошельки (Wallet of Satoshi в кастодиальном режиме) видят всё. Комиссии on‑chain в 2026 г. исторически низкие (медиана ~1 sat/vB весной 2026).

### Cited Findings
- Медиана on‑chain комиссии BTC в апреле–начале июня 2026 г. — ровно 1,0 sat/vB, верхние 10% ~3 sat/vB в пиковые часы; мемпул 0,18–1,5 MB — [btc.network fee report 26.05–01.06.2026](https://btc.network/blog/bitcoin-fee-report-may-26-june-1-2026) [вендор‑аналитика]
- Зондирование балансов каналов Lightning: платежи со случайным хешем, которые гарантированно проваливаются; различие ошибок позволяет бинарным поиском определить баланс (~10–20 проб на канал) — [Tikhomirov et al., arXiv 2004.00333](https://arxiv.org/abs/2004.00333v1) [академ.]; [ePrint 2021/384](https://eprint.iacr.org/2021/384/20210327:071104) [академ.]
- Межуровневая деанонимизация (Romiti et al.): связь on‑chain адресов с узлами Lightning (открытие/закрытие каналов), атрибуция алиасов и IP; 5 акторов контролировали 36 узлов и >33% ёмкости — [TU Wien PDF](https://www.secpriv.tuwien.ac.at/fulltext/publik_297429.pdf); [arXiv 2007.00764](https://arxiv.org/abs/2007.00764v2) [академ.]
- Phoenix (ACINQ): trampoline‑маршрутизация делегирует поиск маршрута узлу ACINQ → ACINQ узнаёт сумму и получателя BOLT11‑платежей; с BOLT12 + blinded routes получатель скрыт, но BOLT12 поддерживают немногие кошельки; при получении ACINQ знает узел‑получатель Phoenix и сумму (не отправителя); Phoenix↔Phoenix — ACINQ всегда знает обоих и сумму; ACINQ — единственный trampoline‑провайдер — [Stacker News: ответ ACINQ](https://stacker.news/items/864332) [первичн. цитата ACINQ на форуме]
- Phoenix удалил встроенный Tor в начале 2025 г. (нужен отдельный Orbot); убран из магазинов США в мае 2024 после дела Samourai, вернулся 8 апреля 2025; один динамический канал с ACINQ — [Spark: wallet comparison](https://www.spark.money/tools/lightning-wallet-comparison) [вендор]
- Комиссии Phoenix: отправка 0,4% + 4 sat; входящая ликвидность — расхождения (1% + майнинг‑комиссия vs только майнинг‑комиссия при splicing) — [Stacker News](https://stacker.news/items/1540682) [форум]; [Bitcoin Magazine](https://bitcoinmagazine.com/?p=4070) [СМИ]; обычные routing fees — «несколько сат» — [Spark: Zeus vs Phoenix](https://www.spark.money/tools/zeus-vs-phoenix-lightning-comparison) [вендор]
- Wallet of Satoshi: ушёл из US App Store/Google Play в ноябре 2023 (The Block) — [The Block](https://www.theblock.co/post/264585/wallet-of-satoshi-bitcoin-lightning) [СМИ]; блокировал кастодиальный сервис в Испании/Европе — [CriptoNoticias](https://www.criptonoticias.com/tecnologia/wallet-of-satoshi-bloquea-servicio-custodial-espana-europa/) [СМИ]; в июле 2025 запустил режим на базе Spark («самостоятельное хранение») — [Spark news](https://www.spark.money/news/wallet-of-satoshi-spark-partnership) [вендор]; WalletScrutiny продолжает классифицировать WoS как кастодиальный (операторы Spark должны со‑подписывать) — [WalletScrutiny issue #947](https://gitlab.com/walletscrutiny/walletScrutinyCom/-/work_items/947) [независимый аудит]
- Breez в 2025 г. отказался от Greenlight в пользу бэкендов Liquid (swap через Boltz) и Spark; Misty Breez (апр. 2025) — на Liquid — [Spark: Phoenix vs Breez](https://www.spark.money/tools/phoenix-vs-breez-wallet-comparison) [вендор]

### Inferences
- Кто что видит в Lightning: отправитель знает получателя (из инвойса); получатель обычно не знает отправителя; LSP/trampoline‑узел может знать сумму и получателя (Phoenix/BOLT11); кастодиальный кошелёк видит всё + KYC‑данные, если требует; открытие/закрытие канала — on‑chain транзакции, связывающие UTXO пользователя с его Lightning‑активностью.
- Кастодиальный Lightning (WoS‑кастодиальный, биржевые) = худший вариант контроля (заморозка, гео‑блок) при хорошем UX; некастодиальный Lightning (Phoenix и др.) переносит риск на LSP и требует on‑chain комиссий при управлении ликвидностью.
- Spark‑кошельки — новый «полукастодиальный» класс; заявленный односторонний выход не проверен на практике (по WalletScrutiny).

### Gaps
- Доступность Phoenix/Breez/Muun/WoS для пользователей в РФ/из российских аккаунтов App Store в 2026 г. не найдена.
- Нет датированной 2026 медианы routing fee Lightning.
- Нет первичной политики приватности ACINQ (только цитата на форуме).

---

## 4. Monero на практике: приватность против ограничений (делистинги, легальные способы приобретения, кошельки, синхронизация, EU AMLR 2027)

### Takeaway
Monero по умолчанию скрывает отправителя (кольцевые подписи), получателя (stealth‑адреса) и суммы (RingCT) — это единственный из рассмотренных активов с приватностью «по умолчанию» для всех транзакций. Практические ограничения растут: делистинги с Binance (2024), OKX (2024), Kraken (EEA — окт. 2024, Канада — сент. 2025); EU AMLR запрещает CASP работать с «анонимизирующими монетами» (применение с 2027 г.); главная децентрализованная площадка Haveno/RetoSwap пострадала от двух эксплойтов в мае–июне 2026 и приостанавливала торги. Кошельки (Cake Wallet, Feather, Monerujo) активны; MyMonero закрыт в январе 2026.

### Cited Findings
- Binance делистинговала XMR (февраль 2024, после «monitoring tag»); OKX — в январе 2024 вместе с ZEC и DASH — [The Block](https://www.theblock.co/post/276176/binance-delisting-monero) [СМИ]
- Kraken: Ирландия и Бельгия — торги остановлены 10.05.2024, делистинг 10.06.2024; EEA — торги и депозиты остановлены 31.10.2024, выводы до 31.12.2024, остатки автоматически конвертированы в BTC; Канада — торги отключены 02.09.2025, режим только вывода — [Kraken support: Europe](https://support.kraken.com/de/articles/support-for-monero-xmr-in-europe) [первичн.]; [Kraken support: Canada](https://support.kraken.com/pt/articles/notice-of-delisting-xmr-canada) [первичн.]; [The Block](https://www.theblock.co/post/287801/ajames@theblock.co) [СМИ]
- Цифра «73 биржи делистинговали XMR в 2025 г.» повторяется, но первоисточник не найден — [Traders Union](https://tradersunion.com/news/cryptocurrency-news/show/2203917-monero-slides-7-46percent-today-to/) [СМИ низкой надёжности]
- EU AMLR, ст. 79: кредитным/финансовым институтам и CASP запрещено вести анонимные счета или «любой механизм, обеспечивающий усиленную обфускацию транзакций, включая анонимизирующие монеты»; исключение — производители аппаратных/программных некастодиальных кошельков без доступа к ключам; существующие анонимные счета — только после CDD; отбор AMLA для прямого надзора с 1.07.2027 — [Cointelegraph](https://cointelegraph.com/news/eu-crypto-ban-anonymous-privacy-tokens-2027) [СМИ, пересказ EUCI AML Handbook]; [The Defiant](https://thedefiant.io/news/regulation/eu-aml-rules-to-ban-anonymous-accounts-privacy-coins) [СМИ]
- Haveno/RetoSwap: 20.05.2026 уязвимость протокола Haveno позволила выдать себя за арбитра при настройке multisig — похищено ~7 000 XMR (~$2,7 млн); второй эксплойт 16–17.06.2026, торги вновь приостановлены; статус возобновления неясен; фиатные сделки в первом инциденте не пострадали — [ThreatCluster](https://threatcluster.io/cluster/retoswap-hack-exploits-haveno-protocol-vulnerability-36c21fbd) [агрегатор]; [ChainCatcher](https://www.chaincatcher.com/en/article/2271832) [СМИ]; [KuCoin News](https://www.kucoin.com/news/flash/retoswap-users-lose-2-7m-after-haveno-hack) [вендор‑СМИ]
- Кошельки: официальная страница загрузок getmonero.org перечисляет Monerujo (Android), Feather (десктоп, лёгкий), Cake Wallet (мультивалютный, поддержка аппаратных кошельков) — [getmonero.org downloads/community](https://beta.getmonero.org/downloads/community/) [первичн.]; MyMonero закрыт 06.01.2026, пользователи переводятся в Cake Wallet — [блог Cake Wallet](https://blog.cakewallet.com/announcing-mymoneros-sunset-and-stewardship-transition-to-cake-wallet/) [первичн.]
- Remote‑узел vs light‑wallet: кошельки с remote‑узлом (Feather, Cake, GUI) расшифровывают данные локально — узел видит IP (без Tor) и время/паттерн синхронизации, но не view key; light‑wallet (модель MyMonero) отдаёт серверу view key → сервер видит входящие транзакции и суммы (не может тратить) — [Privacy Guides forum](https://discuss.privacyguides.net/t/how-private-is-monero-without-your-own-node/40077?page=2) [форум]
- Вредоносный remote‑узел может подсовывать «отравленные» выходы‑приманки и отслеживать активность — [opb.sepiol: chainalysis attempts](https://opb.sepiol.duckdns.org/opsec/chainalysis-attempts/) [блог]
- TRM (2025/2026) фиксирует повышенную активность XMR несмотря на делистинги — [Cryptopolitan (fr)](https://www.cryptopolitan.com/fr/trm-labs-elevated-xmr-activity-delistings/) [СМИ]

### Inferences
- Легальные регулируемые каналы покупки XMR в ЕС к 2027 г. фактически исчезнут (запрет для CASP); вне ЕС часть азиатских/офшорных бирж ещё может листить XMR, но актуальный подтверждённый список не найден.
- Практическая приватность XMR требует: собственного узла или как минимум Tor/I2P и доверенного узла; удобные мобильные кошельки по умолчанию подключаются к сторонним узлам — это точка утечки IP/времени (именно её эксплуатирует метод из утечки Chainalysis).
- Приобретение XMR через KYC‑биржу или своп из USDT/BTC создаёт on‑chain/учётную запись на входе; приватность внутри сети Monero не стирает эту запись.
- Синхронизация полного узла Monero требует существенного диска/времени (не проверено числом в этом исследовании) — сложность выше, чем у USDT‑кошелька.

### Gaps
- Нет проверенного перечня регулируемых бирж, листящих XMR на октябрь 2026 (в выдаче преимущественно аффилированные блоги, напр. [arnoldnakamura.codeberg.page](https://arnoldnakamura.codeberg.page/monero-exchanges-delisted/) — низкая надёжность).
- Не проверена точная дата применения AMLR (по памяти — 10.07.2027; требует сверки с Official Journal).
- Возобновил ли RetoSwap торги — неизвестно.
- Доступность Cake Wallet/Monerujo в российских App Store/Google Play в 2026 — не найдено.

---

## 5. Другие технологии с реальными преимуществами приватности: Zcash (shielded), Liquid (Confidential Transactions), ecash (Cashu/Fedimint), Railgun

### Takeaway
Zcash shielded даёт сильную криптографическую приватность (скрыты отправитель, получатель, сумма), но только ~26–31% предложения в shielded‑пулах, а в мае–июне 2026 г. в пуле Orchard обнаружена критическая уязвимость фальсификации (исправлена; 28.07.2026 запущен новый пул Ironwood/NU6.3, требуется миграция). Liquid скрывает суммы и типы активов, но это федеративный сайдчейн, а в сентябре 2026 г. пережил взлом на ~4 000 BTC с приостановкой peg‑out. Ecash (Cashu/Fedimint) даёт сильную приватность платежей внутри монетного двора, но это кастодиальная модель с риском потери средств. Railgun — приватность на EVM с «доказательствами невиновности», с умеренной ликвидностью.

### Cited Findings
**Zcash**
- Доля shielded‑предложения: 31,0% (5,16 млн ZEC, Blockworks Q1 2026) vs 26,3% (4,42 млн ZEC, ZEC Stats на 29.06.2026); в начале 2025 ~8–20% в зависимости от трекера; Orchard — 87,6% shielded‑балансов — [Blockworks Q1 2026 (PDF)](https://blockworks.com/api/investor-report/zcash-token-holder-report-q1-2026/pdf) [СМИ‑аналитика]; [The Block](https://www.theblock.co/amp/post/383546/zcashs-shielded-supply-holds-23-privacy-adoption-sticky) [СМИ]
- Уязвимость Orchard: найдена 29.05.2026 исследователем Hornby при аудите с ИИ; «недоограниченный» элемент схемы позволял чеканку неограниченных подделок; присутствовала с мая 2022 до экстренного исправления 1–2.06.2026; криптографически невозможно доказать, что не эксплуатировалась (доказательств эксплуатации нет); ZEC упал на ~30–38% — [The Block](https://www.theblock.co/post/403698/zcash-vulnerability-zec-drops) [СМИ]; [Decrypt](https://decrypt.co/370105/zec-crashes-38-as-zcash-discloses-critical-counterfeiting-vulnerability) [СМИ]
- Ремедиация: софт‑форк 2.06 отключил Orchard; NU6.2 (3.06) восстановил с исправленной схемой; Ironwood (NU6.3) активирован 28.07.2026 на высоте 3 428 143 — Orchard ограничен, выход через «турникет» в Ironwood; на момент активации в Ironwood мигрировало ~40 тыс. ZEC, в Orchard оставалось ~3,6 млн ZEC; пользователям нужно мигрировать через поддерживаемый кошелёк — [The Block](https://theblock.co/post/409934/zcash-ironwood-upgrade-launching-new-shielded-pool-after-orchard-vulnerability) [СМИ]; [zodl.com: Ironwood is live](https://zodl.com/ironwood-is-live-on-zcash/) [первичн.? — статус домена не проверен]
- Zashi (кошелёк ECC) поддерживает Sapling/Orchard и Unified Addresses — [F‑Droid](https://f-droid.org/bo/packages/co.electriccoin.zcash.foss) [первичн.]
- ZEC также подпадает под запрет AMLR для CASP — [Cointelegraph](https://cointelegraph.com/news/eu-crypto-ban-anonymous-privacy-tokens-2027)

**Liquid (Blockstream)**
- Все транзакции по умолчанию используют Confidential Transactions: суммы и типы активов скрыты от наблюдателей, включая функционеров федерации; федерация 11‑из‑15 (другие источники упоминают консорциум ~65 членов) — [BIT knowledge hub](https://www.bit.com/knowledge-hub/liquid-network-hack-2026) [вендор]; [Spark: Liquid deep dive](https://spark.money/research/liquid-network-federated-sidechain) [вендор]
- Сентябрь 2026: ошибка в ПО Elements позволила создать невалидные L‑BTC, которые через ключ peg‑out SideSwap превратились в реальные выводы ~4 000 BTC (~$320 млн); публичные bridge‑узлы отключены, биржам рекомендовано приостановить L‑BTC; атакующие вернули ~3 400 BTC, удержав ~598,5 BTC; USDT на Liquid не затронут; peg‑out приостановлены до подтверждения обеспечения 1:1 — [Crypto Briefing](https://cryptobriefing.com/liquid-network-320m-hack-bitcoin-sidechain/) [СМИ]; [Crowdfund Insider](https://www.crowdfundinsider.com/?p=307251) [СМИ]

**Ecash: Cashu / Fedimint**
- IACR ePrint 2026/2174: Cashu — 31 спецификация, 58 индексированных монетных дворов, 7 совместимых кошельков; все инциденты (включая межмонетную кражу, раскрытую в начале 2026) — «композиционные» (ротация ключей, восстановление кошелька, мульти‑mint), а не в самой криптографии слепых подписей — [IACR ePrint 2026/2174](https://eprint.iacr.org/2026/2174.pdf) [академ., препринт]
- Монетный двор не может связать погашение с выдачей токена (слепые подписи), но при получении через Lightning оператор может идентифицировать получателя и цензурировать входящие; Cashu — единичный оператор; Fedimint — федерация с пороговыми подписями; риски: сговор кворума, «частичное резервирование», регуляторный, цензура шлюза, недоступность; при исчезновении монетного двора токены обесцениваются — [Spark: Cashu vs Fedimint](https://www.spark.money/tools/bitcoin-cashu-vs-fedimint-comparison) [вендор]; [Spark: Fedimint research](https://www.spark.money/research/fedimint-federated-ecash) [вендор]

**Railgun (EVM: Ethereum, Polygon, Arbitrum, BSC)**
- Private Proofs of Innocence: депозиты скринируются по спискам известных вредоносных адресов; подозрительные средства не попадают в privacy set и могут быть выведены только на исходный адрес — [Blockworks](https://blockworks.com/news/defi-privacy-zero-knowledge-proofs) [СМИ]
- Объём: $1,16 млрд с запуска (янв. 2022) по Dune (статья ~2024); TVL в 2026 — «высокие десятки миллионов» (по DeFiLlama, пересказ) — [The Defiant](https://thedefiant.io/news/regulation/railgun-privacy-protocol-surpasses-usd1b-in-volume-amid-crackdown-on-crypto-mixers) [СМИ]; [DEXTools tutorial 2026](https://www.dextools.io/tutorials/what-is-railgun-privacy-protocol-evm-defi-guide-2026-ko) [вендор]
- Railgun опровергал обвинения ФБР в отмывании Lazarus, заявив, что группа была заблокирована PPOI — [FinTelegram](https://fintelegram.com/crypto-privacy-protocol-railgun-denies-fbis-money-laundering-allegations/) [СМИ]

### Inferences
- Zcash: сильная криптография, но (а) малая доля shielded‑пула = меньший набор анонимности; (б) свежий инцидент 2026 г. показывает риск ошибок в сложной ZK‑криптографии и необходимость действий от пользователя (миграция Orchard→Ironwood); (в) переходы transparent↔shielded видны.
- Liquid: приватность сумм, но не графа (адреса/связи видимы), и федеративный контроль + недавний инцидент безопасности; USDT на Liquid эмитируется тем же Tether (функция заморозки — вывод по аналогии, не проверено).
- Ecash: хорошая приватность между пользователями одного mint ценой кастодиального риска; подходит лишь для малых сумм.
- Railgun: приватность USDT/USDC внутри EVM без устранения власти эмитента над токеном; вход/выход в пул видимы; юридическая неопределённость (сравн. дело Samourai/Tornado).
- Все эти технологии значительно сложнее для новичка, чем USDT‑TRON.

### Gaps
- Официальная страница Zcash/ECC/Zcash Foundation по Ironwood не открыта; статус «zodl.com» (возможное переименование Zashi) не проверен.
- Возобновлены ли peg‑out Liquid на 2026‑10‑09 — неизвестно.
- Нет независимых данных 2026 г. об объёме Railgun.

---

## 6. Метаданные кошельков и инфраструктуры: RPC/узлы, IP‑логирование, Telegram Wallet vs TON Space, доступность в магазинах приложений РФ

### Takeaway
Некастодиальный кошелёк ≠ приватный: большинство мобильных кошельков ходят на сервер/RPC разработчика, который видит IP и опрашиваемые адреса. MetaMask через Infura документированно собирает IP и адрес при отправке транзакций. Telegram Wallet — кастодиальный сервис, замораживавший средства российских активистов после их внесения в перечень Росфинмониторинга; TON Space — некастодиальный. Trust Wallet недоступен в российском App Store с 2022 г.; Apple в 2026 г. продолжает удалять приложения, связанные с санкционными российскими компаниями.

### Cited Findings
- Consensys (ноябрь 2022): при использовании Infura как RPC по умолчанию в MetaMask собираются IP‑адрес и адрес кошелька при отправке транзакции («write»); для «read» (проверка баланса) адрес не хранится; при использовании своего узла/другого RPC Infura/MetaMask этих данных не получают — [The Block](https://www.theblock.co/post/189717/consensys-says-it-collects-ip-addresses-of-metamask-users-via-infura) [СМИ]; [Decrypt](https://decrypt.co/115486/infura-collect-metamask-users-ip-ethereum-addresses-after-privacy-policy-update?amp=1) [СМИ]; анализ политики 2026 — [Conduct Atlas](https://conductatlas.com/platform/metamask/metamask-privacy-policy/infura-ip-address-and-wallet-address-collection/) [третья сторона]
- Trust Wallet Privacy Notice (обновлена 22.10.2025): сбор только «строго необходимых» данных; автоматически собираемые технические данные; для self‑custody кошелька не собираются e‑mail и иные персональные данные; более старая версия прямо указывала сбор публичных адресов кошельков — [Trust Wallet Privacy Notice](https://trustwallet.com/privacy-notice) [первичн.]; [tostracker архив](https://tostracker.app/document/trustwallet-privacy) [архив]
- TronLink (Helix Tech Company Limited): листинг App Store — диагностические данные, не связанные с личностью; Chrome Web Store — «не собирает и не использует данные»; текст политики не проверен — [App Store](https://apps.apple.com/app/id1453530188) [первичн.]; [Chrome Web Store](https://chromewebstore.google.com/detail/ibnejdfjmmkpcnlpebklmnkoeoihofec) [первичн.]
- Trust Wallet вернулся в App Store в марте 2022 г., но недоступен для пользователей из РФ — [ForkLog](https://forklog.com/en/trust-wallet-back-on-the-app-store-but-not-for-users-in-russia/amp) [СМИ]
- Apple удалила Yandex Pay из App Store (август 2026) и ряд приложений VK (июнь 2026); Кремль потребовал объяснений — [The Moscow Times](https://www.themoscowtimes.com/2026/08/12/apple-removes-yandexs-payment-service-app-a93464) [СМИ]; [MacTech](https://www.mactech.com/2026/06/25/the-kremlin-wants-to-know-why-apple-has-removed-some-apps-from-the-russian-app-store/amp/) [СМИ]
- Telegram Wallet: в марте 2025 USDT активиста Д. Чебыкина заморожен вскоре после его внесения в перечень «экстремистов и террористов» Росфинмониторинга (служба поддержки сослалась на нарушение пользовательского соглашения); аналогичный случай Л. Гяммера (~$100); Wallet не публикует статистику заморозок, называет блокировки стандартом для кастодиальных сервисов по AML/CFT — [ForkLog](https://forklog.com/en/wallet-explains-its-approach-to-freezing-user-wallets/) [СМИ]
- Кастодиальный «Крипто‑кошелёк» в Telegram vs некастодиальный TON Space с сид‑фразой — [SecurityLab](https://www.securitylab.ru/blog/personal/paragraph/356688.php) [блог]; в США с июля 2025 г. запущен некастодиальный TON Wallet в Telegram для 87 млн пользователей — [Cointelegraph](https://regional-front.cointelegraph.com/news/telegram-launches-native-crypto-wallet-for-87m-us-users) [СМИ]
- Phoenix убрал встроенный Tor (2025) — см. раздел 3 — [Spark](https://www.spark.money/tools/lightning-wallet-comparison) [вендор]

### Inferences
- Кошелёк с RPC разработчика (TronLink, Trust Wallet, MetaMask по умолчанию, Tonkeeper и т.п.) даёт оператору связку «IP ↔ набор адресов ↔ время», даже если он не знает имени; при запросе властей (юрисдикции операторов: США/Сингапур/др.) или утечке это деанонимизирует пользователя. Это вывод о модели, конкретные политики TronLink/Tonkeeper не проверены.
- Кастодиальный Telegram Wallet для жителей РФ сочетает (а) KYC/AML‑контроль оператора, (б) прецеденты заморозки, коррелирующие с перечнями РФМ, (в) возможность заморозки USDT эмитентом — т.е. наихудший профиль контроля среди рассмотренных.
- Риск «приложение исчезнет из магазина» реален для пользователей российских аккаунтов App Store; ключи в некастодиальном кошельке при этом сохраняются (сид‑фраза), но обновления и переустановка становятся проблемой.

### Gaps
- Политика приватности TronLink и Tonkeeper (сбор IP/адресов) не проверена.
- Нет полного списка криптокошельков, недоступных в российских App Store / Google Play на октябрь 2026.
- Нет подтверждённой информации о сотрудничестве Telegram Wallet с властями РФ (только утверждения пострадавших).

---

## 7. Модель угроз «кто что может узнать» и пределы приватности (включая некастодиальные кошельки); сводная матрица

### Takeaway
Ни одна технология не даёт юридической анонимности: KYC на фиатных входе и выходе (биржи, P2P с банковскими переводами, обменники) связывает личность с обоими концами цепочки, а корреляция суммы и времени может связать их даже через приватную сеть. Для прозрачных сетей (USDT, USDC, BTC) любая точка KYC раскрывает всю историю ретроспективно и навсегда; для Monero/Zcash‑shielded раскрывается в основном «вход/выход», а не внутренние переводы — при условии отсутствия сетевых утечек (IP через узлы).

### Cited Findings
- Корреляция IP и времени через подконтрольные узлы — документированный метод Chainalysis для Monero — [Cointelegraph](https://cointelegraph.com/news/chainalysis-leak-monero-traceability)
- Росфинмониторинг цель системы — связывать фиатные операции клиентов банков с криптооперациями — [SecurityLab](https://www.securitylab.ru/news/556643.php)
- Tether/Circle могут заморозить средства на любом адресе, включая некастодиальный — [BlockSec 2025](https://blocksec.com/blog/1-26-billion-frozen-usdt-blacklisting-on-ethereum-and-tron-in-2025); [AMLBot](https://blog.amlbot.com/circle-froze-16-business-hot-wallets-including-a-blockchain-bridge-smart-contract/)
- Биржи используют TRM/Elliptic/Chainalysis для блокировок выводов/депозитов — [Bybit](https://www.bybit.com/press/post/bybit-unveils-2025-security-milestone-intercepts-300m-in-impersonalization-scams-and-frauds-via-new-ai-driven-risk-framework-blta3f182b8bbda344e)
- LSP Phoenix видит сумму и получателя BOLT11 — [Stacker News/ACINQ](https://stacker.news/items/864332)
- Light‑wallet сервер Monero с view key видит входящие и суммы — [Privacy Guides forum](https://discuss.privacyguides.net/t/how-private-is-monero-without-your-own-node/40077?page=2)
- RPC‑провайдер (Infura) видит IP + адрес при отправке — [The Block](https://www.theblock.co/post/189717/consensys-says-it-collects-ip-addresses-of-metamask-users-via-infura)

### Inferences
**Акторы и что они могут узнать (модель угроз):**

| Актор | Прозрачные сети (USDT‑TRON/ETH/TON/Polygon, USDC, BTC) | Lightning | Monero | Zcash shielded / Liquid / ecash |
|---|---|---|---|---|
| Любой наблюдатель блокчейна (бесплатно) | Полная история адресов, суммы, время, контрагенты; балансы | Открытия/закрытия каналов on‑chain; топология публичных каналов; зондирование балансов | Время транзакций, факт и размер транзакции (без сумм), набор колец‑приманок | Zcash: только переходы transparent↔shielded; Liquid: адреса/граф, но не суммы; ecash: ничего (кроме LN/он‑чейн операций mint) |
| Аналитические фирмы (Chainalysis/TRM/Elliptic/Crystal) | Кластеризация + атрибуция бирж → привязка к KYC; риск‑скор адресов | Межуровневая связь узлов с on‑chain; данные от LSP/кастодиалов по запросу | Скрининг адресов (TRM); вероятностные эвристики по приманкам; IP через шпионские/remote‑узлы | Ограниченно; входы/выходы пулов |
| Эмитент стейблкоина (Tether/Circle) | Заморозка любого адреса, уничтожение и перевыпуск (Tether); прямое сотрудничество с правоохранителями >65 стран | — | — | USDT на Liquid — та же власть эмитента (вывод) |
| Сеть/валидаторы (TRON SR, T3 FCU) | TRON участвует в T3 FCU; может участвовать в цензуре по запросу (вывод) | — | — | Федерация Liquid: контроль peg‑in/out, может приостанавливать (сент. 2026) |
| Оператор кошелька/RPC/узла | IP + адреса + время (MetaMask/Infura документировано) | LSP/trampoline: сумма + получатель (BOLT11) | Remote‑узел: IP + время синхронизации; light‑wallet: входящие + суммы | Mint видит LN‑входящие; Fedimint‑гардианы |
| Кастодиальный сервис (Telegram Wallet, биржи, WoS‑кастодиальный) | Всё + KYC; заморозка без эмитента | Всё | Всё | Всё |
| Биржа/обменник на входе/выходе | Личность + адрес/сумма/время → связка с всей историей | Личность + инвойсы | Личность + адрес депозита/вывода | Личность + вход/выход |
| Банк/РФМ («Прозрачный блокчейн») | Связь фиатных операций с адресами; анализ цепочек (по заявлениям) | По данным бирж/банков | Публичных доказательств трассировки нет | Публичных доказательств нет |
| Интернет‑провайдер/оператор связи | Факт использования кошелька/узла, IP‑адреса узлов (если без VPN/Tor) | То же | То же (P2P‑трафик Monero) | То же |

**Сводная матрица (качественная, для отчёта; оценки — вывод из найденных данных):**

| Критерий | USDT‑TRON | USDT‑ETH L1 / Polygon / L2 | USDT‑TON | USDC (ETH/L2) | BTC on‑chain | Lightning (некаст.) | XMR | ZEC shielded | Liquid CT | Ecash (Cashu/Fedimint) | Railgun |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1. Наблюдаемость истории | Полная | Полная | Полная | Полная | Полная | Частичная (каналы on‑chain) | Низкая (суммы/адреса скрыты) | Низкая внутри пула | Суммы скрыты, граф виден | Очень низкая внутри mint | Низкая внутри пула, вход/выход видны |
| 2. Деанонимизация | Высокая (кластеры, KYC, RPC‑IP, poisoning‑маркеры) | Высокая | Высокая | Высокая | Высокая (CIOH) | Средняя (LSP, probing, cross‑layer) | Низкая on‑chain; средняя на сетевом уровне (узлы) | Низкая‑средняя (малый набор, переходы) | Средняя | Низкая для отправителя; получатель через LN виден mint | Средняя |
| 3. Конфиденциальность баланса | Нет | Нет | Нет | Нет | Нет | Частично (зондирование) | Да | Да | Да (суммы) | Да | Да |
| 4. Самохранение / кошельки для новичка | TronLink, Trust Wallet (RPC‑сервер разработчика) | MetaMask, Trust Wallet | Tonkeeper, TON Space; Telegram Wallet — кастод. | MetaMask и др. | Много | Phoenix (LSP ACINQ), Breez; WoS спорно | Cake Wallet, Monerujo, Feather | Zashi | Blockstream App/Green, SideSwap | Только кастод. mint | Railway Wallet и др. (сложно) |
| 5. Централизованный контроль/заморозка | Максимальный (Tether + T3 FCU + TRON) | Tether | Tether (функция заморозки есть) | Circle (по приказам США, реже) | Нет на уровне протокола; биржи | LSP может цензурировать; кастодиалы | Нет на уровне протокола; давление на биржи/AMLR | Нет на уровне протокола; AMLR | Федерация (пауза peg‑out сент. 2026) | Оператор mint | Эмитент токена + PPOI‑фильтр |
| 6. Ликвидность/доступность | Наивысшая для USDT‑P2P в СНГ (вывод) | Высокая | Средняя | Высокая (но ограничена для РФ‑пользователей — вывод) | Высокая | Средняя | Падает (делистинги, AMLR 2027, проблемы Haveno) | Средняя, есть делистинги | Низкая/средняя, после взлома — нарушена | Низкая | Низкая |
| 7. Типичная комиссия | ~6,5 TRX (имеющий USDT получатель) / ~13 TRX (новый) без энергии; GasFree ~1 USDT | L1 ~$2–7+; L2 ~$0,002–0,2; Polygon ~$0,001–0,05 | ~$0,005–0,01 (в TON) | как ETH/L2 | ~1 sat/vB (2026, медиана) | Phoenix 0,4% + 4 sat; маршрутизация — несколько сат | низкая (не проверено числом) | не проверено | не проверено | ~0 внутри mint | газ EVM + сбор протокола (не проверено) |
| 8. Техническая сложность | Низкая (но нужен TRX/энергия) | Низкая‑средняя | Низкая | Низкая‑средняя | Средняя | Средняя | Средняя‑высокая (узел, Tor) | Средняя‑высокая (миграция Ironwood) | Средняя | Средняя | Высокая |
| 9. Риски потери/ошибок | Address poisoning, неверная сеть (TRC20↔ERC20 невозвратно), заморозка | Poisoning (91% событий на ETH, сент. 2025), неверная сеть | Неверная сеть, memo для бирж (вывод) | Poisoning, заморозка | Потеря сида | Потеря сида, зависимость от LSP, принудительное закрытие | Потеря сида; эксплойты DEX (RetoSwap) | Баг Orchard 2026, миграция | Взлом федерации 2026 | Исчезновение mint | Смарт‑контрактный риск |

**Пределы приватности, которые нужно явно указать в отчёте:**
- KYC‑точка на любом конце (биржа, банк при P2P‑оплате, обменник) — главный канал деанонимизации; некастодиальный кошелёк его не устраняет.
- Корреляция суммы и времени: если 1 000 USDT ушли с KYC‑биржи в момент T, а 1 000 USDT (или эквивалент в XMR) пришли получателю в T+Δ, связь вероятностно восстановима даже через приватную сеть, особенно при малом трафике.
- Сетевые метаданные (IP, время подключения, опрашиваемые адреса) у операторов RPC/узлов/LSP.
- Отпечаток кошелька (wallet fingerprinting): особенности форматирования транзакций/комиссий позволяют аналитикам угадывать используемое ПО (общеизвестная практика; в этом исследовании отдельный источник не найден).
- Техническая приватность не отменяет обязанностей декларирования/налогов и не делает операции законными; для резидентов/граждан РФ и пользователей в ЕС действуют санкционные ограничения (8‑й пакет ЕС) и AMLR с 2027 г.

### Gaps
- Количественных данных о частоте блокировок депозитов обычных пользователей из‑за «загрязнённых» монет не найдено.
- Отдельных академических работ 2025–2026 по wallet fingerprinting не искалось/не найдено.
- Комиссии XMR, ZEC, Liquid, Railgun в 2026 г. не проверены числами.
- Возможности Crystal Blockchain и конкретные сети, покрываемые «Прозрачным блокчейном», не подтверждены.
