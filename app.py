from flask import Flask, render_template, request, send_file, redirect, url_for, abort, flash, jsonify
from werkzeug.utils import secure_filename
import uuid
import os
import datetime
import json
from datetime import datetime as dt
from flask_httpauth import HTTPBasicAuth
from io import BytesIO
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv
from agreement_generator import create_agreement_pdf

# load environment variables 
load_dotenv()   

# Create Flask app instance
app = Flask(__name__)

# Add a secret key for flash messages
app.secret_key = os.urandom(24)

# --- DATABASE SETUP ---
client = MongoClient(
    os.environ.get('MONGODB_URI', 'mongodb://localhost:27017/'),
    tls=True,
    tlsAllowInvalidCertificates=True,
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=5000,
    socketTimeoutMS=5000
)
db = client.str_property



# --- COLLECTIONS ---
pre_bookings = db.pre_bookings
pending_agreements = db.pending_agreements
booking_requests = db.booking_requests
signed_agreements = db.signed_agreements

# Initialize Flask-HTTPAuth
auth = HTTPBasicAuth()

@auth.verify_password
def verify_password(username, password):
    """Verify username and password against environment variables."""
    admin_user = os.environ.get('ADMIN_USERNAME')
    admin_pass = os.environ.get('ADMIN_PASSWORD')
    if username == admin_user and password == admin_pass:
        return username



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
    booking_requests.insert_one({
        'name': name,
        'email': email,
        'phone': phone,
        'check_in_date': check_in,
        'check_out_date': check_out,
        'number_of_guests': guests,
        'created_at': datetime.datetime.now(datetime.timezone.utc)
    })

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
        
        # Store the token back in data if it exists
        if token:
            data['token'] = token

        # Generate a unique ID for this agreement
        agreement_id = str(uuid.uuid4())
        
        # Delete the pre-booking record if it exists
        if token:
            pre_bookings.delete_one({'_id': token})
        
        # Store the booking data in the database, associated with the new ID
        pending_agreements.insert_one({
            '_id': agreement_id,
            'data': data,
            'check_in_date': data.get('check_in_date'),
            'check_out_date': data.get('check_out_date'),
            'created_at': datetime.datetime.now(datetime.timezone.utc)
        }) 
        
        # Redirect the user to the new agreement signing page
        return redirect(url_for("agreement", agreement_id=agreement_id))

    # For a standard GET request, just show a blank booking form.
    return render_template("booking.html")

@app.route("/book/<token>")
def guest_booking(token):
    """This is the unique link the guest will use."""
    pre_booking = pre_bookings.find_one({'_id': token})
    if not pre_booking:
        abort(404, "This booking link is invalid or has already been used.")
    
    # Pass the data and the token to the booking template
    prefill_data = pre_booking['data']
    return render_template("booking.html", token=token, **prefill_data)

@app.route("/admin/requests")
@auth.login_required
def admin_requests():
    """Admin page to view all booking requests."""
    requests = list(booking_requests.find().sort('created_at', -1))
    return render_template("admin_requests.html", requests=requests)

@app.route("/admin/delete-request/<request_id>", methods=["POST"])
@auth.login_required
def delete_request(request_id):
    """Delete a booking request."""
    result = booking_requests.delete_one({'_id': ObjectId(request_id)})
    if result.deleted_count == 0:
        abort(404)
    flash("Booking request deleted successfully.", "success")
    return redirect(url_for('admin_requests'))

@app.route("/admin/agreements")
@auth.login_required
def admin_agreements():
    """Admin page to view all signed agreements."""
    agreements = list(signed_agreements.find().sort('created_at', -1))
    return render_template("admin_agreements.html", agreements=agreements)

