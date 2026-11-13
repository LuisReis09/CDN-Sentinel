import random
import unittest

import numpy as np
from PIL import Image

from watermark.ecc import Secded55Codec
from utils.qim_watermark import _decode_qim3_score_vector, detect_image_qim3, embed_image_qim3
from utils.image_watermark import SYNC_BITS, SYNC_MARKER, marker_bits, visual_marker
from tools.watermark_perceptual_experiments import _ssim


class Secded55Tests(unittest.TestCase):
    def test_windowed_ssim_responds_to_local_structure(self):
        image = np.tile(np.arange(64, dtype=np.float64), (64, 1)) * 4
        self.assertAlmostEqual(_ssim(image, image), 1.0, places=6)
        altered = image.copy()
        altered[20:40, 20:40] = 0
        self.assertLess(_ssim(image, altered), 1.0)

    def test_qim3_image_round_trip_has_real_marker(self):
        rng = np.random.default_rng(2026)
        pixels = np.clip(128 + rng.normal(0, 20, (360, 640, 3)), 0, 255).astype(np.uint8)
        image = Image.fromarray(pixels, "RGB")
        token = "CDNWM4.test-for-image-roundtrip"
        marked, metadata = embed_image_qim3(image, token, "qim3-image-test-secret")
        evidence = detect_image_qim3(marked, "qim3-image-test-secret")
        self.assertEqual(metadata["ecc"], "SECDED-Hamming-55-48-v1")
        self.assertEqual(evidence["marker"], visual_marker(token))

    def test_corrects_every_single_bit_and_detects_double_errors(self):
        codec = Secded55Codec()
        rng = random.Random(2026)
        marker = [rng.randint(0, 1) for _ in range(48)]
        encoded = codec.encode(marker)
        self.assertEqual(codec.decode(encoded), (marker, 0, "CLEAN"))
        for position in range(55):
            damaged = encoded.copy()
            damaged[position] ^= 1
            self.assertEqual(codec.decode(damaged), (marker, 1, "CORRECTED"))
        for left in range(55):
            for right in range(left + 1, 55):
                damaged = encoded.copy()
                damaged[left] ^= 1
                damaged[right] ^= 1
                self.assertEqual(codec.decode(damaged)[2], "UNCORRECTABLE")

    def test_soft_qim3_decoder_recovers_two_low_confidence_channel_errors_without_relaxing_gate(self):
        token = "CDNWM4.soft-decoder-test"
        marker = visual_marker(token)
        bits = marker_bits(SYNC_MARKER, SYNC_BITS) + Secded55Codec().encode(marker_bits(marker))
        scores = np.asarray([-0.6 if bit else 0.6 for bit in bits], dtype=np.float64)
        # Two weak sign errors are uncorrectable for the hard SECDED path but
        # recoverable when their reliabilities identify them as the least
        # trustworthy observations.
        for index in (SYNC_BITS + 3, SYNC_BITS + 17):
            scores[index] *= -0.03
        baseline = _decode_qim3_score_vector(scores)
        improved = _decode_qim3_score_vector(scores, soft_decode=True)
        self.assertEqual(baseline["ecc_status"], "UNCORRECTABLE")
        self.assertEqual(improved["ecc_status"], "SOFT_CORRECTED")
        self.assertEqual(improved["marker"], marker)
        self.assertGreaterEqual(improved["confidence"], 0.15)


if __name__ == "__main__":
    unittest.main()
