from django.db import models
from django.contrib.auth.models import User
from django.db.models import Avg

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

class Showtime(models.Model):
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='showtimes')
    theater = models.ForeignKey(Theater, on_delete=models.CASCADE, related_name='showtimes')
    date = models.DateField()
    time = models.TimeField()
    ticket_price = models.DecimalField(max_digits=6, decimal_places=2)

    def __str__(self):
        return f"{self.movie.title} at {self.theater.name} ({self.date} {self.time})"