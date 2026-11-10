"""Small Tk GUI that launches muse-lsl in a stoppable child process."""
import argparse
import contextlib
import io
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk


def scan_muses():
    """Discover nearby Muse devices through muse-lsl's Bleak backend."""
    from muselsl import list_muses

    with contextlib.redirect_stdout(io.StringIO()):
        return list_muses(backend="bleak") or []


def stream_muse(address, name, ppg, acc, gyro, model):
    """Blocking worker entry point; the parent process owns cancellation."""
    from muselsl import stream

    stream(
        address=address,
        name=name,
        backend="bleak",
        model=model,
        ppg_enabled=ppg,
        acc_enabled=acc,
        gyro_enabled=gyro,
        retries=0,
    )


class App:
    def __init__(self, root):
        self.root = root
        root.title("Muse → LSL")
        root.geometry("610x330")
        root.minsize(550, 300)
        self.events = queue.Queue()
        self.devices = []
        self.process = None
        self.closing = False

        panel = ttk.Frame(root, padding=20)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="Muse → LSL", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(panel, text="Muse 2 · Muse S · Muse S Athena · Bluetooth LE").pack(anchor="w", pady=(3, 15))

        row = ttk.Frame(panel)
        row.pack(fill="x")
        ttk.Label(row, text="Muse vicino").pack(side="left")
        self.device = ttk.Combobox(row, state="readonly", width=52)
        self.device.pack(side="left", padx=10, fill="x", expand=True)
        self.refresh_button = ttk.Button(row, text="Cerca", command=self.refresh)
        self.refresh_button.pack(side="left")

        self.ppg = tk.BooleanVar(value=True)
        self.acc = tk.BooleanVar(value=False)
        self.gyro = tk.BooleanVar(value=False)
        options = ttk.Frame(panel)
        options.pack(anchor="w", pady=14)
        self.option_controls = (
            ttk.Checkbutton(options, text="PPG / ottica", variable=self.ppg),
            ttk.Checkbutton(options, text="Accelerometro", variable=self.acc),
            ttk.Checkbutton(options, text="Giroscopio", variable=self.gyro),
        )
        for control, padding in zip(self.option_controls, ((0, 14), (0, 14), 0)):
            control.pack(side="left", padx=padding)

        row = ttk.Frame(panel)
        row.pack(fill="x", pady=(0, 13))
        self.start_button = ttk.Button(row, text="Avvia stream LSL", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(row, text="Ferma", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=10)
        self.status = tk.StringVar(value="Pronto. Accendi il Muse e premi Cerca.")
        ttk.Label(panel, textvariable=self.status, wraplength=550).pack(anchor="w")
        ttk.Label(panel, text="In PhysioViewerRT: Aggiorna LSL e seleziona lo stream Muse con tipo EEG, PPG, accelerometro o giroscopio.", wraplength=550).pack(anchor="w", pady=(12, 0))

        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)
        self.refresh()

    def refresh(self):
        if self.process is not None:
            return
        self.refresh_button.configure(state="disabled")
        self.status.set("Ricerca Bluetooth in corso…")

        def work():
            try:
                self.events.put(("devices", scan_muses()))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def start(self):
        index = self.device.current()
        if index < 0 or index >= len(self.devices):
            messagebox.showerror("Seleziona un Muse", "Accendi il dispositivo e premi Cerca.")
            return
        muse = self.devices[index]
        command = [
            sys.executable, "-m", "muse_lsl", "--stream-worker",
            "--address", str(muse["address"]), "--name", str(muse.get("name", "Muse")),
            "--model", "auto",
        ]
        for enabled, flag in ((self.ppg.get(), "--ppg"), (self.acc.get(), "--acc"), (self.gyro.get(), "--gyro")):
            if enabled:
                command.append(flag)
        try:
            self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        except Exception as exc:
            self.status.set(f"Errore di avvio: {exc}")
            return
        self.set_stream_controls(False)
        self.stop_button.configure(state="normal")
        self.status.set(f"Connessione a {muse.get('name', 'Muse')}…")
        threading.Thread(target=self.read_output, args=(self.process,), daemon=True).start()

    def read_output(self, process):
        try:
            for line in process.stdout:
                line = line.strip()
                if line:
                    self.events.put(("output", line))
            code = process.wait()
            self.events.put(("stopped", code))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def stop(self):
        process = self.process
        if process is not None and process.poll() is None:
            self.status.set("Arresto stream…")
            process.terminate()

    def set_stream_controls(self, enabled):
        state = "normal" if enabled else "disabled"
        self.device.configure(state="readonly" if enabled else "disabled")
        self.refresh_button.configure(state=state)
        self.start_button.configure(state=state)
        for control in self.option_controls:
            control.configure(state=state)

    def poll(self):
        while True:
            try:
                key, value = self.events.get_nowait()
            except queue.Empty:
                break
            if key == "devices":
                self.devices = value
                labels = [f"{m.get('name', 'Muse')} · {m.get('address', '')}" for m in value]
                self.device["values"] = labels
                if labels:
                    self.device.current(0)
                    self.status.set(f"Trovati {len(labels)} Muse. Seleziona il dispositivo e avvia lo stream.")
                else:
                    self.device.set("")
                    self.status.set("Nessun Muse trovato. Accendilo, chiudi l'app Muse sul telefono e riprova.")
                self.refresh_button.configure(state="normal")
            elif key == "output":
                self.status.set(value)
            elif key == "error":
                self.status.set(f"Errore: {value}")
                self.refresh_button.configure(state="normal")
            elif key == "stopped":
                self.process = None
                self.stop_button.configure(state="disabled")
                self.set_stream_controls(True)
                self.status.set("Stream terminato." if value == 0 else f"Stream terminato con codice {value}. Controlla Bluetooth e stato del Muse.")
                if self.closing:
                    self.root.destroy()
                    return
        self.root.after(100, self.poll)

    def close(self):
        self.closing = True
        if self.process is not None and self.process.poll() is None:
            self.stop()
        else:
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="Muse Bluetooth LE to LSL")
    parser.add_argument("--stream-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--address", default="")
    parser.add_argument("--name", default="Muse")
    parser.add_argument("--model", default="auto")
    parser.add_argument("--ppg", action="store_true")
    parser.add_argument("--acc", action="store_true")
    parser.add_argument("--gyro", action="store_true")
    args = parser.parse_args()
    if args.stream_worker:
        if not args.address:
            parser.error("--address is required for stream worker")
        stream_muse(args.address, args.name, args.ppg, args.acc, args.gyro, args.model)
        return 0
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
