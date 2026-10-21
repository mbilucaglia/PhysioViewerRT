"""Shared clean VisPy scene, axes policy, and blue sweep cursor.

The same presentation engine hosts both Raw Data and Metrics.
"""
import numpy as np


class VisPyPlotEngine:
    """White, borderless, full-canvas OpenGL plot with an optional sweep cursor."""

    def __init__(self, x_label='Time (s)', y_label='Value', size=(900, 350),
                 show_axes=False):
        from vispy import scene
        self.scene = scene
        self.canvas = scene.SceneCanvas(
            keys=None, show=False, bgcolor='white', size=size, app='pyside6'
        )
        self.widget = self.canvas.native
        self.xaxis = self.yaxis = self.gridlines = None
        if show_axes:
            grid = self.canvas.central_widget.add_grid(margin=4, spacing=3)
            self.yaxis = scene.AxisWidget(
                orientation='left', axis_label=y_label,
                text_color='#303030', axis_color='#888888',
                tick_color='#888888')
            self.xaxis = scene.AxisWidget(
                orientation='bottom', axis_label=x_label,
                text_color='#303030', axis_color='#888888',
                tick_color='#888888')
            grid.add_widget(self.yaxis, row=0, col=0)
            grid.add_widget(self.xaxis, row=1, col=1)
            self.view = grid.add_view(row=0, col=1)
            self.yaxis.width_max = 74
            self.xaxis.height_max = 55
        else:
            self.view = self.canvas.central_widget.add_view()
        self.view.camera = scene.PanZoomCamera(rect=(0, 0, 1, 1), aspect=None)
        self.view.camera.interactive = False
        if show_axes:
            self.xaxis.link_view(self.view)
            self.yaxis.link_view(self.view)
        self.sweep_cursor = self.line('#1769e0', width=2)
        self.sweep_cursor.visible = False
        self._y_bounds = (0., 1.)
        # Restrained in-scene axes, no heavy AxisWidget margins.
        self.axis_x = self.line('#d0d7df', width=1)
        self.axis_y = self.line('#d0d7df', width=1)
        self._axis_x_labels = [self.text(color='#607386', size=9) for _ in range(3)]
        self._axis_y_labels = [self.text(color='#607386', size=9) for _ in range(3)]
        self._axis_duration = None
        self._axis_range = None
        self.set_axis_labels(duration=5., bounds=(0., 1.))

    def line(self, color='black', width=1):
        return self.scene.visuals.Line(
            parent=self.view.scene, color=color, method='gl',
            connect='segments', width=width, antialias=False)

    def markers(self):
        return self.scene.visuals.Markers(parent=self.view.scene)

    def text(self, text='', pos=(0, 0), color='#303030', size=11):
        return self.scene.visuals.Text(
            text=text, pos=pos, color=color, font_size=size,
            anchor_x='left', anchor_y='center', parent=self.view.scene)

    def set_view(self, left, right, bottom, top):
        if right <= left or top <= bottom:
            return
        self._y_bounds = (float(bottom), float(top))
        # Never introspect the bounds of empty VisPy Markers.
        self.view.camera.rect = (float(left), float(bottom),
                                 float(right-left), float(top-bottom))
        self.canvas.update()

    def set_axis_labels(self, duration=None, bounds=None):
        """Minimal time and vertical-value labels, with no tick marks."""
        if duration is not None and duration > 0 and duration != self._axis_duration:
            self._axis_duration = float(duration)
            for label, phase in zip(self._axis_x_labels, (.1, .5, .9)):
                label.text = f'{phase * duration:g} s'
                label.pos = (phase, self._y_bounds[0] +
                             .03*(self._y_bounds[1]-self._y_bounds[0]))
        if bounds is not None:
            bottom, top = float(bounds[0]), float(bounds[1])
            if top > bottom and (bottom, top) != self._axis_range:
                self._axis_range = (bottom, top)
                self.axis_x.set_data(pos=np.array(
                    [[.025, bottom+.09*(top-bottom)], [.985, bottom+.09*(top-bottom)]],
                    dtype=np.float32))
                self.axis_y.set_data(pos=np.array(
                    [[.025, bottom+.09*(top-bottom)], [.025, bottom+.97*(top-bottom)]],
                    dtype=np.float32))
                for label, phase in zip(self._axis_y_labels, (.25, .5, .75)):
                    label.text = f'{bottom + phase*(top-bottom):.2g}'
                    label.pos = (.04, bottom + phase*(top-bottom))
                for label, phase in zip(self._axis_x_labels, (.1, .5, .9)):
                    label.pos = (phase, bottom+.035*(top-bottom))
        self.canvas.update()

    def set_channel_labels(self, names):
        """Update labels used by raw EEG/PPG/EDA; safe during stream reset."""
        names = tuple(str(name) for name in names)
        if not hasattr(self, '_channel_labels'):
            self._channel_labels = []
        while len(self._channel_labels) < len(names):
            self._channel_labels.append(self.text(color='#526272', size=9))
        for index, label in enumerate(self._channel_labels):
            label.visible = index < len(names)
            if index < len(names):
                label.text = names[index]
                label.pos = (.002, (6.*index+1.) /
                             max(6.*len(names)+3., 6.))
        self.canvas.update()

    def set_sweep_cursor(self, phase):
        """Thin blue line; no white erase band is drawn."""
        phase = float(phase)
        if not np.isfinite(phase):
            self.sweep_cursor.visible = False
            return
        low, high = self._y_bounds
        x = min(1., max(0., phase))
        pos = np.array([[x, low], [x, high]], dtype=np.float32)
        self.sweep_cursor.set_data(pos=pos, color='#1769e0',
                                   connect='segments')
        self.sweep_cursor.visible = True
        self.canvas.update()

    def close(self):
        self.canvas.close()
