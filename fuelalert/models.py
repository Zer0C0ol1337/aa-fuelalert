"""Models for aa-fuelalert."""

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from allianceauth.eveonline.models import EveCorporationInfo

phone_validator = RegexValidator(
    regex=r"^\+\d{7,15}$",
    message=_("Phone number in international format, e.g. +491701234567"),
)

telegram_validator = RegexValidator(
    regex=r"^@?[A-Za-z0-9_]{5,32}$",
    message=_("Telegram username, e.g. @dave_eve (5-32 letters, digits or _)"),
)


class General(models.Model):
    """Unmanaged model that only carries the app permissions."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = (("basic_access", _("Can access Fuel Alert")),)


class Recipient(models.Model):
    """Alert settings of one user (one entry per user): channel, contact data and corps."""

    class Channel(models.TextChoices):
        """Where alerts are delivered."""

        WHATSAPP = "whatsapp", _("WhatsApp")
        TELEGRAM = "telegram", _("Telegram")

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="fuelalert_recipient"
    )
    channel = models.CharField(
        max_length=16,
        choices=Channel.choices,
        default=Channel.WHATSAPP,
        verbose_name=_("channel"),
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        validators=[phone_validator],
        verbose_name=_("WhatsApp phone number"),
    )
    api_key = models.CharField(
        max_length=64, blank=True, verbose_name=_("CallMeBot WhatsApp API key")
    )
    telegram_user = models.CharField(
        max_length=33,
        blank=True,
        validators=[telegram_validator],
        verbose_name=_("Telegram username"),
    )
    enabled = models.BooleanField(default=True, verbose_name=_("enabled"))
    corporations = models.ManyToManyField(
        EveCorporationInfo,
        blank=True,
        related_name="+",
        verbose_name=_("corporations"),
        help_text=_("Corporations whose structures you want alerts for"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_permissions = ()
        verbose_name = _("recipient")
        verbose_name_plural = _("recipients")

    def __str__(self) -> str:
        """Readable name for admin and logs (no contact data)."""
        return f"Recipient of {self.user}"

    def clean(self):
        """Require the contact data of the chosen channel; normalize the Telegram name to @name."""
        super().clean()
        if self.telegram_user and not self.telegram_user.startswith("@"):
            self.telegram_user = f"@{self.telegram_user}"
        if self.channel == self.Channel.WHATSAPP:
            errors = {}
            if not self.phone:
                errors["phone"] = _("Required for WhatsApp.")
            if not self.api_key:
                errors["api_key"] = _("Required for WhatsApp.")
            if errors:
                raise ValidationError(errors)
        elif self.channel == self.Channel.TELEGRAM and not self.telegram_user:
            raise ValidationError({"telegram_user": _("Required for Telegram.")})

    @property
    def phone_masked(self) -> str:
        """Phone number with all but the last three digits hidden (safe for logs/admin lists)."""
        if not self.phone:
            return "-"
        return f"{'*' * max(len(self.phone) - 3, 0)}{self.phone[-3:]}"

    @property
    def contact_display(self) -> str:
        """Short, non-sensitive description of where alerts go (for admin lists)."""
        if self.channel == self.Channel.TELEGRAM:
            return f"Telegram {self.telegram_user}"
        return f"WhatsApp {self.phone_masked}"


class AlertLog(models.Model):
    """Remembers which alert was already sent for a structure, so nothing is sent twice."""

    structure_id = models.BigIntegerField(db_index=True)
    key = models.CharField(max_length=16)  # "t24" = threshold 24h, "offline" = out of fuel
    fuel_expires = models.DateTimeField(null=True, default=None)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["structure_id", "key"], name="fuelalert_unique_structure_key"
            )
        ]

    def __str__(self) -> str:
        """Readable name for admin."""
        return f"{self.structure_id} {self.key}"
