"""Quick Image Search package.

TFM registers the docker. Importing this package does not add a Krita plugin
or a second copy of the panel.
"""


def register(app):
    from krita import DockWidgetFactory, DockWidgetFactoryBase
    from .docker import ImageSearchDocker
    app.addDockWidgetFactory(
        DockWidgetFactory(
            "quick_image_search",
            DockWidgetFactoryBase.DockPosition.DockRight,
            ImageSearchDocker,
        )
    )
