from flask import Flask, render_template, request, send_file
from fpdf import FPDF
import os

app = Flask(__name__)
os.makedirs("agreements", exist_ok=True)

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

        # Create PDF agreement
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        pdf.cell(200, 10, txt="Rental Agreement", ln=True, align="C")
        pdf.ln(10)

        for key, val in data.items():
            pdf.cell(200, 10, txt=f"{key}: {val}", ln=True)

        file_path = f"agreements/{data['name']}_agreement.pdf"
        pdf.output(file_path)

        return send_file(file_path, as_attachment=True)

    return render_template("booking.html")

@app.route("/agreement")
def agreement():
    return render_template("agreement.html")

if __name__ == "__main__":
    app.run(debug=True)
