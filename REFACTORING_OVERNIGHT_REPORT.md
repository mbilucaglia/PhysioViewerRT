# Audit architetturale e sessione autonoma — PhysioViewerRT

Sessione del 9–10 novembre 2026, Europe/Rome, macchina LAB-PC.
Checkout: `portable-environment`; ramo `codex/portable-environment`;
HEAD iniziale `0a8b2f5ace05d6288ef8483c143b307a5c7da45b`.

## A. Executive Summary

**Audit completato; nessun refactoring applicato, per attivazione del criterio di arresto sulla perdita dati.**
Il salvataggio delle calibrazioni tronca il file di destinazione prima di completare
la scrittura. Una prova su un file esclusivamente sintetico conferma che un errore
di scrittura lascia a zero byte una calibrazione precedente di 938 byte. Nessun
file dell'utente è stato usato o danneggiato. La richiesta prescrive di interrompere
le modifiche al codice in presenza di rischi concreti di perdita dati: l'intervento
correttivo è quindi documentato e rinviato, insieme ai refactoring.

L'architettura ha già confini utili: modelli senza widget, buffer limitati,
mailbox sincronizzata, configurazioni immutabili e controller distinti per raw e
metriche. Non serve una riscrittura globale. Le fragilità principali sono la
persistenza delle calibrazioni, la chiusura dei worker e la concentrazione delle
politiche di sessione in `MainWindow`.

Sono stati analizzati staticamente tutti i **66 moduli** di `physiolab`, con
ispezione mirata dei percorsi di acquisizione, rendering, calibrazione, ASR,
topografia, persistenza, signal/slot e test. Sono stati compilati in memoria
**145 file Python**. La baseline è verde:

- Core: **248 test, OK**, 21,307 secondi.
- GUI offscreen: **149 test, OK con 3 skip**, 157,398 secondi; 146 eseguiti con successo.
- `pip check`: nessun requisito incompatibile rilevato.
- Pytest, pytest-qt, Ruff, mypy, Pyright e coverage non disponibili nella `.venv`;
  nessuna dipendenza installata.

Non si certificano rendering GPU nativo, prestazioni prolungate o dispositivi fisici.
La sessione ha avuto una lunga attesa per l'esecuzione fuori sandbox: non è stata
attività computazionale continua durante tutta la notte. Il registro esclude il
periodo non attestato dagli intervalli di lavoro.

## B. Architecture Audit

### Baseline, struttura e strumenti

La cartella iniziale è un contenitore e non una repository Git. Contiene anche
`rendering-refactor`, lasciato intatto. È stato scelto `portable-environment`
perché contiene `AGENTS.md`, la procedura portabile e la `.venv` locale.
`AGENTS.md` è stato letto integralmente e non modificato; nessun ulteriore file
di istruzioni annidato è stato trovato nel checkout analizzato.

| Area | Implementazione e responsabilità |
| --- | --- |
| Avvio | `main.py`: QApplication e MainWindow; `simulate.py`: sorgenti sintetiche LSL. |
| GUI | PySide6, form `.ui` in `designer/`, icone e montaggi in `assets/`; `gui.py` compone controlli e sessioni. |
| Acquisizione | `worker.py`, `lsl_tasks.py`, `ingress.py`, `acquisition_contracts.py`: discovery, receiver e consegna limitata. |
| Elaborazione | `processing.py`, `processing_filters.py`, `physiological_metrics.py`, `eeg_asr.py`, `peripheral_reduction.py`, `sc_decomposition.py`. |
| Stato | `metric_state.py`, `affect_state.py`, `asr_session.py`, `calibration_session.py`, `signal_history.py`, `raw_display_state.py`. |
| Rendering | `plot_controller.py`, `metric_plot_controller.py`, preparazione numerica e backend VisPy/pyqtgraph separati. |
| Persistenza | `calibration.py`: NPZ con JSON e array; `performance.py`: diagnostica JSONL opzionale. Nessun uso di database rilevato nei sorgenti esaminati. |
| Configurazione | `ViewerSettings` congelato, policy di rendering, requirements generali e lock Windows/Python 3.12. |

