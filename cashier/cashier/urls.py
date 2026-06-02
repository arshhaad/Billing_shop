from django.urls import path
from . import views

app_name = 'cashier'

urlpatterns = [
    path('', views.billing_view, name='billing'),
    path('get-product/', views.get_product_by_barcode, name='get_product_by_barcode'),
    path('generate-bill/', views.generate_bill, name='generate_bill'),
]
