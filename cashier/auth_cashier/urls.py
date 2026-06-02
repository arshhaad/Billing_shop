from django.urls import path
from . import views

app_name = 'auth_cashier'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('forget/', views.forget_view, name='forget'),
    path('logout/', views.logout_view, name='logout'),
]
