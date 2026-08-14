import uuid
import csv
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.db.models import Count, Sum, Avg, Min, Q
from django.db.models.functions import ExtractHour
from django.utils import timezone
from django.conf import settings
from django.http import HttpResponse
from django.core.paginator import Paginator
from django.views.decorators.csrf import csrf_exempt

from .models import Movie, Showtime, Screen, Seat, SeatReservation, Payment, Booking
from .utils import generate_ticket_pdf_and_qr
from .tasks import send_ticket_email_celery

# --- USER AUTHENTICATION VIEWS ---

def register_view(request):
    if request.user.is_authenticated:
        return redirect('movie_list')
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        email = request.POST.get('email', '')
        if form.is_valid():
            user = form.save(commit=False)
            if email:
                user.email = email
            user.save()
            login(request, user)
            messages.success(request, f"Welcome to BookMyShow, {user.username}! Your account is active.")
            return redirect('movie_list')
        else:
            messages.error(request, "Registration failed. Please check the requirements below.")
    else:
        form = UserCreationForm()
    return render(request, 'movies/register.html', {'form': form})

def login_view(request):
    if request.user.is_authenticated:
        return redirect('movie_list')
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"Welcome back, {user.username}!")
            return redirect('movie_list')
        else:
            messages.error(request, "Invalid username or password.")
    else:
        form = AuthenticationForm()
    return render(request, 'movies/login.html', {'form': form})

def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out successfully.")
    return redirect('movie_list')

# --- MOVIE DISCOVERY & CATALOG ---

def movie_list(request):
    query = request.GET.get('q', '')
    genre = request.GET.get('genre', '')
    language = request.GET.get('language', '')
    theater = request.GET.get('theater', '')
    min_rating = request.GET.get('min_rating', '')
    sort_by = request.GET.get('sort', '')

    movies = Movie.objects.all().annotate(
        avg_rating=Avg('reviews__rating'),
        min_price=Min('showtimes__ticket_price')
    )

    if query:
        movies = movies.filter(Q(title__icontains=query) | Q(description__icontains=query))
    if genre:
        movies = movies.filter(genres__icontains=genre)
    if language:
        movies = movies.filter(languages__icontains=language)
    if theater:
        movies = movies.filter(showtimes__screen__name__icontains=theater)
    if min_rating:
        try:
            movies = movies.filter(avg_rating__gte=float(min_rating))
        except ValueError:
            pass

    if sort_by == 'popularity':
        movies = movies.annotate(booking_count=Count('showtimes__bookings')).order_by('-booking_count')
    elif sort_by == 'newest':
        movies = movies.order_by('-release_date')
    elif sort_by == 'rating':
        movies = movies.order_by('-avg_rating')
    elif sort_by == 'price_low':
        movies = movies.order_by('min_price')
    elif sort_by == 'price_high':
        movies = movies.order_by('-min_price')
    else:
        movies = movies.order_by('title')

    movies = movies.distinct()
    matching_count = movies.count()

    paginator = Paginator(movies, 8)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    recommended_movies = []
    if request.user.is_authenticated:
        booked_movie_ids = list(Booking.objects.filter(user=request.user).values_list('showtime__movie_id', flat=True))
        user_genres = Movie.objects.filter(id__in=booked_movie_ids).values_list('genres', flat=True)
        if user_genres:
            recommended_movies = Movie.objects.filter(genres__in=user_genres).exclude(id__in=booked_movie_ids).distinct()[:4]
    
    if not recommended_movies:
        recommended_movies = Movie.objects.order_by('-release_date')[:4]

    available_genres = Movie.objects.values_list('genres', flat=True).distinct()
    available_languages = Movie.objects.values_list('languages', flat=True).distinct()
    available_theaters = Screen.objects.values_list('name', flat=True).distinct()

    context = {
        'page_obj': page_obj,
        'matching_count': matching_count,
        'recommended_movies': recommended_movies,
        'available_genres': available_genres,
        'available_languages': available_languages,
        'available_theaters': available_theaters,
        'query': query,
        'selected_genre': genre,
        'selected_language': language,
        'selected_theater': theater,
        'selected_rating': min_rating,
        'selected_sort': sort_by,
    }
    return render(request, 'movies/movie_list.html', context)

