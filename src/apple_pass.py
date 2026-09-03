import json
import zipfile
import io
import hashlib
from typing import Dict, Any, Optional
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.x509 import load_pem_x509_certificate


def build_pass_json(
    pass_id: str,
    member_name: str,
    tier: str,
    serial_number: str,
    organization_name: str = "VegSpoons",
    pass_type_identifier: str = "pass.com.vegspoons.membership",
    team_identifier: str = "ABCDE12345",
) -> Dict[str, Any]:
    return {
        "formatVersion": 1,
        "passTypeIdentifier": pass_type_identifier,
        "serialNumber": serial_number,
        "teamIdentifier": team_identifier,
        "organizationName": organization_name,
        "description": "VegSpoons Membership Pass",
        "logoText": "VegSpoons Member",
        "foregroundColor": "rgb(255, 255, 255)",
        "backgroundColor": "rgb(46, 125, 50)",
        "storeCard": {
            "primaryFields": [
                {
                    "key": "member",
                    "label": "MEMBER",
                    "value": member_name,
                }
            ],
            "secondaryFields": [
                {
                    "key": "tier",
                    "label": "TIER",
                    "value": tier,
                }
            ],
            "auxiliaryFields": [
                {
                    "key": "pass_id",
                    "label": "PASS ID",
                    "value": pass_id,
                }
            ],
        },
        "barcode": {
            "format": "PKBarcodeFormatQR",
            "message": pass_id,
            "messageEncoding": "iso-8859-1",
        },
    }


def create_apple_pass_package(
    pass_id: str,
    member_name: str,
    tier: str,
    cert_pem: Optional[str] = None,
    key_pem: Optional[str] = None,
    wwdr_pem: Optional[str] = None,
) -> bytes:
    """
    Generates a .pkpass zip bundle containing pass.json, manifest.json, and signature.
    If certificates/keys are provided, signs the manifest using PKCS7; otherwise generates unsigned or test signature.
    """
    pass_dict = build_pass_json(pass_id, member_name, tier, serial_number=pass_id)
    pass_bytes = json.dumps(pass_dict, indent=2).encode("utf-8")

    manifest = {"pass.json": hashlib.sha1(pass_bytes).hexdigest()}
    manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")

    signature_bytes = b"MOCK_PKCS7_SIGNATURE"
    if cert_pem and key_pem and wwdr_pem:
        cert = load_pem_x509_certificate(cert_pem.encode("utf-8"))
        key = load_pem_private_key(key_pem.encode("utf-8"), password=None)

        options = [pkcs7.PKCS7Options.DetachedSignature]
        signature_bytes = (
            pkcs7.PKCS7SignatureBuilder()
            .set_data(manifest_bytes)
            .add_signer(cert, key, hashes.SHA256())
            .sign(pkcs7.PKCS7Encoding.DER, options)
        )

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("pass.json", pass_bytes)
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("signature", signature_bytes)

    return zip_buffer.getvalue()