Ambiente osservato: CPython 3.12.10 x64, PySide6 6.12.0, NumPy 2.3.5,
SciPy 1.18.1, pyqtgraph 0.14.0, VisPy 0.17.0 e pylsl 1.18.6.
Dipendenze numeriche aggiuntive: PyWavelets, meegkit fissato a revisione upstream,
pyriemann, cvxEDA/cvxopt e PyOpenGL. I profili ASR/Affect/VisPy sono inclusi da
`requirements.txt`; non sono nuovi requisiti introdotti dall'audit.

Comandi esistenti: `project.cmd test`, `project.cmd test --gui`,
`project.cmd doctor --gui`, `project.cmd run` e `project.cmd simulate`.
`tools/project_env.py` implementa gli equivalenti portabili.
La CI `.github/workflows/calibration-tests.yml` esegue compilazione e unittest
core su Windows/Linux, GUI offscreen su Windows. Non sono stati trovati
`pyproject.toml`, `setup.py`, configurazioni lint/type-check o recipe PyInstaller.
La distribuzione corrente è da sorgenti con script `.cmd`, non un installer
frozen verificato. L'assenza di una recipe non è di per sé un difetto funzionale.

### Criteri di gravità

- **P0:** guasto critico immediato o perdita dati sistematica durante l'uso normale.
- **P1:** rischio concreto di perdita dati o blocco importante del ciclo di vita.
- **P2:** fragilità di correttezza, responsabilità, prestazioni o verificabilità.
- **P3:** debito circoscritto e miglioramenti non urgenti.

**P0: nessun problema dimostrato in questa sessione.** Questo non equivale a una
garanzia di assenza. Le evidenze dinamiche e le inferenze statiche sono distinte sotto.

### P1-01 — Sovrascrittura non atomica delle calibrazioni, confermata

Evidenze: `physiolab/calibration.py:216`, in particolare righe 247–248;
chiamante `physiolab/gui.py:1896`. Dopo le verifiche iniziali,
`open(path, 'wb')` tronca la destinazione prima di `np.savez_compressed`.
La gestione dell'eccezione mostra un messaggio, ma non ripristina il file precedente.

Prova: creazione di un NPZ sintetico valido in una directory temporanea sotto
`.local`, quindi seconda chiamata con `np.savez_compressed` sostituito da una
funzione che solleva `OSError('injected write failure')`.
Risultato: **938 byte prima, 0 dopo; contenuto precedente non preservato**.
L'autorizzazione a sovrascrivere nel dialogo non protegge dal fallimento a metà scrittura.

Proposta: preparare il nuovo file nella stessa directory, completare e chiudere
la scrittura, quindi sostituire atomicamente la destinazione. Definire esplicitamente
durabilità, cleanup e gestione degli errori su Windows; preservare lo schema NPZ.
La correzione è funzionale e richiede la successiva sessione autorizzata.
**Questo problema ha attivato lo stop alle modifiche applicative.**

### P1-02 — Chiusura sincrona e completamento dei worker non garantito

Evidenze: `gui.py:2028` attende senza timeout ASR e replay; attende ogni LSL task
per 3 secondi senza controllarne l'esito; chiama `worker.stop()` ignorando il valore
restituito. `worker.py:202` limita l'attesa a 1,5 secondi, mentre l'inizializzazione
può attendere metadata per 2 secondi (`worker.py:66`) e l'elaborazione numerica non
ha un limite generale. `topography_widgets.py:309` usa `shutdown(wait=True)`.
`gui.py:1928` attende senza limite il task locale dell'analisi modale, che non
compare nelle liste ASR/replay gestite da `closeEvent`.

Conseguenze possibili: event loop fermo durante chiusura lenta; percorso di chiusura
che prosegue con task non terminati; gestione fragile dell'interruzione di un
dialogo durante il calcolo. I normali stop e le chiusure nei test passano: **non è
stato provocato un crash o un deadlock nativo**. Il rischio emerge dai percorsi e
dai timeout discordanti, non da una presunta regola contro l'uso di QThread.

Proposta: progettare un protocollo unico di chiusura asincrona, ownership fino a
`finished`, gestione esplicita dei timeout e cancellazione cooperativa dove possibile.
Non sostituire indiscriminatamente QThread né usare `terminate()`.