def movie_detail(request, pk):
    movie = get_object_or_404(Movie, pk=pk)
    return render(request, 'movies/movie_detail.html', {'movie': movie})

# --- SEAT RESERVATION & PAYMENT ---

@csrf_exempt
def seat_selection(request, showtime_id):
    showtime = get_object_or_404(Showtime, pk=showtime_id)
    all_seats = Seat.objects.filter(screen=showtime.screen).order_by('row', 'number')
    
    expired_reservations = SeatReservation.objects.filter(
        showtime=showtime, status='HELD',
        reserved_at__lt=timezone.now() - timedelta(minutes=2)
    )
    expired_reservations.delete()

    booked_seat_ids = list(SeatReservation.objects.filter(showtime=showtime, status='BOOKED').values_list('seat_id', flat=True))
    held_seat_ids = list(SeatReservation.objects.filter(showtime=showtime, status='HELD').values_list('seat_id', flat=True))

    if request.method == "POST":
        selected_seat_ids = request.POST.getlist('selected_seats')
        
        if not selected_seat_ids:
            messages.error(request, "Please select at least one seat.")
            return redirect('seat_selection', showtime_id=showtime.id)

        try:
            with transaction.atomic():
                seats_to_reserve = Seat.objects.select_for_update().filter(id__in=selected_seat_ids)
                
                already_claimed = SeatReservation.objects.filter(
                    showtime=showtime, seat__in=seats_to_reserve
                ).exists()

                if already_claimed:
                    messages.error(request, "One or more selected seats were just taken! Please choose different seats.")
                    return redirect('seat_selection', showtime_id=showtime.id)

                if request.user.is_authenticated:
                    SeatReservation.objects.filter(showtime=showtime, user=request.user, status='HELD').delete()

                created_reservations = []
                for seat in seats_to_reserve:
                    res = SeatReservation.objects.create(
                        showtime=showtime, seat=seat,
                        user=request.user if request.user.is_authenticated else None,
                        status='HELD'
                    )
                    created_reservations.append(res.id)

                request.session['held_reservation_ids'] = created_reservations

            messages.success(request, "Seats held! Proceeding to payment...")
            return redirect('checkout', showtime_id=showtime.id)

        except Exception:
            messages.error(request, "A system error occurred during seat hold. Please try again.")
            return redirect('seat_selection', showtime_id=showtime.id)

    context = {
        'showtime': showtime,
        'all_seats': all_seats,
        'booked_seat_ids': booked_seat_ids,
        'held_seat_ids': held_seat_ids,
    }
    return render(request, 'movies/seat_selection.html', context)

def create_payment_order(request, showtime_id):
    showtime = get_object_or_404(Showtime, pk=showtime_id)
    
    held_ids = request.session.get('held_reservation_ids', [])
    user_held_seats = SeatReservation.objects.filter(id__in=held_ids, status='HELD')
    
    if not user_held_seats.exists():
        messages.error(request, "Your seat hold expired or no seats were selected.")
        return redirect('seat_selection', showtime_id=showtime.id)

    total_amount = showtime.ticket_price * user_held_seats.count()
    mock_order_id = f"ORDER_{uuid.uuid4().hex[:10].upper()}"

    Payment.objects.create(
        user=request.user if request.user.is_authenticated else None,
        razorpay_order_id=mock_order_id,
        amount=total_amount,
        status='PENDING'
    )

    request.session['current_showtime_id'] = showtime.id
    
    context = {
        'showtime': showtime,
        'total_amount': total_amount,
        'order_id': mock_order_id,
    }
    return render(request, 'movies/mock_payment_gateway.html', context)

