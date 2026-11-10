# Riferimento accelerometrico LSL e cancellazione adattativa

EEG, PPG e SC/EDA hanno un riferimento ACC opzionale indipendente nella pagina
Sources. Il riferimento è disattivato inizialmente. Nessuna nuova dipendenza.

## Uso

1. Avviare il publisher LSL del dispositivo e premere Refresh.
2. Scegliere il segnale primario e i suoi canali come di consueto.
3. Nel selettore ACC scegliere il riferimento del sensore associato a quella
   modalità. I nomi/tipi ACC, accelerometer, acceleration e IMU sono elencati
   prima degli altri stream. Il programma non presume l'associazione fisica.
4. Verificare i canali X/Y/Z (numerazione da 1). I metadati completi vengono
   letti in background; etichette come Acc X, Acc Y, Acc Z vengono riconosciute.
   Gli stream misti possono essere selezionati e mappati manualmente. I canali
   ACC non possono sovrapporsi ai canali primari quando il filtro è attivo.
5. Con il solo riferimento selezionato si leggono X/Y/Z in Sources, nelle unità
   numeriche pubblicate dal dispositivo, senza modificare il segnale.
   Attivare **Adaptive ACC (NLMS)** per applicare la cancellazione.
6. Premere Play. Cambiare riferimento, assi o attivazione su una modalità in
   acquisizione ne richiede automaticamente il riavvio asincrono. Durante una
   calibrazione il cambiamento resta differito, come per gli altri filtri.

Sources mostra stato e ultimi valori X/Y/Z; i pannelli Raw Data hanno uno stato
ACC con dettagli nel tooltip. I valori indicati come stale non sono dati nuovi.
Il refresh conserva una selezione temporaneamente assente dalla discovery.

## Pipeline e sincronizzazione

Ogni receiver possiede e chiude il proprio inlet ACC; uno stesso stream può
essere usato da più modalità, con filtri e coefficienti indipendenti. La GUI non
esegue letture LSL bloccanti. Entrambi gli inlet usano `proc_clocksync`.

Ordine di elaborazione: conversione del primario → **NLMS/ACC** → riduzione
periferica eventuale → filtri ordinari → ASR eventuale → metriche e traccia
elaborata. **IAF, baseline e training ASR ricevono il segnale già pulito da
NLMS.** La traccia grezza e i campioni primari registrati restano separati.
Il training ASR include l'identità della configurazione ACC: un modello addestrato
senza NLMS non viene applicato automaticamente a un ingresso con NLMS, o viceversa.

L'ACC viene allineato causalmente ai timestamp effettivi del primario, prima
del buffer Hampel/Wavelet. Per ogni campione si usa l'ultimo
riferimento non futuro; non si attende un campione ACC successivo. La validità
massima è min(250 ms, tre periodi ACC). Il buffer conserva 40 secondi.
Non si introduce un nuovo buffer di attesa nel segnale primario.

Il filtro multiriferimento NLMS usa tre assi, memoria FIR di 150 ms (2–64 tap
per asse), passo 0.03 e regolarizzazione 1e-8. L'ACC è centrato con un passa-alto
a 0.5 Hz per rimuovere la gravità statica. L'adattamento usa il primario centrato
a 0.1 Hz, ma la sottrazione mantiene il livello del segnale originale. Il primo
secondo serve all'adattamento; nel secondo la sottrazione viene introdotta
gradualmente. Non sono parametri validati per uno specifico sensore.

La versione `acc-nlms-v3-input` evita adattamento su un riferimento quasi nullo:
usa una soglia energetica legata al livello statico ACC (circa 5 milli-g se la
gravità è presente) e al picco recente. In quiete restituisce il primario senza
sottrazione, azzera i pesi e mostra `ACC monitoring: low motion`; alla ripresa
riavvia il warmup. Questa protezione impedisce la crescita dei coefficienti
nelle pause di movimento. L'uscita già registrata con v2 resta leggibile, ma
per il live v3 servono calibrazioni/training con la configurazione v3.

