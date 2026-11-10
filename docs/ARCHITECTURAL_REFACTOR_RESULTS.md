# Refactoring architetturale — risultati del 10 novembre 2026

**Rettifica della baseline, 10 novembre 2026:** il fetch eseguito dopo la segnalazione dell'utente ha aggiornato `origin/main` da `0a8b2f5` a `0450512`. Il refactoring descritto qui parte da una base arretrata di cinque commit, inclusi `aaac96e` (6 novembre, rendering e calibrazioni) ed `e4b18bd` (9 novembre, topografia e viewer). I test sotto valgono esclusivamente per quella base con le modifiche locali: non certificano l'integrazione con l'ultima versione remota. In comune tra modifiche locali e remote ci sono `calibration.py`, `gui.py`, `plot_controller.py`, `topography_widgets.py`, `vispy_raw.py`, due file di test GUI e `docs/ARCHITECTURE.md`. Occorre riconciliare il refactoring con la base aggiornata e ripetere le verifiche prima di considerarlo pronto per l'integrazione. Nessun codice remoto è stato sovrascritto; effettuato solo fetch.

Checkout `portable-environment`, base Git `0a8b2f5`, LAB-PC. B01 preesistente conservato; B02–B17 autorizzati dall'utente come insieme, senza conferme per singolo blocco. Le modifiche rimangono locali, senza commit/push. Il report notturno resta un documento storico non sovrascritto.

**Interventi implementati**

| Blocco | Implementazione e verifica |
| --- | --- |
| B01 | Salvataggio atomico conservato: temporaneo nella stessa directory, flush/fsync/chiusura prima di replace; cleanup best effort che conserva l'errore originale. Tutti i test di failure injection restano attivi. |
| B02 | `metric_observation.eeg_configuration` è puro. `asr_tasks` conserva il nome importabile; `calibration` non importa più task Qt. Test metadata/default/ordine e gate contro cicli. |
| B03 | `reference_policy.compatible_references`: una funzione pura per compatibilità EEG/IAF/ASR, sorgenti, tonic SC e dipendenze EI. Test delle incompatibilità e input invariato. |
| B04 | `calibration_validation` verifica struttura, campioni, fs, timestamp e descrittori prima dell'analisi/attivazione. File incoerenti respinti; nessuna riparazione silenziosa. Fixture legacy opzionali conservate. |
| B05 | `TaskLifecycle` possiede tutti i QThread avviati dall'applicazione fino a `finished`. `TaskProgress` riceve risultati sul thread GUI e termina il dialogo alla conclusione del thread, senza `wait()`. I dialoghi modali sono registrati durante il loro uso. |
| B06 | I receiver ricevono `request_stop`, restano posseduti fino alla fine e chiudono l'inlet nel proprio thread. La chiusura attende anche LSL/discovery mantenendo l'event loop attivo. Test metadata bloccati con Event, close ripetuto e cleanup. |
| B07 | Topografia interrompe nuove submission, invalida i risultati e avvia shutdown non bloccante; la chiusura finale avviene dopo il future e il teardown del pool. Test con calcolo sospeso su Event. |
| B08 | `ReceiverSnapshot` pubblica una revisione coerente con metadata annidati immutabili, stato ASR e feedback. IAF e monitor sono sincronizzati e letti insieme al confine del chunk. La GUI usa una vista snapshot per ogni decisione; i metodi compatibili preservano i chiamanti esistenti. `monitor.status()` include conteggio e limite sotto lock. |
| B09 | Replay: massimo uno attivo e una richiesta pendente, sostituita dalla più recente; generation check conservato. Test raffica A/B/C: eseguiti solo A e C, applicato C. |
| B10 | Discovery: una attiva e un refresh pendente; risultati superati non cambiano selezioni. La deduplicazione metadata per UID resta distinta. Test raffica di 20 refresh: due esecuzioni. |
| B11 | `CalibrationCoordinator` possiede EYC/BSL, IAF, registrazioni immutabili, baseline originale/derivata, generazione e stato replay. `ASRSession` delega i dati di calibrazione; le proprietà MainWindow sono facciate di compatibilità senza una seconda copia. Test transizioni senza QApplication. |
| B12 | `TrainingPolicy` decide fit, retry, limiti e cancellazione con tempo/status espliciti. Nessuna formula o soglia scientifica cambiata. Callback di fit con QObject e slot GUI espliciti. Test retry, limite, timeout, risultato tardivo e integrazione training. |
| B13 | `RawBackend` espone anche timestamp e larghezza di presentazione; `WarmRawBackend` dichiara il warmup specifico VisPy. Il controller non legge più `widget.width()` nel percorso comune. Test con backend finto privo di widget. |
| B14 | Logging per modulo con traceback, tipo operazione e generazione/modalità ai confini receiver/LSL/fit/replay/analisi/I/O. Messaggi GUI preservati; nessun nuovo file di log automatico. Test errore I/O con traceback, esito GUI e baseline invariata. |
| B15 | Test AST degli import anche differiti, dipendenze transitive vietate e cicli; controllo import dei modelli senza Qt/storage. Ruff per errori di esecuzione e mypy progressivo su quattro moduli di contratti. Job CI Windows/Python 3.12 con lock, oltre ai job 3.11 esistenti. Configurazione CI preparata; non è stata eseguita su GitHub in questa sessione. |
| B16 | `calibration_storage` contiene NPZ e filesystem. Le funzioni pubbliche in `calibration` sono wrapper con import locale: importare MetricState non carica lo storage. Failure injection aggiornata al modulo proprietario, senza eliminare verifiche B01. |
| B17 | Save/load in `CalibrationIOTask`, risultati nominati, snapshot di salvataggio posseduto dal task, un'operazione I/O alla volta. La baseline attiva cambia soltanto dopo load e analisi riusciti. Close durante save attende il commit senza distruggere il task. Test lentezza, duplicato, mutazione input, errore e close. |

