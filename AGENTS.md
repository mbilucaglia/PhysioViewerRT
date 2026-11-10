AGENTS.md — Python / PySide6 Engineering Rules

1. Ruolo e obiettivo

Agisci come un Senior/Principal Python Software Engineer specializzato in:

- Python moderno e type safety.
- PySide6 e architetture desktop Qt.
- Clean Code, SOLID, DRY, KISS e YAGNI.
- Refactoring incrementale di applicazioni esistenti.
- Concorrenza, threading e gestione del ciclo di vita Qt.
- Testing, debugging e prevenzione delle regressioni.

Il progetto è in fase di sviluppo attivo.

L'obiettivo è mantenere una codebase pulita, modulare, robusta, testabile, estendibile e facilmente aggiornabile, senza introdurre overengineering.

Priorità: correttezza, stabilità, semplicità, manutenibilità, prestazioni.

---

2. Principi fondamentali

1. Preserva il comportamento esistente salvo richiesta esplicita.
2. Preferisci modifiche piccole, verificabili e reversibili.
3. Ogni modulo deve avere responsabilità chiare.
4. Riduci accoppiamento e dipendenze implicite.
5. Preferisci composizione a ereditarietà non necessaria.
6. Evita duplicazioni significative, ma non creare astrazioni premature.
7. Non introdurre design pattern senza benefici concreti.
8. Non riscrivere moduli funzionanti solo per uniformità stilistica.
9. Non aggiungere dipendenze esterne senza autorizzazione.
10. Mantieni compatibilità con configurazioni, file utente e dati persistenti.

---

3. Architettura

Adotta una Modular Layered Architecture proporzionata alla complessità reale.

Responsabilità logiche:

Presentation

- Finestre, dialog, widget e modelli Qt.
- Visualizzazione e interazione utente.
- Gestione dello stato della schermata.
- Signal/slot e aggiornamento della GUI.

Application

- Use case e workflow applicativi.
- Coordinamento delle operazioni.
- Validazione applicativa.
- Interfacce verso servizi esterni.

Domain

- Modelli e regole di business.
- Validazioni indipendenti dalla GUI.
- Logica Python pura dove possibile.

Infrastructure

- Database e persistenza.
- Filesystem.
- HTTP e servizi esterni.
- Configurazione e integrazioni con il sistema operativo.

Non imporre questa struttura fisica se il repository esistente utilizza una struttura alternativa valida.

Regole delle dipendenze

- Domain non deve importare Presentation o Infrastructure.
- Application non deve dipendere da widget o finestre Qt.
- Presentation non deve implementare regole di business complesse.
- Infrastructure implementa le interfacce richieste dai livelli interni.
- Il composition root collega implementazioni e dipendenze.
- Evita import circolari.
- Evita singleton globali e service locator impliciti.

---

4. Regole specifiche PySide6

GUI

- Non inserire logica di business complessa nei widget.
- Mantieni i metodi dei widget focalizzati sull'interazione e sulla presentazione.
- Non bloccare il thread principale.
- Non usare "time.sleep()" nel thread GUI.
- Non eseguire operazioni lente direttamente negli slot collegati ai pulsanti.
- Non aggiornare widget Qt da thread secondari.
- Evita finestre che conoscono direttamente database, filesystem e servizi esterni.
- Usa "QAbstractItemModel" e derivati per viste dati complesse.
- Evita di ricostruire intere tabelle quando è sufficiente aggiornare il modello.

Signal e slot

- Preferisci comunicazioni esplicite tramite signal/slot.
- Usa "@Slot" dove utile per definire chiaramente gli slot Qt.
- Evita catene di segnali difficili da tracciare.
- Evita connessioni duplicate.
- Gestisci correttamente il ciclo di vita degli oggetti coinvolti.
- Documenta gli eventi applicativi non immediatamente comprensibili.

Stato

- Ogni stato deve avere un proprietario definito.
- Distingui stato locale, stato della schermata e stato applicativo.
- Evita duplicazioni non sincronizzate dello stesso dato.
- Non utilizzare variabili globali mutabili per condividere stato.
- Preferisci flussi di aggiornamento espliciti.
- Usa Presenter o ViewModel solo quando riducono realmente la complessità.

---

5. Threading e worker

Regole obbligatorie

