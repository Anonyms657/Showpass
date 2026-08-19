import os
import qrcode
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from django.conf import settings

def generate_ticket_pdf_and_qr(booking):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # 1. Generate QR Code with Verification URL
    # Replace localhost with production domain in real environment
    verify_url = f"https://example.com/ticket/verify/{booking.id}/"
    qr = qrcode.QRCode(box_size=4, border=2)
    qr.add_data(verify_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    
    qr_path = f"temp_qr_{booking.id}.png"
    qr_img.save(qr_path)

    # 2. Draw PDF Ticket Header
    p.setFillColor(colors.HexColor("#1e1b4b"))
    p.rect(0, height - 120, width, 120, fill=1, stroke=0)

    p.setFillColor(colors.white)
    p.setFont("Helvetica-Bold", 24)
    p.drawString(54, height - 60, "BookMyShow - Verified Ticket")
    
    p.setFont("Helvetica", 12)
    p.drawString(54, height - 85, f"Booking Reference ID: #{booking.id}")
    p.drawString(54, height - 105, f"Booked On: {booking.booked_at.strftime('%d %b %Y, %H:%M')}")

    # 3. Movie & Theater Details
    p.setFillColor(colors.HexColor("#0f172a"))
    p.setFont("Helvetica-Bold", 16)
    movie_title = booking.showtime.movie.title if booking.showtime and booking.showtime.movie else "Movie Screening"
    p.drawString(54, height - 170, f"Movie: {movie_title}")

    p.setFont("Helvetica", 12)
    screen_name = booking.showtime.screen.name if booking.showtime and booking.showtime.screen else "Screen 1"
    theater_name = booking.showtime.screen.theater.name if booking.showtime and booking.showtime.screen and booking.showtime.screen.theater else "Unknown"
    theater_city = booking.showtime.screen.theater.city if booking.showtime and booking.showtime.screen and booking.showtime.screen.theater else "Unknown"
    theater_address = booking.showtime.screen.theater.address if booking.showtime and booking.showtime.screen and booking.showtime.screen.theater else "Unknown"
    show_time = booking.showtime.start_time.strftime('%d %b %Y, %H:%M') if booking.showtime and booking.showtime.start_time else "TBD"
    
    payment_ref = booking.payment.razorpay_payment_id if booking.payment and booking.payment.razorpay_payment_id else "N/A"

    details = [
        ("Theater:", f"{theater_name}, {theater_city}"),
        ("Address:", theater_address),
        ("Screen:", screen_name),
        ("Show Timing:", show_time),
        ("Ticket Price:", f"₹{booking.total_price}"),
        ("Payment Ref:", payment_ref),
        ("Payment Status:", "SUCCESS (Verified)")
    ]

    y_pos = height - 210
    for label, val in details:
        p.setFont("Helvetica-Bold", 11)
        p.drawString(54, y_pos, label)
        p.setFont("Helvetica", 11)
        p.drawString(180, y_pos, val)
        y_pos -= 25

    # 4. Seats Assigned
    p.setFont("Helvetica-Bold", 11)
    p.drawString(54, y_pos, "Assigned Seats:")
    seats_str = ", ".join([f"Row {s.row} - Seat {s.number}" for s in booking.seats.all()])
    p.setFont("Helvetica", 11)
    p.drawString(180, y_pos, seats_str if seats_str else "General Admission")

    # 5. Insert QR Code
    p.drawImage(qr_path, width - 180, height - 380, width=120, height=120)
    p.setFont("Helvetica-Oblique", 9)
    p.setFillColor(colors.gray)
    p.drawString(width - 180, height - 395, "Scan for gate verification")

    # Footer
    p.setStrokeColor(colors.HexColor("#cbd5e1"))
    p.line(54, 100, width - 54, 100)
    p.setFont("Helvetica", 9)
    p.drawString(54, 80, "Thank you for booking with BookMyShow. Enjoy your show!")

    p.showPage()
    p.save()

    if os.path.exists(qr_path):
        os.remove(qr_path)

    buffer.seek(0)
    return buffer.getvalue()
