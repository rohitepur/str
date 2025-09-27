from fpdf import FPDF, XPos, YPos
from io import BytesIO
import tempfile
import base64
import os

class PDF(FPDF):
    """Custom PDF class to include a header and footer."""
    def header(self):
        self.set_font('Arial', 'B', 16)
        self.cell(0, 10, text='Rental Agreement', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, text=f'Page {self.page_no()}', align='C')

def create_agreement_pdf(data, template_text, signature_data_url=None):
    """
    Generates a rental agreement PDF in memory.

    :param data: Dictionary with booking information.
    :param template_text: The string content of the agreement template.
    :param signature_data_url: A base64-encoded data URL for the signature image.
    :return: A BytesIO buffer containing the PDF.
    """
    pdf = PDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    # Replace placeholders in the template with data from the form
    agreement_body = template_text
    for key, val in data.items():
        agreement_body = agreement_body.replace("{" + key + "}", str(val))

    pdf.multi_cell(0, 5, agreement_body)
    pdf.ln(10)

    # If a signature is provided, decode it and add it to the PDF
    if signature_data_url:
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, 10, text="Signature:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        temp_img_path = ""
        try:
            # Decode the base64 signature and write to a temporary file
            img_data = base64.b64decode(signature_data_url.split(',')[1])
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_img:
                temp_img.write(img_data)
                temp_img_path = temp_img.name
            pdf.image(temp_img_path, w=100)
        finally:
            # Ensure the temporary file is always deleted
            if temp_img_path and os.path.exists(temp_img_path):
                os.remove(temp_img_path)
    # pdf.output(dest='S') returns a bytearray, which doesn't need encoding.
    # Pass it directly to BytesIO.
    return BytesIO(pdf.output())
