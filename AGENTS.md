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
