from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.models import User
from django.contrib import messages
from shop_admins.models import CashierProfile

def login_view(request):
    if request.user.is_authenticated and hasattr(request.user, 'cashier_profile'):
        return redirect('cashier:billing')

    if request.method == "POST":
        cashier_id = request.POST.get('cashier_id').strip()
        password = request.POST.get('password').strip()

        try:
            profile = CashierProfile.objects.get(cashier_id=cashier_id)
            user = authenticate(request, username=profile.user.username, password=password)
            if user is not None:
                auth_login(request, user)
                return redirect('cashier:billing')
            else:
                messages.error(request, "Invalid password.")
        except CashierProfile.DoesNotExist:
            messages.error(request, "Invalid Cashier ID.")

    return render(request, 'auth_cashier/login.html')

def forget_view(request):
    if request.method == "POST":
        cashier_id = request.POST.get('cashier_id').strip()
        new_password = request.POST.get('new_password').strip()
        confirm_password = request.POST.get('confirm_password').strip()

        if new_password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, 'auth_cashier/forget.html')

        try:
            profile = CashierProfile.objects.get(cashier_id=cashier_id)
            user = profile.user
            user.set_password(new_password)
            user.save()
            messages.success(request, "Password updated successfully. Please log in.")
            return redirect('auth_cashier:login')
        except CashierProfile.DoesNotExist:
            messages.error(request, "Cashier ID not found.")

    return render(request, 'auth_cashier/forget.html')

def logout_view(request):
    auth_logout(request)
    return redirect('auth_cashier:login')
