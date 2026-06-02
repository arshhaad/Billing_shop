from django.urls import path
from . import views
from cashier.views import admin_get_product_by_barcode

app_name = 'shop_admins'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('cashiers/', views.cashiers_list, name='cashiers_list'),
    path('cashiers/add/', views.add_cashier, name='add_cashier'),
    path('products/', views.product_list, name='product_list'),
    path('products/add/', views.add_product, name='add_product'),
    path('products/<int:pk>/', views.product_detail, name='product_detail'),
    path('products/<int:pk>/print/', views.print_barcode, name='print_barcode'),
    path('stock/', views.stock_management, name='stock_management'),
    path('sales/', views.sales_reports, name='sales_reports'),
    path('customers/', views.customer_credit_book, name='customer_credit_book'),
    path('get-product/', admin_get_product_by_barcode, name='admin_get_product'),
]
