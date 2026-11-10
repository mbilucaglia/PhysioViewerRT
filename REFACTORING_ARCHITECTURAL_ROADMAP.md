# Roadmap architetturale verificata — PhysioViewerRT

**Stato attuale:** completata l'integrazione con main `0450512`, con audit e test ripetuti: 270 core OK, 171 GUI OK con 3 skip superati anche nativamente. Vedere [il report di integrazione](docs/REFACTORING_MAIN_INTEGRATION.md). La rettifica e le sezioni seguenti sono il resoconto storico delle fasi precedenti.

**Rettifica dopo verifica remota del 10 novembre 2026:** questa roadmap e la sua implementazione sono state costruite su `0a8b2f5`, senza fetch preliminare. Il remoto verificato successivamente è `0450512`, avanti di cinque commit, con modifiche funzionali anche nei moduli interessati. L'implementazione locale non è ancora riconciliata o validata sulla versione aggiornata. Vedere la rettifica in [ARCHITECTURAL_REFACTOR_RESULTS.md](docs/ARCHITECTURAL_REFACTOR_RESULTS.md). Le indicazioni di completamento sotto si riferiscono soltanto alla vecchia base locale.

Analisi del 10 novembre 2026, LAB-PC. **Aggiornamento: B01–B17 implementati localmente dopo l'autorizzazione complessiva dell'utente.** Risultati, decisioni e verifiche finali sono in [ARCHITECTURAL_REFACTOR_RESULTS.md](docs/ARCHITECTURAL_REFACTOR_RESULTS.md). L'audit e i blocchi seguenti conservano evidenze e criteri della proposta originale: descrivono lo stato prima dell'implementazione, non difetti tutti ancora presenti. Le voci di approvazione dei blocchi sono state risolte nell'autorizzazione complessiva, come documentato nei risultati.

**Esito della verifica**

Il repository possiede già separazioni utili. La strategia consigliata è completarle per casi d'uso, proteggendo prima persistenza e ciclo di vita. Una riscrittura di MainWindow o una conversione globale a MVVM introdurrebbe più rischio di quanto risolverebbe.

Checkout analizzato: `portable-environment`, ramo `codex/portable-environment`, HEAD `0a8b2f5ace05d6288ef8483c143b307a5c7da45b`, identico alla baseline notturna. Diff tracked e staged iniziali vuoti. Il report e due registri attività erano già non tracciati. Nessun fetch: il confronto con upstream usa riferimenti locali. `git worktree list` mostra anche `main` allo stesso SHA e `rendering-refactor` a `52dc335`; la valutazione applicativa riguarda il primo checkout, non una fusione dei tre.

Il report notturno dichiara **zero refactoring**, coerentemente con lo stato attuale. Esistono invece refactoring precedenti: `8870b5c` introduce ownership del rendering e controller separati; `19a909a`, `403355a` e `4417f7f` apportano successive correzioni. `296738f` aggiunge topografia, con calcolo e widget distinti. Ho confrontato cronologia, documentazione, implementazione corrente e test: le separazioni sono effettive, ma non rendono automaticamente corretta l'intera applicazione.

| Risultato del report | Verifica attuale e interpretazione |
| --- | --- |
| Perdita del file precedente dopo save fallito | Confermata da codice e ripetizione del probe su file sintetico: **942 → 0 byte**. I 938 byte del report non sono un requisito: timestamp e compressione possono cambiare la dimensione. |
| Loader troppo permissivo | Riprodotto: accetta `fs=-1`, NaN/Inf e timestamp decrescenti. Non significa che ogni analisi successiva accetti questi dati. |
| Ciclo calibrazione/ASR | Confermato: `calibration._eeg_transform` importa `asr_tasks.eeg_configuration`; `asr_tasks` importa `calibration`. Nessun ciclo nel grafo dei soli import relativi direttamente a livello modulo; il ciclo emerge includendo quelli differiti. Non è un crash d'importazione riprodotto. |
| Chiusura fragile | Confermati `wait()` senza timeout, esiti di wait ignorati e `shutdown(wait=True)`. Non è stato riprodotto un deadlock o un crash nativo. |
| Stato condiviso incoerente | Confermate letture/scritture di più campi Receiver e lettura diretta di `accepted_samples`; nessuna corruzione di campioni dimostrata. |
| Accumulo replay/discovery | Ogni richiesta può avviare un nuovo task; il token scarta il risultato vecchio, non il calcolo. Nessuna misura di accumulo durante uso reale. I metadata LSL hanno già deduplicazione per sorgente. |
| I/O e preparazione in GUI | Confermati save/load NPZ, flush diagnostico opzionale e preparazione metriche. Mancano misure per attribuire loro blocchi nell'uso ordinario. |
| Rendering già separato | Confermati SignalHistory, RawDisplayState, PlotController, MetricPlotController, mailbox con lock, array di storia read-only, controllo ticket/versione/generazione e pending raw accorpato. I test coprono anche errori e risultati obsoleti. |