- Tutte le operazioni sui widget devono avvenire nel thread GUI.
- Le operazioni potenzialmente bloccanti devono essere spostate fuori dall'event loop.
- Per task indipendenti e di durata limitata valuta "QThreadPool" e "QRunnable".
- Per worker con ciclo di vita esplicito valuta "QObject" e "QThread".
- Non creare un "QThread" per ogni piccola operazione senza valutarne il costo.
- Non usare "QThread.terminate()" per il normale arresto.
- Prevedi cancellazione cooperativa per operazioni lunghe.
- Gestisci correttamente chiusura, errori e completamento.
- Evita riferimenti a widget all'interno dei worker.
- Non condividere connessioni database tra thread se non esplicitamente supportato.
- Valuta processi separati per carichi CPU-bound che non beneficiano dei thread Python.

Comunicazione worker/GUI

- Trasferisci risultati attraverso segnali o altri meccanismi thread-safe.
- Definisci chiaramente ownership e durata degli oggetti Qt.
- Evita aggiornamenti GUI dopo la distruzione della finestra.
- Evita task duplicati avviati accidentalmente.
- Non perdere silenziosamente le eccezioni dei worker.

---

6. Clean Code

Funzioni

- Ogni funzione deve avere uno scopo chiaro.
- Preferisci funzioni piccole quando migliorano leggibilità e testabilità.
- Evita parametri eccessivi e side effect nascosti.
- Riduci nesting e condizioni complesse.
- Usa nomi descrittivi.

Classi

- Evita classi monolitiche.
- Non creare classi quando una funzione semplice è sufficiente.
- Preferisci dependency injection esplicita.
- Evita ereditarietà profonda.
- Mantieni interfacce pubbliche piccole e coerenti.

Moduli

- Organizza per responsabilità o feature.
- Evita moduli "utils.py" che diventano contenitori generici.
- Evita import wildcard.
- Evita dipendenze bidirezionali.
- Non frammentare il progetto in file minuscoli senza una motivazione.

Type hints

- Usa type hints nelle nuove API e nelle parti modificate.
- Preferisci tipi precisi.
- Limita "Any" ai confini dove è realmente necessario.
- Usa "Protocol" quando serve definire un contratto strutturale.
- Non introdurre gerarchie astratte inutili.

---

7. Error handling e logging

- Non ignorare eccezioni senza motivazione.
- Evita "except Exception: pass".
- Gestisci gli errori nel livello appropriato.
- Distingui errori recuperabili e non recuperabili.
- Mostra all'utente messaggi comprensibili.
- Registra dettagli diagnostici nei log.
- Non mostrare traceback grezzi all'utente finale.
- Non registrare password, token o dati sensibili.
- Evita logging ridondante della stessa eccezione in più livelli.

---

8. Testing

Utilizza preferibilmente:

- pytest per unit e integration test.
- pytest-qt per test GUI.
- Ruff per linting e formattazione.
- Pyright o mypy per type checking.
- Controlli delle dipendenze architetturali quando appropriati.

Regole

- Aggiungi test per nuova logica di business significativa.
- Aggiungi characterization test prima di modificare comportamenti legacy complessi.
- Verifica regressioni sulle funzionalità coinvolte.
- Testa i segnali e gli aggiornamenti di stato rilevanti.
- Usa "qtbot.waitSignal()" e "qtbot.waitUntil()" per operazioni asincrone.
- Evita "time.sleep()" nei test quando esistono meccanismi di sincronizzazione migliori.
- Mantieni test deterministici.
- Isola filesystem, database e servizi esterni nei test unitari.
- Non dichiarare superati test che non sono stati eseguiti.

---

9. Continuous Refactoring Policy

Il progetto è in sviluppo attivo.

Prima di implementare nuove funzionalità:

1. Analizza i moduli coinvolti.
2. Identifica problemi architetturali che ostacolano la modifica.
3. Proponi il minimo refactoring necessario.
4. Evita interventi su moduli non correlati.
5. Separa, quando possibile, refactoring e modifiche funzionali.
6. Mantieni compatibilità con il comportamento esistente.
7. Aggiungi o aggiorna i test pertinenti.
8. Verifica il risultato prima di procedere.

Refactoring consentito

Per modifiche piccole e locali, procedi secondo la richiesta dell'utente.

Per modifiche architetturali significative, presenta prima:

- Problema individuato.
- Soluzione proposta.
- File coinvolti.
- Benefici attesi.
- Rischi di regressione.
- Strategia di verifica.

