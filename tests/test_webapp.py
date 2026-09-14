import io
import os
import shutil

import pytest
from PIL import Image

from kutcontour import webapp


@pytest.fixture
def client(tmp_path, sample_dxf, monkeypatch):
    cutfiles = tmp_path / "cutfiles"
    cutfiles.mkdir()
    shutil.copy(sample_dxf, cutfiles / "sample.dxf")
    monkeypatch.setenv("KUTCONTOUR_CUTFILES", str(cutfiles))
    app = webapp.create_app(output_dir=str(tmp_path / "out"))
    app.config["TESTING"] = True
    return app.test_client()


def upload(path):
    return (io.BytesIO(open(path, "rb").read()), os.path.basename(path))


def test_index_lists_the_cut_file(client):
    page = client.get("/").get_data(as_text=True)
    assert "sample.dxf" in page
    assert "CutContour" in page


def test_cutfiles_api_reports_size(client):
    data = client.get("/api/cutfiles").get_json()
    assert data == [
        {"name": "sample.dxf", "paths": 2, "width_mm": 260.0, "height_mm": 300.0, "warnings": []}
    ]


def test_generate_returns_a_downloadable_pdf(client, artwork):
    res = client.post(
        "/api/generate",
        data={"cutfile": "sample.dxf", "image": upload(artwork), "overprint": "on"},
        content_type="multipart/form-data",
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["report"]["spot_name"] == "CutContour"
    assert body["report"]["page_mm"] == [263.0, 303.0]

    pdf = client.get(body["pdf_url"])
    assert pdf.status_code == 200
    assert pdf.data.startswith(b"%PDF")
    assert "art-cutcontour.pdf" in pdf.headers["Content-Disposition"]

    preview = client.get(body["preview_url"])
    assert preview.status_code == 200
    assert Image.open(io.BytesIO(preview.data)).size[0] > 0


def test_generate_accepts_an_uploaded_dxf(client, sample_dxf, artwork):
    res = client.post(
        "/api/generate",
        data={"dxf": upload(sample_dxf), "image": upload(artwork)},
        content_type="multipart/form-data",
    )
    assert res.status_code == 200


def test_generate_without_artwork_still_works(client):
    res = client.post(
        "/api/generate", data={"cutfile": "sample.dxf"}, content_type="multipart/form-data"
    )
    assert res.status_code == 200
    assert any("no artwork" in w for w in res.get_json()["warnings"])


def test_cut_file_names_cannot_escape_the_folder(client):
    res = client.post(
        "/api/generate",
        data={"cutfile": "../../etc/passwd"},
        content_type="multipart/form-data",
    )
    assert res.status_code == 400


def test_unsupported_artwork_type_is_refused(client, tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("not an image")
    res = client.post(
        "/api/generate",
        data={"cutfile": "sample.dxf", "image": upload(str(bad))},
        content_type="multipart/form-data",
    )
    assert res.status_code == 400


def test_template_download(client):
    res = client.get("/template/sample.dxf")
    assert res.status_code == 200
    assert "sample-template.png" in res.headers["Content-Disposition"]


def test_missing_job_is_a_404(client):
    assert client.get("/preview/deadbeef").status_code == 404
    assert client.get("/download/deadbeef/x.pdf").status_code == 404
