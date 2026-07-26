from __future__ import annotations

import unittest

from i18n import (
    language_from_label,
    language_label,
    profile_code,
    profile_label,
    scoring_label,
    translate_text,
)


class I18nTests(unittest.TestCase):
    def test_api_key_persistence_labels_are_translated(self) -> None:
        self.assertEqual(
            translate_text("Mémoriser la clé sur ce PC", "en"),
            "Remember the key on this PC",
        )
        self.assertEqual(
            translate_text(
                "La clé mémorisée est chiffrée par Windows pour ce compte utilisateur.",
                "en",
            ),
            "The saved key is encrypted by Windows for this user account.",
        )

    def test_uma_moe_filter_labels_are_translated(self) -> None:
        self.assertEqual(
            translate_text("Filtres de recherche uma.moe", "en"),
            "uma.moe search filters",
        )
        self.assertEqual(translate_text("Surface cible", "en"), "Target surface")
        self.assertEqual(translate_text("Étoiles blue", "en"), "Blue stars")
        self.assertEqual(
            translate_text("Parent opposé prévu (optionnel)", "en"),
            "Planned opposing parent (optional)",
        )

    def test_language_labels_round_trip(self) -> None:
        self.assertEqual(language_from_label(language_label("fr")), "fr")
        self.assertEqual(language_from_label(language_label("en")), "en")

    def test_core_ui_translation(self) -> None:
        self.assertEqual(translate_text("Liaison & catalogue", "en"), "Link & Catalogue")
        self.assertEqual(translate_text("Prêt", "en"), "Ready")
        self.assertEqual(translate_text("Prêt", "fr"), "Prêt")

    def test_formatted_status_translation(self) -> None:
        source = "Terminé — 42 vétérans liés."
        self.assertEqual(translate_text(source, "en"), "Complete — 42 veterans linked.")

    def test_transfer_helper_runtime_log_translation(self) -> None:
        source = "Évaluation de 42 vétérans dans 32 contextes de profil/catégorie…"
        self.assertEqual(
            translate_text(source, "en"),
            "Evaluating 42 veterans across 32 profile/category contexts…",
        )


    def test_polish_runtime_strings_are_translated(self) -> None:
        self.assertEqual(
            translate_text("Friend ID copié : 123456789", "en"),
            "Friend ID copied: 123456789",
        )
        self.assertEqual(
            translate_text(
                "Pondération Transfer Helper — parent : affinity=20.0%", "en"
            ),
            "Transfer Helper parent weights: affinity=20.0%",
        )

    def test_remaining_runtime_scoring_fragments_are_translated(self) -> None:
        samples = {
            "uma.moe : page 1, objectif 2000 candidats…": "uma.moe: page 1, target 2000 candidates…",
            "- aptitude naturelle : B → départ : -": "- natural aptitude: B → start: -",
            "- facteurs : 0★ / 0 porteur(s)": "- Sparks: 0★ / 0 carrier(s)",
            "Liaison : 25/125": "Linking: 25/125",
            "Friend ID copié dans le presse-papiers": "Friend ID copied to clipboard",
        }
        for source, expected in samples.items():
            with self.subTest(source=source):
                self.assertEqual(translate_text(source, "en"), expected)

    def test_optimizer_detail_panel_is_fully_translated(self) -> None:
        source = """Vertes / uniques
Roses — détail brut
Blues — pertinence selon la distance :
Style — optimisation secondaire :
Surface — optimisation secondaire :
- dont parents directs : 1
- procs requis pour A : 0 | pour S : 1
Distance S — contrainte de la paire finale :
- statut : Prête pour S (palier 4)
Calcul du score global :
Affinité moderne — diagnostic global :"""
        expected = """Green / Unique Sparks
Pink Sparks — raw detail
Blue Sparks — relevance by distance:
Running style — secondary optimisation:
Surface — secondary optimisation:
- including direct parents: 1
- procs required for A: 0 | for S: 1
Distance S — final-pair constraint:
- status: Ready for S (tier 4)
Overall score calculation:
Modern affinity — global diagnostic:"""
        self.assertEqual(translate_text(source, "en"), expected)

    def test_weight_examples_are_human_readable_in_english(self) -> None:
        source = (
            "• Blues → stat favorisée par distance : augmenter Stamina pour Long "
            "favorise les lignées Stamina en Long."
        )
        translated = translate_text(source, "en")
        self.assertIn("Blue Sparks", translated)
        self.assertIn("Stamina lineages", translated)
        self.assertNotIn("blue_stat_weights_by_distance", translated)

    def test_fragment_translation_does_not_retranslate_english_output(self) -> None:
        translated = translate_text(
            "Contribution du candidat = triple(Ace, parent cible, candidat) : 12",
            "en",
        )
        self.assertEqual(
            translated,
            "Candidate contribution = triple(Ace, target parent, candidate): 12",
        )
        self.assertNotIn("Candidatee", translated)

    def test_user_facing_terminology_avoids_card(self) -> None:
        translated = translate_text(
            "Un transfert n'est marqué comme sûr que si un autre exemplaire de la même carte et de la même unique n'est moins bon dans aucune niche globalement viable, y compris pour le support G1 en paire.",
            "en",
        )
        self.assertIn("costume variant", translated)
        self.assertNotIn("same card", translated.casefold())
        self.assertEqual(translate_text("Costume / card", "en"), "Costume / variant")

    def test_profile_values_remain_canonical(self) -> None:
        label = profile_label("style", "pace_chaser", "en")
        self.assertEqual(profile_code("style", label), "pace_chaser")
        self.assertEqual(profile_code("surface", profile_label("surface", "dirt", "fr")), "dirt")

    def test_scoring_labels_are_localised(self) -> None:
        self.assertEqual(scoring_label("future_grandparent", "fr"), "Futur grand-parent")
        self.assertEqual(scoring_label("future_grandparent", "en"), "Future grandparent")
        self.assertEqual(scoring_label("surface_aptitude", "fr"), "Aptitude de la surface cible")
        self.assertEqual(scoring_label("surface_aptitude", "en"), "Target-surface aptitude")


if __name__ == "__main__":
    unittest.main()