Riferimenti mancanti, obsoleti o non finiti producono bypass e reset
dell'adattamento. Anche i gap del primario azzerano lo stato. La ricezione
primaria continua. Un riferimento valido riavvia il warmup. La chiusura e lo
Stop rilasciano entrambi gli inlet.

## Limiti e calibrazioni

La cancellazione riguarda solo componenti spiegabili dal movimento misurato:
non sostituisce la riduzione di rumore indipendente dall'ACC. Può attenuare anche
componenti fisiologiche correlate al movimento. La scelta del sensore e la
verifica raw/processed sono essenziali. L'allineamento LSL non corregge latenze
hardware non dichiarate; il ricampionamento causale non è un filtro antialias.

Le nuove calibrazioni con NLMS usano il formato NPZ **schema 2**: conservano
il primario grezzo, l'uscita effettiva dello stadio NLMS allineata agli stessi
timestamp e la configurazione ACC (versione algoritmo, sorgente, assi e frequenza).
L'uscita catturata incorpora lo stato adattativo già appreso all'inizio della
registrazione. Il replay la usa direttamente come ingresso ai filtri ordinari
e ad ASR; non riavvia NLMS da zero e non lo applica due volte.

EYC stima IAF sul segnale pulito; BSL calcola i riferimenti EEG, HR e SCL sullo
stesso percorso e permette normalizzazione ed EI quando le configurazioni
corrispondono. I buffer periferici preservano l'associazione fra grezzo,
uscita NLMS e timestamp. File con campioni post-NLMS mancanti, non finiti o di
forma errata vengono rifiutati, senza ripiegare sul grezzo.

Le calibrazioni senza ACC mantengono schema 1 e restano leggibili. Un'EYC/BSL
precedente senza lo stadio pulito non può essere trasformata retroattivamente
in una calibrazione con ACC: occorre registrarla con la configurazione richiesta.
Il replay EEG con NLMS disattivato può usare il grezzo conservato. Modificare
sensore, assi o algoritmo richiede una nuova calibrazione e un training ASR
coerente. I file non conservano il flusso ACC originale per sperimentare offline
coefficienti/algoritmi differenti; conservano l'esatto risultato NLMS del live.

## Verifica e fonti

I test coprono attenuazione di un artefatto sintetico correlato, indipendenza
dalla suddivisione in chunk, gravità costante, frequenze diverse, timestamp
futuri, drop-out/NaN, ripresa e mantenimento del grezzo. Test Qt/LSL usano
publisher locali reali per le tre modalità e verificano bypass e cleanup.
I test di calibrazione verificano ordine NLMS → filtri → ASR, IAF del segnale
pulito, baseline delle tre modalità, normalizzazione compatibile e identità
dei risultati dopo salvataggio/ricaricamento schema 2.
Questi test non certificano prestazioni su dispositivi fisici o reti fra PC.

