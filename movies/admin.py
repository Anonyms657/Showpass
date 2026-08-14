from django.contrib import admin
from django.db import models
from django import forms
from .models import Genre, Language, CastMember, Movie, MoviePoster, Review, Theater, Screen, Showtime, Seat, SeatReservation, Booking, Payment

class MoviePosterInline(admin.TabularInline):
    model = MoviePoster
    extra = 3

@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ('title', 'release_date', 'age_certification', 'is_trending', 'average_rating')
    list_filter = ('genres', 'languages', 'age_certification', 'is_trending')
    search_fields = ('title', 'description')
    inlines = [MoviePosterInline]

admin.site.register(Genre)
admin.site.register(Language)
admin.site.register(CastMember)
admin.site.register(Review)
class ScreenInline(admin.TabularInline):
    model = Screen
    extra = 1

@admin.register(Theater)
class TheaterAdmin(admin.ModelAdmin):
    list_display = ('name', 'city')
    inlines = [ScreenInline]

@admin.register(Screen)
class ScreenAdmin(admin.ModelAdmin):
    list_display = ('name', 'theater', 'number_of_rows', 'seats_per_row')
    list_filter = ('theater',)

@admin.register(Showtime)
class ShowtimeAdmin(admin.ModelAdmin):
    list_display = ('movie', 'screen', 'start_time', 'ticket_price')
    formfield_overrides = {
        models.DateTimeField: {
            'form_class': forms.DateTimeField,
            'widget': forms.DateTimeInput(attrs={'type': 'datetime-local'})
        },
    }

@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = ('row', 'number', 'screen')
    list_filter = ('screen',)

@admin.register(SeatReservation)
class SeatReservationAdmin(admin.ModelAdmin):
    list_display = ('showtime', 'seat', 'user', 'status', 'reserved_at')

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('razorpay_order_id', 'user', 'amount', 'status', 'created_at')
    list_filter = ('status', 'created_at')

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'showtime', 'total_price', 'booked_at')
    list_filter = ('booked_at',)