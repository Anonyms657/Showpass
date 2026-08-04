from django.shortcuts import render, get_object_or_404
from .models import Movie

def movie_list(request):
    # Fetch all movies to show on the homepage
    movies = Movie.objects.all()
    return render(request, 'movies/movie_list.html', {'movies': movies})

def movie_detail(request, pk):
    # Fetch the specific movie being viewed
    movie = get_object_or_404(Movie, pk=pk)
    
    # Task 1 Requirement: Similar, Trending, and Recent Recommendations
    similar_movies = Movie.objects.filter(
        genres__in=movie.genres.all(), 
        languages__in=movie.languages.all()
    ).exclude(id=movie.id).distinct()[:4]
    
    trending_movies = Movie.objects.filter(is_trending=True).exclude(id=movie.id)[:4]
    recent_movies = Movie.objects.order_by('-release_date').exclude(id=movie.id)[:4]

    context = {
        'movie': movie,
        'similar_movies': similar_movies,
        'trending_movies': trending_movies,
        'recent_movies': recent_movies
    }
    return render(request, 'movies/movie_detail.html', context)