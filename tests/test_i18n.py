from __future__ import annotations

import unittest

from uma_legacy_linker.i18n import (
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
            translate_text(
                "Mémoriser la clé sur ce PC — chiffrée par Windows", "en"
            ),
            "Remember the key on this PC — encrypted by Windows",
        )
        self.assertEqual(
            translate_text(
                "La clé mémorisée est chiffrée par Windows pour ce compte utilisateur.",
                "en",
            ),
            "The saved key is encrypted by Windows for this user account.",
        )
        self.assertEqual(
            translate_text(
                "Mémoriser la clé sur ce PC — fichier local non chiffré",
                "en",
            ),
            "Remember the key on this PC — unencrypted local file",
        )
        self.assertEqual(
            translate_text(
                "La clé mémorisée est stockée localement dans un fichier lisible uniquement "
                "par ton compte utilisateur ; elle n’est pas chiffrée.",
                "en",
            ),
            "The saved key is stored locally in a file readable only by your user account; "
            "it is not encrypted.",
        )

    def test_current_transfer_labels_are_translated(self) -> None:
        self.assertEqual(
            translate_text("Couverture / remplaçant", "en"),
            "Coverage / replacement",
        )
        self.assertEqual(translate_text("Rang parent", "en"), "Parent rank")
        self.assertEqual(translate_text("Rang GP", "en"), "GP rank")
        self.assertEqual(translate_text("ID technique", "en"), "Technical ID")

    def test_language_labels_round_trip(self) -> None:
        self.assertEqual(language_from_label(language_label("fr")), "fr")
        self.assertEqual(language_from_label(language_label("en")), "en")

    def test_core_ui_translation(self) -> None:
        self.assertEqual(translate_text("Données locales", "en"), "Local data")
        self.assertEqual(translate_text("Prêt", "en"), "Ready")
        self.assertEqual(translate_text("Prêt", "fr"), "Prêt")

    def test_audited_command_labels_are_translated(self) -> None:
        samples = {
            "Reclasser JSON…": "Re-rank JSON…",
            "Reclasse une réponse JSON uma.moe déjà téléchargée avec les réglages actuels, sans appel à l’API.": "Re-ranks an already downloaded uma.moe JSON response using the current settings, without calling the API.",
            "Exporter le profil…": "Export profile…",
            "Rétablir tout": "Restore all",
            "Rétablir la valeur": "Restore value",
            "Rétablir le bloc": "Restore block",
            "Rétablir le défaut": "Restore default",
            "Ouvrir le fichier": "Open file",
            "Analyser mes vétérans": "Analyse my veterans",
            "Recherche locale et uma.moe": "Local and uma.moe search",
        }
        for source, expected in samples.items():
            with self.subTest(source=source):
                self.assertEqual(translate_text(source, "en"), expected)

    def test_formatted_status_translation(self) -> None:
        self.assertEqual(
            translate_text(
                "Impossible d’invalider le cache de liaison : manifest.json", "en"
            ),
            "Unable to invalidate the link cache: manifest.json",
        )

    def test_transfer_helper_runtime_log_translation(self) -> None:
        source = "Évaluation de 42 vétérans dans 32 contextes de profil/catégorie…"
        self.assertEqual(
            translate_text(source, "en"),
            "Evaluating 42 veterans across 32 profile/category contexts…",
        )
        self.assertEqual(
            translate_text(
                "Plancher de protection Spark : Alice [#1] reste review "
                "face à Replacement [#2] — déficits : Nimble Navigator",
                "en",
            ),
            "Spark-protection floor: Alice [#1] remains review versus "
            "Replacement [#2] — deficits: Nimble Navigator",
        )
        self.assertEqual(
            translate_text(
                "Équivalence dans le modèle détaillée : Alice · 9 602 — Sparks : Turf 3★",
                "en",
            ),
            "Detailed model equivalence: Alice · 9 602 — Sparks: Turf 3★",
        )
        self.assertEqual(
            translate_text("Remplaçant vérifié : Bob [#2]", "en"),
            "Verified replacement: Bob [#2]",
        )

    def test_polish_runtime_strings_are_translated(self) -> None:
        self.assertEqual(
            translate_text(
                "Liaison déjà à jour : réutilisation des artefacts existants.", "en"
            ),
            "Link data already up to date: reusing existing artifacts.",
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
            "Liaison : 25/125": "Linking: 25/125",
            "Comparaison exhaustive : 7 locaux × 7 distants (jusqu’à 49 paires avant exclusions).": (
                "Exhaustive comparison: 7 local × 7 remote "
                "(up to 49 pairs before exclusions)."
            ),
        }
        for source, expected in samples.items():
            with self.subTest(source=source):
                self.assertEqual(translate_text(source, "en"), expected)

    def test_current_transfer_and_cache_messages_are_fully_translated(self) -> None:
        samples = {
            "ID technique": "Technical ID",
            "Reliaison complète demandée : le cache est ignoré.": (
                "Full relink requested: ignoring the cache."
            ),
            "Remplaçant vérifié : Bob [#2]": "Verified replacement: Bob [#2]",
        }
        for source, expected in samples.items():
            with self.subTest(source=source):
                self.assertEqual(translate_text(source, "en"), expected)

    def test_weight_examples_are_human_readable_in_english(self) -> None:
        source = (
            "Chaque poids reste indépendant. La roue montre seulement la part "
            "effective obtenue après normalisation du groupe."
        )
        translated = translate_text(source, "en")
        self.assertEqual(
            translated,
            "Each weight remains independent. The wheel only shows the effective "
            "share after the group is normalised.",
        )
        self.assertNotIn("normalised_group", translated)

    def test_fragment_translation_does_not_retranslate_english_output(self) -> None:
        translated = translate_text(
            "Comparaison exhaustive : 7 locaux × 7 distants "
            "(jusqu’à 49 paires avant exclusions).",
            "en",
        )
        self.assertEqual(
            translated,
            "Exhaustive comparison: 7 local × 7 remote "
            "(up to 49 pairs before exclusions).",
        )
        self.assertNotIn("remotee", translated)

    def test_current_transfer_terminology_is_translated(self) -> None:
        self.assertEqual(translate_text("ID technique", "en"), "Technical ID")
        self.assertEqual(
            translate_text("Couverture / remplaçant", "en"),
            "Coverage / replacement",
        )

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