### P2-01 — Validazione incompleta in ingresso delle calibrazioni

`calibration.py:251` verifica schema/tipo e alcune dimensioni, ma non finitezza,
frequenza positiva, vettore timestamp monodimensionale, ordine temporale e coerenza
completa dei descrittori. La prova sintetica carica senza eccezione `fs=-1`, dati
NaN/Inf e timestamp decrescenti. Le analisi successive possono rigettare parte di
questi dati, ma il confine di persistenza non garantisce un contratto valido.

Proposta: validazione centrale con messaggi specifici e test di file incompleti o
incoerenti. Va approvata la politica per file legacy oggi accettati; nessuna migrazione
o modifica del formato eseguita. `allow_pickle=False` è già correttamente presente.

### P2-02 — Dipendenza reciproca fra calcolo puro e infrastruttura Qt

`calibration.py:85` importa `eeg_configuration` da `asr_tasks` dentro
`_eeg_transform`; `asr_tasks.py:7` importa `summarize_metric` da `calibration`,
e a riga 5 importa QThread/Signal. L'analisi del grafo trova la componente
`calibration ↔ asr_tasks` includendo gli import differiti. **Nessun ciclo fra gli
import direttamente al livello di modulo**: non è un errore di import attualmente riprodotto.
Il percorso di calibrazione con ASR dipende però dal modulo Qt soltanto per una
funzione di normalizzazione metadata.

Proposta piccola: spostare quel solo helper in un modulo puro coerente con
`metric_observation`, mantenendo il nome importabile da `asr_tasks` per compatibilità.
Non spostare contemporaneamente fitting, replay e classi worker.

### P2-03 — Politiche di sessione concentrate in MainWindow

`gui.py` contiene 2.044 righe; MainWindow 1.977 righe e 122 metodi.
`_connect_designer_controls` (`:620`) occupa 309 righe,
`train_eeg_asr` (`:225`) 84, `record_calibration` (`:1823`) 79.
La dimensione da sola non è il problema: la finestra decide accettazione/ripetizione
del training, compatibilità delle baseline, attivazione, replay e persistenza oltre
al binding dei widget. In particolare `metric_references` (`:541`) incorpora una
politica di dominio testabile senza Qt, ma oggi richiede lo stato della finestra.

Proposta: estrarre una politica alla volta con input espliciti e characterization
test, lasciando dialoghi e coordinamento Qt alla composizione. Evitare mixin,
conversioni globali a MVVM e classi che inoltrano soltanto chiamate.

### P2-04 — Stato condiviso receiver/GUI senza snapshot coerente

`worker.py:28` e seguenti definiscono campi aggiornati nel worker e letti dalla
GUI; `gui.py:437`/`:1996` aggiorna `iaf_hz`, `gui.py:285`/`:294` installa/rimuove
il monitor di training. Stato ASR, configurazione, timestamp e feedback vengono
letti in momenti differenti. `ASRTrainingAccumulator` usa correttamente un Lock
per `push`, `status`, `snapshot`, ma `gui.py:272` legge anche `accepted_samples`
direttamente dopo lo snapshot dello stato.

Non è dimostrata una corruzione dei campioni: singoli assegnamenti Python non
equivalgono però a uno snapshot coerente di più campi. Il rischio riguarda decisioni
e feedback durante transizioni concorrenti. Proposta: documentare ownership e
introdurre snapshot immutabili soltanto nei confini necessari, senza bloccare il
thread GUI o cambiare il sistema di threading.

### P2-05 — Lavori obsoleti ignorati ma non sempre accorpati

`gui.py:395` crea un nuovo `CalibrationReferenceTask` per ogni aggiornamento delle
reference. La generazione impedisce di applicare un risultato obsoleto (`:422`),
ma il lavoro già avviato continua ed è conservato nella lista fino a `finished`.
`refresh` (`:1110`) crea discovery task senza un limite analogo a quello del renderer.
Aggiornamenti ravvicinati possono quindi accumulare lavori e peggiorare la chiusura.
Il backlog non è stato misurato in questa sessione.

Proposta: un lavoro attivo e un intento pendente accorpato per operazione, dopo
aver definito cancellazione e ordinamento. Conservare i controlli di generazione.

