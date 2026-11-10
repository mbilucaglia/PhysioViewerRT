# Muse → LSL

Piccolo programma Windows per individuare un Muse via Bluetooth LE e pubblicare
i suoi sensori come stream Lab Streaming Layer. Il collegamento BLE e la
decodifica sono forniti da `muse-lsl`; l'ambiente è separato da quello principale
di PhysioViewerRT.

## Avvio

1. Accendi Muse 2 o Muse S e disconnettilo dall'app Muse sul telefono/tablet.
2. Esegui `setup_muse_lsl.cmd` una sola volta.
3. Esegui `run_muse_lsl.cmd`, scegli il dispositivo trovato e premi **Avvia stream LSL**.
4. In PhysioViewerRT premi **Aggiorna LSL** e scegli lo stream `Muse` di tipo
   `EEG`; i sensori abilitati sono stream separati, anch'essi con nome `Muse` e
   tipo rispettivamente `PPG`, `accelerometer` e `gyroscope`.
5. Premi **Ferma** prima di chiudere l'app.

L'EEG è attivo per impostazione predefinita. PPG/ottica, accelerometro e
giroscopio sono facoltativi. PPG è disponibile su Muse 2 e Muse S; Athena usa
il proprio protocollo e può esporre lo stream ottico con una disposizione dei
canali diversa. La scelta automatica del modello è passata al backend.

Il Bluetooth del computer deve supportare BLE. Se la scansione non trova il
dispositivo, chiudi ogni app che lo sta già usando, controlla che sia acceso e
premi **Cerca**. La finestra deve restare aperta per mantenere gli stream LSL.

## Dipendenze e backend

`setup_muse_lsl.cmd` crea `.venv-muse` e installa la versione fissata di
`muse-lsl`. Questa dipendenza non modifica `requirements.txt` o il lock
Windows/Python 3.12 dell'app principale.

Il backend `muse-lsl` documenta il supporto a Muse 2 e Muse S, utilizza Bleak
per la connessione BLE e pubblica i sensori in LSL. Per i dettagli sui modelli,
firmware e limitazioni, consultare il [README del progetto muse-lsl](https://github.com/alexandrebarachant/muse-lsl)
e la [documentazione di BlueMuse su Muse S Athena](https://github.com/kowalej/BlueMuse#-muse-s-athena).

La connessione con hardware reale non è stata provata in questa sessione.
