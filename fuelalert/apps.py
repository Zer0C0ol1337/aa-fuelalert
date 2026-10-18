"""App configuration for aa-fuelalert."""

from django.apps import AppConfig

from . import __version__


class FuelAlertConfig(AppConfig):
    """Django app config. Intentionally does nothing in ready() (no DB writes at startup)."""

    name = "fuelalert"
    label = "fuelalert"
    verbose_name = f"Fuel Alert v{__version__}"
    default_auto_field = "django.db.models.AutoField"
