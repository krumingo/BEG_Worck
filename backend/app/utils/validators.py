"""
Business data validators — EIK, VAT, IBAN, etc.
"""


def validate_eik(eik: str) -> dict:
    """Validate Bulgarian EIK (9 or 13 digits)."""
    if not eik:
        return {"valid": True, "message": ""}
    eik = eik.strip()
    if not eik.isdigit():
        return {"valid": False, "message": "ЕИК трябва да съдържа само цифри"}
    if len(eik) not in [9, 13]:
        return {"valid": False, "message": f"ЕИК трябва да е 9 или 13 цифри, подаден: {len(eik)}"}
    return {"valid": True, "message": ""}


def validate_vat_number(vat: str) -> dict:
    """Validate Bulgarian VAT number (BG + 9 or 10 digits)."""
    if not vat:
        return {"valid": True, "message": ""}
    vat = vat.strip().upper()
    if not vat.startswith("BG"):
        return {"valid": False, "message": "ДДС номер трябва да започва с BG"}
    digits = vat[2:]
    if not digits.isdigit() or len(digits) not in [9, 10]:
        return {"valid": False, "message": "ДДС номер: BG + 9 или 10 цифри"}
    return {"valid": True, "message": ""}