@csrf_exempt
def process_mock_payment(request):
    if request.method == "POST":
        action_type = request.POST.get('action_type')
        order_id = request.POST.get('order_id')
        guest_email = request.POST.get('guest_email', '').strip()
        payment_method = request.POST.get('payment_method', 'card')
        
        showtime_id = request.session.get('current_showtime_id')
        held_ids = request.session.get('held_reservation_ids', [])

        try:
            with transaction.atomic():
                payment = Payment.objects.get(razorpay_order_id=order_id)

                if payment.status in ['SUCCESS', 'FAILED', 'CANCELLED']:
                    messages.warning(request, "This transaction has already been processed.")
                    return redirect('seat_selection', showtime_id=showtime_id)

                if action_type == 'cancel':
                    payment.status = 'CANCELLED'
                    payment.save()
                    SeatReservation.objects.filter(id__in=held_ids, status='HELD').delete()
                    messages.warning(request, "Payment cancelled. Your seats have been released.")
                    return redirect('seat_selection', showtime_id=showtime_id)

                failed = False
                if payment_method == 'card':
                    card_number = request.POST.get('card_number', '')
                    if card_number.endswith('0000'):
                        failed = True
                elif payment_method == 'upi':
                    upi_id = request.POST.get('upi_id', '')
                    if 'fail' in upi_id.lower():
                        failed = True
                elif payment_method == 'netbanking':
                    bank = request.POST.get('bank', '')
                    if bank == 'fail_bank':
                        failed = True

                if failed:
                    payment.status = 'FAILED'
                    payment.save()
                    
                    # Instead of deleting, we adjust the reserved_at so it expires exactly 1 minute from now
                    # (since it expires 2 minutes after reserved_at)
                    SeatReservation.objects.filter(id__in=held_ids, status='HELD').update(
                        reserved_at=timezone.now() - timedelta(minutes=1)
                    )
                    
                    return redirect('payment_failed', showtime_id=showtime_id)
                else:
                    payment.status = 'SUCCESS'
                    payment.razorpay_payment_id = f"GATEWAY_TXN_{uuid.uuid4().hex[:10].upper()}"
                    payment.save()

                    held_reservations = SeatReservation.objects.filter(id__in=held_ids, status='HELD')
                    held_reservations.update(status='BOOKED')

                    showtime = get_object_or_404(Showtime, pk=showtime_id)
                    booking = Booking.objects.create(
                        user=payment.user if payment.user else (request.user if request.user.is_authenticated else None),
                        showtime=showtime,
                        payment=payment,
                        total_price=payment.amount
                    )
                    for res in SeatReservation.objects.filter(id__in=held_ids):
                        booking.seats.add(res.seat)

                    booking_id = booking.id
                    transaction.on_commit(lambda: send_ticket_email_celery.delay(booking_id, guest_email))

                    # Redirect directly to the dedicated confirmation screen!
                    return redirect('booking_confirmation', booking_id=booking.id)

        except Payment.DoesNotExist:
            messages.error(request, "Invalid payment order.")
            return redirect('movie_list')

    return redirect('movie_list')

# --- BOOKING CONFIRMATION & HISTORY ---

def payment_failed(request, showtime_id):
    return render(request, 'movies/payment_failed.html', {'showtime_id': showtime_id})

def booking_confirmation(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)
    return render(request, 'movies/booking_confirmation.html', {'booking': booking})

def booking_history(request):
    if not request.user.is_authenticated:
        messages.warning(request, "Please log in to access your Account Center and Booking History.")
        return redirect('login')
    bookings = Booking.objects.filter(user=request.user).order_by('-booked_at')
    return render(request, 'movies/booking_history.html', {'bookings': bookings})

