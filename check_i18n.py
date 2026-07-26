#!/usr/bin/env python3
"""Vérifie la couverture EN de toutes les chaînes visibles : UI, logs, résultats."""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from i18n import translate_text, SCORING_LABELS_FR, SCORING_LABELS_EN  # noqa: E402

FRENCH_MARKERS = re.compile(
    r"[àâäéèêëîïôöùûüçœÀÂÉÈÊËÎÏÔÖÙÛÜÇŒ]|«|»"
    r"|\b(aucune?|avec|pour|sur|dans|les|des|de|du|aux|une?|et|ou|ne|pas|doit|peut|valoir"
    r"|chaque|tous|toutes|entre|depuis|vers|choisis|fichier|dossier|paires?|lignées?"
    r"|réponse|recherche|résultats?|pondérations?|priorités?|vétérans?|liés?|utilisées?"
    r"|manuelles?|générations?|calculs?|liaisons?|terminées?|étapes?|suivante|contient"
    r"|entier|supérieur|positif|nulle?s?|vide|deux|autre|même|contextuel(le)?|automatique|complémentaire|pondération|personnages?|introuvables?|invalides?|requis|manquants?)\b",
    re.IGNORECASE,
)

# Chaînes identiques FR/EN ou données brutes : pas des oublis.
WHITELIST_EQUAL = {
    "Turf", "Dirt", "Sprint", "Mile", "Medium", "Long", "Front Runner", "Pace Chaser",
    "Late Surger", "End Closer", "uma.moe", "Transfer Helper", "UmaLegacyLinker",
    "Trainer", "Score", "Distance", "Style", "Whites", "Blues", "Uniques", "Pinks",
    "data.json", "master.mdb", "—", "-", "#", "%", "…", "P(S)", "P(A+)", "Surface P(A+)",
}


def looks_french(text: str) -> bool:
    return bool(FRENCH_MARKERS.search(text))


def fstring_template(node: ast.JoinedStr) -> str:
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        else:
            parts.append("7")  # jeton neutre pour les interpolations
    return "".join(parts)


class Collector(ast.NodeVisitor):
    """Collecte (contexte, chaîne, ligne) pour toutes les chaînes visibles."""

    UI_KEYWORDS = {"text", "title"}
    LOG_FUNCS = {
        "_append_log", "_enqueue_log", "_worker_log", "_set_status",
        "_show_error", "_show_warning", "_show_info", "_ask_yes_no", "logger",
        "log",
    }

    def __init__(self, module: str) -> None:
        self.module = module
        self.found: list[tuple[str, str, int]] = []

    def _string_parts(self, node: ast.AST) -> list[str] | None:
        """Flatten string literal / f-string / '+' concatenation nodes.

        Returns the ordered list of literal text chunks (interpolations and
        non-string operands become the neutral token '7'), or None if the
        node isn't a string expression at all. This exists because messages
        built as `"base." + helper()` bypass EXACT whole-string matching in
        i18n.py: only the FRAGMENTS path can translate them, and it's easy
        for a fragment to silently miss one side of the '+'.
        """
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, ast.JoinedStr):
            return [fstring_template(node)]
        if isinstance(node, ast.IfExp):
            # Both branches of a ternary are alternative user-facing texts:
            # concatenate them so an untranslated branch flags the whole node.
            body = self._string_parts(node.body) or ["7"]
            orelse = self._string_parts(node.orelse) or ["7"]
            if body == ["7"] and orelse == ["7"]:
                return None
            return body + [" / "] + orelse
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self._string_parts(node.left)
            right = self._string_parts(node.right)
            if left is None and right is None:
                return None
            return (left or ["7"]) + (right or ["7"])
        return None

    def add(self, context: str, node: ast.AST) -> None:
        if isinstance(node, ast.IfExp):
            # Exact-path contexts (titles, widget texts) translate one branch
            # at a time at runtime: test each branch on its own.
            self.add(context, node.body)
            self.add(context, node.orelse)
            return
        parts = self._string_parts(node)
        if parts is None:
            return
        text = "".join(parts)
        if len(text.strip()) < 2 or not re.search(r"[A-Za-zÀ-ÿ]", text):
            return
        self.found.append((context, text, node.lineno))

    def visit_Call(self, node: ast.Call) -> None:
        func_name = ""
        if isinstance(node.func, ast.Attribute):
            func_name = node.func.attr
        elif isinstance(node.func, ast.Name):
            func_name = node.func.id

        for keyword in node.keywords:
            if keyword.arg in self.UI_KEYWORDS:
                self.add(f"{self.module}:ui", keyword.value)
        if func_name == "title" and node.args:
            self.add(f"{self.module}:title", node.args[0])
        if func_name in self.LOG_FUNCS:
            for arg in node.args:
                self.add(f"{self.module}:{func_name}", arg)
        if func_name == "put" and node.args:
            # queue.put(("progress", (pct, MSG))) / ("status", MSG)
            arg = node.args[0]
            if isinstance(arg, ast.Tuple) and len(arg.elts) == 2:
                payload = arg.elts[1]
                if isinstance(payload, ast.Tuple) and len(payload.elts) == 2:
                    self.add(f"{self.module}:progress", payload.elts[1])
                else:
                    self.add(f"{self.module}:queue", payload)
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        if isinstance(node.exc, ast.Call):
            for arg in node.exc.args:
                self.add(f"{self.module}:raise", arg)
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        # dictionnaires str -> str : en-têtes de colonnes, labels de statut, label_map
        values = [v for v in node.values if isinstance(v, (ast.Constant, ast.JoinedStr))]
        if len(values) == len(node.values) and node.values:
            str_values = [
                v for v in node.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)
            ]
            if len(str_values) >= max(2, len(node.values) - 1):
                for v in str_values:
                    self.add(f"{self.module}:dictlabel", v)
        self.generic_visit(node)

    def visit_List(self, node: ast.List) -> None:
        # lignes de panneaux de détail : listes contenant des f-strings
        for element in node.elts:
            if isinstance(element, ast.JoinedStr) or (
                isinstance(element, ast.Constant)
                and isinstance(element.value, str)
                and looks_french(element.value)
            ):
                self.add(f"{self.module}:detail", element)
        self.generic_visit(node)