### P2-06 — I/O e preparazione ancora sincroni nel thread GUI

`gui.py:1896` comprime/scrive NPZ, `:2018` carica/decomprime NPZ prima dell'analisi
in background. `performance.py:32` calcola percentili e scrive JSONL nel tick GUI
quando il profiling è abilitato (`gui.py:1787`). `metric_plot_controller.py:135`
normalizza e interpola le serie nella GUI. I limiti di storia riducono il carico;
`settings.py:18` limita i chunk per tick, non il tempo consumato da ogni batch.

Non sono stati misurati blocchi durante l'uso ordinario; sono percorsi da profilare
con registrazioni grandi e storage lento. Priorità al salvataggio affidabile,
poi eventuale spostamento dell'I/O mantenendo dialoghi, ordine e stato invariati.

### P2-07 — Diagnostica degli errori poco ricostruibile

`worker.py:186`, `asr_tasks.py:93`/`:131`, `calibration_tasks.py:15` e
`lsl_tasks.py:19` convertono errori generici in stringhe per i segnali. È appropriato
evitare che un'eccezione termini silenziosamente il worker, ma si perdono traceback
e contesto persistente. Il fallback metadata e la chiusura dell'inlet in
`worker.py:66`/`:191` assorbono eccezioni senza logging. Esiste già un esempio con
`logging.warning(..., exc_info=True)` in `vispy_raw.py:156`.

Proposta: logging per modulo con contesto operativo e traceback, conservando i
messaggi GUI attuali ed evitando campioni e dati dei soggetti nei log. Non serve
modificare tutte le clausole `except Exception`: ai confini worker sono spesso intenzionali.

### P2-08 — Copertura buona dei percorsi ordinari, lacune sui fallimenti

`tests/test_calibration.py` copre roundtrip e analisi, non conservazione del file
precedente dopo errore. `tests_gui/test_calibration_tasks.py` verifica che i timer
avanzino durante l'analisi ordinaria; non verifica chiusura mentre il backend non
termina. Ci sono regression test per cancellazione raw, replay, pause, restart e
training cancellato. Le attese preesistenti in vari test usano polling/processEvents
e `time.sleep` (es. `tests_gui/test_rendering_regressions.py:14`, `:217`): sono debito
dei test esistenti, non attese introdotte da questa sessione.

Proposta: aggiungere prima prove di failure injection e lifecycle con Event/segnali,
timeout espliciti e teardown verificato; valutare pytest-qt solo dopo autorizzazione
all'installazione. Nessuna percentuale di copertura è stata misurata.

### P3-01 — Registri mutabili e duplicazioni limitate

`physiological_metrics.py:81` espone un dizionario globale di calculator; Processor
lo consulta anche durante `metrics` (`processing.py:129`). La documentazione ne
limita le modifiche alla fase precedente alla creazione dei processor: congelarlo
o iniettarlo richiede preservare questo contratto e i test che sostituiscono il registro.
`processing_filters.py:5` e varie tabelle di unità/label sono mutabili, ma non è
stata rilevata una mutazione indesiderata in esecuzione. I default `ViewerSettings`
sono invece già congelati.

Il confronto AST dei corpi esatti trova soprattutto adapter vuoti, tre
`eventFilter` di quattro righe e i wrapper `gui.py:1524`/`:1527`. Non giustificano
un framework comune. Esistono inoltre espressioni simili di configurazione e
compatibilità che richiedono characterization test prima di essere unificate;
la somiglianza testuale non prova equivalenza semantica.

### P3-02 — Mancanza di quality gate statici e contratto di packaging da esplicitare

Non ci sono gate configurati per lint/type checking né relativi tool nella `.venv`
o comandi omonimi individuati nel PATH. I contratti di rendering hanno dataclass e
Protocol, mentre diversi payload di calibrazione/task restano dizionari e
`Signal(object, ...)`. Type hints mirati sarebbero utili ai confini, senza introdurre
validazioni funzionali implicite. Il caricamento degli asset da percorsi relativi
a `__file__` (`gui.py:170`, `eeg_montage.py:13`) è coerente con l'avvio da sorgenti;
un futuro bundle deve includere esplicitamente Designer e asset.

### Aspetti positivi verificati e limiti dell'analisi

