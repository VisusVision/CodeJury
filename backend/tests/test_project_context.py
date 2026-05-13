import unittest

from backend.agents.project_context import build_project_context


class ProjectContextTests(unittest.TestCase):
    def test_api_assignment_extracts_project_terms_and_io(self):
        ctx = build_project_context(
            "Kutuphane Odunc Takip API",
            (
                "FastAPI ile kitap, uye, odunc ve iade kayitlarini yoneten REST API gelistirin. "
                "POST /books ve POST /loans endpointleri JSON hata yanitlari uretmelidir."
            ),
        )

        self.assertIn("kitap", ctx.terms)
        self.assertIn("api", ctx.terms)
        self.assertIn("/books", ctx.terms)
        self.assertIn("api", ctx.deliverables)
        self.assertIn("json", ctx.io_formats)
        self.assertIn("fastapi", ctx.tech_stack)

    def test_csv_assignment_extracts_report_and_error_context(self):
        ctx = build_project_context(
            "CSV Rapor Export Araci",
            "Ogrenci skorlarini alip gecme durumunu hesaplayan, hatali satirlari raporlayan CLI yazin.",
        )

        self.assertIn("csv", ctx.terms)
        self.assertIn("csv raporu", ctx.deliverables)
        self.assertIn("komut satiri", ctx.io_formats)
        self.assertIn("hatali satir/deger", ctx.error_cases)

    def test_rubric_rows_support_short_assignment_context(self):
        ctx = build_project_context(
            "Not Programi",
            "Python programi.",
            [
                {"name": "Ortalama", "description": "Not listesinden sinif ortalamasini hesaplar."},
                {"name": "Gecme Kalma", "description": "Gecen ve kalan ogrenci sayisini raporlar."},
            ],
        )

        self.assertIn("ortalamasini", ctx.terms)
        self.assertIn("rapor", ctx.deliverables)


if __name__ == "__main__":
    unittest.main()