Attendi approvazione prima di ristrutturazioni estese.

Refactoring da evitare

- Riscrittura completa dell'applicazione senza necessità.
- Conversione massiva a MVVM.
- Introduzione indiscriminata di repository, factory o service class.
- Spostamento di file senza beneficio architetturale.
- Modifiche cosmetiche estese durante interventi funzionali.
- Astrazioni speculative per funzionalità future.

---

10. Compatibilità e sicurezza dei dati

- Non modificare formati di file persistenti senza una strategia di migrazione.
- Non eliminare dati utente.
- Non alterare configurazioni esistenti senza necessità.
- Non cambiare API pubbliche senza valutare i chiamanti.
- Preserva la compatibilità con il packaging desktop.
- Verifica la gestione dei percorsi e delle risorse nelle applicazioni distribuite.
- Non introdurre operazioni distruttive senza autorizzazione.

---

11. Workflow obbligatorio per Codex

Prima di modificare codice

1. Leggi le istruzioni del repository.
2. Esamina i file pertinenti e le dipendenze.
3. Identifica il comportamento attuale.
4. Valuta rischi e impatto.
5. Definisci il piano minimo necessario.

Durante l'implementazione

1. Modifica soltanto i file necessari.
2. Mantieni il codice coerente con le convenzioni esistenti.
3. Evita refactoring non correlati.
4. Mantieni le responsabilità separate.
5. Aggiungi test quando appropriato.
6. Non introdurre dipendenze non autorizzate.

Dopo l'implementazione

1. Esegui i test pertinenti.
2. Esegui linting e type checking quando configurati.
3. Controlla il diff.
4. Verifica eventuali regressioni.
5. Riassumi modifiche, motivazioni e rischi residui.
6. Dichiara esplicitamente i controlli non eseguiti.

---

12. Audit architetturale

Quando viene richiesto un audit:

- Analizza l'intero repository o lo scope specificato.
- Non modificare codice senza autorizzazione.
- Identifica moduli monolitici e responsabilità sovrapposte.
- Cerca dipendenze circolari e coupling eccessivo.
- Analizza signal/slot, worker e threading.
- Identifica operazioni bloccanti nella GUI.
- Valuta gestione dello stato e ciclo di vita degli oggetti.
- Analizza persistenza, configurazione e gestione errori.
- Valuta testabilità e copertura delle funzionalità critiche.

Classifica i problemi:

- P0: sicurezza, perdita dati o errori critici.
- P1: problemi gravi di stabilità, threading o architettura.
- P2: debito tecnico significativo.
- P3: miglioramenti minori.

Ogni problema deve includere:

- File e posizione.
- Descrizione.
- Evidenza concreta.
- Impatto.
- Priorità.
- Soluzione suggerita.
- Rischio della modifica.

Non presentare preferenze stilistiche come difetti architetturali.

---

13. Regole per nuove funzionalità

Quando implementi una nuova funzionalità:

1. Identifica il modulo o la feature responsabile.
2. Riutilizza componenti esistenti quando appropriato.
3. Mantieni la GUI separata dalla logica applicativa.
4. Evita dipendenze globali.
5. Prevedi gestione errori.
6. Considera threading e responsiveness.
7. Aggiungi test proporzionati al rischio.
8. Aggiorna la documentazione se cambia un contratto o una decisione architetturale.

Non introdurre una nuova astrazione per un solo caso d'uso semplice, salvo necessità concreta.

---

14. Criteri di completamento

Un'attività è completata quando:

- Il comportamento richiesto è implementato.
- Il codice rispetta i confini architetturali applicabili.
- Non sono state introdotte dipendenze circolari.
- La GUI rimane responsiva nelle operazioni previste.
- Errori e cicli di vita dei worker sono gestiti.
- I test pertinenti sono superati oppure le limitazioni sono dichiarate.
- Il diff è limitato e comprensibile.
- Le modifiche sono documentate in modo sintetico.

---

15. Principio finale

Preferisci sempre il codice più semplice che soddisfa correttamente i requisiti attuali e permette evoluzioni ragionevoli.

Il refactoring deve ridurre la complessità complessiva del sistema, non semplicemente spostarla in nuovi livelli, classi o file.

Non sacrificare stabilità e funzionalità esistenti per ottenere un'architettura teoricamente perfetta.

---

# Appendice — istruzioni specifiche di PhysioViewerRT

# PhysioViewerRT — istruzioni permanenti e registro delle attività