- La mailbox (`ingress.py`) protegge put/drain/stats con lock e limita il backlog.
- La storia dei segnali marca gli array non scrivibili (`signal_history.py:60` e seguenti).
- Il renderer scarta risultati obsoleti per ticket, versione e generazione della sorgente.
- Discovery, ricezione e calcoli principali non accedono direttamente ai widget dai worker.
- La topografia presenta i risultati nella GUI soltanto dopo `future.done()`.
- Non sono emersi doppi collegamenti signal/slot dimostrati nei percorsi ispezionati.
  I binding principali sono nel costruttore; i nuovi task collegano i segnali una volta.
- Non sono emersi accessi SQL o migrazioni database. Gli accessi persistenti rilevati
  riguardano calibrazioni e diagnostica; Designer/montaggi sono risorse in lettura.

Il grafo AST considera gli import relativi espliciti, anche nei corpi di funzione;
non dimostra proprietà di import dinamici o librerie esterne. L'audit non è una
prova formale di assenza di race condition, leak o blocchi su hardware reale.

## C. Refactoring completati

**Zero.** Il criterio di arresto P1-01 è stato rilevato prima di qualsiasi modifica
al codice applicativo o ai test versionati. Non ci sono interventi da annullare.
Non sono state cambiate API, dipendenze, formati, threading, layout o workflow.

Sono stati creati soltanto il presente report, un nuovo registro attività e
artefatti diagnostici locali ignorati da Git. Il probe sintetico rende riproducibili
due problemi senza trasformarli in test che sanciscano come corretto un comportamento
difettoso. I rischi elencati rimangono aperti.

Per la successiva sessione, dopo la gestione dei P1, sono candidati **al massimo tre
interventi indipendenti**, qui proposti e non implementati:

| Candidato | Minimo cambiamento e compatibilità | Characterization test richiesti |
| --- | --- | --- |
| Helper configurazione EEG puro | Estrarre `asr_tasks.eeg_configuration`, conservando l'import pubblico e usando il helper puro in `calibration._eeg_transform`. Elimina il ciclo differito e la dipendenza Qt su quel percorso. | Metadata mancanti, unità/canali/conversione, mismatch del modello; suite EEG ASR e replay esistenti. |
| Politica delle reference pura | Estrarre il corpo di `MainWindow.metric_references` con input espliciti, mantenendo il metodo delegante. Nessuna modifica a normalizzazione o accettazione. | IAF, ASR, replay pendente/fallito, mismatch delle sorgenti, tonic pipeline e dipendenza EI da HR/SCL; verificare mancata mutazione dell'input. |
| Geometria Affect separata | Estrarre la sola trasformazione punti/segmenti/alpha da `affect_widgets.trajectory_geometry`; mantenere l'adapter QColor e la funzione esistente nel modulo GUI. | Vuoto, punti non finiti, segmenti disconnessi, fading acceso/spento, dtype e forma degli array; suite Affect GUI esistente. |

Per ognuno: characterization test prima della modifica, suite pertinente prima/dopo,
diff limitato e verifica degli import. Non avviare tutti e tre come una sola riscrittura.

## D. Test e verifiche

| Verifica realmente eseguita | Risultato | Evidenza locale |
| --- | --- | --- |
| `project.cmd test` | 248 test, OK; processo terminato con exit 0 | `.local/overnight-baseline-core.log` |
| `project.cmd test --gui` | 149 test, 3 skip, nessun failure/error; exit 0 | `.local/overnight-baseline-gui.log` |
| `.venv/Scripts/python.exe -B .local/overnight_audit.py` | Exit 0; analisi AST e probe completati | `.local/overnight-audit.log`, `.local/overnight-audit.json` |
| `compile(...)` in memoria, eseguito dal probe | 145 file senza errori sintattici; nessun `.pyc` scritto dal controllo | `.local/overnight-audit.json` |
| `python -B -m pip check`, eseguito dal probe con timeout 60 s | Exit 0, `No broken requirements found.` | `.local/overnight-audit.json` |
| Error injection durante save | Difetto confermato: destinazione troncata | Chiave `failed_save` nel JSON |
| Caricamento NPZ sintetico incoerente | Dati non validi accettati dal loader | Chiave `invalid_load_accepted` nel JSON |
| Stato Git e diff tracked/staged | Nessuna modifica a file versionati | Controlli iniziali e finali della sessione |

