from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db.models import Sum, Q, Count
from django.core.paginator import Paginator
from django.utils import timezone
from django.http import JsonResponse
import random
import datetime

from .models import Product, StockLog, CashierProfile, Bill, BillItem, CustomerCredit, CreditLog

# Decorator to ensure only admin (non-cashier) is logged in
def admin_required(view_func):
    @login_required(login_url='auth_shop_admins:login')
    def _wrapped_view(request, *args, **kwargs):
        if hasattr(request.user, 'cashier_profile'):
            messages.error(request, "Access denied. Cashiers cannot access the admin panel.")
            return redirect('auth_cashier:login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

@admin_required
def dashboard(request):
    today = timezone.localtime(timezone.now()).date()
    
    # Today's Sales
    today_sales_query = Bill.objects.filter(created_at__date=today).aggregate(total=Sum('grand_total'))
    today_sales = today_sales_query['total'] or 0.00
    
    # Total products count
    total_products = Product.objects.count()
    
    # Low stock products count (stock < 10)
    low_stock_products = Product.objects.filter(stock__lt=10).count()
    
    # Total Revenue (All-time sales)
    total_revenue_query = Bill.objects.aggregate(total=Sum('grand_total'))
    total_revenue = total_revenue_query['total'] or 0.00

    # Recent Bills
    recent_bills = Bill.objects.order_by('-created_at')[:5]

    context = {
        'today_sales': today_sales,
        'total_products': total_products,
        'low_stock_products': low_stock_products,
        'total_revenue': total_revenue,
        'recent_bills': recent_bills,
    }
    return render(request, 'shop_admins/dashboard.html', context)

# Cashier Management
@admin_required
def cashiers_list(request):
    cashiers = CashierProfile.objects.all().order_by('-created_at')
    
    if request.method == "POST":
        action = request.POST.get('action')
        if action == 'delete':
            profile_id = request.POST.get('profile_id')
            profile = get_object_or_404(CashierProfile, id=profile_id)
            user = profile.user
            profile.delete()
            user.delete()
            messages.success(request, "Cashier profile removed successfully.")
        return redirect('shop_admins:cashiers_list')

    return render(request, 'shop_admins/cashiers.html', {'cashiers': cashiers})

@admin_required
def add_cashier(request):
    if request.method == "POST":
        cashier_id = request.POST.get('cashier_id', '').strip()
        password = request.POST.get('password', '').strip()
        
        if not cashier_id or not password:
            messages.error(request, "Cashier ID and Password are required.")
            return render(request, 'shop_admins/add_cashier.html')
            
        if User.objects.filter(username=cashier_id).exists() or CashierProfile.objects.filter(cashier_id=cashier_id).exists():
            messages.error(request, "Cashier ID already exists.")
            return render(request, 'shop_admins/add_cashier.html')
            
        user = User.objects.create_user(username=cashier_id, password=password)
        CashierProfile.objects.create(user=user, cashier_id=cashier_id)
        messages.success(request, f"Cashier profile created successfully! Cashier ID: {cashier_id}")
        return redirect('shop_admins:cashiers_list')

    return render(request, 'shop_admins/add_cashier.html')

# Product Management
@admin_required
def product_list(request):
    query = request.GET.get('q', '').strip()
    category = request.GET.get('category', '').strip()
    stock_status = request.GET.get('stock_status', '').strip()
    
    products = Product.objects.all().order_by('-created_at')
    
    if query:
        products = products.filter(Q(name__icontains=query) | Q(barcode__icontains=query))
    if category:
        products = products.filter(category__iexact=category)
    if stock_status == 'low':
        products = products.filter(stock__lt=10)
    elif stock_status == 'out':
        products = products.filter(stock=0)

    # Categories list for filter dropdown
    categories = Product.objects.values_list('category', flat=True).distinct()

    paginator = Paginator(products, 10)  # 10 products per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'categories': categories,
        'q': query,
        'selected_category': category,
        'selected_stock_status': stock_status,
    }
    return render(request, 'shop_admins/Product_List.html', context)

def generate_unique_barcode():
    while True:
        barcode = "".join([str(random.randint(0, 9)) for _ in range(8)])
        if not Product.objects.filter(barcode=barcode).exists():
            return barcode

