from django.contrib import admin
from .models import Genre, Language, CastMember, Movie, MoviePoster, Review, Theater, Showtime

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
admin.site.register(Theater)
admin.site.register(Showtime)