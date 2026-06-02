from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.models import User
from django.contrib import messages

# Default credentials as requested
DEFAULT_EMAIL = "cloudhub.ai.in@gmail.com"
DEFAULT_PASSWORD = "cloud@123"

def ensure_default_admin():
    # Check if the default admin user exists, create if not
    if not User.objects.filter(email=DEFAULT_EMAIL).exists():
        # Django usernames can be emails. We'll use the email as the username
        User.objects.create_superuser(
            username=DEFAULT_EMAIL,
            email=DEFAULT_EMAIL,
            password=DEFAULT_PASSWORD
        )

def login_view(request):
    ensure_default_admin()
    if request.user.is_authenticated and not hasattr(request.user, 'cashier_profile'):
        return redirect('shop_admins:dashboard')

    if request.method == "POST":
        email = request.POST.get('email')
        password = request.POST.get('password')

        try:
            # Find the user by email
            user_obj = User.objects.get(email=email)
            # Authenticate using username (which is email in our setup)
            user = authenticate(request, username=user_obj.username, password=password)
            if user is not None:
                # Ensure they are not a cashier
                if hasattr(user, 'cashier_profile'):
                    messages.error(request, "Cashiers must log in through the cashier portal.")
                    return redirect('auth_cashier:login')
                auth_login(request, user)
                return redirect('shop_admins:dashboard')
            else:
                messages.error(request, "Invalid password.")
        except User.DoesNotExist:
            messages.error(request, "Invalid email address.")

    return render(request, 'auth_shop_admins/login.html')

def forget_view(request):
    ensure_default_admin()
    if request.method == "POST":
        email = request.POST.get('email')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')

        if new_password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, 'auth_shop_admins/forget.html')

        try:
            user = User.objects.get(email=email)
            if hasattr(user, 'cashier_profile'):
                messages.error(request, "Cannot reset cashier password here.")
                return redirect('auth_cashier:forget')
            
            user.set_password(new_password)
            user.save()
            messages.success(request, "Password reset successfully. Please log in.")
            return redirect('auth_shop_admins:login')
        except User.DoesNotExist:
            messages.error(request, "No admin user found with that email address.")

    return render(request, 'auth_shop_admins/forget.html')

def logout_view(request):
    auth_logout(request)
    return redirect('auth_shop_admins:login')
