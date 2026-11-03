# Riprendere PhysioViewerRT su un altro PC

La repository contiene codice, istruzioni Codex, dipendenze e registro attività.
Ogni checkout mantiene il proprio ambiente Python e i propri dati locali.
Non è necessario usare lo stesso nome utente o percorso sui diversi computer.

## Windows: primo avvio o aggiornamento

Prerequisiti: Git e Python 3.12 x64 (il riferimento verificato è 3.12.10).
Aprire in Codex la cartella della repository come cartella principale del progetto.
Dopo il clone, oppure dopo un pull senza conflitti sul ramo di lavoro:

```powershell
.\setup_windows.cmd --non-interactive
.\project.cmd doctor --gui
```

Il setup crea `.venv` se assente, installa il profilo fissato in
`requirements-lock-windows-py312.txt`, verifica i pacchetti e costruisce la finestra
Qt in modalità offscreen. Le dipendenze opzionali ASR, Affect e VisPy sono incluse.
Il profilo riproduce le versioni del PC di riferimento; non uniforma driver GPU,
dispositivi, firewall o rete LSL. Il setup non installa Python, Git o driver.
Una `.venv` copiata, incompleta o incompatibile non viene cancellata automaticamente:
preservarla/rinominarla e ricrearla localmente. Con Python 3.11 il profilo automatico
usa i vincoli generali di `requirements.txt`, non il lock Windows/Python 3.12.

```powershell
.\project.cmd run
.\project.cmd simulate
.\project.cmd simulate -- --artifacts strong --seed 2026
.\project.cmd test
.\project.cmd test --gui
```

I comandi funzionano anche se invocati da un'altra cartella; usano sempre la radice
della repository e la sua `.venv`. Gli script storici start_windows.cmd e
simulate_windows.cmd restano disponibili. Il setup si può ripetere dopo un pull.
Quando cambiano le dipendenze, aggiornare e verificare anche il lock, non soltanto
requirements.txt. `pip check` verifica la compatibilità dei pacchetti installati.

## macOS e Linux

Usare Python 3.11/3.12 x64 e le dipendenze di sistema richieste da Qt/OpenGL e LSL:

```sh
python3 tools/project_env.py setup --profile portable
python3 tools/project_env.py doctor --gui
python3 tools/project_env.py run
```

Questo percorso usa i vincoli multipiattaforma di requirements.txt. Non è un lock
identico a quello Windows e deve essere verificato su ciascun sistema operativo.
Il comando doctor non installa librerie di sistema e segnala gli import falliti.

## Codex su ogni macchina

- Selezionare la repository come cartella principale del progetto, non una
  cartella contenitore esterna. Dopo il primo pull avviare una nuova conversazione
  perché le istruzioni AGENTS.md siano caricate dall'inizio.
- Usare AGENTS.md per il registro attività e TODO.md per il passaggio di consegne.
- `.codex/environments/environment.toml` contiene il setup e le azioni Windows
  condivise di Codex. Aprire la repository come cartella principale per caricarle.
  Questo manifest usa `cmd`: su macOS/Linux configurare le azioni con Python,
  usando la procedura multipiattaforma sopra. La configurazione Windows usa
  `cmd /c setup_windows.cmd --non-interactive`; le azioni eseguono
  `cmd /c project.cmd doctor --gui`, `cmd /c project.cmd run` e
  `cmd /c project.cmd test`. Su macOS/Linux usare i comandi Python sopra riportati.
- La configurazione delle cartelle, il login e le connessioni ai servizi sono
  locali. Questo setup non copia le conversazioni o le credenziali di Codex.
- Prima di cambiare PC: aggiornare TODO e registro, fare commit e push sul ramo
  concordato. Sul secondo PC recuperare quel ramo, non presumere che sia main.
- Due PC che lavorano contemporaneamente dovrebbero usare rami separati e file
  di sessione distinti. Integrare i registri anche se le funzionalità sono ancora
  in sviluppo, mantenendo gli ID per evitare doppi conteggi.

## Dati e diagnostica locali

`.venv/`, `.local/`, `.test-tmp/`, `.env` e le calibrazioni predefinite
`bsl_calibration.npz` / `eyc_calibration.npz` non vengono pubblicati con Git.
I file di calibrazione già presenti restano al loro posto; trasferirli separatamente
quando necessario e verificare che corrispondano a dispositivo e preprocessing.
Altri nomi di registrazioni/dati vanno esclusi esplicitamente prima del commit.

`doctor` salva `.local/environment.json` con versioni e risultati; conservarlo
localmente per confrontare due PC. Include percorsi locali, quindi non viene
aggiunto automaticamente alla repository. Il test offscreen non certifica il
rendering GPU nativo o l'acquisizione da hardware reale: verificare anche Play,
selezione stream, ASR e Wavelet sul PC di destinazione.

Il benchmark di confronto richiede un checkout baseline esplicito:
`python tools/benchmark_rendering_matrix.py --baseline PERCORSO_BASELINE`.
Non esiste più un percorso fisso verso il PC dello sviluppatore.
