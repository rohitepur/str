from flask import Flask, render_template, request, send_file, redirect, url_for, abort, flash
from werkzeug.utils import secure_filename
import uuid
import os
import datetime
# Add email imports
import smtplib
import ssl
from email.message import EmailMessage

# Import the new modular function
from agreement_generator import create_agreement_pdf

app = Flask(__name__)

# Add a secret key for flash messages
app.secret_key = os.urandom(24)

# Ensure the 'agreements' directory exists for saving signed PDFs
os.makedirs("agreements", exist_ok=True)

# Use a dictionary as a simple in-memory store for pending agreements.
# In a production app, you would use a database for persistence.
pending_agreements = {}
pre_bookings = {} # new store for pre booking data

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/request-booking", methods=["POST"])
def request_booking():
    """Handles the booking request from the home page and sends an email."""
    # Get form data
    name = request.form.get("name")
    email = request.form.get("email")
    phone = request.form.get("phone")
    check_in = request.form.get("check_in_date")
    check_out = request.form.get("check_out_date")
    guests = request.form.get("number_of_guests")

    # Get Email credentials from environment variables
    email_sender = os.environ.get('EMAIL_SENDER')
    email_password = os.environ.get('EMAIL_PASSWORD')
    email_receiver = os.environ.get('EMAIL_RECEIVER') # This will be the owner's email
    email_host = os.environ.get('EMAIL_HOST', 'smtp.gmail.com') # Default to Gmail
    email_port = int(os.environ.get('EMAIL_PORT', 465)) # Default to Gmail SSL port

    if not all([email_sender, email_password, email_receiver]):
        print("Email environment variables are not fully configured.")
        flash("Could not process request due to a server configuration error.", "error")
        return redirect(url_for('home'))

    # Create the email message
    subject = f"New Booking Request from {name}"
    body = (
        f"You have a new booking request for the Pocono Lake House:\n\n"
        f"Name: {name}\n"
        f"Email: {email}\n"
        f"Phone: {phone}\n"
        f"Check-in: {check_in}\n"
        f"Check-out: {check_out}\n"
        f"Guests: {guests}\n\n"
        f"You can use the admin panel to generate a pre-filled booking link for them."
    )
    
    em = EmailMessage()
    em['From'] = email_sender
    em['To'] = email_receiver
    em['Subject'] = subject
    em.set_content(body)

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(email_host, email_port, context=context) as smtp:
            smtp.login(email_sender, email_password)
            smtp.sendmail(email_sender, email_receiver, em.as_string())
        flash("Thank you for your request! The owner will be in touch with you shortly.", "success")
    except Exception as e:
        print(f"Error sending email: {e}")
        flash("There was an error submitting your request. Please try again later.", "error")

    return redirect(url_for('home'))

@app.route("/booking", methods=["GET", "POST"])
def booking():
    if request.method == "POST":
        data = request.form.to_dict()

        # If this booking came from a generated link, we can remove the temporary
        # pre-booking data. We use pop to also remove the token from the data dict.
        token = data.pop('token', None)
        if token:
            # This was a pre-filled booking, clean up the pre_bookings store.
            pre_bookings.pop(token, None)

        if not data.get("name") or not data.get("email"):
            abort(400, "Name and email are required fields.")
    
        # Add the current date to the data dictionary for the agreement template.
        data['today'] = datetime.date.today().strftime("%B %d, %Y")

        # Generate a unique ID for this agreement
        agreement_id = str(uuid.uuid4())
        
        # Store the booking data temporarily, associated with the new ID
        pending_agreements[agreement_id] = data
        
        # Redirect the user to the new agreement signing page
        return redirect(url_for("agreement", agreement_id=agreement_id))

    # For a standard GET request, just show a blank booking form.
    return render_template("booking.html")

@app.route("/book/<token>")
def guest_booking(token):
    """This is the unique link the guest will use."""
    prefill_data = pre_bookings.get(token)
    if not prefill_data:
        abort(404, "This booking link is invalid or has already been used.")
    
    # Pass the data and the token to the booking template
    return render_template("booking.html", token=token, **prefill_data)

@app.route("/admin/generate", methods=["GET", "POST"])
def generate_link():
    """An admin page to create a pre-filled link for a guest."""
    if request.method == "POST":
        data = request.form.to_dict()
        token = str(uuid.uuid4())
        pre_bookings[token] = data
        
        link = url_for('guest_booking', token=token, _external=True)
        return render_template("admin_generate.html", generated_link=link)

    return render_template("admin_generate.html")


@app.route("/agreement/<agreement_id>")
def agreement(agreement_id):
    agreement_data = pending_agreements.get(agreement_id)
    if not agreement_data:
        abort(404, "Agreement not found or has expired.")

    with open("agreement_template.txt", "r") as f:
        template_text = f.read()

    # Pre-populate the template with booking data for review
    populated_text = template_text
    for key, val in agreement_data.items():
        populated_text = populated_text.replace("{" + key + "}", str(val))

    return render_template("agreement.html", agreement_id=agreement_id, agreement_text=populated_text)

@app.route("/sign/<agreement_id>", methods=["POST"])
def sign_agreement(agreement_id):
    agreement_data = pending_agreements.pop(agreement_id, None)
    if not agreement_data:
        abort(404, "Agreement not found or has expired.")

    signature_data_url = request.form.get("signature")

    with open("agreement_template.txt", "r") as f:
        template_text = f.read()

    pdf_buffer = create_agreement_pdf(agreement_data, template_text, signature_data_url)
    
    safe_name = secure_filename(agreement_data.get("name", "guest"))
    filename = f"{safe_name}_signed_agreement.pdf"

    # Save a copy of the signed agreement to the server
    file_path = os.path.join("agreements", filename)
    with open(file_path, "wb") as f:
        f.write(pdf_buffer.getbuffer())

    # Reset the buffer's position to the beginning for send_file
    pdf_buffer.seek(0)

    return send_file(pdf_buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')

if __name__ == "__main__":
    app.run(debug=True)

