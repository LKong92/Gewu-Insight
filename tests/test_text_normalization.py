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

    def test_fflo_names_keep_initial_capitals(self):
        self.assertEqual(
            normalize_publication_title("fulde ferrell larkin ovchinnikov state in superconductors"),
            "Fulde Ferrell Larkin Ovchinnikov state in superconductors",
        )
        self.assertEqual(
            normalize_publication_title("Fulde-Ferrell-Larkin-Ovchinnikov phase"),
            "Fulde-Ferrell-Larkin-Ovchinnikov phase",
        )

    def test_parenthesized_formula_counts_become_subscripts(self):
        self.assertEqual(
            normalize_publication_title("Superconductivity in Ba(Fe1-xCox)2As2"),
            "Superconductivity in Ba(Fe₁₋ₓCoₓ)₂As₂",
        )
        self.assertEqual(
            normalize_publication_title("Evidence of Andreev bound states as a hallmark of the FFLO phase in κ-(BEDT-TTF)2Cu(NCS)2"),
            "Evidence of andreev bound states as a hallmark of the FFLO phase in κ-(BEDT-TTF)₂Cu(NCS)₂",
        )
        self.assertEqual(
            normalize_publication_title("Cu(NCS)2"),
            "Cu(NCS)₂",
        )
        self.assertEqual(
            normalize_publication_title("Transport in (NH4)2SO4 and La(O1-xFx)1+δBiS2"),
            "Transport in (NH₄)₂SO₄ and La(O₁₋ₓFₓ)₁₊δBiS₂",
        )
        self.assertEqual(
            normalize_publication_title("La(O1-yFy)1-δBiS2"),
            "La(O₁₋ᵧFᵧ)₁₋δBiS₂",
        )

    def test_formula_delta_case_is_preserved(self):
        self.assertEqual(
            normalize_publication_title("Bi2Sr2CaCu2O8+Δ and La2CuO4+Δ"),
            "Bi₂Sr₂CaCu₂O₈₊Δ and La₂CuO₄₊Δ",
        )
        self.assertEqual(
            normalize_publication_title("Bi2Sr2CaCu2O8+δ and La2CuO4+δ"),
            "Bi₂Sr₂CaCu₂O₈₊δ and La₂CuO₄₊δ",
        )


if __name__ == "__main__":
    unittest.main()
