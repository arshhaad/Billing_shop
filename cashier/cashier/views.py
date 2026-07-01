from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.contrib import messages
from django.db import transaction
from decimal import Decimal, InvalidOperation
import json
import random

from shop_admins.models import (
    Product, StockLog, Bill, BillItem,
    CustomerCredit, CreditLog, CreditPaymentHistory,
)

# ── Auth Decorator ──────────────────────────────────────────────────────────

def cashier_required(view_func):
    @login_required(login_url='auth_cashier:login')
    def _wrapped_view(request, *args, **kwargs):
        if not hasattr(request.user, 'cashier_profile') and not request.user.is_superuser:
            messages.error(request, "Access denied. Cashier login required.")
            return redirect('auth_cashier:login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

# ── Billing / POS ────────────────────────────────────────────────────────────

@cashier_required
def billing_view(request):
    customers = CustomerCredit.objects.all().order_by('name')
    return render(request, 'cashier/purches.html', {'customers': customers})

# ── Products Stock View ──────────────────────────────────────────────────────

@cashier_required
def products_view(request):
    products = Product.objects.all().order_by('category', 'name')
    return render(request, 'cashier/products.html', {'products': products})

# ── Credit Book Views ────────────────────────────────────────────────────────

@cashier_required
def credit_book_view(request):
    customers = CustomerCredit.objects.all().order_by('name')
    return render(request, 'cashier/credit_book.html', {'customers': customers})

@csrf_exempt
@cashier_required
def add_credit_customer(request):
    """Add a new customer to the credit book."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST required'})
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        phone = data.get('phone', '').strip()
        address = data.get('address', '').strip()

        # Validate name
        if not name:
            return JsonResponse({'success': False, 'message': 'Customer name is required.'})
        
        if len(name) < 2:
            return JsonResponse({'success': False, 'message': 'Customer name must be at least 2 characters long.'})
        
        if len(name) > 255:
            return JsonResponse({'success': False, 'message': 'Customer name is too long (max 255 characters).'})
        
        # Check for valid name characters (letters, spaces, dots, hyphens)
        if not all(c.isalpha() or c.isspace() or c in '.-' for c in name):
            return JsonResponse({'success': False, 'message': 'Customer name can only contain letters, spaces, dots and hyphens.'})

        # Validate phone number (Indian format)
        if phone:
            # Remove common separators for validation
            phone_clean = phone.replace('-', '').replace(' ', '').replace('(', '').replace(')', '')
            if not phone_clean.isdigit():
                return JsonResponse({'success': False, 'message': 'Phone number must contain only digits, spaces, and hyphens.'})
            
            if len(phone_clean) < 10:
                return JsonResponse({'success': False, 'message': 'Phone number must be at least 10 digits.'})
            
            if len(phone_clean) > 15:
                return JsonResponse({'success': False, 'message': 'Phone number is too long (max 15 digits).'})
            
            # Indian mobile number validation (should start with 6,7,8,9)
            if len(phone_clean) == 10 and not phone_clean[0] in '6789':
                return JsonResponse({'success': False, 'message': 'Indian mobile numbers should start with 6, 7, 8, or 9.'})

        # Validate address
        if address:
            if len(address) < 5:
                return JsonResponse({'success': False, 'message': 'Address must be at least 5 characters long.'})
            
            if len(address) > 500:
                return JsonResponse({'success': False, 'message': 'Address is too long (max 500 characters).'})

        # Check for duplicate name
        if CustomerCredit.objects.filter(name__iexact=name).exists():
            return JsonResponse({'success': False, 'message': f'A customer named "{name}" already exists.'})

        customer = CustomerCredit.objects.create(
            name=name,
            phone=phone or None,
            address=address or None,
            total_due=0.00
        )
        return JsonResponse({
            'success': True,
            'customer': {
                'id': customer.id,
                'name': customer.name,
                'phone': customer.phone or '',
                'address': customer.address or '',
                'total_due': float(customer.total_due),
                'created_at': customer.created_at.strftime('%d %b %Y'),
            }
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})

@cashier_required
def credit_customer_detail(request, pk):
    """Return JSON with customer details + credit logs."""
    customer = get_object_or_404(CustomerCredit, pk=pk)
    logs = customer.credit_logs.order_by('-created_at')[:50]
    return JsonResponse({
        'success': True,
        'customer': {
            'id': customer.id,
            'name': customer.name,
            'phone': customer.phone or '',
            'address': customer.address or '',
            'total_due': float(customer.total_due),
            'created_at': customer.created_at.strftime('%d %b %Y'),
        },
        'logs': [
            {
                'date': log.created_at.strftime('%d %b %Y %I:%M %p'),
                'amount': float(log.amount),
                'description': log.description or '',
            }
            for log in logs
        ]
    })


# ── Credit Payment Service ───────────────────────────────────────────────────

VALID_PAYMENT_METHODS = {'cash', 'upi', 'card', 'bank', 'cheque', 'other'}


class CreditPaymentService:
    """
    Encapsulates all business logic for receiving a payment against
    a customer's outstanding credit balance.

    Usage:
        result = CreditPaymentService().receive_payment(
            customer_id=5, amount=Decimal('500.00'),
            payment_method='cash', notes='Partial payment',
            received_by=request.user,
        )
    """

    def receive_payment(
        self,
        customer_id: int,
        amount: Decimal,
        payment_method: str,
        notes: str,
        received_by,
    ) -> dict:
        """
        Validate, record, and apply a payment against the customer's balance.

        Returns a dict with keys: success, message, and on success:
            previous_balance, paid_amount, remaining_balance.

        Raises nothing — all exceptions are caught and returned as
        {'success': False, 'message': ...}.
        """
        # ── 1. Validate amount (pre-DB) ──────────────────────────────────
        if amount is None:
            return {'success': False, 'message': 'Payment amount is required.'}
        if not isinstance(amount, Decimal):
            return {'success': False, 'message': 'Payment amount must be numeric.'}
        if amount <= Decimal('0'):
            return {'success': False, 'message': 'Payment amount must be greater than zero.'}

        # ── 2. Validate payment method ───────────────────────────────────
        method = (payment_method or 'cash').strip().lower()
        if method not in VALID_PAYMENT_METHODS:
            return {
                'success': False,
                'message': (
                    f'Invalid payment method "{payment_method}". '
                    f'Allowed: {", ".join(VALID_PAYMENT_METHODS)}.'
                ),
            }

        # ── 3. Database transaction with row-level lock ──────────────────
        try:
            with transaction.atomic():
                # SELECT … FOR UPDATE prevents race conditions when two
                # concurrent requests try to pay the same customer.
                customer = (
                    CustomerCredit.objects
                    .select_for_update()
                    .get(pk=customer_id)
                )

                previous_balance: Decimal = customer.total_due

                if previous_balance <= Decimal('0'):
                    return {
                        'success': False,
                        'message': 'No outstanding balance available.',
                    }

                if amount > previous_balance:
                    return {
                        'success': False,
                        'message': (
                            f'Payment amount (₹{amount:.2f}) cannot exceed '
                            f'the outstanding balance (₹{previous_balance:.2f}).'
                        ),
                    }

                remaining_balance: Decimal = previous_balance - amount

                # 4. Insert payment history record
                CreditPaymentHistory.objects.create(
                    customer=customer,
                    previous_balance=previous_balance,
                    paid_amount=amount,
                    remaining_balance=remaining_balance,
                    payment_method=method,
                    notes=(notes or '').strip() or None,
                    received_by=received_by,
                )

                # 5. Insert audit log into CreditLog (negative = payment)
                CreditLog.objects.create(
                    customer=customer,
                    amount=-amount,
                    description=f'Payment received ({method.upper()}) — ₹{amount:.2f}',
                )

                # 6. Update customer balance
                customer.total_due = remaining_balance
                customer.save(update_fields=['total_due', 'updated_at'])

            # ── 7. Commit succeeded ──────────────────────────────────────
            return {
                'success': True,
                'message': 'Payment received successfully.',
                'previous_balance': float(previous_balance),
                'paid_amount': float(amount),
                'remaining_balance': float(remaining_balance),
            }

        except CustomerCredit.DoesNotExist:
            return {'success': False, 'message': 'Customer not found.'}
        except Exception as exc:
            # transaction.atomic() rolls back automatically on any exception
            return {
                'success': False,
                'message': f'A database error occurred. Please try again. ({exc})',
            }


# ── Receive Payment Endpoint ─────────────────────────────────────────────────

@csrf_exempt
@cashier_required
def receive_payment(request, pk: int):
    """
    POST /cashier/credit-book/<pk>/receive-payment/

    Body (JSON):
        {
            "amount": "500.00",
            "payment_method": "cash",
            "notes": "Partial payment"          // optional
        }

    Response (JSON):
        {
            "success": true,
            "message": "Payment received successfully.",
            "previous_balance": 1200.00,
            "paid_amount": 500.00,
            "remaining_balance": 700.00
        }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST method required.'}, status=405)

    # ── Parse JSON body ───────────────────────────────────────────────────
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'message': 'Invalid JSON body.'}, status=400)

    # ── Validate & coerce amount ──────────────────────────────────────────
    raw_amount = data.get('amount', '').strip() if isinstance(data.get('amount'), str) else data.get('amount')

    if raw_amount is None or str(raw_amount).strip() == '':
        return JsonResponse({'success': False, 'message': 'Payment amount is required.'}, status=400)

    try:
        amount = Decimal(str(raw_amount))
    except (InvalidOperation, ValueError):
        return JsonResponse({'success': False, 'message': 'Payment amount must be a valid number.'}, status=400)

    payment_method = data.get('payment_method', 'cash')
    notes          = data.get('notes', '')

    # ── Delegate to service ───────────────────────────────────────────────
    service = CreditPaymentService()
    result  = service.receive_payment(
        customer_id=pk,
        amount=amount,
        payment_method=payment_method,
        notes=notes,
        received_by=request.user,
    )

    status_code = 200 if result.get('success') else 400
    return JsonResponse(result, status=status_code)