**Precisazioni aggiuntive rispetto al report**

- Il protocollo `RawBackend` (`physiolab/render_contracts.py:52`) dichiara cinque metodi, ma `PlotController.draw` usa anche `latest_sample_time` e `widget.width()` (`plot_controller.py:198`, `:209`). I due backend attuali li forniscono: è un contratto incompleto, non un errore attuale di esecuzione.
- La CI usa Python 3.11 e dipendenze risolte dai requirements; l'ambiente Windows esaminato usa Python 3.12 e un lock dedicato. La baseline locale non certifica quel lock in CI (`.github/workflows/calibration-tests.yml`).
- Il normale stop del receiver è già asincrono (`gui.py:1320`, `receiver_finished`). Va riutilizzato il comportamento corretto, correggendo soprattutto la chiusura dell'applicazione.
- `QThread` non è di per sé il problema. Aggiungere slot alla sua sottoclasse non garantisce che girino nel thread di `run()`: l'oggetto mantiene l'affinità al thread che lo crea. Il Receiver ha un loop bloccante proprio; non si può assumere che elabori comandi Qt accodati. [Documentazione Qt](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThread.html).
- Cambiare soltanto `ThreadPoolExecutor.shutdown(wait=True)` in `wait=False` non garantisce l'uscita del processo e non cancella il lavoro già in esecuzione. [Documentazione Python](https://docs.python.org/3.12/library/concurrent.futures.html#concurrent.futures.Executor.shutdown).
- I test e i controlli AST non sono prove di assenza di race, leak o regressioni GPU. Non sono state misurate percentuali di copertura.

**Verifiche di questa sessione**

- Suite core rieseguita: **248 test, OK, 17,886 s**, exit 0; `.local/roadmap-review-core.log`.
- Suite GUI offscreen rieseguita: **149 test, OK con 3 skip, 153,114 s**, exit 0; `.local/roadmap-review-gui.log`. Sono 146 test superati e tre controlli nativi esclusi. Restano warning OpenGL offscreen e di mancata convergenza della mediana geometrica; non sono failure della suite né vengono dichiarati risolti.
- Probe notturno letto e rieseguito senza modificarne il sorgente, cambiando in memoria soltanto i nomi degli artefatti diagnostici: **66 moduli**, **145 file compilati in memoria**, `pip check` OK, difetti di persistenza riprodotti; `.local/roadmap-review-audit.json` e `.log`. Il grafo usa lo stesso algoritmo del probe precedente, integrato qui dall'ispezione manuale dei percorsi: non costituisce un secondo analizzatore indipendente.
- Il tentativo Python nella sandbox è fallito prima dei test; le esecuzioni valide sono quelle fuori sandbox. Nessuna installazione. Nessun dispositivo fisico, benchmark GPU nativo o soak test in questa verifica.

**Architettura da raggiungere, per passi**

La GUI raccoglie intenzioni e presenta risultati. Piccoli coordinatori dei casi d'uso gestiscono le operazioni asincrone. Funzioni e modelli puri decidono compatibilità, transizioni e validità. Gli adapter si occupano di LSL, NPZ e worker. Il rendering mantiene i controller e i backend già introdotti.

La direzione delle dipendenze è `GUI → coordinamento → politiche/stato puro`; anche gli adapter dipendono dai contratti puri. Il coordinamento riceve le poche operazioni esterne necessarie come funzioni o interfacce strette. Non occorrono container DI, event bus globale, repository generico o un nuovo framework.

Ownership prevista:

| Dato/risorsa | Unico responsabile |
| --- | --- |
| Widget, presentazione, connessioni GUI | MainWindow e viste |
| Campioni e storia autorevole | SignalHistory; mailbox soltanto per trasporto |
| Pause, viewport, ticket e backend | Controller rendering esistenti |
| Metriche e Affect | MetricState e AffectState |
| Baseline originale, risultato ricalcolato, stato del replay | Coordinatore calibrazione, distinguendo esplicitamente originale e derivato |
| Training e modello ASR | ASRSession; policy di training estratta per gradi |
| Inlet e Processor attivi | Thread Receiver |
| Stato osservabile del receiver | Snapshot pubblicato dal Receiver |
| Task in corso | Owner Qt mantenuto fino alla conclusione, integrato nel protocollo di chiusura |
| File NPZ | Adapter di persistenza, introdotto quando si separa davvero l'I/O |

Nessun obiettivo in termini di numero massimo di righe: il successo è poter verificare una decisione senza costruire una finestra, sostituire un adapter senza conoscere i suoi dettagli e chiudere senza perdere ownership.

**Blocchi di lavoro**

