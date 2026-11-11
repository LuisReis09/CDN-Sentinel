import base64
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from app import create_app
from services.watermark_service import WatermarkService
from utils.image_watermark import _luminance, embed_image, visual_marker
from utils.security import create_watermark_token
from utils.video import get_video_asset
from utils.video_watermark import embed_video


class WatermarkSecurityTests(unittest.TestCase):
    def test_versioned_claim_keeps_legacy_and_adds_content_binding(self):
        service = WatermarkService("watermark-test-secret")
        legacy_token, legacy_claim = service.issue("client-1", "server-1", 2)
        self.assertTrue(legacy_token.startswith("CDNWM2."))
        self.assertIsNone(legacy_claim.content_id)

        token, claim = service.issue("client-1", "server-1", 2, "video-42")
        self.assertTrue(token.startswith("CDNWM3."))
        verified = service.verify(token)
        self.assertEqual(verified.content_id, "video-42")
        self.assertEqual(verified.chunk_id, claim.chunk_id)

    def test_crypto_rejects_tampering_wrong_key_and_unknown_version(self):
        token = create_watermark_token("client-1", "server-1", 1.0, "chunk-1", "secret", "video-1")
        service = WatermarkService("secret")
        self.assertEqual(service.verify(token).content_id, "video-1")
        with self.assertRaises(ValueError):
            service.verify(token[:-1] + ("0" if token[-1] != "0" else "1"))
        with self.assertRaises(ValueError):
            WatermarkService("wrong-secret").verify(token)
        with self.assertRaises(ValueError):
            service.verify("CDNWM9.not-a-valid-envelope.signature")

    def test_detector_is_independent_from_original_and_expected_token(self):
        service = WatermarkService("image-test-secret")
        token, _claim = service.issue("client-1", "server-1", 0, "video-1")
        original = Image.new("RGB", (256, 256), (123, 117, 110))
        marked, _metadata = embed_image(original, token, service.secret_key)

        evidence = service.detect_image(marked)
        self.assertEqual(evidence["status"], "VALID")
        self.assertEqual(evidence["marker"], visual_marker(token))
        self.assertEqual(evidence["client_id"], "client-1")
        self.assertEqual(service.detect_image(original)["status"], "NOT_FOUND")

        blurred = marked.filter(ImageFilter.GaussianBlur(radius=1))
        self.assertEqual(service.detect_image(blurred)["status"], "VALID")

    def test_perceptual_mask_reduces_flat_region_energy_without_losing_detection(self):
        service = WatermarkService("perceptual-mask-secret")
        token, _claim = service.issue("client-1", "server-1", 0, "video-1")
        original = Image.new("RGB", (256, 256), (140, 120, 100))
        legacy, _metadata = embed_image(original, token, service.secret_key, strength=12, adaptive=False)
        adaptive, _metadata = embed_image(original, token, service.secret_key, strength=12, adaptive=True)
        before, _mode, _alpha = _luminance(original)
        legacy_luma, _mode, _alpha = _luminance(legacy)
        adaptive_luma, _mode, _alpha = _luminance(adaptive)
        legacy_delta = float(np.abs(legacy_luma - before).mean())
        adaptive_delta = float(np.abs(adaptive_luma - before).mean())
        self.assertLess(adaptive_delta, legacy_delta * 0.25)
        self.assertEqual(service.detect_image(adaptive)["status"], "VALID")

    def test_plain_images_do_not_become_valid_and_small_images_are_inconclusive(self):
        service = WatermarkService("negative-test-secret")
        plain = Image.new("RGB", (256, 256), (0, 0, 0))
        self.assertEqual(service.detect_image(plain)["status"], "NOT_FOUND")
        self.assertEqual(service.detect_image(Image.new("RGB", (20, 20), (10, 10, 10)))["status"], "INCONCLUSIVE")
        self.assertEqual(service.detect_image(Image.new("L", (64, 64), 80))["status"], "INCONCLUSIVE")

    def test_detector_route_accepts_png_upload_and_base64(self):
        app = create_app()
        controller = app.extensions["cdn_controller"]
        token, _claim = controller.watermark_service.issue("client-route", "server-route", 0, "video-route")
        marked, _metadata = embed_image(Image.new("RGBA", (256, 256), (140, 120, 100, 255)), token, controller.watermark_service.secret_key)
        buffer = io.BytesIO()
        marked.save(buffer, format="PNG")
        payload = buffer.getvalue()
        client = app.test_client()

        uploaded = client.post(
            "/api/security/watermark/detect",
            data={"file": (io.BytesIO(payload), "marked.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.get_json())
        self.assertEqual(uploaded.get_json()["status"], "VALID")
        self.assertEqual(uploaded.get_json()["content_id"], "video-route")

        encoded = base64.b64encode(payload).decode("ascii")
        detected_base64 = client.post(
            "/api/security/watermark/detect",
            json={"media_base64": encoded, "media_type": "image"},
        )
        self.assertEqual(detected_base64.status_code, 200, detected_base64.get_json())
        self.assertEqual(detected_base64.get_json()["status"], "VALID")

        video_token, _claim = controller.watermark_service.issue("client-video-route", "server-video-route", 0, "video-route")
        source, _content_type = get_video_asset("cdn_sentinel_demo", "original")
        with tempfile.TemporaryDirectory(prefix="cdn-watermark-test-") as temporary:
            marked_video = Path(temporary) / "marked.mp4"
            embed_video(source, marked_video, video_token, controller.watermark_service.secret_key)
            with marked_video.open("rb") as video_file:
                detected_video = client.post(
                    "/api/security/watermark/detect",
                    data={"file": (video_file, "marked.mp4")},
                    content_type="multipart/form-data",
                )
        self.assertEqual(detected_video.status_code, 200, detected_video.get_json())
        self.assertEqual(detected_video.get_json()["status"], "VALID")
        self.assertLessEqual(detected_video.get_json()["visual_hamming_distance"], 5)


if __name__ == "__main__":
    unittest.main()