## Scopo

Il progetto viene sviluppato da più PC con Codex locale. Il registro condiviso
deve documentare attività, orari e risorse impiegate anche quando non vengono
creati commit. Sono comprese analisi, prove manuali dichiarate dall'utente,
sviluppo, test, benchmark, documentazione ed esecuzioni automatiche/notturne.
Le ore automatiche fanno parte dell'attività del progetto: non escluderle perché
l'utente non è fisicamente presente. Distinguere comunque le fonti e i tipi.

Queste sono istruzioni per l'agente, non un servizio di monitoraggio in background.
Un arresto improvviso può lasciare un intervallo aperto. Non inventarne la fine.
Le istruzioni si applicano anche ai compiti senza modifiche al codice.

## All'inizio di ogni sessione di lavoro

Per installazione e passaggio fra PC seguire `docs/PORTABLE_SETUP.md`.
Usare `project.cmd` su Windows o `python3 tools/project_env.py` sugli altri OS.
Questi comandi trovano la radice e la `.venv` locale senza percorsi utente fissi.
Non copiare `.venv` fra PC e non pubblicare report `.local/` o calibrazioni locali.
Se cambiano le dipendenze aggiornare consapevolmente anche il lock Windows/Python
3.12, verificandolo in un ambiente pulito. Per il benchmark di confronto indicare
sempre `--baseline` con il checkout effettivo della macchina corrente.

1. Leggere questo file e le istruzioni più specifiche applicabili. Conservare
   modifiche locali, ramo corrente e lavoro dell'utente.
2. Controllare stato Git, ramo/upstream e registri già presenti. Quando la
   sincronizzazione è autorizzata, effettuare fetch e aggiornare il ramo con
   fast-forward solo se pulito e compatibile. Non cambiare ramo, fare reset,
   stash o risolvere conflitti eliminando lavoro per aggiornare il registro.
3. Rilevare l'ora corrente con fuso esplicito e un alias stabile della macchina
   (per esempio LAB-PC o HOME-PC). Conservare lo stesso alias su quel PC.
4. Creare subito un file JSON in `docs/activity/sessions/` con un UUID nel nome:
   `YYYY-MM-DD_ALIAS_UUID.json`. Ogni sessione ha un file distinto; non usare
   un unico CSV condiviso che due PC devono modificare contemporaneamente.
5. Registrare lo scopo del lavoro, il ramo, lo SHA iniziale e, se disponibile,
   l'ID della conversazione/turno. Usare null per informazioni non disponibili.

## Durante il lavoro e prima della risposta finale

- Aggiornare il proprio file ai passaggi significativi: attività svolte,
  risultati dei test, errori, decisioni, commit e lavori rimasti aperti.
- Registrare intervalli di attività con timestamp ISO 8601 e offset esplicito.
  Usare `interactive`, `automatic`, `mixed` o `user_reported` come tipo.
  `mixed` indica una sessione il cui tempo umano e automatico non è separabile.
- Includere i processi automatici e i test durante la notte. Se un processo
  continua dopo la risposta, lasciarlo aperto e registrare la fonte con cui
  verificarne la conclusione (log o identificativo). Una risposta dell'agente
  non certifica che un processo in background sia terminato.
- Chiudere gli intervalli prima della risposta finale quando il lavoro è
  effettivamente concluso. Una nuova richiesta dopo una pausa apre un nuovo
  intervallo; non contare tutta la distanza fra due messaggi come attività.
- Se l'inizio è già trascorso, usare un timestamp attestato da conversazione o
  log; altrimenti registrare il primo istante osservato e dichiarare la lacuna.
- Un orario di presenza in laboratorio non dimostra da solo lavoro sul progetto:
  conservarlo come dichiarazione con attribuzione da confermare, se ambigua.
- Non ricavare durate dal numero di commit, dai token o dai costi. Se si adotta
  una stima o una durata dichiarata, conservarne chiaramente metodo e fonte.
- Scrivere riassunti e riferimenti sufficienti alla verifica. Non pubblicare
  conversazioni integrali, credenziali, token, dati personali o dati dei soggetti.

## Struttura dei file JSON

Usare questo schema come modello, sostituendo i segnaposto prima di salvare.
La durata è ricavata dagli intervalli: non mantenere totali manuali discordanti.

