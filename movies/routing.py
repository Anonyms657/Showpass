from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/seats/(?P<showtime_id>\d+)/$', consumers.SeatConsumer.as_asgi()),
]
