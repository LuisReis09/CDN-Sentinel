import unittest

from watermark.anticollusion import TardosCodebook, simulate


class AntiCollusionTests(unittest.TestCase):
    def test_seeded_codebook_and_coalition_simulation(self):
        users = [f"u{i}" for i in range(20)]
        first = TardosCodebook.generate(users, 256, seed=17)
        second = TardosCodebook.generate(users, 256, seed=17)
        self.assertTrue((first.bits == second.bits).all())
        observed = first.coalition_copy(["u0", "u1"], strategy="interleaving", seed=18)
        self.assertEqual(observed.shape, (256,))
        self.assertEqual(len(first.scores(observed)), 20)
        self.assertEqual(simulate(20, 256, 2, 17)["attribution"], "NONE")


if __name__ == "__main__":
    unittest.main()
