"""Forms for aa-fuelalert."""

from django import forms
from django.utils.translation import gettext_lazy as _

from allianceauth.eveonline.models import EveCorporationInfo

from .models import Recipient


class RecipientForm(forms.ModelForm):
    """Alert settings of the current user; corp choices are limited to corps the user may see."""

    corporations = forms.ModelMultipleChoiceField(
        queryset=EveCorporationInfo.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label=_("Corporations"),
    )

    class Meta:
        model = Recipient
        fields = ["channel", "telegram_user", "phone", "api_key", "enabled", "corporations"]
        widgets = {
            "channel": forms.RadioSelect,
            "telegram_user": forms.TextInput(attrs={"placeholder": "@your_telegram_name"}),
            "phone": forms.TextInput(attrs={"placeholder": "+491701234567"}),
            "api_key": forms.PasswordInput(render_value=True),
        }

    def __init__(self, *args, corporations_qs=None, **kwargs):
        """Takes the queryset of corporations the user is allowed to subscribe to."""
        super().__init__(*args, **kwargs)
        if corporations_qs is not None:
            self.fields["corporations"].queryset = corporations_qs.order_by(
                "corporation_name"
            )