Il probe è un artefatto d'audit locale, non un test aggiunto alla suite. I file
sintetici sono stati creati in `TemporaryDirectory` sotto `.local` e rimossi dal
relativo context manager. Nessuna calibrazione reale è stata aperta o modificata.

Il primo tentativo di avvio nella sandbox ha prodotto `Unable to create process`
per l'interprete Python locale. Non viene conteggiato come test passato, anche se
il wrapper aveva restituito exit 0. La baseline valida è quella effettivamente
eseguita fuori sandbox, con riepilogo unittest e terminazione verificati.

Warning preesistenti osservati: limitazioni OpenGL del plugin offscreen e messaggio
`Geometric median could not converge in 500 iterations with a tolerance of 1e-05`.
Quest'ultimo non ha fatto fallire la suite; non è stato attribuito a una causa non
dimostrata né corretto come parte di un refactoring.

I tre skip sono i due controlli nativi Affect in `test_affect_widgets.py` e la
verifica pixel/OpenGL di `test_waveform_playback.py`. Nessun test interattivo è stato avviato.
Le suite esistenti usano anche outlet LSL sintetici locali: non è una validazione
di dispositivi reali. I processi delle due suite sono terminati; nessun worker o
simulatore è stato lasciato intenzionalmente in background da questa sessione.

**Controlli non eseguiti:** pytest/pytest-qt, Ruff, mypy/Pyright e coverage perché
assenti; build/installer perché non configurati; benchmark GPU, hardware e soak test;
`doctor --gui` non necessario dopo queste verifiche e non usato per sovrascrivere
il report ambiente esistente. I probe standalone `audit_paused_plot_commands.py`
e `validate_rendering_native.py` richiedono il percorso nativo e non sono stati avviati.
`audit_rendering_boundaries.py` è stato letto ma non eseguito: contiene attese e
scrive un report storico con percorso fisso. Le regressioni di rendering già
incluse nelle due suite sono state eseguite. Nessuna misura prestazionale nuova è dichiarata.

## E. Problemi PySide6

| Aspetto | Esito e azione successiva |
| --- | --- |
| QThread | Receiver, LSLTask, ASRFitTask, CalibrationReferenceTask e CalibrationAnalysisTask eseguono lavoro nei rispettivi `run`; la sottoclasse QThread non costituisce da sola un difetto. Rivedere timeout e ownership in chiusura (P1-02). |
| QThreadPool/QRunnable | Nessun uso rilevato. Topografia usa ThreadPoolExecutor; raw preparation usa thread Python e QObject per i risultati. Nessuna sostituzione automatica proposta. |
| Worker raw | Due lane per sorgente, coalescing del pending, Condition e cancellazione cooperativa; `stop` attende al massimo circa 100 ms complessivi (`raw_render_worker.py:70`). Una chiamata numerica non cooperativa può continuare su thread daemon, ma il codice sopprime gli emit dopo lo stop e non detiene widget. Non equivale alla garanzia di terminazione immediata. |
| Topografia | Un future alla volta, invalidazione per revisione; corretta presentazione nella GUI. `shutdown(wait=True)` può bloccare la chiusura. |
| Signal/slot | Collegamenti ordinari e task ispezionati senza duplicazioni dimostrate. Le callback con lambda e dialoghi annidati meritano test di cancellazione/chiusura; non dichiarate automaticamente errate. |
| Stato GUI | I controller già possiedono pause, viewport e rendering. La compatibilità delle calibrazioni e il training conservano politiche nella finestra; candidati a estrazione mirata. |
| Race condition | Mailbox e accumulatore protetti; campi di controllo/diagnostica del receiver non raccolti in snapshot unico. Nessuna race con corruzione dati riprodotta. |
| Event loop | Discovery/acquisizione/analisi principali sono asincroni. Persistenza NPZ, profiling opzionale e chiusure sincrone restano punti di blocco possibili. |
| Test asincroni | Nessun nuovo sleep aggiunto. Le attese preesistenti sono state rilevate e lasciate intatte; futuri test devono usare segnali/Event, timeout espliciti e teardown dei worker. |