@admin_required
def add_product(request):
    if request.method == "POST":
        name = request.POST.get('name', '').strip()
        category = request.POST.get('category', '').strip()
        buy_price = request.POST.get('buy_price', '').strip()
        selling_price = request.POST.get('selling_price', '').strip()
        stock = request.POST.get('stock', '').strip()
        tax_percentage = request.POST.get('tax_percentage', '').strip()
        unit = request.POST.get('unit', 'piece')
        image = request.FILES.get('image')

        bp = None
        if buy_price:
            try:
                bp = float(buy_price)
            except ValueError:
                messages.error(request, "Invalid buy price.")
                return render(request, 'shop_admins/Add_Product.html')

        tax_pct = None
        if tax_percentage:
            try:
                tax_pct = float(tax_percentage)
                if tax_pct < 0 or tax_pct > 100:
                    messages.error(request, "Tax percentage must be between 0 and 100.")
                    return render(request, 'shop_admins/Add_Product.html')
            except ValueError:
                messages.error(request, "Invalid tax percentage.")
                return render(request, 'shop_admins/Add_Product.html')

        try:
            sp = float(selling_price)
            st = float(stock)  # Changed to float for decimal support
        except (ValueError, TypeError):
            messages.error(request, "Invalid price or stock values.")
            return render(request, 'shop_admins/Add_Product.html')

        barcode = generate_unique_barcode()

        product = Product.objects.create(
            name=name, category=category, buy_price=bp,
            selling_price=sp, stock=st, barcode=barcode,
            unit=unit, image=image if image else None,
            tax_percentage=tax_pct
        )

        if st > 0:
            StockLog.objects.create(
                product=product, change_type='ADD',
                quantity=st, reason="Initial stock upon creation"
            )

        messages.success(request, f"Product '{name}' added successfully with Barcode: {barcode}")
        return redirect('shop_admins:product_list')

    return render(request, 'shop_admins/Add_Product.html')


@admin_required
def edit_product(request, pk):
    product = get_object_or_404(Product, pk=pk)

    if request.method == "POST":
        name = request.POST.get('name', '').strip()
        category = request.POST.get('category', '').strip()
        buy_price = request.POST.get('buy_price', '').strip()
        selling_price = request.POST.get('selling_price', '').strip()
        tax_percentage = request.POST.get('tax_percentage', '').strip()
        unit = request.POST.get('unit', 'piece')
        image = request.FILES.get('image')
        remove_image = request.POST.get('remove_image')

        bp = None
        if buy_price:
            try:
                bp = float(buy_price)
            except ValueError:
                messages.error(request, "Invalid buy price.")
                return render(request, 'shop_admins/Edit_Product.html', {'product': product})

        tax_pct = None
        if tax_percentage:
            try:
                tax_pct = float(tax_percentage)
                if tax_pct < 0 or tax_pct > 100:
                    messages.error(request, "Tax percentage must be between 0 and 100.")
                    return render(request, 'shop_admins/Edit_Product.html', {'product': product})
            except ValueError:
                messages.error(request, "Invalid tax percentage.")
                return render(request, 'shop_admins/Edit_Product.html', {'product': product})

        try:
            sp = float(selling_price)
        except (ValueError, TypeError):
            messages.error(request, "Invalid selling price.")
            return render(request, 'shop_admins/Edit_Product.html', {'product': product})

        product.name = name
        product.category = category
        product.buy_price = bp
        product.selling_price = sp
        product.tax_percentage = tax_pct
        product.unit = unit

        if remove_image == '1':
            product.image = None
        elif image:
            product.image = image

        product.save()
        messages.success(request, f"Product '{name}' updated successfully.")
        return redirect('shop_admins:product_detail', pk=product.pk)

    return render(request, 'shop_admins/Edit_Product.html', {'product': product})

@admin_required
def product_detail(request, pk):
    product = get_object_or_404(Product, pk=pk)
    logs = product.stock_logs.order_by('-created_at')[:10]
    return render(request, 'shop_admins/Product_Detail.html', {'product': product, 'logs': logs})

@admin_required
def print_barcode(request, pk):
    product = get_object_or_404(Product, pk=pk)
    return render(request, 'shop_admins/Print_Barcode.html', {'product': product})

# Inventory Page
@admin_required
def stock_management(request):
    products = Product.objects.all().order_by('name')
    history = StockLog.objects.all().order_by('-created_at')[:30]

    history = StockLog.objects.all().order_by('-created_at')

    if request.method == "POST":
        product_id = request.POST.get('product_id')
        change_type = request.POST.get('change_type') # 'ADD' or 'REMOVE'
        try:
            quantity = float(request.POST.get('quantity', 0))
        except (ValueError, TypeError):
            quantity = 0
        reason = (request.POST.get('reason') or '').strip()

        product = get_object_or_404(Product, id=product_id)

        if change_type == 'ADD':
            product.stock = float(product.stock) + quantity
            product.save()
            StockLog.objects.create(product=product, change_type='ADD', quantity=quantity, reason=reason)
            messages.success(request, f"Added {quantity} to '{product.name}' stock.")
        elif change_type == 'REMOVE':
            if float(product.stock) < quantity:
                messages.error(request, f"Cannot remove {quantity}. Only {product.stock} available.")
            else:
                product.stock = float(product.stock) - quantity
                product.save()
                StockLog.objects.create(product=product, change_type='REMOVE', quantity=quantity, reason=reason)
                messages.success(request, f"Removed {quantity} from '{product.name}' stock.")

        return redirect('shop_admins:stock_management')

    # Pagination for history
    paginator = Paginator(history, 15)
    page_number = request.GET.get('page')
    history_page = paginator.get_page(page_number)

    return render(request, 'shop_admins/stock.html', {'products': products, 'history': history_page})