# ── Today's Sales Report ─────────────────────────────────────────────────────

@cashier_required
def sales_report_view(request):
    today = timezone.localdate()
    # Bills by this cashier today
    bills = Bill.objects.filter(
        cashier=request.user,
        created_at__date=today
    ).prefetch_related('items').order_by('-created_at')

    total_sales = sum(float(b.grand_total) for b in bills)
    total_items = sum(
        sum(item.quantity for item in b.items.all()) for b in bills
    )

    return render(request, 'cashier/sales_report.html', {
        'bills': bills,
        'total_sales': total_sales,
        'total_items': total_items,
        'bill_count': bills.count(),
        'today': today,
    })

# ── Barcode Lookup ───────────────────────────────────────────────────────────

@cashier_required
def get_product_by_barcode(request):
    import re
    barcode = request.GET.get('barcode', '').strip()

    if not barcode:
        return JsonResponse({'success': False, 'invalid_barcode': True, 'message': 'Barcode is empty.'})

    if len(barcode) < 4 or len(barcode) > 30:
        return JsonResponse({
            'success': False, 'invalid_barcode': True,
            'message': f'Invalid barcode length ({len(barcode)} chars). Must be 4–30 characters.'
        })

    if not re.match(r'^[A-Za-z0-9\-_]+$', barcode):
        return JsonResponse({
            'success': False, 'invalid_barcode': True,
            'message': 'Barcode contains invalid characters. Only letters, digits, hyphens and underscores are allowed.'
        })

    try:
        product = Product.objects.get(barcode=barcode)
        if product.stock <= 0:
            return JsonResponse({'success': False, 'invalid_barcode': False, 'message': f"'{product.name}' is out of stock."})
        return JsonResponse({
            'success': True,
            'id': product.id,
            'name': product.name,
            'category': product.category,
            'selling_price': float(product.selling_price),
            'stock': float(product.stock),
            'unit': product.unit,
            'tax_percentage': float(product.tax_percentage) if product.tax_percentage else 0
        })
    except Product.DoesNotExist:
        return JsonResponse({'success': False, 'invalid_barcode': False, 'message': f'No product found for barcode "{barcode}".'})

