from django.db import models
from django.contrib.auth.models import User

class Product(models.Model):
    UNIT_CHOICES = [
        ('piece', 'Piece'),
        ('kg', 'Kilogram (kg)'),
        ('liter', 'Liter (L)'),
        ('gram', 'Gram (g)'),
        ('ml', 'Milliliter (ml)'),
        ('pack', 'Pack'),
        ('box', 'Box'),
    ]
    
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=100)
    buy_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.DecimalField(max_digits=10, decimal_places=3, default=0, help_text="Stock quantity (supports decimals for kg/liter)")
    barcode = models.CharField(max_length=100, unique=True)
    image = models.ImageField(upload_to='products/', null=True, blank=True)
    tax_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Tax percentage (e.g., 18 for 18%)")
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default='piece', help_text="Unit of measurement")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class StockLog(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_logs')
    change_type = models.CharField(max_length=10, choices=[('ADD', 'Add Stock'), ('REMOVE', 'Remove Stock')])
    quantity = models.DecimalField(max_digits=10, decimal_places=3, help_text="Quantity (supports decimals for kg/liter)")
    reason = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.change_type} - {self.product.name} ({self.quantity} {self.product.unit})"

class CashierProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='cashier_profile')
    cashier_id = models.CharField(max_length=50, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Cashier: {self.cashier_id} ({self.user.username})"

class Bill(models.Model):
    bill_number = models.CharField(max_length=100, unique=True)
    cashier = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='bills_served')
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    grand_total = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.bill_number

class BillItem(models.Model):
    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True)
    product_name = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=3, help_text="Quantity (supports decimals for kg/liter)")
    unit = models.CharField(max_length=20, default='piece', help_text="Unit of measurement")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.product_name} x {self.quantity} {self.unit}"

class CustomerCredit(models.Model):
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    total_due = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class CreditLog(models.Model):
    customer = models.ForeignKey(CustomerCredit, on_delete=models.CASCADE, related_name='credit_logs')
    amount = models.DecimalField(max_digits=10, decimal_places=2)  # Positive for added credit, Negative for paid amount
    description = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.customer.name} - {self.amount}"


class CreditPaymentHistory(models.Model):
    """Full audit trail for every payment received against a customer's credit."""

    PAYMENT_METHOD_CHOICES = [
        ('cash',   'Cash'),
        ('upi',    'UPI'),
        ('card',   'Card'),
        ('bank',   'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('other',  'Other'),
    ]

    customer          = models.ForeignKey(
                            CustomerCredit, on_delete=models.CASCADE,
                            related_name='payment_history')
    previous_balance  = models.DecimalField(max_digits=10, decimal_places=2)
    paid_amount       = models.DecimalField(max_digits=10, decimal_places=2)
    remaining_balance = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method    = models.CharField(
                            max_length=20,
                            choices=PAYMENT_METHOD_CHOICES,
                            default='cash')
    notes             = models.TextField(null=True, blank=True)
    received_by       = models.ForeignKey(
                            User, on_delete=models.SET_NULL,
                            null=True, related_name='payments_received')
    reference_number  = models.CharField(max_length=100, null=True, blank=True)
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return (
            f"Payment ₹{self.paid_amount} from {self.customer.name} "
            f"on {self.created_at:%d-%b-%Y}"
        )