P1 = integrità o ciclo di vita; P2 = confini e correttezza; P3 = miglioramento differibile. Ogni blocco è una modifica revisionabile autonoma. Una dipendenza indica una condizione necessaria, non l'obbligo di accorpare i diff. Le nuove prove vanno introdotte nel blocco che proteggono; le funzioni estratte devono prima avere test del comportamento attuale.

**B01 — Salvare senza distruggere la calibrazione precedente. Completato dopo approvazione.**

1. **Problema/evidenza:** `open(path, 'wb')` precede la compressione; perdita riprodotta (`calibration.py:247`).
2. **File:** `physiolab/calibration.py`, `tests/test_calibration.py`; GUI solo come chiamante da verificare.
3. **Soluzione:** serializzare in un file temporaneo nella directory di destinazione, completare flush/chiusura, poi `os.replace`; cleanup in errore. Conservare firma e schema NPZ. Il replace è il punto di commit: dopo il suo successo un problema di cleanup non va presentato come salvataggio fallito. [API Python](https://docs.python.org/3.12/library/os.html#os.replace).
4. **Priorità/dipendenze:** P1, nessuna. Piccola correzione propedeutica alla futura separazione della persistenza.
5. **Rischio:** basso–medio; permessi, file aperti e filesystem Windows richiedono prove.
6. **Test:** errore alla creazione temporaneo, scrittura parziale, compressione, flush e replace; destinazione esistente/assente; roundtrip EYC/BSL; nessun temporaneo residuo nei fallimenti gestibili. Tutti su dati sintetici.
7. **Completamento:** ogni fallimento prima del commit preserva byte per byte il file precedente; successo produce NPZ leggibile nello schema 1; stato GUI di successo solo dopo commit.
8. **Approvazione:** autorizzare questo perimetro. Proposta: garanzia contro errori di scrittura su filesystem locale, senza promettere durabilità assoluta dopo perdita di alimentazione o equivalenza su share di rete. Eventuali garanzie ulteriori vanno concordate.

**B02 — Eliminare il ciclo differito con un helper EEG puro.**

1. **Problema/evidenza:** `calibration.py:85` dipende da un modulo Qt per normalizzare metadata; `asr_tasks.py:7` torna a dipendere da calibrazione.
2. **File:** `calibration.py`, `asr_tasks.py`, `metric_observation.py`; test ASR/replay e nuovo test puro mirato.
3. **Soluzione:** spostare soltanto `eeg_configuration` nel modulo puro; re-export da `asr_tasks` per mantenere compatibilità. Non spostare fitting e replay in questo diff.
4. **Priorità/dipendenze:** P2, nessuna; primo refactoring strutturale dopo B01 nell'ordine consigliato.
5. **Rischio:** basso, se si preservano esattamente default e confronti.
6. **Test:** metadata assenti, ordine canali, unità/conversione, mismatch modello; output identico e input non mutato; import helper senza Qt; suite ASR e reference replay.
7. **Completamento:** nessun arco `calibration → asr_tasks`, nessun ciclo relativo esplicito risultante nel grafo attuale, nome pubblico precedente ancora disponibile.
8. **Approvazione:** solo avvio del blocco; nessuna scelta funzionale aggiuntiva.

**B03 — Estrarre la politica delle reference.**

1. **Problema/evidenza:** `MainWindow.metric_references` (`gui.py:541`) decide compatibilità EEG/PPG/EDA/EI leggendo worker, baseline e stato di replay.
2. **File:** `gui.py`, nuovo `reference_policy.py`; `tests_gui/test_calibration_tasks.py`, nuovi test core.
3. **Soluzione:** funzione pura con analysis, configurazioni live, IAF, stato ASR/replay e identificativo tonic come input espliciti. Il metodo GUI rimane delegante; stessa politica per Metrics e Affect.
4. **Priorità/dipendenze:** P2, indipendente da B02 e dal lifecycle. Può iniziare subito dopo B01.
5. **Rischio:** medio: una reference erroneamente accettata cambia il significato delle metriche.
6. **Test:** tabella combinatoria con baseline assente, sorgente assente/incompatibile, IAF, ASR, replay pendente/fallito, tonic mismatch, HR/SCL mancanti; input non mutato. Conservare anche il comportamento attuale quando live è assente.
7. **Completamento:** decisioni verificabili senza QApplication; stessa uscita prima/dopo e integrazione Metrics/Affect verde.
8. **Approvazione:** sola estrazione. Cambiare le regole di compatibilità è un intervento funzionale distinto.

**B04 — Validare il payload NPZ prima dell'attivazione.**

1. **Problema/evidenza:** `load_calibration` (`calibration.py:251`) controlla solo parte delle dimensioni; accettazione invalida riprodotta.
2. **File:** `calibration.py`, test calibrazione; `gui.py:2011` come confine di attivazione da verificare.
3. **Soluzione:** validator puro del payload caricato: fs finita/positiva, array 2D, timestamp 1D finiti e ordinati secondo policy, canali e dimensioni coerenti, modalità/tipo richiesti. Separare struttura dei campioni dalla validità delle statistiche ricalcolate; non inventare valori mancanti.
4. **Priorità/dipendenze:** P2 alta; nessuna dipendenza tecnica da B01, ma richiede scelta legacy.
5. **Rischio:** medio: file finora accettati potrebbero essere respinti.
6. **Test:** NPZ troncati, schema/tipo errato, chiavi mancanti, zero campioni, fs invalida, NaN/Inf, timestamp duplicati/inversi/2D, mismatch canali; fixture legacy sintetiche; baseline attiva immutata dopo errore.
7. **Completamento:** errore specifico prima di analisi/attivazione, fixture valide caricate senza modificare dati, `allow_pickle=False` conservato.
8. **Approvazione:** decidere rifiuto dei file incoerenti e trattamento dei timestamp duplicati; mantenere default dei metadata opzionali legacy compatibili. Nessuna riparazione o migrazione automatica implicita.

**B05 — Chiusura asincrona dei task Qt e analisi modale.**

1. **Problema/evidenza:** `gui.py:2028` attende fit/replay senza limite; il task locale in `analyze_calibration_background` (`:1908`) ha un ulteriore `wait()` e non è nelle liste di chiusura.
2. **File:** `gui.py`, `asr_tasks.py`, `calibration_tasks.py`; piccolo `task_lifecycle.py` se serve un owner condiviso.
3. **Soluzione:** owner esplicito, stati running/closing/closed; alla richiesta di close rifiutare nuovi avvii e ignorare temporaneamente l'evento, mantenere event loop e riferimenti finché i task finiscono. Registrare anche l'analisi modale. Risultato disponibile e thread terminato sono eventi distinti. Callback di UI verso QObject GUI con contesto chiaro.
4. **Priorità/dipendenze:** P1, indipendente da B01–B04. Prima versione limitata a questi task; B06/B07 completano gli altri partecipanti.
5. **Rischio:** medio–alto, per rientranza dei dialoghi e callback tardive.
6. **Test:** fit/replay/analisi rallentati con Event, close ripetuto, errore, completamento dopo close, timer GUI attivo, callback sul thread GUI e teardown verificato; timeout dei test esplicito.
7. **Completamento:** nessuna wait bloccante nel percorso migrato, nessun oggetto distrutto mentre il task è attivo, chiusura finale una sola volta dopo conclusione.
8. **Approvazione:** proposta di UX: finestra responsiva in stato «chiusura in corso», senza nuovi comandi; lavoro numerico non cooperativo atteso senza terminarlo forzatamente. Deadline e messaggio devono essere concordati, non confusi con una garanzia di poter interrompere il backend.

**B06 — Integrare receiver e LSL nella chiusura.**

1. **Problema/evidenza:** `Receiver.stop` aspetta 1,5 s (`worker.py:202`) contro metadata fino a 2 s e processing senza limite generale; `closeEvent` ignora esiti di stop/wait LSL.
2. **File:** `worker.py`, `lsl_tasks.py`, `gui.py`, integrazione col lifecycle B05.
3. **Soluzione:** riutilizzare `request_stop` e `finished`, già usati nello stop ordinario; includere receiver e task LSL tra i partecipanti alla chiusura, mantenendo inlet nel thread proprietario. Nessun falso completamento dopo timeout.
4. **Priorità/dipendenze:** P1, dipende dal protocollo B05.
5. **Rischio:** medio–alto, coinvolge stop/restart e perdita della sorgente.
6. **Test:** metadata lento oltre 1,5 s, pull senza dati, eccezione di elaborazione, close durante discovery/restart, close_stream eseguito e nessun task residuo; suite LSL/wavelet.
7. **Completamento:** event loop attivo durante stop; cleanup confermato prima della distruzione; errore terminale preservato; normale restart invariato.
8. **Approvazione:** stessa politica di attesa di B05; eventuale arresto forzato del processo escluso dal blocco.

**B07 — Integrare il future topografico nella chiusura.**

1. **Problema/evidenza:** `topography_widgets.py:309` chiama `shutdown(wait=True)` sulla GUI; è già presente il limite di un solo future.
2. **File:** `topography_widgets.py`, integrazione lifecycle in `gui.py`; test topografia GUI.
3. **Soluzione:** fermare nuove submission, invalidare risultati, cancellare solo pending cancellabili; attendere asincronamente il future attivo tramite timer/notifica GUI e concludere lo shutdown dopo il suo completamento. Conservare il pool attuale.
4. **Priorità/dipendenze:** P1, dipende da B05; indipendente da B06.
5. **Rischio:** medio: risultati tardivi e ownership del widget/pool.
6. **Test:** calcolo bloccato su Event, chiusura con timer attivo, rilascio e cleanup, close ripetuto, nessuna presentazione dopo chiusura; test topografia esistenti.
7. **Completamento:** nessuna attesa del future sul thread GUI e nessun worker del pool rimasto attivo dopo la chiusura completata.
8. **Approvazione:** politica di attesa comune B05. Non sostituire il pool con processi in questo blocco.

**B08 — Rendere coerente il confine di controllo Receiver/GUI.**

1. **Problema/evidenza:** campi pubblici di `worker.py:28` aggiornati durante `run`; GUI scrive IAF e monitor (`gui.py:282`, `:440`) e legge stato ASR in momenti diversi. `monitor.accepted_samples` è letto fuori dal lock (`:269`).
2. **File:** `worker.py`, `gui.py`, `asr_training.py`, `acquisition_contracts.py` o piccolo modulo di contratti del receiver.
3. **Soluzione:** snapshot coerente di configurazione/status/timestamp/revisione, con copie immutabili dei contenuti annidati; comandi IAF e attach/detach monitor sincronizzati e consumati a confini di chunk. Lock brevi, mai intorno al calcolo. Includere il dato necessario nel già protetto `monitor.status()`.
4. **Priorità/dipendenze:** P2; B06 raccomandato prima di migrare i chiamanti. La correzione isolata di `status()` può essere il primo piccolo diff del blocco.
5. **Rischio:** medio: va preservato l'istante logico in cui una configurazione diventa effettiva.
6. **Test:** interleaving deterministici con Event/barriere, configurazione e model ID della stessa revisione, detach durante push, aggiornamento IAF, restart; nessuna attesa GUI durante processing rallentato.
7. **Completamento:** chiamanti migrati non leggono/scrivono separatamente i campi di controllo; ogni snapshot ha un owner e una revisione; nessuna modifica a campioni/formule/cadenze.
8. **Approvazione:** confermare applicazione dei comandi al confine del chunk; Signal(object) può trasportare un payload tipizzato, non serve sostituire tutti i segnali.

**B09 — Accorpare il replay delle reference.**

1. **Problema/evidenza:** `_apply_asr_metric_references` (`gui.py:395`) avvia un task per aggiornamento; `reference_generation` protegge solo l'applicazione del risultato.
2. **File:** `gui.py`, `asr_tasks.py`, `asr_session.py`, test reference replay.
3. **Soluzione:** massimo un replay attivo e un intento pendente sostituibile dall'ultimo; input fotografati alla richiesta; al termine avviare soltanto l'ultima richiesta. Conservare controllo della generazione e stato pending.
4. **Priorità/dipendenze:** P2, dopo B05. Nessuna dipendenza dall'estrazione della policy B03.
5. **Rischio:** medio: la richiesta più recente può attendere il vecchio calcolo non interrompibile.
6. **Test:** raffica A/B/C, risultati e fallimenti fuori ordine, chiusura con pending, nessuna pubblicazione di A/B quando C è attuale; statistiche periferiche preservate.
7. **Completamento:** contatori osservabili sempre ≤1 attivo/≤1 pending; solo l'ultima generazione aggiorna lo stato; nessun backlog crescente.
8. **Approvazione:** accettare il compromesso tra limite di concorrenza e latenza. Conservare l'attuale indicazione di reference in aggiornamento.

**B10 — Accorpare discovery LSL senza cambiare i metadata.**

1. **Problema/evidenza:** `refresh` (`gui.py:1110`) avvia sempre una discovery; `_metadata_requests` già deduplica i metadata per identificativo.
2. **File:** `gui.py`, `lsl_tasks.py`, test LSL integration.
3. **Soluzione:** una discovery attiva e al massimo un refresh richiesto durante l'esecuzione; non generalizzare subito il meccanismo dei replay né alterare il caching metadata.
4. **Priorità/dipendenze:** P2, dopo B06; indipendente da B09.
5. **Rischio:** basso–medio, per selezioni e risultati tardivi.
6. **Test:** refresh ripetuto, selezione cambiata mentre si cerca, errore e retry, chiusura con refresh pendente; controllare conteggio task e selezione conservata.
7. **Completamento:** limite rispettato, ultima richiesta servita, nessun aggiornamento della selezione da token obsoleto.
8. **Approvazione:** sola semantica di accorpamento dei click; nessuna nuova UX necessaria.

**B11 — Dare un owner unico allo stato delle calibrazioni.**

1. **Problema/evidenza:** `gui.py:127`, `:395`, `:1987` conserva loaded EYC/BSL, registrazione, pending/error e IAF; `ASRSession.set_baseline` conserva anche base_analysis/streams/cleaned_analysis. Le copie hanno ruoli diversi, ma la loro riconciliazione è distribuita nella finestra.
2. **File:** `gui.py`, `asr_session.py`, nuovo `calibration_coordinator.py`; non spostare MetricState/AffectState.
3. **Soluzione:** estrarre il solo caso d'uso applicazione/ricalcolo delle calibrazioni. Separare esplicitamente baseline originale, derivata e stato del replay; il coordinatore applica la policy B03 e richiede task attraverso un confine stretto. Dialoghi e messaggi rimangono nelle viste. Nessuna seconda copia delle storie.
4. **Priorità/dipendenze:** P2, dopo B03/B05/B09; B08 fornisce poi i dati live coerenti.
5. **Rischio:** medio–alto: modifica ownership di stato significativo, da mantenere circoscritta a questo caso d'uso.
6. **Test:** applicazione EYC cambia IAF e invalida solo reference dipendenti, BSL non salvata resta attiva, errore non sostituisce la baseline, reset, ASR on/off e replay obsoleto; test del coordinatore senza MainWindow.
7. **Completamento:** un owner per ogni valore; MainWindow delega le transizioni e presenta gli esiti; nessuna policy duplicata nei widget.
8. **Approvazione:** nessuna modifica al comportamento di attivazione/salvataggio; eventuali differenze scoperte vanno proposte separatamente.

**B12 — Estrarre la politica del training ASR, separatamente.**

1. **Problema/evidenza:** `train_eeg_asr` (`gui.py:225`) combina dialogo, durata, retry, limite campioni e dizionario locale `fit` con callback annidate.
2. **File:** `gui.py`, `asr_session.py` o nuovo `asr_training_policy.py`, `asr_training_dialog.py` come adapter, test ASR training capture.
3. **Soluzione:** piccolo modello delle sole transizioni di training con tempo e status espliciti; azioni «continuare / richiedere fit / terminare» gestite dal coordinamento Qt. Nessuna modifica ai criteri scientifici di accettazione.
4. **Priorità/dipendenze:** P2, dopo B05/B08; indipendente da B11.
5. **Rischio:** medio, soprattutto retry e cancellazione.
6. **Test:** primo tentativo, fit fallito e nuovo tentativo, limite temporale/campioni, stop sorgente, annullamento, risultato tardivo e modello precedente conservato; clock finto nei test puri.
7. **Completamento:** decisioni testabili senza dialogo e senza sleep; vista aggiornata solo da GUI; task gestiti dal lifecycle.
8. **Approvazione:** sola estrazione; cambiare soglie, timeout operativi o messaggi richiede una scelta funzionale separata.

**B13 — Completare il contratto dei backend esistenti.**

1. **Problema/evidenza:** protocollo incompleto rispetto a `PlotController.draw`, come precisato sopra.
2. **File:** `render_contracts.py`, `plot_controller.py`, `pyqtgraph_raw.py`, `vispy_raw.py`, test rendering.
3. **Soluzione:** dichiarare la proprietà temporale effettivamente richiesta e una piccola superficie per la larghezza di presentazione, oppure fornire la larghezza al controller dalla GUI. Mantenere widget/GPU fuori dai contratti numerici. Scegliere l'opzione con diff minore e documentarla.
4. **Priorità/dipendenze:** P3, nessuna; può precedere l'introduzione di type checking.
5. **Rischio:** basso–medio: evitare cambiamenti al point budget e alle geometrie.
6. **Test:** backend finto che implementa solo il contratto dichiarato; smoke dei due adapter; regressioni su pausa, replay, extrema e gap.
7. **Completamento:** il controller non richiede membri non dichiarati; geometria e comportamento invariati.
8. **Approvazione:** solo avvio, nessuna sostituzione del renderer o nuova dipendenza.

**B14 — Conservare contesto e traceback ai confini dei task.**

1. **Problema/evidenza:** `worker.py:186`, `asr_tasks.py:93`, `calibration_tasks.py:15`, `lsl_tasks.py:19` riducono eccezioni a stringhe; i fallback inlet perdono contesto.
2. **File:** i quattro moduli; configurazione logging minima all'avvio se necessaria.
3. **Soluzione:** logger per modulo, operation/generazione/modalità, traceback dell'errore inatteso; mantenere i messaggi GUI esistenti. Frequenza limitata per errori ripetitivi; nessun campione nei log.
4. **Priorità/dipendenze:** P2, nessuna; utile prima delle modifiche lifecycle.
5. **Rischio:** basso, salvo duplicazioni o volume di log.
6. **Test:** errore iniettato genera un evento contestualizzato e il medesimo esito GUI; fallback non termina acquisizione; assenza di array/payload registrati.
7. **Completamento:** errori ricostruibili senza modificare il flusso applicativo; nessun logging sincrono pesante aggiunto al tick.
8. **Approvazione:** logging diagnostico tecnico nel perimetro; destinazione persistente, rotazione e retention da concordare se si aggiungono file automatici.

**B15 — Rendere verificabili i confini in CI.**

1. **Problema/evidenza:** manca un gate contro nuovi import GUI dai modelli; CI 3.11 diversa dal profilo Windows 3.12; Protocol non attualmente controllati.
2. **File:** test architetturali dedicati, `.github/workflows/calibration-tests.yml`, eventuali configurazione e requirements dev separati.
3. **Soluzione:** prima test stdlib AST mirati ai moduli puri, includendo import differiti, e job Windows con lock 3.12, conservando la copertura 3.11 dichiarata. In un successivo diff opzionale, Ruff e un solo type checker limitati ai contratti migrati. Nessuna pulizia globale per soddisfare nuovi gate.
4. **Priorità/dipendenze:** P2 per import/ambiente, P3 per tool nuovi. B02 prima di imporre il divieto oggi violato; B13 prima di controllare il protocollo backend.
5. **Rischio:** basso sul runtime, medio su tempo/costo e riproducibilità CI.
6. **Test:** caso sintetico con import vietato che il gate intercetta, suite sull'ambiente pulito 3.12 bloccato; nessuna falsa violazione per adapter Qt autorizzati.
7. **Completamento:** PR che reintroduce dipendenza GUI nel nucleo fallisce; ambiente supportato riproducibile; differenze di versioni esplicite.
8. **Approvazione:** nuovi job e relativo costo, eventuali installazioni dev e scelta di un type checker. Pytest/pytest-qt non sono prerequisiti: unittest, Event e segnali bastano per i blocchi precedenti.

**B16 — Separare la persistenza dal calcolo prima di spostarla in background. Condizionale.**

1. **Problema/evidenza:** `calibration.py` ospita calcolo, normalizzazione e NPZ; `gui.py:1896`, `:2018` esegue I/O sincrono.
2. **File:** `calibration.py`, nuovo `calibration_storage.py`, chiamanti/test di persistenza.
3. **Soluzione:** estrarre soltanto save/load e serializzazione nell'adapter, conservando le API mediante wrapper con import locale nei soli entrypoint di persistenza. Un re-export eager caricherebbe ancora lo storage quando MetricState importa normalize. Validator puro separato dall'accesso file. Prima raccogliere tempi di save/load con dimensioni realistiche e storage rappresentativo.
4. **Priorità/dipendenze:** P3, dopo B01/B04; utile prima di B17 o quando compare un secondo uso dell'I/O.
5. **Rischio:** basso–medio, soprattutto import e compatibilità delle API.
6. **Test:** tutta la matrice B01/B04, import dei modelli senza caricare l'adapter NPZ, roundtrip compatibile.
7. **Completamento:** calcolo e stato non dipendono dall'implementazione NPZ, firme e schema invariati; misura separa I/O e calcolo.
8. **Approvazione:** avvio dell'estrazione; formato diverso o nuovo sistema di storage fuori perimetro.

**B17 — I/O asincrono delle calibrazioni, solo se giustificato dalle misure.**

1. **Problema/evidenza:** percorsi sincroni confermati, blocco percepibile non ancora misurato. Profiling JSONL e preparazione metriche sono candidati diversi, da misurare separatamente.
2. **File:** adapter B16, `calibration_tasks.py`, `calibration_coordinator.py`, `gui.py`.
3. **Soluzione:** un'operazione I/O esplicita con snapshot stabile dei dati, risultato/errore tipizzato e integrazione lifecycle. I salvataggi espliciti dell'utente non si eliminano con una policy «vince l'ultimo»: serializzarli o impedire nuove richieste mentre occupato. Nel load mantenere l'attuale baseline fino al risultato valido.
4. **Priorità/dipendenze:** P2 soltanto dopo misura del problema; richiede B01/B04/B05–B07/B11/B16.
5. **Rischio:** medio–alto: ordine delle operazioni, memoria e chiusura durante commit.
6. **Test:** storage lento/errore con GUI responsiva, close durante save, doppia richiesta, load fallito, snapshot non alterato durante scrittura; verifica memoria su registrazioni grandi.
7. **Completamento:** nessun I/O NPZ sul thread GUI, nessuna perdita di richieste autorizzate, successo solo dopo commit, miglioramento misurato rispetto alla stessa baseline/hardware.
8. **Approvazione:** workflow durante save/load e close, budget di memoria e obiettivo di reattività. Nessuna parallelizzazione automatica di interpolazione o logging in questo blocco.

**Ordine e perimetro delle approvazioni**

| Tranche | Blocchi | Uscita verificabile |
| --- | --- | --- |
| Primo intervento | B01 | Il save fallito non distrugge il file precedente. |
| Piccoli confini puri | B02, B03, B04 separati | Niente ciclo Qt nel percorso ASR; reference testabili; input validato secondo policy approvata. |
| Lifecycle | B14 opzionale in anticipo; B05, poi B06/B07 separati | Chiusura responsiva con ownership mantenuta per tutti i task. |
| Concorrenza limitata | B08, B09 e B10 nei rispettivi prerequisiti | Snapshot coerenti, replay/discovery con numero di lavori limitato. |
| Snellimento dei casi d'uso | B11 e B12 separati | Decisioni di sessione fuori dalla finestra. |
| Consolidamento | B13 e B15 | Contratti espliciti e regressioni architetturali intercettate. |
| Eventuale I/O asincrono | B16, poi B17 se motivato | Adapter isolato e reattività verificata. |

B02/B03/B04/B14 non devono attendere l'intera risoluzione del lifecycle: non aggiungono nuovi worker. B01 precede gli altri per beneficio concreto, non perché la sua implementazione sia una dipendenza tecnica di tutto. La correzione della perdita dati è il miglior primo intervento complessivo; B02 è il miglior primo intervento di puro disaccoppiamento, con B03 subito dopo per il beneficio sulla testabilità delle decisioni.

Non pianifico ora l'estrazione della geometria Affect: `trajectory_geometry` è piccola, localizzata e legata al colore Qt; il suo beneficio è inferiore ai blocchi sopra. Analogamente non propongo nuovi sistemi plugin, congelamento indiscriminato dei registry, riscrittura dei filtri, cambio delle formule, migrazione totale a QObject/moveToThread, process pool o packaging frozen. Servono requisiti o misure che li giustifichino.

**Regola di completamento per ogni blocco**

Una responsabilità per diff, test che osservano comportamento e fallimenti reali, baseline pertinente prima/dopo, import/API compatibili, rollback del solo blocco possibile senza migrazione dati. Le suite complete sono richieste per cambi trasversali di lifecycle/stato; per l'helper puro bastano inizialmente i test mirati più il controllo import, con la CI come rete complessiva. I cambi al rendering richiedono anche il percorso nativo sui due backend quando toccano risorse o geometrie: offscreen non lo sostituisce. Nessun numero prestazionale della sessione precedente viene assunto come requisito già verificato sul codice futuro.

**Esito B01 — 10 novembre 2026, dopo «Procedi»**

In questo primo passaggio era stato implementato soltanto B01. `save_calibration` scrive un temporaneo nella directory di destinazione, completa flush, `fsync` e chiusura, poi usa `os.replace`. Nessun lavoro fallibile di cleanup viene eseguito dopo il commit. In caso di errore precedente tenta di rimuovere il temporaneo; se la rimozione fallisce, conserva l'eccezione originale con una nota sul file residuo. I file temporanei non rimovibili non vengono dichiarati eliminati.

Firma, schema NPZ 1, validazione esistente e flusso GUI restano invariati. La nuova registrazione rimane attiva anche se il salvataggio fallisce, ma non viene etichettata come salvata. Nessuna modifica al loader o alle regole dei file legacy (B04).

| Verifica B01 | Risultato |
| --- | --- |
| Test prima della correzione | 10 test, 8 fallimenti nei subtest del nuovo test di regressione: EYC/BSL, destinazione presente/assente, scrittura nulla/parziale. `.local/b01-before.log` |
| Prima verifica mirata dopo correzione | 14 test OK; `.local/b01-after.log`. I successivi due casi aggiunti sono inclusi nella suite core finale. |
| Suite core finale | **255 test OK**, 17,499 s, exit 0; `.local/b01-core.log`. |
| Suite GUI calibrazioni | **5 test OK**, 3,257 s, exit 0; `.local/b01-gui.log`. |
| Controllo diff | `git diff --check` senza errori. |

Coperti errori di creazione, compressione/scrittura parziale, flush, sincronizzazione, chiusura, replace e cleanup; preservazione byte per byte e assenza di destinazioni parziali; roundtrip EYC/BSL, sostituzione di un file esistente, percorsi relativi e filename senza estensione; destinazione realmente aperta su Windows; errore e retry attraverso la GUI. Tutte le prove usano dati sintetici temporanei.

Nel passaggio B01 non era stata rieseguita l'intera suite GUI: era stata eseguita quella pertinente alle calibrazioni, insieme all'intera suite core. Non vengono promesse durabilità assoluta dopo perdita di alimentazione o identiche garanzie su filesystem di rete. In quel passaggio: nessuna nuova dipendenza, nessun commit o push.

**Esito successivo B02–B17 — autorizzazione complessiva**

La successiva istruzione dell'utente «Procedi con tutte le modifiche senza chiedermelo ogni volta» ha autorizzato i blocchi restanti. Implementati e verificati con 268 test core OK, 162 test GUI OK con 3 skip, controllo grafico nativo, Ruff e mypy progressivo. B17 è stato attivato dopo la misura del blocco GUI durante I/O. Vedere il report dei risultati per scelte conservative, misure e limitazioni. Tutte le modifiche restano locali; la CI remota, i dispositivi fisici e le prove di durata restano non verificati.
