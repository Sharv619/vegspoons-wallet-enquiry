import zipfile
import io
import json
from src.apple_pass import create_apple_pass_package, build_pass_json


def test_build_pass_json():
    pjson = build_pass_json("pass_123", "Jane Doe", "GOLD", "pass_123")
    assert pjson["formatVersion"] == 1
    assert pjson["serialNumber"] == "pass_123"
    assert pjson["storeCard"]["primaryFields"][0]["value"] == "Jane Doe"


def test_create_apple_pass_package():
    pkpass_bytes = create_apple_pass_package("pass_123", "Jane Doe", "GOLD")
    assert len(pkpass_bytes) > 0

    zip_file = zipfile.ZipFile(io.BytesIO(pkpass_bytes))
    namelist = zip_file.namelist()
    assert "pass.json" in namelist
    assert "manifest.json" in namelist
    assert "signature" in namelist

    pass_json_content = json.loads(zip_file.read("pass.json").decode("utf-8"))
    assert pass_json_content["serialNumber"] == "pass_123"