- [Equazione NLMS, MathWorks](https://www.mathworks.com/help/dsp/ref/lmsupdate.html)
- [Cancellazione con riferimento, MathWorks](https://www.mathworks.com/help/dsp/ug/acoustic-noise-cancellation-lms.html)
- [Sincronizzazione LSL](https://labstreaminglayer.readthedocs.io/info/time_synchronization.html)

## Generatore sintetico con ACC

Il simulatore pubblica sei stream con un'unica origine temporale LSL:

| Segnale | Stream primario | Riferimento ACC | Frequenza ACC |
| --- | --- | --- | --- |
| EEG | SimulatedEEG (256 Hz, 32 canali) | SimulatedEEG_ACC | 64 Hz |
| PPG | SimulatedPPG (128 Hz) | SimulatedPPG_ACC | 64 Hz |
| SC | SimulatedEDA (32 Hz) | SimulatedEDA_ACC | 32 Hz |

Gli ACC hanno tipo `Accelerometer`, canali `AccX`, `AccY`, `AccZ`, unità `m/s^2`
e gravità statica su Z. I metadati collegano ciascun riferimento al source_id
del primario. In Sources scegliere il riferimento della stessa modalità;
gli assi 1/2/3 vengono riconosciuti dalle etichette.

Per isolare il movimento dagli altri artefatti:

```powershell
.\project.cmd simulate -- --artifacts none --motion strong
```

`--motion none|mild|moderate|strong` controlla sia ACC sia contaminazione;
il simulatore interattivo usa `moderate` come default. `--artifacts` controlla
separatamente i disturbi preesistenti (blink, EMG e disturbi di contatto/sensore),
che non sono tutti spiegabili dall'ACC. Per il segnale senza questi due gruppi
di artefatti usare `--artifacts none --motion none`; resta il rumore fisiologico
sintetico di fondo. Con movimento disattivato gli ACC continuano a pubblicare
la gravità costante. `--seed` rende la simulazione ripetibile; `--seconds 80`
la termina automaticamente. Anche `simulate_windows.cmd` inoltra questi argomenti.

Il movimento inizia a 8 s (EEG), 11 s (PPG), 14 s (SC): episodi di 18 s con
attacco/rilascio graduale e periodo di 36 s. Ogni sensore combina movimento
comune e locale con fasi proprie. La contaminazione deriva dagli stessi campioni
ACC float32 pubblicati, con accoppiamento causale a ritardi 0/1/3 campioni,
pesi diversi per modalità/canale e guadagno lentamente variabile.

Il test su 80 s, seed 2026, movimento strong e altri artefatti disattivati,
confronta l'uscita NLMS con la stessa fisiologia senza movimento. Sui tratti di
movimento sostenuto la potenza dell'errore si riduce di circa 10.53 dB (EEG),
9.78 dB (PPG) e 7.83 dB (SC). Sono risultati del modello sintetico controllato,
non stime di efficacia su sensori o persone. I test verificano anche riposo,
ripresa, indipendenza dai chunk e discovery/ricezione LSL dei sei stream.

La classe `SyntheticPhysiology` mantiene `motion_level='none'` come default
per compatibilità con fixture e benchmark esistenti; `simulate.py` abilita
esplicitamente il movimento. `generate_acc()` avanza un clock separato per
riferimento; `motion_artifact()` espone la contaminazione nota per i confronti.


## Calibrazione statica ACC

In Sources selezionare riferimento e assi, quindi **Calibra zero ACC — Stai fermo (5 s)**.
Il pulsante permette di annullare; la chiusura richiede cancellazione cooperativa.
Si raccolgono campioni nuovi, continui e finiti su un worker, con timeout di 12 s.
La mediana X/Y/Z definisce lo zero statico; 1,5 volte il percentile 99 della
norma dei residui definisce il limite di rumore a riposo. Movimento eccessivo
(95° percentile oltre il 5% della gravità misurata) richiede di ripetere la prova.
Questo controllo non distingue ogni movimento lento dal rumore: restare fermi.

La norma del vettore statico stima **1 g nelle unità dello stream**.
La UI mostra tale fattore e il limite di rumore in mg (1000 mg = 1 g).
Non è una verifica metrologica: presuppone accelerometro con gravità inclusa,
assi nella stessa scala e offset strumentali piccoli rispetto a g; non usare
giroscopi o accelerazione già privata della gravità. Le unità originali non
sono determinate automaticamente da questa misura.

Per il riferimento calibrato il gate usa l'energia media della norma XYZ
sulla storia FIR: la soglia effettiva è almeno il massimo tra soglia scelta
e rumore calibrato; resta inoltre il gate relativo adattativo preesistente.
Lo zero viene sottratto prima della rimozione lenta della componente DC.
I campioni raw e la loro visualizzazione restano nelle unità originarie.

La calibrazione vive nella sessione, si invalida cambiando sorgente o assi,
e viene inclusa nella provenienza delle registrazioni con ACC attivo.
Le registrazioni precedenti restano leggibili.
