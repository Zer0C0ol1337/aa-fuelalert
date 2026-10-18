"""Alliance Auth hooks: menu entry and URLs."""

from django.utils.translation import gettext_lazy as _

from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook

from . import urls


class FuelAlertMenuItem(MenuItemHook):
    """Menu entry, shown to everyone with fuelalert.basic_access (no DB query on render)."""

    def __init__(self):
        """Set label, icon and target of the menu entry."""
        MenuItemHook.__init__(
            self,
            _("Fuel Alert"),
            "fas fa-gas-pump fa-fw",
            "fuelalert:index",
            navactive=["fuelalert:"],
        )

    def render(self, request):
        """Only render the entry for users with access."""
        if request.user.has_perm("fuelalert.basic_access"):
            return MenuItemHook.render(self, request)
        return ""


@hooks.register("menu_item_hook")
def register_menu():
    """Register the menu entry."""
    return FuelAlertMenuItem()


@hooks.register("url_hook")
def register_urls():
    """Register the app URLs under /fuelalert/."""
    return UrlHook(urls, "fuelalert", r"^fuelalert/")
