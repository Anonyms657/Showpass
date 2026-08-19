from celery import shared_task
from django.core.mail import EmailMessage
from django.conf import settings
from .models import Booking
from .utils import generate_ticket_pdf_and_qr

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_ticket_email_celery(self, booking_id, guest_email=None):
    try:
        booking = Booking.objects.get(pk=booking_id)
        user_email = None
        if booking.user and booking.user.email:
            user_email = booking.user.email
        elif guest_email:
            user_email = guest_email
        else:
            user_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'support@bookmyshow.com')
        
        pdf_content = generate_ticket_pdf_and_qr(booking)

        subject = f"Your Movie Tickets Confirmed - Booking #{booking.id}"
        body = f"Hello {booking.user.username if booking.user else 'Valued Customer'},\n\nYour payment was successful! Attached is your verified PDF ticket containing your QR code and seat details.\n\nEnjoy the show!\nBookMyShow Team"
        
        email = EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user_email]
        )
        email.attach(f"Ticket_Booking_{booking.id}.pdf", pdf_content, "application/pdf")
        email.send(fail_silently=False)
    except Exception as exc:
        # Automatically retry the task if email dispatch fails
        raise self.retry(exc=exc)
from django.utils import timezone
from .models import SeatReservation
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

@shared_task
def release_expired_seat(reservation_id):
    try:
        reservation = SeatReservation.objects.get(id=reservation_id, status='HELD')
        reservation.delete()
        
        # Broadcast the release to all connected clients
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'seats_{reservation.showtime.id}',
            {
                'type': 'seat_update',
                'action': 'unlocked',
                'seat_id': reservation.seat.id
            }
        )
    except SeatReservation.DoesNotExist:
        pass
