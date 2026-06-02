from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.contrib import messages
import json
import random

from shop_admins.models import Product, StockLog, Bill, BillItem, CustomerCredit, CreditLog

# Decorator to ensure only logged in cashier or admin
def cashier_required(view_func):
    @login_required(login_url='auth_cashier:login')
    def _wrapped_view(request, *args, **kwargs): 
        if not hasattr(request.user, 'cashier_profile') and not request.user.is_superuser:
            messages.error(request, "Access denied. Cashier login required.")
            return redirect('auth_cashier:login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

@cashier_required
def billing_view(request):
    customers = CustomerCredit.objects.all().order_by('name')
    return render(request, 'cashier/purches.html', {'customers': customers})

@cashier_required
def get_product_by_barcode(request):
    import re
    barcode = request.GET.get('barcode', '').strip()

    # ── Server-side barcode validation ──────────────────────────
    if not barcode:
        return JsonResponse({
            'success': False,
            'invalid_barcode': True,
            'message': 'Barcode is empty.'
        })

    if len(barcode) < 4 or len(barcode) > 30:
        return JsonResponse({
            'success': False,
            'invalid_barcode': True,
            'message': f'Invalid barcode length ({len(barcode)} chars). Must be 4–30 characters.'
        })

    if not re.match(r'^[A-Za-z0-9\-_]+$', barcode):
        return JsonResponse({
            'success': False,
            'invalid_barcode': True,
            'message': 'Barcode contains invalid characters. Only letters, digits, hyphens and underscores are allowed.'
        })
    # ────────────────────────────────────────────────────────────

    try:
        product = Product.objects.get(barcode=barcode)
        # Verify stock (cashier checkout only)
        if product.stock <= 0:
            return JsonResponse({
                'success': False,
                'invalid_barcode': False,
                'message': f"'{product.name}' is out of stock."
            })

        # Return info (strictly exclude buy price)
        return JsonResponse({
            'success': True,
            'id': product.id,
            'name': product.name,
            'category': product.category,
            'selling_price': float(product.selling_price),
            'stock': product.stock
        })
    except Product.DoesNotExist:
        return JsonResponse({
            'success': False,
            'invalid_barcode': False,
            'message': f'No product found for barcode "{barcode}".'
        })

@login_required(login_url='auth_shop_admins:login')
def admin_get_product_by_barcode(request):
    """Barcode lookup for admin-side features (e.g. credit book). No stock check."""
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

@csrf_exempt
@cashier_required
def generate_bill(request):
    if request.method != "POST":
        return JsonResponse({'success': False, 'message': 'Only POST method is allowed'})

    try:
        data = json.loads(request.body)
        cart = data.get('cart', [])
        discount = float(data.get('discount', 0))
        tax = float(data.get('tax', 0))
        credit_customer_id = data.get('credit_customer_id')

        if not cart:
            return JsonResponse({'success': False, 'message': 'Cart is empty'})

        # Validate stock levels first
        items_to_process = []
        for item in cart:
            p_id = item.get('id')
            qty = int(item.get('qty', 0))
            
            product = get_object_or_404(Product, id=p_id)
            if product.stock < qty:
                return JsonResponse({
                    'success': False,
                    'message': f"Insufficient stock for '{product.name}'. Available: {product.stock}, Requested: {qty}"
                })
            items_to_process.append((product, qty))

        # Calculate totals
        subtotal = 0.00
        bill_items_data = []

        for product, qty in items_to_process:
            selling_price = float(product.selling_price)
            item_subtotal = selling_price * qty
            subtotal += item_subtotal
            bill_items_data.append({
                'product': product,
                'name': product.name,
                'qty': qty,
                'price': selling_price,
                'subtotal': item_subtotal
            })

        # Apply calculations
        grand_total = max(0.00, (subtotal - discount) + tax)

        # Generate unique bill number
        timestamp = timezone.localtime(timezone.now()).strftime("%Y%m%d%H%M%S")
        rand_suffix = random.randint(1000, 9999)
        bill_number = f"BILL-{timestamp}-{rand_suffix}"

        # Create Bill in DB
        bill = Bill.objects.create(
            bill_number=bill_number,
            cashier=request.user,
            total_amount=subtotal,
            discount=discount,
            tax=tax,
            grand_total=grand_total
        )

        # Process stock changes and save items
        for item in bill_items_data:
            product = item['product']
            qty = item['qty']
            
            # Decrease stock
            product.stock -= qty
            product.save()

            # Log stock removal
            StockLog.objects.create(
                product=product,
                change_type='REMOVE',
                quantity=qty,
                reason=f"Sold via bill {bill_number}"
            )

            # Create BillItem
            BillItem.objects.create(
                bill=bill,
                product=product,
                product_name=item['name'],
                quantity=qty,
                price=item['price'],
                subtotal=item['subtotal']
            )

        # Credit Book Integration
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
            'tax': tax,
            'grand_total': grand_total,
            'credit_applied': credit_applied,
            'customer_name': customer_name,
            'items': [{'name': i['name'], 'qty': i['qty'], 'price': i['price'], 'subtotal': i['subtotal']} for i in bill_items_data],
            'date': timezone.localtime(bill.created_at).strftime("%d-%b-%Y %I:%M %p")
        })

    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})