**Decisioni applicate nell'autorizzazione complessiva**

- File legacy: conservare default dei campi opzionali; rifiutare valori non finiti, fs non positiva, dimensioni incoerenti e timestamp duplicati/decrescenti. Non ordinare o interpolare campioni per rendere accettabile un file.
- Chiusura: disabilitare nuovi comandi, mostrare stato di chiusura e attendere i calcoli non interrompibili conservando l'event loop. Nessun timeout viene interpretato come «thread terminato», nessun `terminate()`, nessun process pool introdotto. Un backend nativo che non ritorna può impedire la chiusura definitiva, ma non una chiamata sincrona di join sulla GUI.
- Scheduling: il replay/discovery più recente può aspettare il vecchio calcolo; l'accorpamento limita CPU/memoria. I salvataggi espliciti non vengono scartati come richieste obsolete: una seconda richiesta durante I/O viene rifiutata prima dell'avvio.
- Logging: usare i logger standard senza aggiungere file persistenti o cambiare retention. Gli errori iniettati nei test generano intenzionalmente traceback diagnostici.
- Qualità: Ruff e mypy fissati in `requirements-dev.txt`, installati per questa verifica in `.local/quality-venv`; ambiente runtime e lock applicativo non modificati. Le versioni scelte sono rilasci pubblicati: [Ruff 0.14.1](https://pypi.org/project/ruff/0.14.1/), [mypy 1.18.2](https://pypi.org/project/mypy/1.18.2/).

**Misure che hanno motivato B17**

Fixture sintetica riproducibile: 60 s, 32 canali, 256 Hz, 4.055.040 byte tra campioni e timestamp, NPZ circa 3,8 MB. Tre salvataggi sull'adapter B01 sincrono: mediana **172,6 ms**; load **24,6 ms**. Nessun dato reale aperto o modificato.

Confronto successivo nella stessa sessione, stesso PC/fixture, heartbeat GUI ogni 5 ms:

| Operazione | Durata totale | Eventi GUI durante operazione | Intervallo massimo heartbeat |
| --- | ---: | ---: | ---: |
| Save sincrono | 164,1 ms | 0 | 164,1 ms |
| Save worker | 167,9 ms | 29 | 24,4 ms |
| Load sincrono | 24,6 ms | 0 | 24,6 ms |
| Load worker | 19,2 ms | 3 | 5,7 ms |

È una misura locale della reattività, non una promessa di latenza o un benchmark statistico dei dischi. Il save worker possiede una copia aggiuntiva dei campioni/timestamp; non accoda altre copie di salvataggi pendenti. Il caricamento trasferisce gli array al chiamante come read-only. Per file molto più grandi restano il costo di decompressione e delle copie necessarie al cambio di ownership.

Comandi riproducibili: `python -B tools/benchmark_calibration_io.py` e `python -B tools/benchmark_calibration_responsiveness.py`, usando la `.venv` locale. Entrambi lavorano su file temporanei sotto `.local`.

**Validazione**

- Primo checkpoint puro: 260 test core OK.
- Core dopo integrazione e nuovi test: **268 test OK**, 26,154 s, exit 0 (`.local/roadmap-final-core.log`).
- Ruff: tutti i controlli configurati passati; mypy: nessun errore sui quattro moduli selezionati. Non è un type check completo dell'applicazione.
- Suite GUI finale: **162 test, OK con 3 skip**, 167,472 s, exit 0 (`.local/roadmap-final-gui.log`). Gli skip riguardano verifiche pixel/camera native non disponibili offscreen.
- Verifica grafica nativa Windows sui backend VisPy e pyqtgraph: **30 transizioni e 21 cicli di memoria, nessun errore, `passed: true`**. Chiusura misurata: 170,3 ms. Artefatti locali in `.local/roadmap-native-20261110/`; log `.local/roadmap-native.log`. Questa prova integra, senza equivalere a tutti i casi pixel saltati, la suite offscreen.
- `git diff --check`: nessun errore; dipendenze runtime e lock applicativo invariati.

Durante lo sviluppo, il test modale ha intercettato una collisione del nome `finished` con il segnale ereditato QDialog: slot rinominato `finish_task`. La prima suite GUI completa ha anche intercettato un test rendering che impostava direttamente la viewport lasciando attivo il timer della finestra: il timer poteva sovrascrivere la visibilità dai widget prima che arrivasse il frame. Quel test ora ferma il timer e mantiene tutte le asserzioni su frame, gap e geometria. Il test di save con receiver sintetico ferma analogamente il timer che richiederebbe telemetria non presente nel fake. Non sono state modificate formule o geometrie per far passare i test.

Restano fuori da questa verifica dispositivi fisici, stabilità di ore, garanzia di durabilità dopo perdita di alimentazione, semantica equivalente su share di rete e risultati del servizio CI remoto. I warning numerici/driver preesistenti sono distinti dai fallimenti dei test.
