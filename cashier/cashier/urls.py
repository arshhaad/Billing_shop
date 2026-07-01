from django.urls import path
from . import views

app_name = 'cashier'

urlpatterns = [
    path('', views.billing_view, name='billing'),
    path('products/', views.products_view, name='products'),
    path('credit-book/', views.credit_book_view, name='credit_book'),
    path('credit-book/add/', views.add_credit_customer, name='add_credit_customer'),
    path('credit-book/<int:pk>/', views.credit_customer_detail, name='credit_customer_detail'),
    path('credit-book/<int:pk>/receive-payment/', views.receive_payment, name='receive_payment'),
    path('sales-report/', views.sales_report_view, name='sales_report'),
    path('get-product/', views.get_product_by_barcode, name='get_product_by_barcode'),
    path('generate-bill/', views.generate_bill, name='generate_bill'),
]
