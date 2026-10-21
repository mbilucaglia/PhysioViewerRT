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
