from django.db import models
from django.db.models import Q


class Product(models.Model):
    """A catalogue item. `sku` is the business key used in every URL and order line."""

    sku = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=64, blank=True, default="", db_index=True)
    brand = models.CharField(max_length=64, blank=True, default="")
    vehicle_fitment = models.CharField(max_length=128, blank=True, default="")
    price = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sku"]
        constraints = [models.CheckConstraint(condition=Q(price__gt=0), name="product_price_positive")]

    def __str__(self):
        return f"{self.sku} {self.name}"


class Inventory(models.Model):
    """Available stock for one product. A separate 1:1 row so stock locking (SELECT ... FOR UPDATE)
    never blocks catalogue edits such as a supplier price update, and vice versa."""

    product = models.OneToOneField(Product, on_delete=models.CASCADE, primary_key=True, related_name="inventory")
    quantity = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Last line of defence: the database itself refuses negative stock.
        constraints = [models.CheckConstraint(condition=Q(quantity__gte=0), name="inventory_quantity_non_negative")]

    def __str__(self):
        return f"{self.product_id}: {self.quantity}"


class StockMovement(models.Model):
    """Append-only ledger of every stock change (audit trail; never read by business rules)."""

    class Reason(models.TextChoices):
        SEED = "SEED"
        MANUAL = "MANUAL"
        ORDER_CONFIRM = "ORDER_CONFIRM"
        ORDER_CANCEL = "ORDER_CANCEL"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="stock_movements")
    order = models.ForeignKey("orders.Order", on_delete=models.SET_NULL, null=True, blank=True, related_name="stock_movements")
    kind = models.CharField(max_length=16, choices=Reason.choices)
    delta = models.IntegerField()
    quantity_after = models.IntegerField()
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["product", "created_at"])]
