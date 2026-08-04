from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    # This line connects the homepage to your movies app routing
    path('', include('movies.urls')),
]