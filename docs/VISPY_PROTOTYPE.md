# Experimental VisPy/OpenGL Raw Data renderer

This branch tests a GPU presentation path inspired by the architecture of
[Intheon's StreamViewer](https://github.com/intheon/stream_viewer).
No StreamViewer package or code is vendored.

## Windows quick start

```powershell
git fetch origin
git switch experiment/vispy-raw-renderer
git pull origin experiment/vispy-raw-renderer
python -m pip install -r requirements.txt -r requirements-vispy.txt
$env:PHYSIOLAB_PROFILE = "1"
.\start_windows.cmd
```

In **Raw Data**, select **Waveform renderer → VisPy / OpenGL
(experimental)**. Switch back to **pyqtgraph (original)** without restarting.

Compare under identical synthetic EEG (32 channels, 256 Hz), EDA (32 Hz),
and PPG (128 Hz) loads for 60–120 seconds per renderer. Record GUI FPS,
hangs, CPU/GPU utilization, and whether traces appear and scroll smoothly.
Keep the same window size, visible channels, time window and tab.

## Prototype scope and limitations

- Acquisition, channel selection, calibration, metrics, and history are unchanged.
- VisPy is optional; pyqtgraph remains the default.
- One GPU line visual per layer (raw/filtered) per modality. Segment geometry
  is assembled from the existing background-prepared waveform arrays.
- OpenGL initialization can fail on unsupported graphics drivers; the
  selector falls back to pyqtgraph.
- GPU mode supports live following and time-window controls, but not mouse
  panning/wheel zoom or the original pyqtgraph grid/axes.
- This is not a benchmark result. Performance and Windows OpenGL stability
  require testing on the target notebook.

Run geometry tests without VisPy:

```powershell
python -m unittest discover -s tests -p "test_vispy_raw.py"
```
