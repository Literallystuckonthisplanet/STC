# Португалия / ЕС: правовой и практический режим криптопереводов и конвертации в/из EUR для частных лиц (с фокусом на граждан РФ, резидентов РФ и средства из РФ)

Дата проверки всех пунктов: 2026-10-09 (если не указано иное). Ограничение метода: в этой сессии прямое открытие страниц (WebFetch/curl) было заблокировано прокси (DNS/403), поэтому все выводы опираются на поисковые выдержки из юрфирм, СМИ и страниц провайдеров. Официальные ссылки EUR-Lex / Banco de Portugal / CMVM / AT приводятся как адреса для сверки, но их текст в этой сессии напрямую не открывался — это помечено. Статусы: [В СИЛЕ] — применяется; [ПРИНЯТО, НЕ ПРИМЕНЯЕТСЯ] — принято, но дата применения в будущем; [ПРОЕКТ] — предложение; [НЕ ПОДТВЕРЖДЕНО] — один/вторичный источник или конфликт источников.

Ориентир по сумме: 50–200 тыс. RUB в месяц — это порядка нескольких сотен — ~2 тыс. EUR в месяц (курс не проверялся в этой сессии; пересчитать по курсу ЕЦБ на дату отчёта). Верхняя часть диапазона пересекает порог 1 000 EUR из TFR для самостоятельных кошельков (см. раздел 3).

## 1. MiCA (Регламент (ЕС) 2023/1114): авторизация CASP, переходный период в Португалии, компетентные органы, кто авторизован

### Takeaway
[В СИЛЕ] Режим CASP по MiCA применяется с 30.12.2024; в Португалии переходный (grandfathering) период для VASP, зарегистрированных в Banco de Portugal, закончился 1 июля 2026 г. — с этой даты легально оказывать криптоуслуги жителям Португалии может только CASP с полной авторизацией MiCA (португальской или паспортизованной из другой страны ЕС). Компетентные органы по закону Lei 69/2025 — Banco de Portugal (авторизация/пруденциальный надзор CASP, EMT/ART) и CMVM (поведенческий надзор).

