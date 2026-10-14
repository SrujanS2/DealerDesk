from django.test import TestCase

from core.testutils import JsonClientMixin, make_dealer


class DealerApiTests(JsonClientMixin, TestCase):
    def test_create_list_get(self):
        r = self.post_json("/api/dealers/", {"dealer_code": "DLR-900", "name": "New Dealer"})
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertEqual(body["credit_limit"], "0.00")
        self.assertEqual(self.client.get(f"/api/dealers/{body['id']}/").json()["dealer_code"], "DLR-900")
        self.assertEqual(self.client.get("/api/dealers/").json()["count"], 1)

    def test_duplicate_and_validation(self):
        make_dealer("DLR-001")
        self.assertError(self.post_json("/api/dealers/", {"dealer_code": "DLR-001", "name": "x"}), 409, "DUPLICATE")
        self.assertError(self.post_json("/api/dealers/", {"name": "x"}), 400, "VALIDATION_ERROR")
        self.assertError(self.post_json("/api/dealers/", {"dealer_code": "D", "name": ""}), 400, "VALIDATION_ERROR")

    def test_404(self):
        self.assertError(self.client.get("/api/dealers/999999/"), 404, "NOT_FOUND")
        self.assertError(self.client.get("/api/dealers/abc/"), 404, "NOT_FOUND")