@app.route("/admin/download/<agreement_id>")
@auth.login_required
def download_agreement(agreement_id):
    """Download a signed agreement PDF."""
    agreement = signed_agreements.find_one({'_id': ObjectId(agreement_id)})
    if not agreement:
        abort(404)
    return send_file(
        BytesIO(agreement['pdf_data']),
        as_attachment=True,
        download_name=agreement['filename'],
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
        pre_bookings.insert_one({
            '_id': token,
            'data': data,
            'check_in_date': data.get('check_in_date'),
            'check_out_date': data.get('check_out_date'),
            'created_at': datetime.datetime.now(datetime.timezone.utc)
        })
        link = url_for('guest_booking', token=token, _external=True)
        return render_template("admin_generate.html", generated_link=link)

    return render_template("admin_generate.html")

@app.route("/admin/unsigned")
@auth.login_required
def admin_unsigned():
    """Admin page to view all unsigned agreements (active PreBooking tokens)."""
    unsigned = list(pre_bookings.find().sort('created_at', -1))
    return render_template("admin_unsigned.html", unsigned=unsigned)

@app.route("/admin/delete-unsigned/<token>", methods=["POST"])
@auth.login_required
def delete_unsigned(token):
    """Delete an unsigned booking link."""
    result = pre_bookings.delete_one({'_id': token})
    if result.deleted_count == 0:
        abort(404)
    flash("Unsigned booking link deleted successfully.", "success")
    return redirect(url_for('admin_unsigned'))

@app.route("/admin/calendar")
@auth.login_required
def admin_calendar():
    """Admin calendar view showing all bookings."""
    return render_template("admin_calendar.html")

@app.route("/api/calendar-events")
@auth.login_required
def calendar_events():
    """API endpoint for calendar events."""
    events = []
    
    # Booking requests (red)
    requests = booking_requests.find()
    for req in requests:
        if req.get('check_in_date') and req.get('check_out_date'):
            events.append({
                'title': f'Request: {req["name"]}',
                'start': req['check_in_date'],
                'end': req['check_out_date'],
                'color': '#dc3545',
                'type': 'request',
                'id': str(req['_id']),
                'name': req['name'],
                'email': req['email']
            })
    
    # Unsigned agreements (orange)
    unsigned = pre_bookings.find()
    for pre in unsigned:
        if pre.get('check_in_date') and pre.get('check_out_date'):
            events.append({
                'title': f'Unsigned: {pre["data"].get("name", "Unknown")}',
                'start': pre['check_in_date'],
                'end': pre['check_out_date'],
                'color': '#fd7e14',
                'type': 'unsigned',
                'token': pre['_id'],
                'name': pre['data'].get('name', 'Unknown')
            })
    
    # Pending agreements (yellow)
    pending = pending_agreements.find()
    for pend in pending:
        if pend.get('check_in_date') and pend.get('check_out_date'):
            events.append({
                'title': f'Pending: {pend["data"].get("name", "Unknown")}',
                'start': pend['check_in_date'],
                'end': pend['check_out_date'],
                'color': '#ffc107',
                'type': 'pending',
                'id': pend['_id'],
                'name': pend['data'].get('name', 'Unknown')
            })
    
    # Signed agreements (green)
    signed = signed_agreements.find()
    for sign in signed:
        if sign.get('check_in_date') and sign.get('check_out_date'):
            events.append({
                'title': f'Signed: {sign["name"]}',
                'start': sign['check_in_date'],
                'end': sign['check_out_date'],
                'color': '#28a745',
                'type': 'signed',
                'id': str(sign['_id']),
                'name': sign['name'],
                'email': sign['email']
            })
    
    return jsonify(events)

@app.route("/agreement/<agreement_id>")
def agreement(agreement_id):
    pending = pending_agreements.find_one({'_id': agreement_id})
    if not pending:
        abort(404, "Agreement not found or has expired.")

    agreement_data = pending['data']
    with open("agreement_template.txt", "r") as f:
        template_text = f.read()

    # Pre-populate the template with booking data for review
    populated_text = template_text
    for key, val in agreement_data.items():
        populated_text = populated_text.replace("{" + key + "}", str(val))

    return render_template("agreement.html", agreement_id=agreement_id, agreement_text=populated_text)

@app.route("/sign/<agreement_id>", methods=["POST"])
def sign_agreement(agreement_id):
    pending = pending_agreements.find_one({'_id': agreement_id})
    if not pending:
        abort(404, "Agreement not found or has expired.")

    agreement_data = pending['data']
    
    # Delete the PreBooking token if it exists
    token = agreement_data.get('token')
    if token:
        pre_bookings.delete_one({'_id': token})
    
    # Delete the pending agreement
    pending_agreements.delete_one({'_id': agreement_id})
    
    signature_data_url = request.form.get("signature")

    with open("agreement_template.txt", "r") as f:
        template_text = f.read()

    # Generate the PDF in memory
    pdf_buffer = create_agreement_pdf(agreement_data, template_text, signature_data_url)
    
    # Get the raw bytes of the PDF
    pdf_bytes = pdf_buffer.getvalue()
    pdf_buffer.close()

    safe_name = secure_filename(agreement_data.get("name", "guest"))
    filename = f"{safe_name}_signed_agreement.pdf"
 
    # Store signed agreement in database
    signed_agreements.insert_one({
        'name': agreement_data.get("name", "guest"),
        'email': agreement_data.get("email", ""),
        'filename': filename,
        'pdf_data': pdf_bytes,
        'check_in_date': agreement_data.get('check_in_date'),
        'check_out_date': agreement_data.get('check_out_date'),
        'created_at': datetime.datetime.now(datetime.timezone.utc)
    })
    
    flash("Agreement successfully signed and saved.", "success")
    return send_file(BytesIO(pdf_bytes), as_attachment=True, download_name=filename, mimetype='application/pdf')

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

