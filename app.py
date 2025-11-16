from flask import Flask, render_template, request, send_file, redirect, url_for, abort, flash
from werkzeug.utils import secure_filename
import uuid
import os
import datetime
from flask_httpauth import HTTPBasicAuth
from io import BytesIO
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from agreement_generator import create_agreement_pdf

# load environment variables 
load_dotenv()   

# Create Flask app instance
app = Flask(__name__)

# Add a secret key for flash messages
app.secret_key = os.urandom(24)

# --- DATABASE SETUP ---
# Configure the database. Use DATABASE_URL from env if available, otherwise fallback to a local sqlite file.
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///data.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)



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

class BookingRequest(db.Model):
    """Stores booking requests from the homepage."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    check_in_date = db.Column(db.String(20), nullable=False)
    check_out_date = db.Column(db.String(20), nullable=False)
    number_of_guests = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class SignedAgreement(db.Model):
    """Stores signed agreements."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    pdf_data = db.Column(db.LargeBinary, nullable=False)
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
try:
    with app.app_context():
        db.create_all()
except Exception as e:
    print(f"Database initialization error: {e}")

@app.route("/health")
def health():
    return "OK", 200

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/request-booking", methods=["POST"])
def request_booking():
    """Handles the booking request from the home page."""
    # Get form data
    name = request.form.get("name")
    email = request.form.get("email")
    phone = request.form.get("phone")
    check_in = request.form.get("check_in_date")
    check_out = request.form.get("check_out_date")
    guests = int(request.form.get("number_of_guests"))

    # Store booking request in database
    booking_request = BookingRequest(
        name=name,
        email=email,
        phone=phone,
        check_in_date=check_in,
        check_out_date=check_out,
        number_of_guests=guests
    )
    db.session.add(booking_request)
    db.session.commit()

    flash("Thank you for your request! We have received your booking inquiry and will contact you within 24 hours.", "success")
    return redirect(url_for('home'))

@app.route("/booking", methods=["GET", "POST"])
def booking():
    if request.method == "POST":
        data = request.form.to_dict()
        
        # Keep the token for later deletion when agreement is signed
        token = data.pop('token', None)

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

@app.route("/admin/requests")
@auth.login_required
def admin_requests():
    """Admin page to view all booking requests."""
    requests = BookingRequest.query.order_by(BookingRequest.created_at.desc()).all()
    return render_template("admin_requests.html", requests=requests)

@app.route("/admin/delete-request/<int:request_id>", methods=["POST"])
@auth.login_required
def delete_request(request_id):
    """Delete a booking request."""
    booking_request = BookingRequest.query.get_or_404(request_id)
    db.session.delete(booking_request)
    db.session.commit()
    flash("Booking request deleted successfully.", "success")
    return redirect(url_for('admin_requests'))

@app.route("/admin/agreements")
@auth.login_required
def admin_agreements():
    """Admin page to view all signed agreements."""
    agreements = SignedAgreement.query.order_by(SignedAgreement.created_at.desc()).all()
    return render_template("admin_agreements.html", agreements=agreements)

@app.route("/admin/download/<int:agreement_id>")
@auth.login_required
def download_agreement(agreement_id):
    """Download a signed agreement PDF."""
    agreement = SignedAgreement.query.get_or_404(agreement_id)
    return send_file(
        BytesIO(agreement.pdf_data),
        as_attachment=True,
        download_name=agreement.filename,
        mimetype='application/pdf'
    )

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

@app.route("/admin/unsigned")
@auth.login_required
def admin_unsigned():
    """Admin page to view all unsigned agreements (active PreBooking tokens)."""
    unsigned = PreBooking.query.order_by(PreBooking.created_at.desc()).all()
    return render_template("admin_unsigned.html", unsigned=unsigned)


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
    
    # Delete the PreBooking token if it exists
    token = agreement_data.get('token')
    if token:
        pre_booking_to_delete = PreBooking.query.get(token)
        if pre_booking_to_delete:
            db.session.delete(pre_booking_to_delete)
    
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
 
    # Store signed agreement in database
    signed_agreement = SignedAgreement(
        name=agreement_data.get("name", "guest"),
        email=agreement_data.get("email", ""),
        filename=filename,
        pdf_data=pdf_bytes
    )
    db.session.add(signed_agreement)
    db.session.commit()
    
    print(f"Agreement saved to database: {filename}")
    flash("Agreement successfully signed and saved.", "success")

    return send_file(BytesIO(pdf_bytes), as_attachment=True, download_name=filename, mimetype='application/pdf')

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