def check_module(path: Path, contexts_filter: set[str] | None = None) -> list[tuple[str, str, int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    collector = Collector(path.stem)
    collector.visit(tree)
    problems = []
    seen: set[str] = set()
    for context, text, lineno in collector.found:
        if contexts_filter and not any(context.endswith(c) for c in contexts_filter):
            continue
        if text in seen:
            continue
        seen.add(text)
        if text.strip() in WHITELIST_EQUAL:
            continue
        if context.endswith(":detail"):
            # Les panneaux traduisent le bloc entier : seule la voie FRAGMENTS s'applique.
            wrapped = str(translate_text(f"\u2029{text}\u2029", "en"))
            translated = wrapped.strip("\u2029")
        else:
            translated = str(translate_text(text, "en"))
        if looks_french(translated):
            problems.append((context, text, lineno, translated))
    return problems


def main() -> None:
    total = 0
    # app.py : tout ; moteurs : logger/raise (ce qui remonte à l'utilisateur)
    plans = [
        (ROOT / "app.py", None),
        (ROOT / "legacy_linker.py", {"logger", "log", "raise"}),
        (ROOT / "skill_catalog.py", {"logger", "log", "raise"}),
        (ROOT / "manual_weights.py", {"logger", "log", "raise"}),
        (ROOT / "simulator_weights.py", {"logger", "log", "raise"}),
        (ROOT / "parent_optimizer.py", {"logger", "log", "raise"}),
        (ROOT / "transfer_helper.py", {"logger", "log", "raise"}),
        (ROOT / "uma_moe.py", {"logger", "log", "raise"}),
        (ROOT / "lineage_planner.py", {"logger", "log", "raise"}),
        (ROOT / "scoring_config.py", {"logger", "log", "raise"}),
    ]
    for path, contexts in plans:
        problems = check_module(path, contexts)
        for context, text, lineno, translated in problems:
            total += 1
            print(f"[{context}:{lineno}]")
            print(f"  FR : {text[:150]!r}")
            print(f"  EN : {translated[:150]!r}")
    # Labels de pondération : chaque clé FR doit avoir un EN
    missing = [k for k in SCORING_LABELS_FR if k not in SCORING_LABELS_EN]
    for key in missing:
        total += 1
        print(f"[scoring_label] clé sans EN : {key!r} -> FR {SCORING_LABELS_FR[key]!r}")
    print(f"\n{total} chaîne(s) sans traduction complète")


if __name__ == "__main__":
    main()