def download_ticket_pdf(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)
    pdf_content = generate_ticket_pdf_and_qr(booking)
    response = HttpResponse(pdf_content, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Movie_Ticket_{booking.id}.pdf"'
    return response

# --- ADMIN DASHBOARD ---

@staff_member_required
def admin_dashboard(request):
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    bookings = Booking.objects.all()
    payments = Payment.objects.all()
    
    if start_date and end_date:
        bookings = bookings.filter(booked_at__date__range=[start_date, end_date])
        payments = payments.filter(created_at__date__range=[start_date, end_date])

    now = timezone.now()
    today = now.date()
    week_start = today - timedelta(days=7)
    month_start = today - timedelta(days=30)
    year_start = today - timedelta(days=365)

    revenue_stats = payments.filter(status='SUCCESS').aggregate(
        total_revenue=Sum('amount'),
        daily_revenue=Sum('amount', filter=Q(created_at__date=today)),
        weekly_revenue=Sum('amount', filter=Q(created_at__date__gte=week_start)),
        monthly_revenue=Sum('amount', filter=Q(created_at__date__gte=month_start)),
        yearly_revenue=Sum('amount', filter=Q(created_at__date__gte=year_start)),
    )

    top_movies = bookings.values('showtime__movie__title').annotate(
        total_bookings=Count('id'),
        revenue=Sum('total_price')
    ).order_by('-total_bookings')[:5]

    peak_hours = bookings.annotate(
        hour=ExtractHour('booked_at')
    ).values('hour').annotate(
        count=Count('id')
    ).order_by('hour')

    cancellation_stats = payments.aggregate(
        total_success=Count('id', filter=Q(status='SUCCESS')),
        total_failed=Count('id', filter=Q(status='FAILED')),
        total_cancelled=Count('id', filter=Q(status='CANCELLED')),
    )

    top_theaters = bookings.values('showtime__screen__name').annotate(
        total_screen_bookings=Count('id'),
        screen_revenue=Sum('total_price')
    ).order_by('-total_screen_bookings')[:5]

    total_possible_seats = Seat.objects.count() * Showtime.objects.count() or 1
    total_booked_seats = bookings.aggregate(total=Count('seats'))['total'] or 0
    occupancy_percentage = round((total_booked_seats / total_possible_seats) * 100, 1)

    user_growth_count = User.objects.count()

    if request.GET.get('export') == 'csv':
        return export_analytics_csv(bookings)

    context = {
        'revenue_stats': revenue_stats,
        'top_movies': top_movies,
        'peak_hours': peak_hours,
        'cancellation_stats': cancellation_stats,
        'top_theaters': top_theaters,
        'occupancy_percentage': occupancy_percentage,
        'user_growth_count': user_growth_count,
        'start_date': start_date,
        'end_date': end_date,
    }
    return render(request, 'movies/admin_dashboard.html', context)

def export_analytics_csv(bookings):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="booking_analytics_report.csv"'
    writer = csv.writer(response)
    writer.writerow(['Booking ID', 'User', 'Movie', 'Total Price', 'Booking Date'])
    for b in bookings.select_related('user', 'showtime__movie'):
        writer.writerow([
            b.id,
            b.user.username if b.user else 'Guest',
            b.showtime.movie.title,
            b.total_price,
            b.booked_at
        ])
    return response

def admin_login_view(request):
    # If already logged in as admin, go straight to the home page (navbar will have the links)
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('movie_list')
        
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            # ONLY allow login if the user is a staff/superuser
            if user.is_staff or user.is_superuser:
                login(request, user)
                messages.success(request, f"Admin access granted. Welcome, {user.username}.")
                return redirect('movie_list')  # <-- FIXED: Redirects to homepage
            else:
                messages.error(request, "Access Denied: You do not have administrator privileges.")
        else:
            messages.error(request, "Invalid admin credentials.")
    else:
        form = AuthenticationForm()
        
    return render(request, 'movies/admin_login.html', {'form': form})