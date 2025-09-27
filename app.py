from flask import Flask, render_template, request, send_file, redirect, url_for, abort
from werkzeug.utils import secure_filename
import uuid
import os

# Import the new modular function
from agreement_generator import create_agreement_pdf

app = Flask(__name__)

# Ensure the 'agreements' directory exists for saving signed PDFs
os.makedirs("agreements", exist_ok=True)

# Use a dictionary as a simple in-memory store for pending agreements.
# In a production app, you would use a database for persistence.
pending_agreements = {}

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/gallery")
def gallery():
    return render_template("gallery.html")

@app.route("/booking", methods=["GET", "POST"])
def booking():
    if request.method == "POST":
        data = request.form.to_dict()
        if not data.get("name") or not data.get("email"):
            abort(400, "Name and email are required fields.")

        # Generate a unique ID for this agreement
        agreement_id = str(uuid.uuid4())
        
        # Store the booking data temporarily, associated with the new ID
        pending_agreements[agreement_id] = data
        
        # Redirect the user to the new agreement signing page
        return redirect(url_for("agreement", agreement_id=agreement_id))

    return render_template("booking.html")

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

