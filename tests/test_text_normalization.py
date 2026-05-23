import unittest

from paper_monitor.text import normalize_publication_title


class TitleNormalizationTest(unittest.TestCase):
    def test_wave_symmetry_prefixes_stay_lowercase_and_tight(self):
        self.assertEqual(
            normalize_publication_title(
                "D -wave Fermi surface instability in the nematic phase of two monolayer FeSe/SrTiO 3"
            ),
            "d-wave Fermi surface instability in the nematic phase of two monolayer FeSe/SrTiO₃",
        )
        self.assertEqual(
            normalize_publication_title("Possible SD - wave and G -wave states"),
            "Possible sd-wave and g-wave states",
        )

    def test_variable_doping_formula_counts_become_subscripts(self):
        self.assertEqual(
            normalize_publication_title("Observation of non-Fermi liquid behavior in hole-doped LiFe1-xVxAs"),
            "Observation of non-Fermi liquid behavior in hole-doped LiFe₁₋ₓVₓAs",
        )
        self.assertEqual(
            normalize_publication_title("Ba1+xKxFe2As2 and FeSe1+xTex"),
            "Ba₁₊ₓKₓFe₂As₂ and FeSe₁₊ₓTeₓ",
        )
        self.assertEqual(
            normalize_publication_title("La2CuO4+x"),
            "La₂CuO₄₊ₓ",
        )
        self.assertEqual(
            normalize_publication_title("Ba1 + x Kx Fe2 As2 and Fe1 + δ Se1 - x Tex"),
            "Ba₁₊ₓKₓFe₂As₂ and Fe₁₊δSe₁₋ₓTeₓ",
        )
        self.assertEqual(
            normalize_publication_title("La2CuO4 + δ"),
            "La₂CuO₄₊δ",
        )
        self.assertEqual(
            normalize_publication_title("Anomalous Andreev conductance in InAs-AlSb quantum wells"),
            "Anomalous andreev conductance in InAs-AlSb quantum wells",
        )


if __name__ == "__main__":
    unittest.main()
