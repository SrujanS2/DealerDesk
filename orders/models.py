from django.db import models
from django.db.models import Q


class Order(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        CONFIRMED = "CONFIRMED"
        DISPATCHED = "DISPATCHED"
        DELIVERED = "DELIVERED"
        CANCELLED = "CANCELLED"

    order_number = models.CharField(max_length=20, unique=True)
    # PROTECT: an order is a financial record; deleting a dealer must never erase its orders.
    dealer = models.ForeignKey("dealers.Dealer", on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["dealer", "status"]), models.Index(fields=["status"])]

    def __str__(self):
        return self.order_number


class OrderItem(models.Model):
    # CASCADE: a line has no meaning without its order.
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    # PROTECT: a product that appears on any order line cannot be deleted.
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="order_items")
    quantity = models.PositiveIntegerField()
    # NULL while DRAFT (the line follows the live catalogue price); set once, on confirm.
    locked_unit_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["order", "product"], name="orderitem_unique_sku_per_order"),
            models.CheckConstraint(condition=Q(quantity__gte=1), name="orderitem_quantity_positive"),
        ]


class DailyOrderSequence(models.Model):
    """One row per IST calendar day; `last_value` is the last NNNN handed out for that day.
    Incremented with a single atomic INSERT ... ON CONFLICT DO UPDATE (see orders/services.py)."""

    day = models.DateField(primary_key=True)
    last_value = models.PositiveIntegerField(default=0)


class IdempotencyKey(models.Model):
    """Remembers the outcome of POST /api/orders/ per Idempotency-Key header."""

    key = models.CharField(max_length=255, unique=True)
    request_hash = models.CharField(max_length=64)
    # CASCADE: the key only exists to point at its order.
    order = models.OneToOneField(Order, on_delete=models.CASCADE, null=True, blank=True, related_name="idempotency_key")
    created_at = models.DateTimeField(auto_now_add=True)
