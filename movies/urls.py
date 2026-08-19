from django.urls import path
from . import views

urlpatterns = [
    # Movies & Discovery
    path('', views.movie_list, name='movie_list'),
    path('movie/<int:pk>/', views.movie_detail, name='movie_detail'),
    path('movie/<int:pk>/review/', views.submit_review, name='submit_review'),
    path('review/<int:review_id>/report/', views.report_review, name='report_review'),
    
    # Booking & Payment flow
    path('showtime/<int:showtime_id>/seats/', views.seat_selection, name='seat_selection'),
    path('checkout/<int:showtime_id>/', views.create_payment_order, name='checkout'),
    path('payment/process/', views.process_mock_payment, name='process_mock_payment'),
    path('payment/failed/<int:showtime_id>/', views.payment_failed, name='payment_failed'),
    path('booking/<int:booking_id>/confirmation/', views.booking_confirmation, name='booking_confirmation'),
    path('ticket/download/<int:booking_id>/', views.download_ticket_pdf, name='download_ticket_pdf'),
    path('ticket/verify/<int:booking_id>/', views.verify_ticket, name='verify_ticket'),
    
    # User Account Center & History
    path('my-bookings/', views.booking_history, name='booking_history'),
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # Admin Portal & Analytics
    path('admin-portal/login/', views.admin_login_view, name='admin_login'),
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),  # <-- Added this line!
]