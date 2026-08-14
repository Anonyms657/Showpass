import string
from django.db import models
from django.contrib.auth.models import User
from django.db.models import Avg
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

class Genre(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name

class Language(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name

class CastMember(models.Model):
    name = models.CharField(max_length=100)
    role = models.CharField(max_length=100, help_text="e.g. Director, Lead Actor")

    def __str__(self):
        return f"{self.name} ({self.role})"

class Movie(models.Model):
    AGE_RATINGS = [
        ('U', 'Universal'),
        ('UA', 'Parental Guidance'),
        ('A', 'Adults Only'),
    ]

    title = models.CharField(max_length=200)
    description = models.TextField()
    duration_minutes = models.IntegerField()
    age_certification = models.CharField(max_length=5, choices=AGE_RATINGS)
    youtube_trailer_url = models.URLField(help_text="YouTube URL or Embed ID")
    release_date = models.DateField()
    genres = models.ManyToManyField(Genre)
    languages = models.ManyToManyField(Language)
    cast = models.ManyToManyField(CastMember, blank=True)
    is_trending = models.BooleanField(default=False)

    @property
    def average_rating(self):
        avg = self.reviews.aggregate(Avg('rating'))['rating__avg']
        return round(avg, 1) if avg else 0.0

    def __str__(self):
        return self.title

class MoviePoster(models.Model):
    movie = models.ForeignKey(Movie, related_name='posters', on_delete=models.CASCADE)
    image = models.ImageField(upload_to='movie_posters/')

class Review(models.Model):
    movie = models.ForeignKey(Movie, related_name='reviews', on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.IntegerField(choices=[(i, str(i)) for i in range(1, 6)])
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_verified_viewer = models.BooleanField(default=False)
    is_reported = models.BooleanField(default=False)

    class Meta:
        unique_together = ('movie', 'user') # One review per user per movie

class Theater(models.Model):
    name = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    address = models.TextField()

    def __str__(self):
        return f"{self.name} - {self.city}"
    
class Screen(models.Model):
    theater = models.ForeignKey(Theater, on_delete=models.CASCADE, related_name='screens')
    name = models.CharField(max_length=50)  # e.g., "Screen 1", "IMAX 3D"
    number_of_rows = models.IntegerField(default=4, help_text="e.g., 4 creates rows A, B, C, D")
    seats_per_row = models.IntegerField(default=8, help_text="Number of seats in each row")

    def __str__(self):
        return f"{self.theater.name} - {self.name}"

class Showtime(models.Model):
    movie = models.ForeignKey('Movie', on_delete=models.CASCADE, related_name='showtimes')
    screen = models.ForeignKey(Screen, on_delete=models.CASCADE, null=True) # Links directly to Screen!
    start_time = models.DateTimeField()
    ticket_price = models.DecimalField(max_digits=6, decimal_places=2, default=200.00)

    def __str__(self):
        screen_name = self.screen.name if self.screen else "No Screen"
        return f"{self.movie.title} - {screen_name} ({self.start_time.strftime('%I:%M %p')})"

class Seat(models.Model):
    screen = models.ForeignKey(Screen, on_delete=models.CASCADE, related_name='seats', null=True)
    row = models.CharField(max_length=2)  # e.g., 'A', 'B'
    number = models.IntegerField()        # e.g., 1, 2

    class Meta:
        unique_together = ('screen', 'row', 'number')

    def __str__(self):
        screen_name = self.screen.name if self.screen else "No Screen"
        return f"{screen_name} - {self.row}{self.number}"

class SeatReservation(models.Model):
    STATUS_CHOICES = (
        ('HELD', 'Temporarily Held'),
        ('BOOKED', 'Booked'),
    )
    showtime = models.ForeignKey(Showtime, on_delete=models.CASCADE)
    seat = models.ForeignKey(Seat, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='HELD')
    reserved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('showtime', 'seat')

    def is_expired(self):
        if self.status == 'HELD':
            return timezone.now() > self.reserved_at + timedelta(minutes=2)
        return False

# --- THE MAGIC SIGNAL ---
# This automatically generates all seats whenever a new Screen is created in Admin!
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=Screen)
def create_seats_for_screen(sender, instance, created, **kwargs):
    if created:
        alphabet = string.ascii_uppercase
        for row_idx in range(instance.number_of_rows):
            row_letter = alphabet[row_idx % 26] # Handles up to 26 rows (A-Z)
            for seat_num in range(1, instance.seats_per_row + 1):
                Seat.objects.create(screen=instance, row=row_letter, number=seat_num)


class Payment(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_signature = models.CharField(max_length=200, blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, default='PENDING') # PENDING, SUCCESS, FAILED
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Order {self.razorpay_order_id} - {self.status}"

class Booking(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    showtime = models.ForeignKey(Showtime, on_delete=models.CASCADE)
    seats = models.ManyToManyField(Seat)
    payment = models.OneToOneField(Payment, on_delete=models.CASCADE)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    booked_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Booking {self.id} for {self.showtime.movie.title}"