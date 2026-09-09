import os
import re
import json
import shutil

import pdfplumber

from validators import validar_cuit


def tesseract_available() -> bool:
    if shutil.which("tesseract"):
        return True
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def ocr_extract_text(path) -> str:
    """Convierte cada página a imagen y le pasa OCR. Se usa solo cuando el PDF
    no tiene texto seleccionable (ej. una factura escaneada como imagen)."""
    try:
        import pypdfium2 as pdfium
        import pytesseract
    except ImportError:
        return ""

    if not tesseract_available():
        return ""

    text_parts = []
    pdf = pdfium.PdfDocument(str(path))
    for page in pdf:
        bitmap = page.render(scale=300 / 72)
        image = bitmap.to_pil()
        try:
            text_parts.append(pytesseract.image_to_string(image, lang="spa"))
        except Exception:
            text_parts.append(pytesseract.image_to_string(image))
    return "\n".join(text_parts)


def extract_text_from_pdf(file) -> tuple[str, bool]:
    """Devuelve (texto, uso_ocr). Si el PDF no tiene texto seleccionable
    (escaneado como imagen), intenta leerlo con OCR."""
    text_parts = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
    text = "\n".join(text_parts)

    if len(text.strip()) < 20:
        ocr_text = ocr_extract_text(file)
        if len(ocr_text.strip()) > len(text.strip()):
            return ocr_text, True

    return text, False


CUIT_LABELED_RE = re.compile(r"cuit\s*[:\.]?\s*(\d{2}-?\d{8}-?\d)", re.IGNORECASE)
CUIT_RE = re.compile(r"\b\d{2}-?\d{8}-?\d\b")

FECHA_LABELED_RE = re.compile(
    r"fecha(?:\s+de\s+emisi[oó]n)?\s*[:\.]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", re.IGNORECASE
)
FECHA_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")

FACTURA_NUM_RE = re.compile(
    r"(?:factura|comprobante|nro\.?\s*(?:de\s*)?comp(?:robante)?|n[°ºo]\.?)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-]{3,20})",
    re.IGNORECASE,
)

# Cualquier "total" que no sea "subtotal"; se buscan TODAS las apariciones y se
# toma la última porque el total final suele ir después del subtotal/IVA.
TOTAL_RE = re.compile(
    r"(?<!sub)(?:total a pagar|importe total|total general|total)\s*[:$]?\s*\$?\s*([\d]{1,3}(?:[\.,]\d{3})*(?:[\.,]\d{2})?)",
    re.IGNORECASE,
)

PROVEEDOR_HINT_RE = re.compile(r"(?:raz[oó]n social|proveedor|emisor)\s*[:]?\s*(.+)", re.IGNORECASE)


def heuristic_extract(text: str) -> dict:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    first_line = lines[0] if lines else ""

    cuit_match = CUIT_LABELED_RE.search(text) or CUIT_RE.search(text)
    fecha_match = FECHA_LABELED_RE.search(text) or FECHA_RE.search(text)
    numero_match = FACTURA_NUM_RE.search(text)
    total_matches = list(TOTAL_RE.finditer(text))
    proveedor_match = PROVEEDOR_HINT_RE.search(text)

    proveedor = proveedor_match.group(1).strip() if proveedor_match else first_line
    cuit = cuit_match.group(1) if cuit_match and cuit_match.lastindex else (cuit_match.group(0) if cuit_match else None)

    return {
        "proveedor": proveedor[:120] if proveedor else None,
        "cuit": cuit,
        "numero_factura": numero_match.group(1) if numero_match else None,
        "fecha": fecha_match.group(1) if fecha_match and fecha_match.lastindex else (fecha_match.group(0) if fecha_match else None),
        "total": total_matches[-1].group(1) if total_matches else None,
        "moneda": "ARS" if "$" in text else None,
        "cuit_valido": "Si" if validar_cuit(cuit) else "No",
        "metodo_extraccion": "heuristico",
    }


CLAUDE_SYSTEM_PROMPT = (
    "Extraes datos estructurados de facturas/comprobantes en texto plano extraido de un PDF. "
    "Respondes UNICAMENTE con un JSON valido, sin texto adicional, con exactamente estas claves: "
    "proveedor, cuit, numero_factura, fecha (formato DD/MM/AAAA si es posible), total (solo el numero, "
    "sin simbolo de moneda, usando punto decimal), moneda (ej ARS, USD). "
    "Si un dato no aparece en el texto, usa null para esa clave."
)


def claude_extract(text: str) -> dict | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import anthropic
    except ImportError:
        return None

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=500,
        system=CLAUDE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text[:8000]}],
    )
    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    data["metodo_extraccion"] = "claude"
    data["cuit_valido"] = "Si" if validar_cuit(data.get("cuit")) else "No"
    return data


def extract_fields(text: str) -> dict:
    result = claude_extract(text)
    if result:
        return result
    return heuristic_extract(text)
