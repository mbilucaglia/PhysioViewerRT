"""Shared VisPy canvas, axes, grid, GPU lines and viewport.

Both waveform and metrics adapters use this scene; only how they prepare
coordinates differs. No VisPy dependency is required for pyqtgraph fallback.
"""


class VisPyPlotEngine:
    """Common visual shell for time-series displays."""

    AXIS_WIDTH = 74
    AXIS_HEIGHT = 55

    def __init__(self, x_label='Time (s)', y_label='Value', size=(900, 350)):
        from vispy import scene
        self.scene = scene
        self.canvas = scene.SceneCanvas(
            keys=None, show=False, bgcolor='white', size=size,
            app='pyside6',
        )
        self.widget = self.canvas.native
        self.grid = self.canvas.central_widget.add_grid(margin=4, spacing=3)
        self.yaxis = scene.AxisWidget(
            orientation='left', axis_label=y_label,
            text_color='#252525', axis_color='#555555',
            tick_color='#777777',
        )
        self.xaxis = scene.AxisWidget(
            orientation='bottom', axis_label=x_label,
            text_color='#252525', axis_color='#555555',
            tick_color='#777777',
        )
        self.grid.add_widget(self.yaxis, row=0, col=0)
        self.grid.add_widget(self.xaxis, row=1, col=1)
        self.view = self.grid.add_view(row=0, col=1, border_color='#cccccc')
        # Axis sizing properties belong to the widgets, not AxisVisual.
        self.yaxis.width_max = self.AXIS_WIDTH
        self.xaxis.height_max = self.AXIS_HEIGHT
        self.view.camera = scene.PanZoomCamera(rect=(0, -1, 5, 2), aspect=None)
        self.view.camera.interactive = False
        self.xaxis.link_view(self.view)
        self.yaxis.link_view(self.view)
        self.gridlines = scene.visuals.GridLines(
            parent=self.view.scene, color=(.65, .65, .65, .13),
        )

    def line(self, color='black', width=1):
        return self.scene.visuals.Line(
            parent=self.view.scene, color=color,
            method='gl', connect='segments', width=width,
            antialias=False,
        )

    def markers(self):
        return self.scene.visuals.Markers(parent=self.view.scene)

    def text(self, text='', pos=(0, 0), color='#303030', size=11):
        return self.scene.visuals.Text(
            text=text, pos=pos, color=color, font_size=size,
            anchor_x='left', anchor_y='center', parent=self.view.scene,
        )

    def set_view(self, left, right, bottom, top):
        if right <= left or top <= bottom:
            return
        # Direct assignment never queries empty GL marker bounds.
        self.view.camera.rect = (
            float(left), float(bottom), float(right-left), float(top-bottom)
        )
        self.canvas.update()

    def close(self):
        self.canvas.close()