@login_required(login_url='auth_shop_admins:login')
def admin_get_product_by_barcode(request):
    barcode = request.GET.get('barcode', '').strip()
    if not barcode:
        return JsonResponse({'success': False, 'message': 'Barcode is empty'})
    try:
        product = Product.objects.get(barcode=barcode)
        return JsonResponse({
            'success': True,
            'id': product.id,
            'name': product.name,
            'category': product.category,
            'selling_price': float(product.selling_price),
            'stock': product.stock
        })
    except Product.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Product not found'})

# ── Generate Bill ────────────────────────────────────────────────────────────

@csrf_exempt
@cashier_required
def generate_bill(request):
    if request.method != "POST":
        return JsonResponse({'success': False, 'message': 'Only POST method is allowed'})

    try:
        data = json.loads(request.body)
        cart = data.get('cart', [])
        discount = float(data.get('discount', 0))
        credit_customer_id = data.get('credit_customer_id')

        if not cart:
            return JsonResponse({'success': False, 'message': 'Cart is empty'})

        items_to_process = []
        for item in cart:
            product = get_object_or_404(Product, id=item.get('id'))
            qty = float(item.get('qty', 0))
            if float(product.stock) < qty:
                return JsonResponse({
                    'success': False,
                    'message': f"Insufficient stock for '{product.name}'. Available: {product.stock} {product.unit}, Requested: {qty} {product.unit}"
                })
            items_to_process.append((product, qty))

        subtotal = 0.00
        total_tax = 0.00
        bill_items_data = []
        for product, qty in items_to_process:
            selling_price = float(product.selling_price)
            item_subtotal = selling_price * qty
            
            # Calculate tax for this item if product has tax
            item_tax = 0.00
            if product.tax_percentage:
                item_tax = item_subtotal * (float(product.tax_percentage) / 100)
            
            subtotal += item_subtotal
            total_tax += item_tax
            
            bill_items_data.append({
                'product': product,
                'name': product.name,
                'qty': qty,
                'unit': product.unit,
                'price': selling_price,
                'subtotal': item_subtotal,
                'tax': item_tax,
                'tax_percentage': float(product.tax_percentage) if product.tax_percentage else 0
            })

        grand_total = max(0.00, subtotal - discount + total_tax)

        timestamp = timezone.localtime(timezone.now()).strftime("%Y%m%d%H%M%S")
        rand_suffix = random.randint(1000, 9999)
        bill_number = f"BILL-{timestamp}-{rand_suffix}"

        bill = Bill.objects.create(
            bill_number=bill_number,
            cashier=request.user,
            total_amount=subtotal,
            discount=discount,
            tax=total_tax,
            grand_total=grand_total
        )

        for item in bill_items_data:
            product = item['product']
            qty = item['qty']
            product.stock = float(product.stock) - qty
            product.save()
            StockLog.objects.create(
                product=product,
                change_type='REMOVE',
                quantity=qty,
                reason=f"Sold via bill {bill_number}"
            )
            BillItem.objects.create(
                bill=bill,
                product=product,
                product_name=item['name'],
                quantity=qty,
                unit=item['unit'],
                price=item['price'],
                subtotal=item['subtotal']
            )

        credit_applied = False
        customer_name = ""
        if credit_customer_id:
            try:
                customer = CustomerCredit.objects.get(id=credit_customer_id)
                customer.total_due = float(customer.total_due) + grand_total
                customer.save()
                CreditLog.objects.create(
                    customer=customer,
                    amount=grand_total,
                    description=f"Charged from Bill: {bill_number}"
                )
                credit_applied = True
                customer_name = customer.name
            except CustomerCredit.DoesNotExist:
                pass

        return JsonResponse({
            'success': True,
            'bill_number': bill_number,
            'subtotal': subtotal,
            'discount': discount,
            'tax': total_tax,
            'grand_total': grand_total,
            'credit_applied': credit_applied,
            'customer_name': customer_name,
            'items': [{'name': i['name'], 'qty': i['qty'], 'unit': i['unit'], 'price': i['price'], 'subtotal': i['subtotal'], 'tax': i['tax'], 'tax_percentage': i['tax_percentage']} for i in bill_items_data],
            'date': timezone.localtime(bill.created_at).strftime("%d-%b-%Y %I:%M %p")
        })

    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})