# Sales Reports
@admin_required
def sales_reports(request):
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    bills = Bill.objects.all().order_by('-created_at')
    
    if start_date_str:
        bills = bills.filter(created_at__date__gte=start_date_str)
    if end_date_str:
        bills = bills.filter(created_at__date__lte=end_date_str)

    # Totals
    total_sales = bills.aggregate(total=Sum('grand_total'))['total'] or 0.00
    total_bills = bills.count()
    
    # Calculate total profit (revenue - cost of goods sold)
    total_profit = 0.00
    for bill in bills:
        for item in bill.items.all():
            if item.product and item.product.buy_price:
                cost = item.product.buy_price * item.quantity
                profit = item.subtotal - cost
                total_profit += float(profit)
            else:
                # If buy price is not defined, profit equals subtotal
                total_profit += float(item.subtotal)

    # Pagination
    paginator = Paginator(bills, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'total_sales': total_sales,
        'total_bills': total_bills,
        'total_profit': total_profit,
        'start_date': start_date_str,
        'end_date': end_date_str,
    }
    return render(request, 'shop_admins/Sales_reports.html', context)

# Customers (Credit Book)
@admin_required
def customer_credit_book(request):
    query = request.GET.get('q', '').strip()
    customers = CustomerCredit.objects.all().order_by('-total_due')

    if query:
        customers = customers.filter(Q(name__icontains=query) | Q(phone__icontains=query))

    if request.method == "POST":
        action = request.POST.get('action')

        if action == 'add_customer':
            name = request.POST.get('name', '').strip()
            phone = request.POST.get('phone', '').strip()
            if not name:
                messages.error(request, "Customer name is required.")
            elif CustomerCredit.objects.filter(name__iexact=name).exists():
                messages.error(request, f"Customer '{name}' already exists.")
            else:
                CustomerCredit.objects.create(name=name, phone=phone)
                messages.success(request, f"Customer '{name}' added to Credit Book.")

        elif action == 'add_credit':
            customer_id = request.POST.get('customer_id')
            amount_str = request.POST.get('amount', '0').strip()
            description = request.POST.get('description', '').strip()
            try:
                amount = float(amount_str)
            except ValueError:
                amount = 0
            customer = get_object_or_404(CustomerCredit, id=customer_id)
            if amount <= 0:
                messages.error(request, "Credit amount must be greater than zero.")
            else:
                customer.total_due = float(customer.total_due) + amount
                customer.save()
                CreditLog.objects.create(
                    customer=customer,
                    amount=amount,
                    description=description or "Credit added manually"
                )
                messages.success(request, f"Credit of ₹{amount:.2f} added for '{customer.name}'.")

        elif action == 'record_payment':
            customer_id = request.POST.get('customer_id')
            amount_str = request.POST.get('amount', '0').strip()
            description = request.POST.get('description', '').strip()
            try:
                amount = float(amount_str)
            except ValueError:
                amount = 0
            customer = get_object_or_404(CustomerCredit, id=customer_id)
            if amount <= 0:
                messages.error(request, "Payment amount must be greater than zero.")
            else:
                customer.total_due = max(0.00, float(customer.total_due) - amount)
                customer.save()
                CreditLog.objects.create(
                    customer=customer,
                    amount=-amount,
                    description=description or "Payment received"
                )
                messages.success(request, f"Payment of ₹{amount:.2f} recorded for '{customer.name}'.")

        return redirect('shop_admins:customer_credit_book')

    return render(request, 'shop_admins/customers(credit book).html', {'customers': customers, 'q': query})

@admin_required
def add_customer(request):
    if request.method == "POST":
        name = request.POST.get('name', '').strip()
        phone = request.POST.get('phone', '').strip()
        
        if not name:
            messages.error(request, "Customer name is required.")
            return render(request, 'shop_admins/add_customer.html')
            
        CustomerCredit.objects.create(name=name, phone=phone)
        messages.success(request, f"Customer '{name}' added to Credit Book successfully.")
        return redirect('shop_admins:customer_credit_book')

    return render(request, 'shop_admins/add_customer.html')

