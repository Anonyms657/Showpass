from datetime import datetime
import razorpay
from django.conf import settings
import uuid
import csv
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
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
    city = request.GET.get('city', '')
    release_date = request.GET.get('release_date', '')
    show_timing = request.GET.get('show_timing', '')
    min_rating = request.GET.get('min_rating', '')
    sort_by = request.GET.get('sort', '')

    movies = Movie.objects.all().annotate(
        avg_rating=Avg('reviews__rating'),
        min_price=Min('showtimes__ticket_price')
    )

    if query:
        movies = movies.filter(Q(title__icontains=query) | Q(description__icontains=query))
    if genre:
        movies = movies.filter(genres__name__icontains=genre)
    if language:
        movies = movies.filter(languages__name__icontains=language)
    if theater:
        movies = movies.filter(showtimes__screen__theater__name__icontains=theater)
    if city:
        movies = movies.filter(showtimes__screen__theater__city__icontains=city)
    if release_date:
        movies = movies.filter(release_date=release_date)
    if show_timing:
        try:
            show_date = datetime.strptime(show_timing, '%Y-%m-%d').date()
            movies = movies.filter(showtimes__start_time__date=show_date)
        except:
            pass
    if min_rating:
        try:
            movies = movies.filter(avg_rating__gte=float(min_rating))
        except ValueError:
            pass

    if sort_by == 'popularity':
        movies = movies.annotate(booking_count=Count('showtimes__booking')).order_by('-booking_count')
    elif sort_by == 'newest':
        movies = movies.order_by('-release_date')
    elif sort_by == 'price_low':
        movies = movies.order_by('min_price')
    elif sort_by == 'price_high':
        movies = movies.order_by('-min_price')

    movies = movies.distinct()

    paginator = Paginator(movies, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Recently viewed
    recently_viewed_ids = request.session.get('recently_viewed', [])
    recently_viewed = Movie.objects.filter(id__in=recently_viewed_ids) if recently_viewed_ids else []

    context = {
        'page_obj': page_obj,
        'search_query': query,
        'genres': Genre.objects.all(),
        'languages': Language.objects.all(),
        'recently_viewed': recently_viewed,
    }
    return render(request, 'movies/movie_list.html', context)


def movie_detail(request, pk):
    movie = get_object_or_404(Movie, pk=pk)
    
    # Store recently viewed in session
    recently_viewed = request.session.get('recently_viewed', [])
    if pk not in recently_viewed:
        recently_viewed.insert(0, pk)
        request.session['recently_viewed'] = recently_viewed[:5]
        
    showtimes = movie.showtimes.filter(start_time__gte=timezone.now()).order_by('start_time')
    
    # Group showtimes by date for the template
    grouped_showtimes = {}
    for st in showtimes:
        date_key = st.start_time.date()
        if date_key not in grouped_showtimes:
            grouped_showtimes[date_key] = []
        grouped_showtimes[date_key].append(st)
        
    # Recommendations
    similar_movies = Movie.objects.filter(genres__in=movie.genres.all()).exclude(id=movie.id).distinct()[:5]
    trending_movies = Movie.objects.filter(is_trending=True).exclude(id=movie.id)[:5]
    recent_movies = Movie.objects.exclude(id=movie.id).order_by('-release_date')[:5]

    context = {
        'movie': movie,
        'grouped_showtimes': grouped_showtimes,
        'similar_movies': similar_movies,
        'trending_movies': trending_movies,
        'recent_movies': recent_movies,
    }
    return render(request, 'movies/movie_detail.html', context)

@login_required
def submit_review(request, pk):
    if request.method == 'POST':
        movie = get_object_or_404(Movie, pk=pk)
        
        # Check if user booked and watched the movie
        has_watched = Booking.objects.filter(
            user=request.user, 
            showtime__movie=movie, 
            showtime__start_time__lt=timezone.now()
        ).exists()
        
        if not has_watched:
            messages.error(request, "You can only review movies you have booked and watched.")
            return redirect('movie_detail', pk=pk)
            
        rating = request.POST.get('rating')
        comment = request.POST.get('comment')
        
        Review.objects.update_or_create(
            movie=movie, user=request.user,
            defaults={'rating': rating, 'comment': comment, 'is_verified_viewer': True}
        )
        messages.success(request, "Review submitted successfully.")
    return redirect('movie_detail', pk=pk)
    
@login_required
def report_review(request, review_id):
    review = get_object_or_404(Review, pk=review_id)
    review.is_reported = True
    review.save()
    messages.success(request, "Review reported.")
    return redirect('movie_detail', pk=review.movie.id)


@login_required
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
                    
                    # Schedule release task
                    from .tasks import release_expired_seat
                    release_expired_seat.apply_async((res.id,), countdown=120)
                    
                    # Broadcast lock via websockets
                    from asgiref.sync import async_to_sync
                    from channels.layers import get_channel_layer
                    channel_layer = get_channel_layer()
                    async_to_sync(channel_layer.group_send)(
                        f'seats_{showtime.id}',
                        {
                            'type': 'seat_update',
                            'action': 'locked',
                            'seat_id': seat.id
                        }
                    )

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
    amount_in_paise = int(total_amount * 100)

    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    razorpay_order = client.order.create({
        "amount": amount_in_paise,
        "currency": "INR",
        "payment_capture": "1"
    })

    Payment.objects.create(
        user=request.user if request.user.is_authenticated else None,
        razorpay_order_id=razorpay_order['id'],
        amount=total_amount,
        status='PENDING'
    )

    request.session['current_showtime_id'] = showtime.id
    
    context = {
        'showtime': showtime,
        'total_amount': total_amount,
        'order_id': razorpay_order['id'],
        'razorpay_key_id': settings.RAZORPAY_KEY_ID,
        'amount_in_paise': amount_in_paise,
    }
    return render(request, 'movies/payment_gateway.html', context)

@csrf_exempt
def process_mock_payment(request):
    if request.method == "POST":
        razorpay_payment_id = request.POST.get('razorpay_payment_id')
        razorpay_order_id = request.POST.get('razorpay_order_id')
        razorpay_signature = request.POST.get('razorpay_signature')
        guest_email = request.POST.get('guest_email', '').strip()
        showtime_id = request.session.get('current_showtime_id')
        held_ids = request.session.get('held_reservation_ids', [])

        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

        try:
            client.utility.verify_payment_signature({
                'razorpay_order_id': razorpay_order_id,
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_signature': razorpay_signature
            })
        except razorpay.errors.SignatureVerificationError:
            messages.error(request, "Payment signature verification failed.")
            return redirect('seat_selection', showtime_id=showtime_id)

        try:
            with transaction.atomic():
                payment = Payment.objects.get(razorpay_order_id=razorpay_order_id)
                if payment.status in ['SUCCESS', 'FAILED', 'CANCELLED']:
                    messages.warning(request, "This transaction has already been processed.")
                    return redirect('seat_selection', showtime_id=showtime_id)

                payment.status = 'SUCCESS'
                payment.razorpay_payment_id = razorpay_payment_id
                payment.razorpay_signature = razorpay_signature
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
                from .tasks import send_ticket_email_celery
                transaction.on_commit(lambda: send_ticket_email_celery.apply_async((booking_id, guest_email)))

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

@login_required
def download_ticket_pdf(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)
    if booking.user != request.user and not request.user.is_staff:
        messages.error(request, "You do not have permission to view this ticket.")
        return redirect('movie_list')
        
    pdf_content = generate_ticket_pdf_and_qr(booking)
    response = HttpResponse(pdf_content, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Movie_Ticket_{booking.id}.pdf"'
    return response

@staff_member_required
def verify_ticket(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)
    return render(request, 'movies/verify_ticket.html', {'booking': booking})


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
        total_refunded=Count('id', filter=Q(status='REFUNDED')),
    )

    top_theaters = bookings.values('showtime__screen__theater__name').annotate(
        total_screen_bookings=Count('id'),
        screen_revenue=Sum('total_price')
    ).order_by('-screen_revenue')[:5]

    # Calculate actual occupancy based on past showtimes
    past_showtimes = Showtime.objects.filter(start_time__lt=now)
    total_possible_seats = 0
    for st in past_showtimes:
        total_possible_seats += st.screen.seats.count()
        
    total_booked_seats = Booking.objects.filter(showtime__in=past_showtimes).aggregate(total=Count('seats'))['total'] or 0
    occupancy_percentage = round((total_booked_seats / total_possible_seats) * 100, 1) if total_possible_seats > 0 else 0

    user_growth_count = User.objects.filter(date_joined__gte=month_start).count()

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