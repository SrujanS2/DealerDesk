from django.db import models


class Dealer(models.Model):
    dealer_code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    city = models.CharField(max_length=128, blank=True, default="")
    phone = models.CharField(max_length=32, blank=True, default="")
    email = models.CharField(max_length=254, blank=True, default="")
    gstin = models.CharField(max_length=15, blank=True, default="")
    credit_limit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.dealer_code} {self.name}"
