from django.db import models


class Item(models.Model):
    """Modelo único: existe para que `migrate` cree UNA tabla real en Postgres."""

    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name
