from flask import Flask, render_template, request, send_file, redirect, url_for, abort, flash
from werkzeug.utils import secure_filename
import uuid
import os
import datetime
# Add email imports
import smtplib
import ssl
from email.message import EmailMessage
# Add authentication import
from flask_httpauth import HTTPBasicAuth
from io import BytesIO
# Add database and S3 client imports
from flask_sqlalchemy import SQLAlchemy
import boto3
# To load environment variables from a .env file
from dotenv import load_dotenv
from email import policy
# Import the new modular function
from agreement_generator import create_agreement_pdf
import boto3

app = Flask(__name__)

# Initialize S3 client
s3 = boto3.client('s3')

# load environment variables 
load_dotenv()   

# Add a secret key for flash messages
app.secret_key = os.urandom(24)

# --- DATABASE SETUP ---
# Configure the database. Use DATABASE_URL from env if available, otherwise fallback to a local sqlite file.
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///data.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Ensure the 'agreements' directory exists for local fallback storage
os.makedirs("agreements", exist_ok=True)

# --- DATABASE MODELS ---
class PreBooking(db.Model):
    """Stores temporary data for pre-filled booking links."""
    token = db.Column(db.String(36), primary_key=True)
    data = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class PendingAgreement(db.Model):
    """Stores data for an agreement that is awaiting a signature."""
    id = db.Column(db.String(36), primary_key=True)
    data = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

# Initialize Flask-HTTPAuth
auth = HTTPBasicAuth()

@auth.verify_password
def verify_password(username, password):
    """Verify username and password against environment variables."""
    admin_user = os.environ.get('ADMIN_USERNAME')
    admin_pass = os.environ.get('ADMIN_PASSWORD')
    if username == admin_user and password == admin_pass:
        return username

# Create database tables if they don't exist
with app.app_context():
    db.create_all()

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
    
    em = EmailMessage(policy=policy.SMTPUTF8)
    em['From'] = email_sender
    em['To'] = email_receiver
    em['Subject'] = subject
    em.set_content(body)
    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(email_host, email_port, context=context) as smtp:
            smtp.login(email_sender, email_password)
            smtp.send_message(em)
        flash("Thank you for your request! The owner will be in touch with you shortly.", "success")
    except Exception as e:
        print(f"Error sending email: {e}")
        flash("There was an error submitting your request. Please try again later.", "error")

    return redirect(url_for('home'))

@app.route("/booking", methods=["GET", "POST"])
def booking():
    if request.method == "POST":
        data = request.form.to_dict()
        
       # If this booking came from a generated link, remove the temporary pre-booking data.
        token = data.pop('token', None)
        if token:
            pre_booking_to_delete = PreBooking.query.get(token)
            if pre_booking_to_delete:
                db.session.delete(pre_booking_to_delete)

        if not data.get("name") or not data.get("email"):
            abort(400, "Name and email are required fields.")
        
        if not data.get("adults") or not data.get("adults").strip():
            abort(400, "Guest names (adults over 12) are required.")
        
        if not data.get("vehicles") or not data.get("vehicles").strip():
            abort(400, "Vehicle information is required.")
    
        # Add the current date to the data dictionary for the agreement template.
        data['today'] = datetime.date.today().strftime("%B %d, %Y")

        # Generate a unique ID for this agreement
        agreement_id = str(uuid.uuid4())
        
        # Store the booking data in the database, associated with the new ID
        new_agreement = PendingAgreement(id=agreement_id, data=data)
        db.session.add(new_agreement)
        db.session.commit() 
        
        # Redirect the user to the new agreement signing page
        return redirect(url_for("agreement", agreement_id=agreement_id))

    # For a standard GET request, just show a blank booking form.
    return render_template("booking.html")

@app.route("/book/<token>")
def guest_booking(token):
    """This is the unique link the guest will use."""
    pre_booking = PreBooking.query.get(token)
    if not pre_booking:
        abort(404, "This booking link is invalid or has already been used.")
    
    # Pass the data and the token to the booking template
    prefill_data = pre_booking.data
    return render_template("booking.html", token=token, **prefill_data)

@app.route("/admin/generate", methods=["GET", "POST"])
@auth.login_required
def generate_link():
    """An admin page to create a pre-filled link for a guest."""
    if request.method == "POST":
        data = request.form.to_dict()
        token = str(uuid.uuid4())
        
        # Store the pre-booking data in the database
        new_pre_booking = PreBooking(token=token, data=data)
        db.session.add(new_pre_booking)
        db.session.commit()
        link = url_for('guest_booking', token=token, _external=True)
        return render_template("admin_generate.html", generated_link=link)

    return render_template("admin_generate.html")


@app.route("/agreement/<agreement_id>")
def agreement(agreement_id):
    pending = PendingAgreement.query.get(agreement_id)
    if not pending:
        abort(404, "Agreement not found or has expired.")

    agreement_data = pending.data
    with open("agreement_template.txt", "r") as f:
        template_text = f.read()

    # Pre-populate the template with booking data for review
    populated_text = template_text
    for key, val in agreement_data.items():
        populated_text = populated_text.replace("{" + key + "}", str(val))

    return render_template("agreement.html", agreement_id=agreement_id, agreement_text=populated_text)

@app.route("/sign/<agreement_id>", methods=["POST"])
def sign_agreement(agreement_id):
    pending = PendingAgreement.query.get(agreement_id)
    if not pending:
        abort(404, "Agreement not found or has expired.")

    agreement_data = pending.data
    db.session.delete(pending)
    db.session.commit()
    signature_data_url = request.form.get("signature")

    with open("agreement_template.txt", "r") as f:
        template_text = f.read()

    # Generate the PDF in memory
    pdf_buffer = create_agreement_pdf(agreement_data, template_text, signature_data_url)
    
    # Get the raw bytes of the PDF. This is safer than passing the buffer around.
    pdf_bytes = pdf_buffer.getvalue()
    pdf_buffer.close()

    safe_name = secure_filename(agreement_data.get("name", "guest"))
    filename = f"{safe_name}_signed_agreement.pdf"
 
    # --- PERSISTENT FILE STORAGE ---
    # Upload to a cloud service like AWS S3 instead of saving locally.
    s3_bucket = os.environ.get('S3_BUCKET_NAME')
    if s3_bucket:
        try:
            s3.put_object(
                Body=pdf_bytes,
                Bucket=s3_bucket,
                Key=f"agreements/{filename}",
                ContentType='application/pdf'
            )
            flash("Agreement successfully uploaded to secure storage.", "info")
        except Exception as e:
            print(f"Error uploading to S3: {e}")
            flash("Critical: Could not save the signed agreement to cloud storage.", "error")
    else:
        # Fallback to local storage if S3 is not configured (for development)
        print("WARNING: S3_BUCKET_NAME not set. Saving agreement to local 'agreements/' directory.")
        file_path = os.path.join("agreements", filename)
        with open(file_path, "wb") as f:
            f.write(pdf_bytes)

    return send_file(BytesIO(pdf_bytes), as_attachment=True, download_name=filename, mimetype='application/pdf')

if __name__ == "__main__":
    app.run(debug=True)