## F. Roadmap

1. **P1-01, integrità dei salvataggi:** approvare strategia atomica; aggiungere test
   di errore prima/durante scrittura e sostituzione. Accettazione: il file precedente
   resta leggibile dopo ogni errore simulato; il roundtrip mantiene lo schema attuale.
2. **P1-02, lifecycle:** indipendente dal punto 1, ma prima di spostare altro lavoro
   in background. Definire chi possiede ogni task fino alla fine e cosa accade al
   timeout. Testare chiusura durante discovery, fit, replay, topografia e analisi modale.
3. **P2-01, caricamento:** dopo accordo sulla compatibilità legacy; validare un payload
   prima di attivarlo. Fixture sintetiche invalide e fixture legacy documentate.
4. **Refactoring piccoli:** i tre candidati della sezione C, in interventi separati
   con test prima/dopo e mantenimento delle superfici pubbliche.
5. **Scheduling e snapshot:** dopo il protocollo lifecycle, accorpare lavori obsoleti
   e rendere coerenti le letture fra receiver e GUI. Non modificare formule o cadence.
6. **Logging e qualità:** aggiungere contesto alle eccezioni; poi concordare un profilo
   dev con lint/type checking progressivi. Nessuna pulizia massiva per soddisfare regole nuove.
7. **Prestazioni e distribuzione:** misurare sul PC reale I/O, p95 dei tick e chiusura;
   validare OpenGL e dispositivi. Solo in seguito definire eventuale packaging frozen.

## G. Decisioni da approvare

- Correzione del salvataggio con garanzie di sostituzione atomica/durabilità e
  comportamento su errori, file in uso e filesystem non locali.
- Politica di accettazione/rifiuto dei file legacy incoerenti; nessuna migrazione automatica.
- Semantica di chiusura con task numerici ancora attivi: attesa, cancellazione e
  messaggi all'utente; eventuali cambiamenti al workflow richiedono una scelta esplicita.
- Spostamento dell'I/O fuori dalla GUI e limite dei task pendenti, dopo il protocollo lifecycle.
- Installazione dei tool dev mancanti e aggiunta di nuovi gate CI, solo se autorizzate.
- Eventuale installer/bundle e supporto delle relative risorse/piattaforme.

Non sono state richieste decisioni architetturali durante la sessione. Le richieste
tecniche di esecuzione fuori sandbox erano necessarie perché il processo Python
locale risultava inaccessibile; non autorizzavano installazioni o modifiche ulteriori.

## H. Stato Git

Ramo e HEAD conservati. Upstream configurato:
`origin/codex/portable-environment`. Non è stato fatto fetch: il confronto con
upstream riflette il riferimento locale, non una verifica dello stato remoto attuale.
La lettura Git nella sandbox ha richiesto `-c safe.directory=<checkout>` per comando;
nessuna configurazione globale Git è stata modificata.

**File versionati modificati: nessuno. File staged: nessuno.**

Nuovi file non tracciati prodotti dalla sessione:

- `REFACTORING_OVERNIGHT_REPORT.md`.
- `docs/activity/sessions/2026-11-09_LAB-PC_e8361d58-2c1b-4569-aabd-95e1ed226bd5.json`.

File non tracciato preesistente, conservato:

- `docs/activity/sessions/2026-11-06_LAB-PC_da10848e-69fb-464e-9528-cfacee60b2c7.json`.

Artefatti locali ignorati da Git:

- `.local/overnight-baseline-core.log` e `.local/overnight-baseline-gui.log`.
- `.local/overnight_audit.py`, `.local/overnight-audit.json`, `.local/overnight-audit.log`.
- `.local/overnight-audit-search.txt`.

Intenzionalmente non modificati: `AGENTS.md`, tutti i moduli applicativi e test,
Designer, asset, requisiti e lock, script di avvio/setup, CI, documentazione
preesistente e dati utente. Il checkout fratello `rendering-refactor` è rimasto
pulito sul proprio ramo. Non sono stati usati reset, stash, cambi ramo o comandi
distruttivi sui file esistenti.

**Nessun commit, push o pubblicazione eseguito. Report e registro restano locali.**