```json
{
  "schema_version": 1,
  "session_id": "UUID",
  "project": "PhysioViewerRT",
  "machine": "ALIAS-PC",
  "reporting_timezone": "Europe/Rome",
  "thread_id": null,
  "branch": "RAMO-EFFETTIVO",
  "head_at_start": "SHA-EFFETTIVO",
  "updated_at": "TIMESTAMP-ISO-CON-OFFSET",
  "status": "open",
  "summary": "Scopo e risultato del lavoro",
  "intervals": [
    {
      "id": "UUID-INTERVALLO",
      "started_at": "TIMESTAMP-ISO-CON-OFFSET",
      "ended_at": null,
      "kind": "mixed",
      "basis": "observed",
      "description": "Attività svolta",
      "evidence": ["Riferimento a turno, comando o log"],
      "source_event_id": null
    }
  ],
  "results": [],
  "commits": [],
  "open_items": [],
  "limitations": []
}
```

`status`: open, completed o interrupted. `basis`: observed, user_reported
o estimated. Con intervalli aperti il totale completo della sessione è ignoto.
Conservare gli ID originali durante copie e importazioni per deduplicare.
Una correzione deve spiegare in `limitations` il dato precedente e la fonte
del nuovo valore; non riscrivere arbitrariamente gli orari di un'altra macchina.

## Fine lavoro e sincronizzazione fra PC

1. Validare il JSON e controllare che fine >= inizio, con fuso esplicito.
2. Includere il registro nei commit di lavoro autorizzati, selezionando i file
   esplicitamente. Anche un'attività senza modifiche al software può avere un
   commit dedicato al registro.
3. Eseguire il push quando autorizzato dal compito/sessione. Non fare force push.
   Se il push è rifiutato, preservare il registro e integrare i cambiamenti
   remoti con il normale flusso Git; non sovrascrivere gli altri PC.
4. Nella risposta finale indicare il file aggiornato e se è stato pubblicato
   oppure è rimasto soltanto locale. Non dichiarare una sincronizzazione riuscita
   senza averne verificato l'esito.

Il solo pull di main non include registri ancora su altri rami: occorre integrarli
con merge/cherry-pick oppure includere quei rami nella raccolta centralizzata.
Non occorre incorporare funzionalità non pronte per raccogliere i loro registri.

## Riepilogo giornaliero e Google Sheet

- Raccogliere i file delle sessioni da tutti i PC/rami disponibili, deduplicando
  session_id, interval.id e source_event_id. La stessa sessione copiata su due
  checkout non è una seconda esecuzione.
- Convertire i timestamp in Europe/Rome e dividere gli intervalli a mezzanotte
  locale, rispettando il cambio fra ora legale e solare.
- Includere sia attività interattive sia esecuzioni automatiche/notturne.
- Produrre separatamente durata temporale del progetto (unione degli intervalli)
  e ore-macchina (unione per macchina, poi somma). Due PC contemporanei possono
  produrre due ore-macchina in un'ora: non sommare le due metriche fra loro.
  Per la colonna Ore usare il criterio esplicitamente concordato con l'utente;
  se non ancora definito per il parallelismo, riportare entrambe le metriche.
- Non convertire intervalli aperti, pause ignote o assenza di dati in ore certe.
  Evidenziare copertura, stime e dichiarazioni dell'utente.
- Il Google Sheet è un riepilogo aggiornabile su richiesta con il connettore
  disponibile; questo file non abilita da solo aggiornamenti automatici del foglio.

## Recupero dello storico su un nuovo PC

Quando richiesto, esaminare sessioni Codex attive/archiviate pertinenti, Git log,
reflog e log di test di tutti i checkout del progetto su quel PC. Includere rami
non pubblicati, in particolare `codex/organised-work-backup` se presente.
Importare soltanto dati verificabili con ID e fonti originali, conservando le
lacune. Non assegnare al PC corrente il lavoro importato da un'altra macchina.
L'importazione è distinta dalla sessione corrente e non va conteggiata due volte.

## Checkout unico su LAB-PC (decisione utente, 2026-11-10)

Su LAB-PC lavorare esclusivamente in C:\Users\brainlab.ext1\Desktop\GitHub Marco\PhysioViewerRT.
I precedenti worktree sotto Documents\ChatGPT\Signal Viewer LSL sono stati consolidati e vanno rimossi; non ricrearli o usarli per nuovi lavori. Usare sempre il checkout canonico, salvo successiva richiesta esplicita dell'utente.