### Cited Findings
- Португалия использовала максимальный переходный период: VASP, зарегистрированные в Banco de Portugal на 30.12.2024 и начавшие деятельность, могли работать до решения по заявке или до 1 июля 2026 г. (что раньше); механизма продления нет — [Sérvulo & Associados](https://www.servulo.com/en/knowledge/End-of-the-MiCA-Regulation-transitional-period-immediate-implications-for-CASPs/9810/); [Zyphe](https://www.zyphe.com/resources/news/mica-transitional-period-ends-july-2026); [DLA Piper, 22.12.2025](https://www.dlapiper.com/insights/publications/2025/12/legal-alert-portugal-implements-laws-on-crypto-assets-and-transfer-of-funds-regulations)
- Закон об исполнении MiCA в Португалии — Lei 69/2025, опубликован 22.12.2025; назначает Banco de Portugal и CMVM компетентными органами, распределяет полномочия, вводит режим административных правонарушений. Один источник даёт дату 1.12.2025 — расхождение — [DLA Piper](https://www.dlapiper.com/insights/publications/2025/12/legal-alert-portugal-implements-laws-on-crypto-assets-and-transfer-of-funds-regulations); [Cuatrecasas](https://www.cuatrecasas.com/en/spain/finance/art/law-mica-regulation-portugal); [Abreu Advogados](https://abreuadvogados.com/en/conhecimento/publications/mica-in-portugal-highlights-of-the-new-implementing-law/)
- Распределение ролей: большинство источников — Banco de Portugal выдаёт авторизацию CASP и ведёт пруденциальный надзор, также надзирает за публичными предложениями ART/EMT; CMVM — поведенческий (conduct) надзор и мнение по заявкам. Один практический гайд называет лицензирующим органом CMVM со ссылкой на «Lei 27/2024» — это выглядит ошибкой (выброс) — [Chambers Fintech 2026 Portugal](https://practiceguides.chambers.com/practice-guides/fintech-2026/portugal/trends-and-developments); против: [cryptolawindex](https://cryptolawindex.com/knowledge/portugal-cmvm-casp-practitioner-guide-2026/)
- ESMA 23.06.2026 выпустила публичное заявление об окончании переходного периода: неавторизованные фирмы должны упорядоченно сворачивать деятельность в ЕС; принимающий CASP при переводе клиентов обязан провести полный онбординг — [Zyphe](https://www.zyphe.com/resources/news/mica-transitional-period-ends-july-2026); [Sérvulo](https://www.servulo.com/en/knowledge/End-of-the-MiCA-Regulation-transitional-period-immediate-implications-for-CASPs/9810/)
- Bison Bank (Лиссабон) — первый CASP по MiCA в Португалии (через слияние с дочерней Bison Digital Assets, одобренное Banco de Portugal); Lusa от 22–23.06.2026, пресс-релиз от 29.07.2026 («первый банк в Португалии, работающий напрямую как CASP»); ориентирован на институциональных клиентов; выпускает EMT EUB и USB — [Portugal Global](https://portugalglobal.pt/pt/noticias/2026/junho/bison-bank-e-o-primeiro-prestador-de-servicos-de-criptoativos/); [Cryptobriefing](https://cryptobriefing.com/bison-bank-portugal-mica-crypto-license/); [Gettex](https://www.gettex.de/en/news-overview/newsdetail/bison-bank-becomes-portugals-first-mica-regulated-crypto-asset-service-provider/) [НЕ ПОДТВЕРЖДЕНО по реестру регулятора]
- Паспортизованные CASP, обслуживающие Португалию (по вторичным данным): Bit2Me (Bitcoinforme S.L., CNMV Испания, авторизация 31.10.2025; Португалия в числе нотифицированных стран, снимок реестра 30.07.2026) — [paymentproviders.io (зеркало реестра ESMA)](https://paymentproviders.io/registry/mica/9598007R5LSUJLGLS853); [Jornal de Negócios](https://www.jornaldenegocios.pt/mercados/criptoativos/detalhe/mica-da-seguranca-confianca-e-competitividade-a-portugal-diz-exchange-iberica-bit2me); Bitstamp (CSSF Люксембург, май 2025, паспорт на весь ЕЭЗ) — [Crowdfund Insider](https://www.crowdfundinsider.com/2025/05/239791-bitstamp-approved-for-crypto-asset-service-provider-casp-license-under-mica/); Coinbase (CSSF Люксембург) — [Yahoo Finance/BeInCrypto](https://finance.yahoo.com/news/entrant-aims-flip-eu-crypto-171035510.html)
- Binance: заявка в Грецию (HCMC, январь 2026) направлена на дополнительный пересмотр на уровне ESMA; затем сообщалось об отзыве заявки и поиске другой страны; ESMA: «клиенты ЕС должны обслуживаться через MiCA-авторизованное лицо»; в августе 2026 г. сообщалось, что Binance всё ещё онбордит клиентов из ЕС без авторизации MiCA — [The Defiant](https://thedefiant.io/binance-withdraws-greece-mica-application-targets-new-eu-jurisdiction); [Cointelegraph](https://cointelegraph.com/news/esma-challenge-binance-serving-certain-eu-users-post-mica); [Crowdfund Insider, 08.2026](https://www.crowdfundinsider.com/2026/08/300081-binance-is-reportedly-onboarding-european-users-even-after-missing-key-regulatory-and-mica-compliance-deadline/); [Test-Achats: уход Binance из Бельгии, 06.2026](https://www.test-achats.be/invest/investir/marches-et-devises/devises/articles/2026/06/binance-fin-belgique)
- Официальные ссылки для сверки (не открывались в сессии): MiCA — https://eur-lex.europa.eu/eli/reg/2023/1114/oj ; интерим-реестр ESMA — https://www.esma.europa.eu/esmas-activities/digital-finance-and-innovation/markets-crypto-assets-regulation-mica ; Banco de Portugal — https://www.bportugal.pt ; CMVM — https://www.cmvm.pt

### Inferences
- Для частного лица в Португалии с октября 2026 г. «легальный» канал конвертации крипто↔EUR — только CASP из реестра ESMA (с нотификацией Португалии). Использование неавторизованной биржи не делает клиента нарушителем MiCA (MiCA адресован провайдерам), но лишает защиты MiCA и повышает риск отказа португальского банка принять EUR (см. раздел 8).
- Binance на 10.2026 не подтверждён как MiCA-CASP; для целей матрицы посредников — «статус не урегулирован / не авторизован».

### Gaps
- Полный список CASP, авторизованных в Португалии или нотифицировавших Португалию, по официальному реестру ESMA не выгружен (прямой доступ был заблокирован).
- Точная дата и номер публикации Lei 69/2025 в Diário da República не сверены с первоисточником.

## 2. Стейблкоины (EMT/ART): USDT vs USDC у CASP ЕС

### Takeaway
[В СИЛЕ] Разделы MiCA о стейблкоинах применяются с 30.06.2024; USDT (Tether) не является авторизованным EMT, и крупные биржи ЕС в Q1 2025 убрали спотовую торговлю USDT для пользователей ЕЭЗ; хранение и перевод USDT, по позиции ESMA в комментарии прессе, не запрещены. USDC — EMT, выпускаемый в ЕС (Circle) — [данные о Circle из общих знаний, не перепроверены в сессии].

### Cited Findings
- Binance 03.03.2025 объявила делистинг 9 не соответствующих MiCA стейблкоинов, включая USDT, для пользователей ЕЭЗ (спот — с 31.03/01.04.2025), сохранив депозиты/выводы и хранение — [Cointelegraph](https://cointelegraph.com/news/binance-halt-spot-usdt-trading-eea-mica-compliance); [CriptoNoticias](https://www.criptonoticias.com/regulacion/binance-completa-retiro-usdt-para-usuarios-europa)
- Kraken поэтапно: с 27.02.2025 sell-only, блокировка новых депозитных адресов, USDT в режиме sell-only в ЕЭЗ с 24.03.2025; затронуты USDT, PYUSD, EURT, TUSD, USTC — [Cryptometer](https://www.cryptometer.io/news/kraken-to-delist-tether-usdt-and-four-stablecoins-in-europe/); [FXStreet](https://www.fxstreet.com/cryptocurrencies/news/how-will-bnb-price-react-as-binance-and-kraken-delist-usdt-for-eu-countries-202504040409)
- Coinbase убрала USDT для ЕС заранее (конец 2024) — только вторичные источники — [Unlock-bc](https://www.unlock-bc.com/en/binance-officially-halts-usdt-trading-in-europe-amid-mica-compliance-push) [НЕ ПОДТВЕРЖДЕНО первоисточником]
- Представитель ESMA (05.03.2025, Cointelegraph): услуги хранения и перевода не соответствующих MiCA стейблкоинов не нарушают MiCA — [TradingView/Cointelegraph](https://ru.tradingview.com/news/cointelegraph%3Ab73a4a03e094b%3A0-custody-and-transfers-of-non-mica-compliant-stablecoins-not-restricted-esma)
- Сроки делистинга объяснялись требованием «к концу Q1 2025» убрать торговые пары с не соответствующими токенами — [Cointelegraph](https://cointelegraph.com/news/binance-halt-spot-usdt-trading-eea-mica-compliance)

### Inferences
- Практически: если контрагент в РФ/Армении отправляет USDT (основной P2P-инструмент в регионе), житель Португалии на MiCA-бирже, как правило, сможет зачислить/продать USDT только в режиме sell-only либо не сможет вовсе; конвертация через USDC/EUR-стейблкоины или BTC/ETH для EU-CASP проще.
- Рублёвые стейблкоины A7A5 и RUBx — под прямым санкционным запретом (раздел 4), т.е. не «не авторизованы», а запрещены для операций лиц под юрисдикцией ЕС.

### Gaps
- Текущий (10.2026) статус USDT на каждой конкретной бирже (Kraken, Bitstamp, Bit2Me, Bitpanda) не проверен по их уведомлениям.
- Официальное заявление ESMA от 17.01.2025 о не соответствующих ART/EMT в сессии не открывалось.

## 3. Регламент о переводах (ЕС) 2023/1113 (TFR, «travel rule» для криптоактивов)

### Takeaway
[В СИЛЕ с 30.12.2024] Каждый перевод криптоактивов через CASP сопровождается данными отправителя и получателя без минимального порога; для переводов на/с самостоятельного (unhosted) кошелька CASP собирает данные, а при сумме >1 000 EUR обязан принять «адекватные меры» для проверки, что адрес принадлежит/контролируется его клиентом. Португалия приняла национальный закон об исполнении TFR вместе с законом о MiCA (декабрь 2025).

### Cited Findings
- Recital 39 TFR: CASP собирают данные отправителя/получателя по переводам с/на self-hosted адреса и, по общему правилу, не обязаны верифицировать личность пользователя такого адреса; при >1 000 EUR — «адекватные меры» для оценки принадлежности адреса клиенту (ст. 14(5) и 16(2)) — [wiki.private.law (разбор TFR)](https://wiki.private.law/en/travel-rule.md); [Freshfields](https://riskandcompliance.freshfields.com/post/102iu2n/fund-transfers-crypto-assets-and-aml-ctf-the-european-banking-authoritys-take)
- Финальные руководящие указания EBA по travel rule (июль 2024): ниже 1 000 EUR — только сбор информации, без обязательного технического сопоставления (блокчейн-аналитики); выше порога — по умолчанию один метод проверки владения (в проекте было два) — [Notabene](https://notabene.id/post/ebas-new-travel-rule-guidelines-for-crypto-transfers-what-you-need-to-know---july-2024); расхождение: ранний разбор проекта упоминал «минимум два метода» — [Notabene (консультация)](https://notabene.id/post/key-takeaways-from-the-ebas-consultation-on-travel-rule-guidelines)
- Методы проверки в документах EBA: тестовый перевод заданной суммы с self-hosted адреса, подпись сообщения ключом адреса и др. (перечень открытый) — [Dudkowiak](https://www.dudkowiak.com/blog/is-this-the-end-of-anonymity-for-self-hosted-crypto-wallets/); отклики индустрии в EBA: [Coinbase](https://eba.europa.eu/system/files/webform/webform_consultation_16435/73590/Coinbase%20Response%20to%20EBA%20Consultation%20on%20Travel%20Rule%20Guidelines%20%2826-2-24%29.pdf)
- Португалия: закон, реализующий MiCA и TFR, — алерт DLA Piper «Portugal implements laws on crypto-assets and transfer of funds regulations» (22.12.2025) — [DLA Piper](https://www.dlapiper.com/insights/publications/2025/12/legal-alert-portugal-implements-laws-on-crypto-assets-and-transfer-of-funds-regulations)
- Официальные ссылки (не открывались в сессии): TFR — https://eur-lex.europa.eu/eli/reg/2023/1113/oj ; руководство EBA (EBA/GL/2024/11 — номер по памяти, сверить) — https://www.eba.europa.eu

### Inferences
- Состав данных (по ст. 14 TFR, по памяти, сверить с EUR-Lex): у отправителя — имя, адрес в распределённом реестре/номер криптосчёта, а также адрес, или номер документа, или идентификатор клиента, или дата и место рождения; у получателя — имя и адрес/номер счёта. Для частного лица это означает: EU-CASP спросит ФИО получателя/отправителя по каждому входящему/исходящему переводу, а также может спросить связь с контрагентом и источник средств.
- Перевод с российской биржи на EU-CASP после 24.05.2026 упрётся не только в travel rule, но и в санкционный запрет транзакций с CASP, учреждёнными в РФ (раздел 4) — EU-CASP обязан такой входящий перевод не обрабатывать.
- Ежемесячные переводы 50–200 тыс. RUB в эквиваленте с собственного self-hosted кошелька на EU-CASP: при сумме разового перевода >1 000 EUR — ожидать проверки владения (подпись/микроперевод); при меньших суммах — заполнение анкеты отправителя. Дробление сумм ради обхода порога — признак структурирования, который CASP обязаны отслеживать (это не способ, а риск).

### Gaps
- Текст португальского закона об исполнении TFR (номер, санкции) не сверен; руководство EBA не открыто напрямую.

## 4. Санкции ЕС против РФ, затрагивающие криптоактивы (Регламент Совета 833/2014 и пакеты 8–21)

### Takeaway
[В СИЛЕ] Ст. 5b(2) Рег. 833/2014 запрещает EU-провайдерам предоставлять услуги криптокошелька, счёта или хранения гражданам РФ, лицам, проживающим в РФ, и юрлицам РФ — с 8-го пакета (октябрь 2022) без порога суммы; исключение (ст. 5b(3)) — граждане государств ЕС/ЕЭЗ/Швейцарии и лица с временным или постоянным видом на жительство в этих государствах. 19-й пакет (23.10.2025) запретил операции со стейблкоином A7A5 (с 25.11.2025). 20-й пакет (принят 23.04.2026) ввёл новую ст. 5bb: с 24.05.2026 запрещены любые транзакции с CASP/платформами, учреждёнными в РФ (аналог для Беларуси), в список запрещённых криптоактивов добавлены цифровой рубль и RUBx. [ПРОЕКТ] 21-й пакет (предложен в июне 2026) — санкции против 11 иностранных криптоплатформ и возможный страновой запрет; статус принятия на 09.10.2026 не подтверждён.

### Cited Findings
- Исходная редакция ст. 5b(2) (апрель 2022) — запрет при совокупной стоимости >10 000 EUR на одного провайдера; более поздняя редакция (8-й пакет) порог не содержит; также с 18.01.2024 гражданам/резидентам РФ запрещено владеть/контролировать или занимать должности в органах управления EU-провайдеров таких услуг — [выдержки из документов Минфина Люксембурга и FAQ, поисковая сводка](https://mfin.gouvernement.lu/dam-assets/dossiers/sanctions-financi%C3%A8res-internationales/documentation/general-authorization-article-5c-1-f-council-regulation-eu-no-8332014-deposit-necessary-for-the-payment-of-debt-due-to-eu-122023.pdf); [FAQ Комиссии по криптоактивам 2022 (копия Skadden)](https://www.skadden.com/-/media/files/publications/2022/04/us-uk-and-eu-impose-new-sanctions-and-export-controls/faqssanctionsrussiacryptoassets_en.pdf)
- Ст. 5b(3): запрет не применяется к гражданам государства-члена, ЕЭЗ или Швейцарии и к физлицам с временным или постоянным видом на жительство в этих государствах; ст. 5c — индивидуальные разрешения нацорганов — [FAQ MFSA/Мальта](https://smb.gov.mt/gn-final-crypto-faqs/)
- Существующие счета/кошельки подпадающих под запрет лиц должны быть закрыты, отношения прекращены, клиенту даётся разумный срок — [FAQ Мальты](https://smb.gov.mt/gn-final-crypto-faqs/)
- 19-й пакет, принят 23.10.2025: санкции против разработчика A7A5, киргизского эмитента и оператора торговой площадки; запрет компаниям ЕС участвовать в транзакциях с A7A5; по одному источнику — с 25.11.2025, первый в ЕС запрет конкретного криптоактива — [LIGA](https://finance.liga.net/en/all/news/eu-includes-ruble-pegged-shora-stablecoin-in-19th-package-of-sanctions-against-russia); [Coinpedia/TradingView](https://tr.tradingview.com/news/coinpedia%3Ab8b401d22094b%3A0-eu-s-19th-sanctions-package-hits-a7a5-stablecoin-and-crypto-exchanges)
- Контекст Garantex/Grinex: OFAC 14.08.2025 — Old Vector, Grinex, A7 LLC; Великобритания — Old Vector, Grinex; в марте 2025 — изъятие доменов Garantex и заморозка ~26–28 млн USD — [LIGA](https://finance.liga.net/en/all/news/eu-includes-ruble-pegged-shora-stablecoin-in-19th-package-of-sanctions-against-russia); [Coinspot (рус.)](https://coinspot.io/russia_sng/a7a5-ruble-stablecoin-linked-to-grinex/)
- 20-й пакет принят Советом 23.04.2026; новая ст. 5bb Рег. 833/2014 запрещает «любые транзакции с поставщиками криптоуслуг или платформами, позволяющими обмен или перевод криптоактивов, учреждёнными в России» — применяется с 24.05.2026; впервые секторный, а не адресный запрет; распространяется на «зеркальные»/правопреемные структуры ранее включённых в список лиц — [Skadden, 05.2026](https://www.skadden.com/insights/publications/2026/05/eu-20th-sanctions-package); [Steptoe](https://www.steptoe.com/en/news-publications/international-compliance-blog/eu-council-adopts-20th-sanctions-package-against-russia.html); [Elliptic](https://www.elliptic.co/insights/eu-20th-sanctions-package-targets-the-architecture-of-crypto-sanctions-evasion/); [CoinDesk, 27.04.2026](https://www.coindesk.com/policy/2026/04/27/eu-s-largest-measures-against-russia-yet-include-escalation-of-crypto-sanctions-evasion)
- В перечень запрещённых криптоактивов добавлены A7A5, цифровой рубль и RUBx (RUBx и цифровой рубль — с 24.05.2026); правовая база упоминается как Рег. (ЕС) 2026/506 и Решение (CFSP) 2026/508; параллельно для Беларуси — ст. 1zf Рег. 765/2006 — [Bitget/BeInCrypto](https://beincrypto.com/eu-bans-russian-crypto-services-2026/); [VASPnet](https://vaspnet.com/articles/what-the-eus-20th-package-of-sanctions-against-russia-means-for-crypto-compliance-teams); [TRM Labs (заголовок)](https://www.trmlabs.com/resources/blog/eu-adopts-20th-sanctions-package-on-russia----including-a-sweeping-ban-on-all-crypto-asset-transactions-with-russian-and-belarusian-providers) [номера актов — НЕ ПОДТВЕРЖДЕНЫ по EUR-Lex]
- Исключения по ст. 5bb (по сводкам): дипмиссии; граждане государств-членов, ставшие резидентами РФ/Беларуси до 24.02.2022; разрешения нацорганов на выход из активов (divestment/wind-down). Об исключении для держателей ВНЖ ЕС в источниках не упоминается — [сводка по Skadden/Curtis/HSF](https://www.curtis.com/our-firm/news/eu-adopts-its-20th-sanctions-package-against-russia-and-additional-restrictive-measures-against-belarus); [HSF Kramer](https://www.hsfkramer.com/notes/crt/2026-05/sanctions-tracker-eu-sanctions-package-targets-energy-revenues-the-shadow-fleet-and-financial-circumvention)
- Сводки расходятся: TRM говорит о Россия + Беларусь в одном запрете; Cryptobriefing — о распространении на децентрализованные платформы [НЕ ПОДТВЕРЖДЕНО] — [Cryptobriefing](https://cryptobriefing.com/eu-sanctions-russia-crypto-ban/)
- 21-й пакет [ПРОЕКТ]: Комиссия предложила (около 10–15.06.2026) запреты транзакций с 20 нероссийскими структурами, в т.ч. 11 криптоплатформами, и возможный впервые страновой запрет криптоуслуг из третьих стран, где базируются платформы, помогающие обходу — [The Block](https://www.theblock.co/post/404207/eu-proposes-russia-crypto-sanction); [OCCRP](https://www.occrp.org/en/news/eu-plans-massive-21st-sanctions-package-to-target-russian-banks-and-crypto); [Plenitude](https://www.plenitudeconsulting.com/news-insights/european-commission-proposes-21st-russia-sanctions-package)
- Обзор Baker McKenzie (09.2026) подтверждает расширение режима: ограничения в отношении перечисленных криптоактивов, криптоплатформ и иных участников цепочки транзакций — [Baker McKenzie](https://www.bakermckenzie.com/en/insight/publications/2026/09/european-union-sanctions-compliance-for-crypto-assets)
- Официальные ссылки (не открывались): Рег. 833/2014 (консолидированный) — https://eur-lex.europa.eu/eli/reg/2014/833/oj ; FAQ Комиссии по санкциям — https://finance.ec.europa.eu/eu-and-world/sanctions-restrictive-measures/sanctions-adopted-following-russias-military-aggression-against-ukraine/frequently-asked-questions-sanctions-against-russia_en

### Inferences
- Гражданин РФ с португальским ВНЖ (временным или постоянным) подпадает под исключение ст. 5b(3) и может иметь криптосчёт/кошелёк у EU-CASP; гражданин РФ, проживающий в Армении без ВНЖ ЕС/ЕЭЗ/Швейцарии, — нет (запрет ст. 5b(2) завязан и на гражданство, и на проживание в РФ). Армянский гражданин, живущий в Армении, под ст. 5b не подпадает. Исключение по ВНЖ, по логике текста, утрачивается при истечении ВНЖ — CASP вправе запрашивать действующий документ.
- Ст. 5bb адресована всем лицам под юрисдикцией ЕС (по ст. 13 Рег. 833/2014 — в т.ч. любым лицам на территории ЕС и гражданам ЕС где угодно). Значит, житель Португалии (в т.ч. гражданин РФ с ВНЖ) с 24.05.2026 не может сам совершать транзакции с российскими биржами/обменниками (в т.ч. отправлять/получать криптовалюту на счёт российской платформы), а EU-CASP обязаны блокировать входящие/исходящие переводы, атрибутируемые российским CASP (блокчейн-скрининг). Исключение для ВНЖ здесь, по имеющимся сводкам, отсутствует. [Вывод требует сверки с текстом ст. 5bb]
- Перевод от физлица в РФ с его собственного некастодиального кошелька прямо ст. 5bb не охвачен (запрет касается CASP/платформ, учреждённых в РФ), но такой перевод попадает под усиленную проверку (раздел 5) и под риск, если средства ранее прошли через российский CASP или A7A5.
- Ст. 5b(1) (депозиты граждан/резидентов РФ свыше 100 000 EUR в банках ЕС, с тем же исключением для ВНЖ) — по памяти, сверить с EUR-Lex; для сумм 50–200 тыс. RUB в месяц порог не релевантен, но запрет для лиц без ВНЖ ЕС имеет значение при открытии счетов.

### Gaps
- Не удалось получить дословный текст ст. 5bb и её исключений из Официального журнала ЕС; номер Рег. (ЕС) 2026/506 — по вторичным данным.
- Статус 21-го пакета на 09.10.2026 (принят/нет, что вошло в окончательный текст) не найден.
- Не проверено, внесены ли Garantex/Grinex адресно в приложения ЕС (до 20-го пакета) — найдено только про OFAC/UK.
- Позиция португальского органа по санкциям (MNE/DGPE, Минфин — GPEARI) по криптоактивам не найдена.

## 5. ПОД/ФТ: Россия в списке высокорисковых третьих стран ЕС; AMLR (2024/1624), AMLA, запрет анонимных монет

### Takeaway
[В СИЛЕ с 29.01.2026] Делегированный регламент (ЕС) 2026/46 включил Россию в список высокорисковых третьих стран ЕС — все обязанные лица (банки, CASP) обязаны применять усиленную проверку (EDD) к отношениям и операциям с российским элементом. [ПРИНЯТО, НЕ ПРИМЕНЯЕТСЯ] AMLR запрещает CASP вести анонимные счета и счета с монетами повышенной анонимности — применение с июля 2027 г. (дата: в тексте регламента — 10.07.2027 по памяти; часть прессы пишет 1.07.2027).

### Cited Findings
- Рег. 2026/46 изменяет Рег. 2016/1675, добавляет Россию (также Боливию, Британские Виргинские о-ва); вступил в силу 29.01.2026; обязателен для всех «обязанных лиц» по Директиве 2015/849 — [Willkie, 02.2026](https://www.willkie.com/publications/2026/02/eu-deems-russia-a-high-risk-third-country-for-aml-purposes); [Grant Thornton CZ](https://www.grantthornton.cz/en/news/russia-added-to-the-eu-list-of-high-risk-third-countries-for-aml/); [Vixio](https://www.vixio.com/insights/pc-eu-designation-russia-high-risk-aml-creates-new-compliance-obligations)
- Это триггер обязательной EDD по ст. 18a Директивы 2015/849: дополнительные сведения о клиенте и бенефициаре, проверка источника средств и источника благосостояния, цель отношений; комментаторы считают, что у фирм нет дискреции снижать меры по типу клиента, объёму или «наследованному» статусу — [Willkie, 05.2026](https://www.willkie.com/publications/2026/05/european-union-deems-russia-a-high-risk-third-country-for-aml-purposes); [Willkie Compliance Concourse](https://complianceconcourse.willkie.com/articles/eu-deems-russia-a-high-risk-third-country-for-aml-purposes/)
- Даты принятия расходятся: 03.12.2025 (Комиссия) / публикация 09.01.2026; вступление в силу 29.01.2026 — согласованно — [Mondaq](https://webiis08.mondaq.com/uk/white-collar-crime-anti-corruption-fraud/1735170/the-eu-blacklists-russia-for-money-laundering)
- AMLR ст. 79: кредитным, финансовым учреждениям и CASP запрещено вести анонимные счета, а также криптосчета, позволяющие анонимизацию транзакций, и счета с монетами повышенной анонимности; пресса относит к ним XMR, ZEC, DASH (это толкование, не текст); владение монетами в самостоятельном хранении не запрещено — [Cointelegraph](https://cointelegraph.com/news/eu-crypto-ban-anonymous-privacy-tokens-2027); [CoinGeek](https://coingeek.com/eu-law-banning-anonymous-digital-asset-wallets-by-2027-final/); [Kryptonim](https://www.kryptonim.com/blog/eu-privacy-coin-ban-implications-for-users)
- Дата применения в прессе — 1.07.2027 — [Cointelegraph](https://cointelegraph.com/news/eu-crypto-ban-anonymous-privacy-tokens-2027); по ст. 90 AMLR (текст по памяти, не сверен в сессии) — 10.07.2027 — https://eur-lex.europa.eu/eli/reg/2024/1624/oj
- Данных о том, что EU-биржи уже массово делистили Monero к 10.2026, найдено не было — [поисковая сводка; Kryptonim](https://www.kryptonim.com/blog/eu-privacy-coin-ban-implications-for-users)
- Прямой надзор AMLA за крупными CASP (работающими минимум в 6 странах ЕС; критерии >20 000 клиентов в стране или >50 млн EUR оборота) — [CPO Magazine](https://www.cpomagazine.com/data-privacy/eu-looks-to-ban-privacy-coins-and-anonymous-crypto-accounts-by-2027/)

### Inferences
- Для частного лица с российским гражданством/российскими средствами в Португалии с 29.01.2026 EDD — норма, а не исключение: банк и CASP вправе (и обязаны) требовать документы об источнике средств по каждому значимому поступлению, связанному с РФ, даже при малых суммах. Регулярные ежемесячные поступления лучше заранее документально объяснять (договор, справка о доходах, подтверждение родства/дарения).
- Использование XMR как «моста» между РФ и ЕС уже сейчас практически невыгодно: EU-CASP применяют повышенный риск-скоринг, а с июля 2027 г. обслуживание таких монет будет запрещено.

### Gaps
- Текущая доступность XMR у конкретных EU-CASP (Kraken EU и др.) на 10.2026 не проверена.
- Национальная португальская норма (Lei 83/2017, Aviso Banco de Portugal 1/2022) в части EDD по высокорисковым странам в сессии не открывалась.

## 6. Налоговый обмен: DAC8 (Директива 2023/2226), OECD CARF, CRS; транспозиция в Португалии; участие РФ и Армении

### Takeaway
[В СИЛЕ с 01.01.2026] DAC8 обязывает CASP собирать данные о налоговом резидентстве и транзакциях пользователей (крипто↔фиат, крипто↔крипто, переводы) за 2026 г.; первый обмен — в 2027 г. Португалия транспонирует DAC8/DAC9 — сообщается о законе Lei 26/2026 (не подтверждено по Diário da República). Армения взяла обязательство по CARF (отчётность CASP — с 2027 г.); данных о присоединении РФ к CARF не найдено.

### Cited Findings
- DAC8 применяется с 01.01.2026; первый обмен данными ожидается в 2027 г.; отчётность охватывает KYC, обмены крипто↔крипто и крипто↔фиат, депозиты/выводы — [Blockpit](https://www.blockpit.io/tax-guides/tax-authorities-will-get-your-crypto-data); [Finbooks](https://finbooks.com/pt-PT/blog/dac8-reporte-crypto)
- Португалия: Совет министров одобрил транспозицию в феврале 2026; Proposta de Lei n.º 64/XVII (март 2026); один источник — парламент принял Lei 26/2026 (DAC8 + DAC9); упоминается ретроактивное применение; штрафы до 22 000–22 500 EUR (расхождение) — [Belzuz Abogados](https://belzuz.com/en/publicacion/crypto-asset-implementation-dac8-dac9/); [SAPO](https://sapo.pt/artigo/governo-aprova-comunicacao-obrigatoria-de-operacoes-com-criptoativos-e-imposto-de-15-sobre-estes-negocios-69a1e0d6f91c55619a1ee01d); [Echoboomer](https://echoboomer.pt/plataformas-obrigadas-declarar-transacoes-criptomoedas/) [номер закона НЕ ПОДТВЕРЖДЁН]
- «15%» в заголовках февраля 2026 относится к глобальному минимальному налогу (Pillar Two), а не к криптоприбыли — [JornalPT50](https://jornalpt50.pt/noticia/governo-aprova-comunicacao-obrigatoria-de-operacoes-com-criptoativos-e-imposto-de-15-sobre-estes-negocios/)
- Армения: обязательство по CARF; с 2027 г. CASP должны собирать и сообщать налоговое резидентство и транзакции клиентов в Комитет госдоходов; с 31.01.2026 CASP в Армении лицензируются ЦБ — [Lexology](https://www.lexology.com/library/detail.aspx?g=bcee2f63-4a76-4a20-a8cf-d9ba1e8a4eeb); [Kraken CARF FAQ](https://support.kraken.com/fi/articles/carf-faqs)
- Официальная ссылка: DAC8 — https://eur-lex.europa.eu/eli/dir/2023/2226/oj (не открывалась)

### Inferences
- Налоговый резидент Португалии, пользующийся любым EU-CASP (и, с 2027 г., армянским CASP), должен исходить из того, что AT получит сведения о его операциях за 2026 г. и далее. Это делает обязательную декларацию в Modelo 3 (раздел 7) ещё важнее.
- Обмен из РФ по CARF для португальских органов в обозримом будущем маловероятен (обязательств не найдено) — но это не отменяет обязанность резидента Португалии декларировать мировой доход.

### Gaps
- Официальный статус и текст закона о транспозиции DAC8 в Португалии (номер, дата в Diário da República, дата вступления) не подтверждены.
- Не найден официальный список OECD юрисдикций, принявших обязательства по CARF, с датами для Армении и РФ; статус обмена CRS между Португалией и РФ/Арменией не проверен.

## 7. Налогообложение крипто у физлиц в Португалии (Lei 24-D/2022 — бюджет 2023), Imposto do Selo, резидентство, NHR/IFICI

### Takeaway
[В СИЛЕ с 01.01.2023] Прирост от криптоактивов, удерживаемых <365 дней, облагается по ставке 28% (категория G, с опцией совокупного обложения); ≥365 дней — освобождён; обмен крипто↔крипто не является облагаемым событием (срок владения переносится по ряду трактовок/обнуляется по другим — расхождение); стейкинг/доходы — категория E (28%); майнинг/профессиональная деятельность — категория B. Безвозмездное получение криптоактивов облагается Imposto do Selo 10% (с семейными освобождениями — по общему правилу CIS; источники противоречат друг другу).

### Cited Findings
- Ставка 28% при владении <365 дней, освобождение ≥365 дней; продажа за фиат — категория G; стейкинг/лендинг — категория E (28%); майнинг/предпринимательство — категория B по прогрессивной шкале — [CoinTracker](https://www.cointracker.io/blog/portugal-crypto-tax-guide); [Koinly](https://koinly.io/guides/crypto-tax-portugal/); [Jean Galea](https://jeangalea.com/crypto-tax-portugal/)
- Обмен крипто↔крипто не облагается в момент обмена, налог — при выходе в фиат; один источник утверждает, что срок владения нового актива начинается с даты обмена — [Apoio Jurídico Imigração](https://www.apoiojuridico-imigracao.com/blog/portugal-crypto-tax-guide-expats-2026); [CoinTracker](https://www.cointracker.io/blog/portugal-crypto-tax-guide) [трактовка срока — НЕ ПОДТВЕРЖДЕНА первоисточником]
- С 2024 г. все физлица должны отражать криптооперации в декларации IRS (Modelo 3) даже при освобождённом приросте — [Dixcart](https://www.dixcart.com/capital-gains-tax-under-the-portugal-nhr-regime); [ECO, 27.04.2026: как заполнять IRS](https://eco.sapo.pt/2026/04/27/como-preencher-o-irs-se-comprou-ou-vendeu-criptoativos/)
- Imposto do Selo: 10% на безвозмездное получение криптоактивов (подарки, airdrop) свыше 500 EUR; 4% на комиссии криптоуслуг — [Imin Portugal](https://imin-portugal.com/blog/portugal-crypto-taxes/); другой источник указывает, что подарки/наследство между супругами, родителями и детьми — освобождены — [Portugal Buyers Agent](https://portugalbuyersagent.com/portugal-crypto-taxes-how-does-it-work/) [КОНФЛИКТ ИСТОЧНИКОВ; первоисточник CIS не открывался]
- Резидентство: >183 дней в любом 12-месячном периоде, начинающемся или заканчивающемся в налоговом году, либо наличие жилья с намерением сделать его постоянным местом проживания (ст. 16 CIRS); резиденты облагаются по мировому доходу — [Portugal Residency Advisors](https://www.portugalresidencyadvisors.com/tax-residency-portugal/)
- NHR закрыт для новых участников (с 2024/2025 — даты в источниках расходятся), заменён IFICI («NHR 2.0»), рассчитанным на квалифицированных специалистов/науку/инновации; пассивные инвесторы не подходят; по IFICI освобождение иностранных доходов категорий E и G (кроме «чёрных» юрисдикций), применимость к криптоприросту прямо не подтверждена — [Mondaq](https://www.mondaq.com/withholding-tax/1695054/capital-gains-tax-under-the-portugal-nhr-regime); [Dixcart](https://www.dixcart.com/news/capital-gains-tax-under-the-portugal-nhr-and-ifici-regime/)
- Официальные ссылки (не открывались): Portal das Finanças — https://info.portaldasfinancas.gov.pt ; Diário da República (Lei 24-D/2022, 30.12.2022) — https://diariodarepublica.pt

### Inferences
- Получение EUR/крипто от родственников из РФ/Армении для жителя Португалии — это не доход по IRS, но потенциально объект Imposto do Selo (10% при безвозмездной передаче криптоактивов; для денежных дарений — по тому же разделу TGIS, при наличии документа/декларирования). Если семейное освобождение (супруг, предки, потомки) подтверждается по CIS, регулярная помощь родителей/детей налогом не облагается, но может требовать подачи декларации — проверить у AT/консультанта.
- Регулярные поступления от работы/услуг клиентам в РФ/Армении, полученные в крипто, — это доход категории A/B по общему правилу, а не «подарок»; при конвертации в EUR позже может возникнуть ещё и категория G.
- Российские и армянские налоговые нормы на резидента Португалии автоматически не переносятся; вопросы двойного налогообложения (СИДН Португалия–РФ — РФ приостановила ряд СИДН с «недружественными» странами в 2023 г.) требуют отдельной проверки [не проверено в сессии].

### Gaps
- Не открыты первоисточники: Lei 24-D/2022 (ст. 10 CIRS, TGIS верба 1.2 и комиссии), ст. 6 CIS (освобождения для семьи), разъяснения AT по срокам владения при свопах и по «exit»-обложению при утрате резидентства.
- Статус СИДН Португалия–Россия и Португалия–Армения на 2026 г. не проверен.

## 8. Банковский комплаенс в Португалии: EUR из крипто, источник средств, счета для граждан РФ, SEPA от EU-CASP

### Takeaway
Прямых официальных португальских документов именно о «крипто-EUR» найдено не было. С 29.01.2026 любая связь с РФ — триггер обязательной EDD; плюс ст. 5b(1) Рег. 833/2014 (депозиты >100 000 EUR) для граждан РФ без ВНЖ. Практика: банки и необанки ограничивают/закрывают счета россиян без ВНЖ ЕС; для поступлений от EU-CASP по SEPA ожидать запросов о происхождении криптовалюты.

### Cited Findings
- Обязательная EDD для операций с российским элементом с 29.01.2026 (источник средств и благосостояния) — [Willkie](https://www.willkie.com/publications/2026/02/eu-deems-russia-a-high-risk-third-country-for-aml-purposes); [Vixio](https://www.vixio.com/insights/pc-eu-designation-russia-high-risk-aml-creates-new-compliance-obligations)
- Российскоязычный юр-блог: с 29.01.2026 ЕС считает РФ высокорисковой страной; Wise, Revolut и N26 ограничили или закрыли счета россиян без ВНЖ ЕС — [Sterling Law (рус.)](https://sterling-law.co.uk/ru/evropejskie-banki-blokiruyut-scheta-rossiyan/) [вторичный источник]
- Revolut прекратил принимать переводы из России, в т.ч. через третьи страны (Казахстан) — дата не указана — [United24](https://united24media.com/es/latest-news/revolut-el-banco-digital-mas-grande-de-europa-prohibe-todos-los-fondos-procedentes-de-rusia-10583) [НЕ ПОДТВЕРЖДЕНО]

### Inferences
- Для гражданина РФ с ВНЖ Португалии: открытие счёта в португальском банке юридически возможно (исключение ст. 5b(3)), но ожидается EDD; для поступлений от EU-CASP (SEPA) — готовить выписку CASP, историю покупки крипто (в т.ч. с какого кошелька/биржи пришли средства), подтверждение законного источника рублей/драмов. Средства, прошедшие через российский CASP после 24.05.2026 или через A7A5, с высокой вероятностью вызовут отказ/блокировку и сообщение в UIF (подразделение финразведки).

### Gaps
- Официальные позиции Banco de Portugal по крипто-происхождению средств (циркуляры/Aviso), статистика или задокументированные кейсы блокировок именно в португальских банках — не найдены.

## 9. Какие EU-авторизованные биржи/брокеры реально обслуживают жителя Португалии с гражданством РФ и ВНЖ Португалии

### Takeaway
Общая картина: крупные MiCA-CASP допускают граждан РФ только при подтверждённом проживании в ЕС/ЕЭЗ и действующем ВНЖ (Coinbase — прямо прописывает доп. верификацию резидентства для граждан РФ/Беларуси с европейским аккаунтом; Bitpanda — ВНЖ, действующий ≥1 год с начала онбординга). Kraken исторически ограничивал аккаунты с российской привязкой; актуальная политика к россиянам с ВНЖ ЕС не подтверждена.

### Cited Findings
- Coinbase: граждане РФ/Беларуси с европейским аккаунтом проходят дополнительную верификацию резидентства; временный ВНЖ принимается как документ только для граждан РФ и Беларуси с европейскими аккаунтами — [Coinbase Help](https://help.coinbase.com/en/coinbase/managing-my-account/verify-my-identity/por-verification-requirements)
- Kraken: страница о лицензиях обновлена 30.09.2026, список запрещённых регионов включает Беларусь; резидентство влияет на набор доступных активов; сторонний гид 2026 включает Россию в ограниченные юрисдикции; в 2022 г. Kraken запретил регистрацию гражданам РФ и ограничил российские аккаунты — [Kraken Support](https://support.kraken.com/articles/where-is-kraken-licensed-or-regulated); [Datawallet](https://www.datawallet.com/crypto/kraken-countries); [ForkLog](https://forklog.com/en/kraken-bars-russian-users-from-registering-accounts/); [The Block](https://www.theblock.co/post/178631/kraken-becomes-the-latest-crypto-exchange-to-restrict-russia-linked-accounts)
- Bitpanda: санкции ЕС запрещают криптоуслуги резидентам РФ; ВНЖ принимается, если держатель живёт в стране выдачи и ВНЖ действует ≥1 года с начала онбординга; лица из санкционных списков ЕС/OFAC/UK/ОАЭ отклоняются — [Datawallet (вторичный)](https://www.datawallet.com/crypto/bitpanda-countries)
- Bitstamp (CSSF), Bit2Me (CNMV, нотификация Португалии), Coinbase (CSSF) — MiCA-CASP — см. раздел 1; Binance — без MiCA-авторизации на 10.2026, по сообщениям продолжала онбординг клиентов ЕС — [Crowdfund Insider](https://www.crowdfundinsider.com/2026/08/300081-binance-is-reportedly-onboarding-european-users-even-after-missing-key-regulatory-and-mica-compliance-deadline/)

### Inferences
- Для матрицы посредников (житель PT, гражданин РФ, ВНЖ PT): Coinbase — «да, с доп. верификацией ВНЖ»; Bitpanda — «да, при ВНЖ ≥1 года остаточного срока» [вторичный источник]; Kraken — «не подтверждено / исторически ограничено»; Bitstamp, Bit2Me — «MiCA-CASP, политика по гражданам РФ не проверена»; Binance — «не MiCA, не рекомендуется для документируемого банковского пути».
- Любая из этих бирж с 24.05.2026 обязана отклонять транзакции с российскими CASP; входящая крипта с адресов российских бирж будет заморожена/возвращена.

### Gaps
- Официальные ToS / restricted-countries Bitstamp, Bit2Me, Bitpanda (первоисточник), Revolut (крипто через MiCA-лицензию CySEC) — в сессии не открывались.

## 10. Некриптовая база: EUR-переводы Португалия↔Россия и Португалия↔Армения для физлиц (2026)

### Takeaway
Прямые EUR-переводы из ЕС в РФ ограничены: многие российские банки отключены от SWIFT/под санкциями, Wise и Revolut прекратили переводы в РФ с 2022 г. (на 2026 г. официальное подтверждение не найдено). Маршрут через Армению существует: часть армянских банков проводит SWIFT-переводы в EUR, но с повышенными тарифами для РФ/Беларуси и с усиленной проверкой; с 29.01.2026 в ЕС такие переводы с российским элементом проходят EDD.

### Cited Findings
- Wise приостановил переводы в РФ в 2022 г., ссылаясь на санкции — [UKTN](https://www.uktech.news/fintech/wise-russia-ukraine-20220224); [The Block](https://www.theblock.co/news/business/2022-03-01-more-fintechs-follow-wises-lead-in-suspending-transfers-to-russia-135875)
- Revolut: ограничены переводы в российские банки; счета россиян, открытые до 2022 г., работают с ограничениями, без переводов в РФ (вторичный гид 2026) — [Marix](https://marix.app/library/payments/revolut-from-russia-2026); [The Block, 2022](https://www.theblock.co/post/136402/security)
- Армения→РФ по SWIFT: возможно через ограниченный круг несанкционных банков, дольше и дороже (2024) — [Habr](https://habr.com/ru/articles/851114/)
- Evoca (Армения): исходящие EUR (OUR) — 0,15%, мин. 50 000 AMD, макс. 100 000 AMD для РФ и Беларуси (выше, чем для других направлений) — [Evoca Bank](https://www.evoca.am/en/tariffs-for-commissions/transfers-tariffs/tariffs-bank-transfers); ACBA — корреспондент в EUR во Франции, в рублях — российский банк — [ACBA](https://www.acba.am/en/individuals/Money-transfers/with-bank-account); Ararat Bank — спецтариф на SWIFT до 20 000 EUR (2025) — [Ararat Bank](https://www.araratbank.am/en/news/2025/07/01/araratbank-special-rate-for-swift-transfers-up-to-eur-20-000/751/)
- Bloomberg (11.2025): россияне используют маршрут рубли→Армения (перевод по номеру телефона) → EUR в европейский банк — [Bloomberg](https://www.bloomberg.com/news/articles/2025-11-21/russians-adapt-to-life-without-swift-using-new-payment-tools)
- Рост SWIFT-переводов через Арэксимбанк (группа Газпромбанка) — [ARKA](https://arka.am/en/news/business/swift_made_remittances_via_areximbank_gazprombank_group_grow_by_63_in_9_months/)

### Inferences
- Для 50–200 тыс. RUB в месяц законный банковский путь «РФ → армянский счёт (свой) → SEPA/SWIFT EUR в Португалию» технически доступен, но португальский банк применит EDD (РФ — высокорисковая страна; Армения — транзитная юрисдикция, которую банки ЕС отслеживают на предмет обхода санкций). Наличие документов о происхождении средств — ключевое условие.
- Банки, связанные с санкционными российскими группами (напр., Арэксимбанк — группа Газпромбанка), несут повышенный риск отказа в приёме платежа банками ЕС [вывод, санкционный статус банка в ЕС не проверен].

### Gaps
- Официальные 2026-страницы Wise/Revolut о РФ, перечень российских банков в SWIFT-запрете ЕС на 10.2026 и санкционный статус конкретных армянских банков в ЕС — не проверены.

## 11. Сводка для строки «Португалия/ЕС» матрицы и для матрицы посредников

### Takeaway
Для частного лица в Португалии (гражданин РФ с ВНЖ PT) законный путь «крипто↔EUR» существует, но узок: только MiCA-CASP, с travel rule, EDD по российскому элементу и абсолютным запретом на любые транзакции с российскими криптоплатформами (с 24.05.2026), A7A5/RUBx/цифровым рублём; без ВНЖ ЕС гражданин РФ не может пользоваться кастодиальными криптоуслугами EU-провайдеров вообще.

### Cited Findings
- Нормы и даты (см. разделы выше): MiCA CASP — с 30.12.2024, переход PT — до 01.07.2026 ([Sérvulo](https://www.servulo.com/en/knowledge/End-of-the-MiCA-Regulation-transitional-period-immediate-implications-for-CASPs/9810/)); TFR — с 30.12.2024 ([Freshfields](https://riskandcompliance.freshfields.com/post/102iu2n/fund-transfers-crypto-assets-and-aml-ctf-the-european-banking-authoritys-take)); ст. 5b(2)/(3) Рег. 833/2014 — с 2022 ([FAQ Мальты](https://smb.gov.mt/gn-final-crypto-faqs/)); A7A5 — с 25.11.2025 ([LIGA](https://finance.liga.net/en/all/news/eu-includes-ruble-pegged-shora-stablecoin-in-19th-package-of-sanctions-against-russia)); ст. 5bb — с 24.05.2026 ([Skadden](https://www.skadden.com/insights/publications/2026/05/eu-20th-sanctions-package)); РФ в списке высокого риска — с 29.01.2026 ([Willkie](https://www.willkie.com/publications/2026/02/eu-deems-russia-a-high-risk-third-country-for-aml-purposes)); DAC8 — с 01.01.2026 ([Blockpit](https://www.blockpit.io/tax-guides/tax-authorities-will-get-your-crypto-data)); AMLR ст. 79 — июль 2027 ([Cointelegraph](https://cointelegraph.com/news/eu-crypto-ban-anonymous-privacy-tokens-2027)); 21-й пакет — проект ([The Block](https://www.theblock.co/post/404207/eu-proposes-russia-crypto-sanction)); налог PT 28%/<365 дней — с 2023 ([Koinly](https://koinly.io/guides/crypto-tax-portugal/))

### Inferences
- Типовые сценарии для 50–200 тыс. RUB/мес:
  - Отправитель в РФ через российскую биржу/обменник → кошелёк жителя PT на EU-CASP: с 24.05.2026 запрещено для стороны в ЕС (ст. 5bb); EU-CASP обязан блокировать.
  - Отправитель в РФ со своего некастодиального кошелька (BTC/ETH/USDC) → EU-CASP жителя PT: прямо не запрещено, но travel rule (данные отправителя; при >1 000 EUR — проверка владения, если это «свой» адрес), EDD по российскому элементу, скрининг происхождения монет; USDT — трудно продать на MiCA-бирже.
  - Через Армению (армянский CASP, лицензируемый ЦБ РА с 31.01.2026) → EU-CASP: не запрещено как таковое, но если армянская платформа подпадёт под 21-й пакет/список — запрет; армянский CARF-отчёт — с 2027 г.
  - Получатель — гражданин РФ, живущий в Армении без ВНЖ ЕС: EU-CASP не может держать для него кошелёк/счёт (ст. 5b(2)).
- Налоги жителя PT: декларация всех криптоопераций в Modelo 3; 28% при <365 дней; Imposto do Selo 10% на безвозмездное получение крипто (семейные освобождения — уточнить); DAC8-данные доступны AT.

### Gaps
- Ключевые пункты, требующие сверки с первоисточниками перед финальным отчётом: дословный текст ст. 5bb и её исключения (Рег. (ЕС) 2026/506 — номер не подтверждён), статус 21-го пакета на 09.10.2026, закон о DAC8 в Португалии (Lei 26/2026?), семейные освобождения по Imposto do Selo для криптоактивов, официальный реестр ESMA с CASP, нотифицировавшими Португалию.
