import io
import xml.etree.ElementTree as ET

import qrcode
import qrcode.image.svg

DARK_COLOR = "#20252b"


def generate_qr_svg(data: str) -> str:
    """Generate a QR code as inline SVG markup."""
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=0,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)

    buffer = io.BytesIO()
    img.save(buffer)
    buffer.seek(0)

    tree = ET.parse(buffer)
    root = tree.getroot()

    # Set dark module color on the path element
    ns = {"svg": "http://www.w3.org/2000/svg"}
    for path in root.findall(".//svg:path", ns):
        path.set("fill", DARK_COLOR)

    # Remove non-standard attributes left by qrcode library
    for attr in ("fill_color", "back_color"):
        if attr in root.attrib:
            del root.attrib[attr]

    ET.register_namespace("", "http://www.w3.org/2000/svg")
    out = io.StringIO()
    tree.write(out, encoding="unicode", xml_declaration=False)
    return out.getvalue()
