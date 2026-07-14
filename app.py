from __future__ import annotations

import argparse
import copy
import json
import os
import queue
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

from legacy_linker import LinkerError, link_veterans, normalize_json_root
from skill_catalog import generate_skill_catalogs
from simulator_weights import generate_simulator_weights
from manual_weights import generate_manual_skill_weights
from parent_optimizer import OptimizerError, load_ace_options, load_track_options, optimize_parents
from transfer_helper import (
    TransferHelperError,
    analyze_transfer_candidates,
)
from scoring_config import (
    ScoringConfigError,
    build_overrides,
    count_override_leaves,
    deep_merge,
    get_path_value,
    load_effective_scoring_config,
    materialize_effective_scoring_config,
    read_json_object,
    set_path_value,
    validate_scoring_config,
    validate_skill_priorities_config,
    write_json_object,
)
from course_presets import (
    course_preset_conditions,
    course_preset_label,
    load_course_preset_payload,
    ordered_course_presets,
    resolve_course_overrides_path,
)
from i18n import (
    LANGUAGE_LABELS,
    language_from_label,
    language_label,
    normalise_language,
    profile_code,
    profile_label,
    profile_values,
    scoring_label,
    translate_text,
)

from uma_moe import (
    DEFAULT_API_BASE,
    MAX_FETCH_CANDIDATES,
    UmaMoeApiClient,
    UmaMoeError,
    generate_auto_uql,
    rank_online_grandparent_pairs,
)

APP_NAME = "Uma Legacy Linker"
UMAEXTRACTOR_RELEASES = "https://github.com/xancia/UmaExtractor/releases/latest"

UNSPECIFIED = "Non précisé"
ROTATION_OPTIONS = {UNSPECIFIED: None, "Droite": 1, "Gauche": 2}
SEASON_OPTIONS = {UNSPECIFIED: None, "Printemps": [1, 5], "Été": 2, "Automne": 3, "Hiver": 4}
WEATHER_OPTIONS = {UNSPECIFIED: None, "Ensoleillé": 1, "Nuageux": 2, "Pluie": 3, "Neige": 4}
GROUND_OPTIONS = {UNSPECIFIED: None, "Firm": 1, "Good": 2, "Soft": 3, "Heavy": 4}

SCORING_HIDDEN_KEYS = {"schema_version", "description", "formula_notes", "notes"}


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def config_path() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "UmaLegacyLinker" / "config.json"


def load_config() -> dict[str, str]:
    path = config_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_config(data: dict[str, str]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def default_scoring_path() -> Path:
    return app_base_dir() / "default_parent_scoring.json"


def user_scoring_overrides_path() -> Path:
    return config_path().parent / "parent_scoring_overrides.json"


def default_skill_priorities_path() -> Path:
    return app_base_dir() / "default_skill_priorities.json"


def user_skill_priorities_path() -> Path:
    return config_path().parent / "skill_priorities_custom.json"


def candidate_master_paths() -> list[Path]:
    candidates: list[Path] = []
    home = Path.home()
    local_low = home / "AppData" / "LocalLow" / "Cygames"
    for game_dir in ("umamusume", "Umamusume"):
        candidates.append(local_low / game_dir / "master" / "master.mdb")

    env_candidates = [
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("PROGRAMFILES"),
    ]
    steam_roots = [Path(value) / "Steam" for value in env_candidates if value]
    steam_roots.extend(
        [
            Path("C:/Steam"),
            Path("D:/Steam"),
            Path("D:/SteamLibrary"),
            Path("E:/SteamLibrary"),
        ]
    )
    relative_candidates = [
        Path("steamapps/common/UmamusumePrettyDerby/UmamusumePrettyDerby_Data/Persistent/master/master.mdb"),
        Path("steamapps/common/UmamusumePrettyDerby/Umamusume_Data/Persistent/master/master.mdb"),
        Path("steamapps/common/UmamusumePrettyDerby_Global/UmamusumePrettyDerby_Global_Data/Persistent/master/master.mdb"),
    ]
    for root in steam_roots:
        for relative in relative_candidates:
            candidates.append(root / relative)
    return candidates


def auto_detect_master() -> Path | None:
    valid = [path for path in candidate_master_paths() if path.is_file()]
    if not valid:
        return None
    return max(valid, key=lambda path: path.stat().st_mtime)


def auto_detect_extractor() -> Path | None:
    base = app_base_dir()
    candidates = [
        base / "umaextractor.exe",
        base / "UmaExtractor.exe",
        base / "tools" / "umaextractor.exe",
        base / "tools" / "UmaExtractor.exe",
    ]
    valid = [path for path in candidates if path.is_file()]
    return valid[0] if valid else None


def open_path(path: Path) -> None:
    if os.name == "nt":
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class Application:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1240x900")
        self.root.minsize(1000, 700)
        self.queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.running = False
        self.last_output_dir: Path | None = None
        config = load_config()
        self.language_code = normalise_language(config.get("ui_language"))
        self.language_var = tk.StringVar(value=language_label(self.language_code))

        detected_master = auto_detect_master()
        detected_extractor = auto_detect_extractor()
        default_output = app_base_dir() / "output"

        self.master_var = tk.StringVar(
            value=config.get("master_path")
            or (str(detected_master) if detected_master else "")
        )
        self.json_var = tk.StringVar(value=config.get("json_path", ""))
        self.extractor_var = tk.StringVar(
            value=config.get("extractor_path")
            or (str(detected_extractor) if detected_extractor else "")
        )
        self.batch_var = tk.StringVar(value=config.get("umalator_batch_path", ""))
        default_course_overrides = app_base_dir() / "default_course_overrides.json"
        resolved_course_overrides = resolve_course_overrides_path(
            config.get("course_overrides_path"), default_course_overrides
        )
        self.course_overrides_var = tk.StringVar(
            value=str(resolved_course_overrides) if resolved_course_overrides else ""
        )
        self.output_var = tk.StringVar(
            value=config.get("output_dir", str(default_output))
        )
        self._status_source = "Prêt"
        self.status_var = tk.StringVar(value=self._tr(self._status_source))
        self.progress_var = tk.DoubleVar(value=0)
        self.ace_var = tk.StringVar(value="")
        self.future_parent_var = tk.StringVar(value="")
        self.surface_var = tk.StringVar(
            value=profile_label("surface", profile_code("surface", config.get("optimizer_surface", "turf")), self.language_code)
        )
        self.distance_var = tk.StringVar(
            value=profile_label("distance", profile_code("distance", config.get("optimizer_distance", "medium")), self.language_code)
        )
        self.style_var = tk.StringVar(
            value=profile_label("style", profile_code("style", config.get("optimizer_style", "pace_chaser")), self.language_code)
        )
        unspecified = self._tr(UNSPECIFIED)
        self.track_var = tk.StringVar(value=unspecified)
        self.rotation_var = tk.StringVar(value=self._localise_choice(ROTATION_OPTIONS, config.get("optimizer_rotation", UNSPECIFIED)))
        self.season_var = tk.StringVar(value=self._localise_choice(SEASON_OPTIONS, config.get("optimizer_season", UNSPECIFIED)))
        self.weather_var = tk.StringVar(value=self._localise_choice(WEATHER_OPTIONS, config.get("optimizer_weather", UNSPECIFIED)))
        self.ground_var = tk.StringVar(value=self._localise_choice(GROUND_OPTIONS, config.get("optimizer_ground", UNSPECIFIED)))
        self.course_var = tk.StringVar(value=self._tr("Profil générique"))
        self._saved_course_key = str(config.get("optimizer_course_key", "") or "")
        self.top_n_var = tk.IntVar(value=int(config.get("optimizer_top_n", "30")))
        self._saved_ace_card_id = int(config.get("optimizer_ace_card_id", "0") or 0)
        self._saved_future_parent_card_id = int(config.get("optimizer_future_parent_card_id", "0") or 0)
        self._saved_track_id = int(config.get("optimizer_track_id", "0") or 0)
        self._ace_display_to_id: dict[str, int] = {}
        self._ace_id_to_display: dict[int, str] = {}
        self._card_to_chara: dict[int, int] = {}
        self._track_display_to_id: dict[str, int | None] = {self._tr(UNSPECIFIED): None}
        self._track_id_to_display: dict[int, str] = {}
        self._course_display_to_key: dict[str, str | None] = {self._tr("Profil générique"): None}
        self._course_definitions: dict[str, dict[str, object]] = {}
        self._ace_all_values: list[str] = []
        self._track_all_values: list[str] = [self._tr(UNSPECIFIED)]
        self._course_all_values: list[str] = [self._tr("Profil générique")]
        self.uma_moe_base_var = tk.StringVar(value=config.get("uma_moe_base_url", DEFAULT_API_BASE))
        self.uma_moe_query_var = tk.StringVar(value=config.get("uma_moe_query", ""))
        self.uma_moe_response_var = tk.StringVar(value=config.get("uma_moe_response_path", ""))
        self.uma_moe_token_var = tk.StringVar(value=os.environ.get("UMA_MOE_API_KEY", ""))
        self.fixed_gp_var = tk.StringVar(value="")
        self.uma_moe_limit_var = tk.IntVar(
            value=max(100, min(int(config.get("uma_moe_limit", "1000")), MAX_FETCH_CANDIDATES))
        )
        self.uma_moe_parent_g1_budget_var = tk.IntVar(value=int(config.get("uma_moe_parent_g1_budget", "24")))
        self.uma_moe_single_g1_weight_var = tk.DoubleVar(value=float(config.get("uma_moe_single_g1_weight", "0.6")))
        self.uma_moe_auto_uql_var = tk.BooleanVar(value=config.get("uma_moe_auto_uql", "1") not in {"0", "false", "False"})
        self.uma_moe_auto_pairs_var = tk.BooleanVar(value=config.get("uma_moe_auto_pairs", "1") not in {"0", "false", "False"})
        self.uma_moe_local_pool_var = tk.IntVar(value=int(config.get("uma_moe_local_pool", "100")))
        self.uma_moe_remote_pool_var = tk.IntVar(value=int(config.get("uma_moe_remote_pool", "100")))
        self.uql_prefer_whites_var = tk.BooleanVar(value=config.get("uql_prefer_whites", "1") not in {"0", "false", "False"})
        self.uql_lineage_whites_var = tk.BooleanVar(value=config.get("uql_lineage_whites", "1") not in {"0", "false", "False"})
        self.uql_require_dirt_var = tk.BooleanVar(value=config.get("uql_require_dirt", "0") in {"1", "true", "True"})
        self.uql_require_surface_var = tk.BooleanVar(value=config.get("uql_require_surface", "0") in {"1", "true", "True"})
        self.uql_require_distance_var = tk.BooleanVar(value=config.get("uql_require_distance", "0") in {"1", "true", "True"})
        self.uql_require_style_var = tk.BooleanVar(value=config.get("uql_require_style", "0") in {"1", "true", "True"})
        self.uql_pink_min_stars_var = tk.IntVar(value=int(config.get("uql_pink_min_stars", "1")))
        self.use_custom_scoring_var = tk.BooleanVar(
            value=config.get("use_custom_scoring", "0") in {"1", "true", "True"}
        )
        self.scoring_status_var = tk.StringVar(value="")
        self.skill_priorities_var = tk.StringVar(value=config.get("skill_priorities_path", ""))
        self.skill_priorities_status_var = tk.StringVar(value="")
        self._saved_fixed_gp_id = int(config.get("uma_moe_fixed_gp_id", "0") or 0)
        self._saved_ui_tab = int(config.get("ui_tab", "0") or 0)
        self._fixed_gp_display_to_id: dict[str, int] = {}
        self._fixed_gp_all_values: list[str] = []
        self._fixed_gp_records: list[dict[str, object]] = []
        self._log_entries: list[tuple[str, str]] = []
        self._build_ui()
        self._refresh_scoring_status()
        self._refresh_skill_priorities_status()
        # Presets are independent from master.mdb and must be visible even when
        # the game database has not been detected yet.
        self._refresh_course_options()
        self.root.after(150, lambda: self._refresh_optimizer_options(show_errors=False))
        self.root.after(100, self._drain_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _tr(self, text: object) -> object:
        return translate_text(text, self.language_code)

    def _set_status(self, text: object) -> None:
        self._status_source = str(text)
        self.status_var.set(str(self._tr(self._status_source)))

    def _localise_choice(self, options: dict[str, object], stored: str | None) -> str:
        stored = stored or UNSPECIFIED
        if stored in options:
            return str(self._tr(stored))
        for source in options:
            if stored == self._tr(source):
                return str(self._tr(source))
        return str(self._tr(UNSPECIFIED))

    def _choice_source(self, options: dict[str, object], displayed: str) -> str:
        if displayed in options:
            return displayed
        for source in options:
            if displayed == self._tr(source):
                return source
        return UNSPECIFIED

    def _choice_value(self, options: dict[str, object], displayed: str) -> object:
        return options.get(self._choice_source(options, displayed))

    def _apply_translations(self, widget: tk.Misc) -> None:
        if self.language_code == "fr":
            return
        if isinstance(widget, (tk.Tk, tk.Toplevel)):
            try:
                widget.title(str(self._tr(widget.title())))
            except tk.TclError:
                pass
        try:
            text = widget.cget("text")
        except (tk.TclError, AttributeError):
            text = None
        if isinstance(text, str) and text:
            translated = self._tr(text)
            if translated != text:
                try:
                    widget.configure(text=translated)
                except tk.TclError:
                    pass
        if isinstance(widget, ttk.Notebook):
            for tab_id in widget.tabs():
                tab_text = widget.tab(tab_id, "text")
                widget.tab(tab_id, text=self._tr(tab_text))
        if isinstance(widget, ttk.Treeview):
            columns = ["#0", *list(widget.cget("columns"))]
            for column in columns:
                try:
                    heading = widget.heading(column, "text")
                    if heading:
                        widget.heading(column, text=self._tr(heading))
                except tk.TclError:
                    pass
        for child in widget.winfo_children():
            self._apply_translations(child)

    def _show_error(self, message: object, *, parent: tk.Misc | None = None) -> None:
        messagebox.showerror(APP_NAME, self._tr(str(message)), parent=parent)

    def _show_warning(self, message: object, *, parent: tk.Misc | None = None) -> None:
        messagebox.showwarning(APP_NAME, self._tr(str(message)), parent=parent)

    def _show_info(self, message: object, *, parent: tk.Misc | None = None) -> None:
        messagebox.showinfo(APP_NAME, self._tr(str(message)), parent=parent)

    def _ask_yes_no(self, message: object, *, parent: tk.Misc | None = None) -> bool:
        return bool(messagebox.askyesno(APP_NAME, self._tr(str(message)), parent=parent))

    def _on_language_changed(self, _event=None) -> None:
        new_code = language_from_label(self.language_var.get())
        if new_code == self.language_code:
            return
        selected_tab = self.notebook.index("current") if hasattr(self, "notebook") else 0
        condition_sources = {
            "rotation": self._choice_source(ROTATION_OPTIONS, self.rotation_var.get()),
            "season": self._choice_source(SEASON_OPTIONS, self.season_var.get()),
            "weather": self._choice_source(WEATHER_OPTIONS, self.weather_var.get()),
            "ground": self._choice_source(GROUND_OPTIONS, self.ground_var.get()),
        }
        profile_codes = {
            "surface": profile_code("surface", self.surface_var.get()),
            "distance": profile_code("distance", self.distance_var.get()),
            "style": profile_code("style", self.style_var.get()),
        }
        old_unspecified = str(self._tr(UNSPECIFIED))
        old_generic = str(self._tr("Profil générique"))
        track_was_unspecified = self.track_var.get() == old_unspecified
        course_was_generic = self.course_var.get() == old_generic
        self.language_code = new_code
        self.language_var.set(language_label(new_code))
        self._set_status(self._status_source)
        self.rotation_var.set(str(self._tr(condition_sources["rotation"])))
        self.season_var.set(str(self._tr(condition_sources["season"])))
        self.weather_var.set(str(self._tr(condition_sources["weather"])))
        self.ground_var.set(str(self._tr(condition_sources["ground"])))
        self.surface_var.set(profile_label("surface", profile_codes["surface"], new_code))
        self.distance_var.set(profile_label("distance", profile_codes["distance"], new_code))
        self.style_var.set(profile_label("style", profile_codes["style"], new_code))

        new_unspecified = str(self._tr(UNSPECIFIED))
        if track_was_unspecified:
            self.track_var.set(new_unspecified)
        self._track_display_to_id = {
            (new_unspecified if key == old_unspecified else key): value
            for key, value in self._track_display_to_id.items()
        }
        self._track_all_values = [new_unspecified if value == old_unspecified else value for value in self._track_all_values]

        new_generic = str(self._tr("Profil générique"))
        if course_was_generic:
            self.course_var.set(new_generic)
        self._course_display_to_key = {
            (new_generic if key == old_generic else key): value
            for key, value in self._course_display_to_key.items()
        }
        self._course_all_values = [new_generic if value == old_generic else value for value in self._course_all_values]

        if hasattr(self, "root_frame"):
            self.root_frame.destroy()
        self._saved_ui_tab = selected_tab
        self._build_ui()
        self._refresh_scoring_status()
        self._refresh_skill_priorities_status()
        self._refresh_course_options()
        self._render_log_entries()
        self._set_running(self.running)
        self._save_current_config()

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        style.configure("Hint.TLabel", foreground="#666666")
        style.configure("Title.TLabel", font=("Segoe UI", 15, "bold"))
        style.configure("TNotebook.Tab", padding=(14, 5))

        root_frame = ttk.Frame(self.root, padding=(14, 10, 14, 12))
        root_frame.pack(fill=tk.BOTH, expand=True)
        self.root_frame = root_frame

        header = ttk.Frame(root_frame)
        header.pack(fill=tk.X)
        ttk.Label(header, text=APP_NAME, style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Label(
            header,
            text="Sparks, G1 et lignées résolus depuis le master.mdb courant.",
            style="Hint.TLabel",
        ).pack(side=tk.LEFT, padx=(14, 0), pady=(5, 0))
        self.language_combo = ttk.Combobox(
            header,
            textvariable=self.language_var,
            values=tuple(LANGUAGE_LABELS.values()),
            state="readonly",
            width=11,
        )
        self.language_combo.pack(side=tk.RIGHT)
        self.language_combo.bind("<<ComboboxSelected>>", self._on_language_changed)
        ttk.Label(header, text="Langue").pack(side=tk.RIGHT, padx=(0, 6))

        files = ttk.LabelFrame(root_frame, text="Fichiers", padding=10)
        files.pack(fill=tk.X, pady=(8, 10))
        files.columnconfigure(1, weight=1)
        row = self._path_row(
            files, 0, "master.mdb", self.master_var, self._browse_master,
            "Base actuelle du jeu — relue à chaque exécution.",
        )
        row = self._path_row(
            files, row, "data.json", self.json_var, self._browse_json,
            "Vétérans extraits — requis pour la liaison, l'optimisation et uma.moe.",
        )
        self._path_row(
            files, row, "Dossier de sortie", self.output_var, self._browse_output,
            "Reçoit les JSON, CSV et rapports générés.",
        )

        notebook = ttk.Notebook(root_frame)
        notebook.pack(fill=tk.X, pady=(0, 10))
        notebook.enable_traversal()
        self.notebook = notebook

        link_tab = ttk.Frame(notebook, padding=12)
        optimizer_tab = ttk.Frame(notebook, padding=12)
        transfer_tab = ttk.Frame(notebook, padding=12)
        online_tab = ttk.Frame(notebook, padding=12)
        scoring_tab = ttk.Frame(notebook, padding=12)
        legacy_tab = ttk.Frame(notebook, padding=12)
        notebook.add(link_tab, text="Liaison & catalogue")
        notebook.add(optimizer_tab, text="Optimisation de lignée")
        notebook.add(transfer_tab, text="Transfer Helper")
        notebook.add(online_tab, text="uma.moe")
        notebook.add(legacy_tab, text="Outils legacy")
        notebook.add(scoring_tab, text="Pondérations")

        self._build_link_tab(link_tab)
        self._build_optimizer_tab(optimizer_tab)
        self._build_transfer_tab(transfer_tab)
        self._build_uma_moe_tab(online_tab)
        self._build_legacy_tab(legacy_tab)
        self._build_scoring_tab(scoring_tab)

        if 0 <= self._saved_ui_tab < len(notebook.tabs()):
            notebook.select(self._saved_ui_tab)

        statusbar = ttk.Frame(root_frame)
        statusbar.pack(fill=tk.X)
        ttk.Label(statusbar, textvariable=self.status_var).pack(side=tk.LEFT)
        self.open_output_button = ttk.Button(
            statusbar, text="Ouvrir la sortie", command=self._open_output
        )
        self.open_output_button.pack(side=tk.RIGHT)
        ttk.Button(statusbar, text="Effacer le journal", command=self._clear_log).pack(
            side=tk.RIGHT, padx=(0, 8)
        )

        ttk.Progressbar(
            root_frame,
            maximum=100,
            variable=self.progress_var,
            mode="determinate",
        ).pack(fill=tk.X, pady=(6, 8))

        self.log = scrolledtext.ScrolledText(
            root_frame,
            wrap=tk.WORD,
            font=("Consolas", 10),
            height=12,
            state=tk.DISABLED,
        )
        self.log.pack(fill=tk.BOTH, expand=True)
        self._apply_translations(root_frame)

    def _build_link_tab(self, tab: ttk.Frame) -> None:
        tab.columnconfigure(1, weight=1)
        row = self._path_row(
            tab, 0, "UmaExtractor", self.extractor_var, self._browse_extractor,
            "Exécutable externe optionnel, lancé en mode CLI pour produire data.json.",
        )
        actions = ttk.Frame(tab)
        actions.grid(row=row, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.extract_link_button = ttk.Button(
            actions,
            text="Extraire puis lier automatiquement",
            command=self._start_extract_and_link,
        )
        self.extract_link_button.pack(side=tk.LEFT)
        self.link_button = ttk.Button(
            actions,
            text="Lier un data.json existant",
            command=self._start_link_existing,
        )
        self.link_button.pack(side=tk.LEFT, padx=(8, 0))
        self.catalog_button = ttk.Button(
            actions,
            text="Générer catalogue skills",
            command=self._start_catalog_only,
        )
        self.catalog_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            actions,
            text="Télécharger UmaExtractor",
            command=lambda: webbrowser.open(UMAEXTRACTOR_RELEASES),
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(
            tab,
            text=(
                "Produit le JSON enrichi des vétérans, la synthèse CSV, le rapport et les "
                "catalogues skills/conditions. « Générer catalogue skills » ne nécessite pas "
                "de data.json."
            ),
            style="Hint.TLabel",
            wraplength=1080,
        ).grid(row=row + 1, column=0, columnspan=3, sticky="w", pady=(10, 0))

    def _build_optimizer_tab(self, tab: ttk.Frame) -> None:
        tab.columnconfigure(1, weight=1)

        ttk.Label(tab, text="Ace visé", width=20).grid(row=0, column=0, sticky="w")
        self.ace_combo = ttk.Combobox(tab, textvariable=self.ace_var, state="normal")
        self.ace_combo.grid(row=0, column=1, columnspan=4, sticky="ew", padx=(0, 8))
        ttk.Button(
            tab,
            text="Actualiser depuis le MDB",
            command=self._refresh_optimizer_options,
        ).grid(row=0, column=5, sticky="ew")

        ttk.Label(tab, text="Parent à produire", width=20).grid(row=1, column=0, sticky="w", pady=(7, 0))
        self.future_parent_combo = ttk.Combobox(tab, textvariable=self.future_parent_var, state="normal")
        self.future_parent_combo.grid(row=1, column=1, columnspan=4, sticky="ew", padx=(0, 8), pady=(7, 0))
        ttk.Label(
            tab,
            text="Pour le triple Ace × parent × futur GP.",
            style="Hint.TLabel",
        ).grid(row=1, column=5, sticky="w", pady=(7, 0))

        ttk.Label(tab, text="Surface", width=20).grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.surface_combo = ttk.Combobox(
            tab,
            textvariable=self.surface_var,
            values=profile_values("surface", self.language_code),
            state="readonly",
            width=14,
        )
        self.surface_combo.grid(row=2, column=1, sticky="w", pady=(8, 0))
        ttk.Label(tab, text="Distance").grid(row=2, column=2, sticky="e", padx=(12, 5), pady=(8, 0))
        self.distance_combo = ttk.Combobox(
            tab,
            textvariable=self.distance_var,
            values=profile_values("distance", self.language_code),
            state="readonly",
            width=14,
        )
        self.distance_combo.grid(row=2, column=3, sticky="w", pady=(8, 0))
        ttk.Label(tab, text="Style").grid(row=2, column=4, sticky="e", padx=(12, 5), pady=(8, 0))
        self.style_combo = ttk.Combobox(
            tab,
            textvariable=self.style_var,
            values=profile_values("style", self.language_code),
            state="readonly",
            width=18,
        )
        self.style_combo.grid(row=2, column=5, sticky="w", pady=(8, 0))

        conditions = ttk.LabelFrame(tab, text="Conditions de course / green skills", padding=8)
        conditions.grid(row=3, column=0, columnspan=6, sticky="ew", pady=(10, 0))
        conditions.columnconfigure(1, weight=1)
        ttk.Label(conditions, text="Hippodrome").grid(row=0, column=0, sticky="w")
        self.track_combo = ttk.Combobox(conditions, textvariable=self.track_var, state="normal", width=28)
        self.track_combo.grid(row=0, column=1, sticky="ew", padx=(5, 12))
        ttk.Label(conditions, text="Rotation").grid(row=0, column=2, sticky="e")
        ttk.Combobox(conditions, textvariable=self.rotation_var, values=tuple(str(self._tr(value)) for value in ROTATION_OPTIONS), state="readonly", width=14).grid(row=0, column=3, sticky="w", padx=(5, 12))
        ttk.Label(conditions, text="Saison").grid(row=0, column=4, sticky="e")
        ttk.Combobox(conditions, textvariable=self.season_var, values=tuple(str(self._tr(value)) for value in SEASON_OPTIONS), state="readonly", width=14).grid(row=0, column=5, sticky="w", padx=(5, 0))
        ttk.Label(conditions, text="État du terrain").grid(row=1, column=0, sticky="w", pady=(7, 0))
        ttk.Combobox(conditions, textvariable=self.ground_var, values=tuple(str(self._tr(value)) for value in GROUND_OPTIONS), state="readonly", width=18).grid(row=1, column=1, sticky="w", padx=(5, 12), pady=(7, 0))
        ttk.Label(conditions, text="Météo").grid(row=1, column=2, sticky="e", pady=(7, 0))
        ttk.Combobox(conditions, textvariable=self.weather_var, values=tuple(str(self._tr(value)) for value in WEATHER_OPTIONS), state="readonly", width=14).grid(row=1, column=3, sticky="w", padx=(5, 12), pady=(7, 0))
        ttk.Label(
            conditions,
            text="Incompatible → green skill à 0 ; correspondante → activée.",
            style="Hint.TLabel",
            wraplength=420,
        ).grid(row=1, column=4, columnspan=2, sticky="w", pady=(7, 0))

        ttk.Label(tab, text="Preset de course", width=20).grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.course_combo = ttk.Combobox(tab, textvariable=self.course_var, state="normal")
        self.course_combo.grid(row=4, column=1, columnspan=3, sticky="ew", pady=(8, 0), padx=(0, 8))
        ttk.Label(tab, text="Top").grid(row=4, column=4, sticky="e", padx=(12, 5), pady=(8, 0))
        ttk.Spinbox(
            tab,
            from_=5,
            to=200,
            increment=5,
            textvariable=self.top_n_var,
            width=7,
        ).grid(row=4, column=5, sticky="w", pady=(8, 0))

        row = self._path_row(
            tab, 5, "Overrides de course", self.course_overrides_var, self._browse_course_overrides,
            "Facultatif — CM16 à CM46, profils Team Trials et archive CM9 à CM15.",
            entry_span=3,
        )

        self.optimize_button = ttk.Button(
            tab,
            text="Calculer les meilleurs parents / grands-parents",
            command=self._start_optimizer,
        )
        self.optimize_button.grid(row=row, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(
            tab,
            text=(
                "Parents finaux : affinité calculée avec l'Ace. Futurs grands-parents : "
                "contribution exacte du triple Ace × parent à produire × candidat."
            ),
            style="Hint.TLabel",
            wraplength=720,
        ).grid(row=row, column=3, columnspan=3, sticky="w", padx=(12, 0), pady=(8, 0))

        for combo in (self.surface_combo, self.distance_combo):
            combo.bind("<<ComboboxSelected>>", self._on_profile_changed)
        self.course_combo.bind("<<ComboboxSelected>>", self._on_course_selected)

        self._enable_searchable_combo(self.ace_combo, lambda: self._ace_all_values)
        self._enable_searchable_combo(self.future_parent_combo, lambda: self._ace_all_values)
        self._enable_searchable_combo(self.track_combo, lambda: self._track_all_values)
        self._enable_searchable_combo(self.course_combo, lambda: self._course_all_values)

    def _build_transfer_tab(self, tab: ttk.Frame) -> None:
        tab.columnconfigure(0, weight=1)

        intro = ttk.LabelFrame(tab, text="Nettoyage conservateur des vétérans", padding=10)
        intro.grid(row=0, column=0, sticky="ew")
        intro.columnconfigure(0, weight=1)
        ttk.Label(
            intro,
            text=(
                "Analyse chaque vétéran local sur les cinq prochaines Champion Meetings et les cinq "
                "catégories Team Trials, pour les quatre styles, séparément comme parent et comme futur "
                "grand-parent."
            ),
            wraplength=1050,
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            intro,
            text=(
                "Un transfert n'est marqué comme sûr que si un autre exemplaire de la même carte et de la "
                "même unique n'est moins bon dans aucune niche globalement viable, y compris pour le support "
                "G1 en paire."
            ),
            style="Hint.TLabel",
            wraplength=1050,
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))

        verdicts = ttk.LabelFrame(tab, text="Verdicts", padding=10)
        verdicts.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        verdicts.columnconfigure(1, weight=1)
        ttk.Label(verdicts, text="Transfert sûr", width=20).grid(row=0, column=0, sticky="w")
        ttk.Label(
            verdicts,
            text="Remplaçant strict de la même carte détecté dans toutes les niches parent et/ou grand-parent réellement viables.",
        ).grid(row=0, column=1, sticky="w")
        ttk.Label(verdicts, text="À examiner", width=20).grid(row=1, column=0, sticky="w", pady=(5, 0))
        ttk.Label(
            verdicts,
            text="Aucun rôle compétitif détecté, mais pas de remplacement strict : vérification manuelle requise.",
        ).grid(row=1, column=1, sticky="w", pady=(5, 0))
        ttk.Label(verdicts, text="Conserver", width=20).grid(row=2, column=0, sticky="w", pady=(5, 0))
        ttk.Label(
            verdicts,
            text="Au moins une niche parent ou grand-parent reste compétitive, ou l'exemplaire est irremplaçable.",
        ).grid(row=2, column=1, sticky="w", pady=(5, 0))

        settings = ttk.LabelFrame(tab, text="Paramètres", padding=10)
        settings.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        settings.columnconfigure(0, weight=1)
        ttk.Label(
            settings,
            text=(
                "Les seuils de compétitivité et le périmètre (nombre de CM, Team Trials et profils génériques) "
                "se règlent dans Pondérations → transfer_helper."
            ),
            style="Hint.TLabel",
            wraplength=1050,
        ).grid(row=0, column=0, sticky="w")

        actions = ttk.Frame(tab)
        actions.grid(row=3, column=0, sticky="w", pady=(12, 0))
        self.transfer_helper_button = ttk.Button(
            actions,
            text="Analyser les vétérans locaux",
            command=self._start_transfer_helper,
        )
        self.transfer_helper_button.pack(side=tk.LEFT)
        ttk.Label(
            actions,
            text="Aucune suppression automatique : seuls un JSON, un CSV et un résumé sont générés.",
            style="Hint.TLabel",
        ).pack(side=tk.LEFT, padx=(12, 0))

    def _build_uma_moe_tab(self, tab: ttk.Frame) -> None:
        tab.columnconfigure(0, weight=1)

        mode = ttk.LabelFrame(tab, text="Sélection des grands-parents", padding=8)
        mode.grid(row=0, column=0, sticky="ew")
        mode.columnconfigure(1, weight=1)

        pair_mode_frame = ttk.Frame(mode)
        pair_mode_frame.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Checkbutton(
            pair_mode_frame,
            text="Tester automatiquement toutes les paires local × distant",
            variable=self.uma_moe_auto_pairs_var,
            command=self._toggle_uma_moe_pair_mode,
        ).pack(side=tk.LEFT)
        ttk.Label(pair_mode_frame, text="Locaux").pack(side=tk.LEFT, padx=(18, 5))
        ttk.Spinbox(pair_mode_frame, from_=10, to=250, increment=10, textvariable=self.uma_moe_local_pool_var, width=6).pack(side=tk.LEFT)
        ttk.Label(pair_mode_frame, text="Distants").pack(side=tk.LEFT, padx=(12, 5))
        ttk.Spinbox(pair_mode_frame, from_=10, to=500, increment=10, textvariable=self.uma_moe_remote_pool_var, width=6).pack(side=tk.LEFT)
        ttk.Label(pair_mode_frame, text="Fetch API").pack(side=tk.LEFT, padx=(12, 5))
        ttk.Spinbox(
            pair_mode_frame,
            from_=100,
            to=MAX_FETCH_CANDIDATES,
            increment=100,
            textvariable=self.uma_moe_limit_var,
            width=7,
        ).pack(side=tk.LEFT)

        ttk.Label(mode, text="GP local fixé (manuel)", width=20).grid(row=1, column=0, sticky="w", pady=(7, 0))
        fixed_gp_frame = ttk.Frame(mode)
        fixed_gp_frame.grid(row=1, column=1, sticky="ew", pady=(7, 0))
        fixed_gp_frame.columnconfigure(0, weight=1)
        self.fixed_gp_combo = ttk.Combobox(fixed_gp_frame, textvariable=self.fixed_gp_var, state="readonly")
        self.fixed_gp_combo.grid(row=0, column=0, sticky="ew")
        self.fixed_gp_button = ttk.Button(fixed_gp_frame, text="Choisir…", command=self._open_fixed_gp_picker)
        self.fixed_gp_button.grid(row=0, column=1, padx=(7, 0))
        ttk.Label(fixed_gp_frame, text="Ignoré en mode automatique.", style="Hint.TLabel").grid(row=0, column=2, padx=(8, 0))

        g1_frame = ttk.Frame(mode)
        g1_frame.grid(row=2, column=0, columnspan=2, sticky="w", pady=(7, 0))
        ttk.Label(g1_frame, text="G1 prévues sur le parent").pack(side=tk.LEFT)
        ttk.Spinbox(g1_frame, from_=0, to=40, increment=1, textvariable=self.uma_moe_parent_g1_budget_var, width=6).pack(side=tk.LEFT, padx=(7, 0))
        ttk.Label(g1_frame, text="Valeur d'une G1 non commune").pack(side=tk.LEFT, padx=(24, 0))
        ttk.Spinbox(g1_frame, from_=0.0, to=1.0, increment=0.1, textvariable=self.uma_moe_single_g1_weight_var, width=6).pack(side=tk.LEFT, padx=(7, 0))
        ttk.Label(g1_frame, text="0,6 = 60 % de la valeur d'une G1 commune", style="Hint.TLabel").pack(side=tk.LEFT, padx=(7, 0))

        uql = ttk.LabelFrame(tab, text="Requête UQL", padding=8)
        uql.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        uql.columnconfigure(1, weight=1)
        ttk.Label(uql, text="UQL / recherche", width=20).grid(row=0, column=0, sticky="w")
        ttk.Entry(uql, textvariable=self.uma_moe_query_var).grid(row=0, column=1, sticky="ew")
        ttk.Checkbutton(uql, text="Auto", variable=self.uma_moe_auto_uql_var).grid(row=0, column=2, padx=(8, 0))

        uql_options = ttk.Frame(uql)
        uql_options.grid(row=1, column=0, columnspan=3, sticky="w", pady=(7, 0))
        ttk.Checkbutton(uql_options, text="Favoriser les whites du profil", variable=self.uql_prefer_whites_var).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(uql_options, text="Favoriser leur répétition dans la lignée", variable=self.uql_lineage_whites_var).grid(row=0, column=1, sticky="w", padx=(14, 0))
        ttk.Label(uql_options, text="Minimum pink").grid(row=0, column=2, sticky="e", padx=(14, 5))
        ttk.Spinbox(uql_options, from_=1, to=3, increment=1, textvariable=self.uql_pink_min_stars_var, width=5).grid(row=0, column=3, sticky="w")
        ttk.Checkbutton(uql_options, text="Exiger Dirt sur le GP distant", variable=self.uql_require_dirt_var).grid(row=1, column=0, sticky="w", pady=(5, 0))
        ttk.Checkbutton(uql_options, text="Exiger surface cible", variable=self.uql_require_surface_var).grid(row=1, column=1, sticky="w", padx=(14, 0), pady=(5, 0))
        ttk.Checkbutton(uql_options, text="Exiger distance cible", variable=self.uql_require_distance_var).grid(row=1, column=2, columnspan=2, sticky="w", padx=(14, 0), pady=(5, 0))
        ttk.Checkbutton(uql_options, text="Exiger style cible", variable=self.uql_require_style_var).grid(row=1, column=4, sticky="w", padx=(14, 0), pady=(5, 0))
        ttk.Label(
            uql,
            text=(
                "Contraintes strictes : envoyées à uma.moe puis revérifiées localement sur les factors résolus. "
                "Les contraintes pink s'appliquent au Main de uma.moe, donc au GP distant. Sans case cochée, blue et pink restent ouvertes."
            ),
            style="Hint.TLabel",
            wraplength=1080,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

        api = ttk.LabelFrame(tab, text="API et import", padding=8)
        api.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        api.columnconfigure(1, weight=1)
        api.columnconfigure(3, weight=1)
        ttk.Label(api, text="Base API", width=20).grid(row=0, column=0, sticky="w")
        ttk.Entry(api, textvariable=self.uma_moe_base_var).grid(row=0, column=1, sticky="ew", padx=(0, 12))
        ttk.Label(api, text="Clé API").grid(row=0, column=2, sticky="e", padx=(0, 5))
        ttk.Entry(api, textvariable=self.uma_moe_token_var, show="•").grid(row=0, column=3, sticky="ew")
        ttk.Label(
            api,
            text="Clé non enregistrée ; peut aussi venir de UMA_MOE_API_KEY.",
            style="Hint.TLabel",
        ).grid(row=1, column=3, sticky="w", pady=(2, 0))
        ttk.Label(api, text="Réponse JSON", width=20).grid(row=2, column=0, sticky="w", pady=(7, 0))
        ttk.Entry(api, textvariable=self.uma_moe_response_var).grid(row=2, column=1, sticky="ew", padx=(0, 6), pady=(7, 0))
        ttk.Button(api, text="Parcourir…", command=self._browse_uma_moe_response).grid(row=2, column=2, sticky="w", pady=(7, 0))
        ttk.Label(
            api,
            text="Fallback : classe une réponse exportée depuis la doc interactive.",
            style="Hint.TLabel",
        ).grid(row=2, column=3, sticky="w", padx=(8, 0), pady=(7, 0))

        online_actions = ttk.Frame(tab)
        online_actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.uma_moe_live_button = ttk.Button(
            online_actions,
            text="Chercher et tester les paires",
            command=lambda: self._start_uma_moe_search(use_import=False),
        )
        self.uma_moe_live_button.pack(side=tk.LEFT)
        self.uma_moe_import_button = ttk.Button(
            online_actions,
            text="Classer le JSON importé",
            command=lambda: self._start_uma_moe_search(use_import=True),
        )
        self.uma_moe_import_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(
            online_actions,
            text="Ace, parent à produire, profil et conditions proviennent de l'onglet Optimisation.",
            style="Hint.TLabel",
        ).pack(side=tk.LEFT, padx=(14, 0))
        ttk.Label(
            tab,
            text=(
                "Mode automatique : préclasse les meilleurs GP locaux et distants, puis évalue chaque paire local × distant. "
                "Avec 100 × 100, environ 10 000 paires ; le CSV conserve le classement complet."
            ),
            style="Hint.TLabel",
            wraplength=1080,
        ).grid(row=4, column=0, sticky="w", pady=(7, 0))

    def _build_scoring_tab(self, tab: ttk.Frame) -> None:
        tab.columnconfigure(0, weight=1)

        active = ttk.LabelFrame(tab, text="Profil actif", padding=10)
        active.grid(row=0, column=0, sticky="ew")
        active.columnconfigure(0, weight=1)
        ttk.Checkbutton(
            active,
            text="Utiliser mes pondérations personnalisées",
            variable=self.use_custom_scoring_var,
            command=self._on_custom_scoring_toggle,
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            active,
            textvariable=self.scoring_status_var,
            style="Hint.TLabel",
            wraplength=1040,
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))

        actions = ttk.Frame(tab)
        actions.grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Button(actions, text="Configurer les pondérations…", command=self._open_scoring_editor).pack(side=tk.LEFT)
        ttk.Button(actions, text="Importer un profil…", command=self._import_scoring_profile).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(actions, text="Exporter le profil effectif…", command=self._export_scoring_profile).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(actions, text="Réinitialiser", command=self._reset_scoring_overrides).pack(side=tk.LEFT, padx=(8, 0))

        help_box = ttk.LabelFrame(tab, text="Ce qui peut être modifié", padding=10)
        help_box.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(
            help_box,
            text=(
                "L’éditeur expose les poids globaux des scores, la préférence des blues par stat et par distance, "
                "la valeur des pinks par catégorie (distance / surface / style), les paliers d’étoiles, les saturations, "
                "les courbes d’affinité, les green skills, la génération de whites et les poids spécifiques à uma.moe."
            ),
            wraplength=1080,
        ).pack(anchor="w")
        ttk.Label(
            help_box,
            text=(
                "Les valeurs par défaut restent dans default_parent_scoring.json. Le profil utilisateur ne stocke que les différences ; "
                "il continue donc de récupérer automatiquement les nouveaux paramètres ajoutés lors d’une mise à jour. "
                "Les poids d’une même formule sont normalisés : ils n’ont pas besoin de totaliser 1 ou 100."
            ),
            style="Hint.TLabel",
            wraplength=1080,
        ).pack(anchor="w", pady=(6, 0))

        examples = ttk.LabelFrame(tab, text="Repères", padding=10)
        examples.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(
            examples,
            text=(
                "Exemples : augmenter blue_stat_weights_by_distance.long.Stamina favorise les lignées Stamina en Long ; "
                "augmenter pink_dimension_weights.distance donne plus de valeur aux Sparks de distance ; "
                "modifier uma_moe_pair.weights.white_skill change directement la priorité des whites déjà présentes dans les deux GP."
            ),
            style="Hint.TLabel",
            wraplength=1080,
        ).pack(anchor="w")

        white_priorities = ttk.LabelFrame(tab, text="Priorités individuelles des white skills", padding=10)
        white_priorities.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        white_priorities.columnconfigure(0, weight=1)
        ttk.Label(
            white_priorities,
            textvariable=self.skill_priorities_status_var,
            style="Hint.TLabel",
            wraplength=1040,
        ).grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Button(
            white_priorities,
            text="Choisir un JSON…",
            command=self._browse_skill_priorities,
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Button(
            white_priorities,
            text="Créer une copie modifiable",
            command=self._create_skill_priorities_copy,
        ).grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(8, 0))
        ttk.Button(
            white_priorities,
            text="Ouvrir le fichier",
            command=self._open_skill_priorities_file,
        ).grid(row=1, column=2, sticky="w", padx=(8, 0), pady=(8, 0))
        ttk.Button(
            white_priorities,
            text="Revenir au défaut",
            command=self._reset_skill_priorities,
        ).grid(row=1, column=3, sticky="w", padx=(8, 0), pady=(8, 0))
        ttk.Label(
            white_priorities,
            text=(
                "Ce fichier règle la valeur de chaque white skill par surface, distance et style. "
                "Un profil partiel est accepté : il est fusionné avec default_skill_priorities.json avant chaque calcul."
            ),
            style="Hint.TLabel",
            wraplength=1040,
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))

    def _build_legacy_tab(self, tab: ttk.Frame) -> None:
        tab.columnconfigure(1, weight=1)
        ttk.Label(
            tab,
            text=(
                "Depuis la V9, le classement utilise les priorités manuelles intégrées "
                "(default_skill_priorities.json), pas Umalator. L'import ci-dessous est conservé "
                "comme outil de diagnostic."
            ),
            style="Hint.TLabel",
            wraplength=1080,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        row = self._path_row(
            tab, 1, "Batch Umalator", self.batch_var, self._browse_batch,
            "Fichier umalator_skill_chart_batch_v2_*.json produit par le Skill Chart batch v2.",
        )
        self.simulator_button = ttk.Button(
            tab,
            text="Importer poids Umalator",
            command=self._start_simulator_weights,
        )
        self.simulator_button.grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def _refresh_scoring_status(self) -> None:
        default_path = default_scoring_path()
        override_path = user_scoring_overrides_path()
        try:
            if self.use_custom_scoring_var.get():
                _default, overrides, _effective = load_effective_scoring_config(default_path, override_path)
                override_count = count_override_leaves(overrides)
                message = (
                    f"Profil personnalisé actif — {override_count} valeur(s) remplacée(s). "
                    f"Surcharges : {override_path}"
                )
            else:
                load_effective_scoring_config(default_path, None)
                override_count = 0
                invalid_suffix = ""
                if override_path.is_file():
                    try:
                        override_count = count_override_leaves(read_json_object(override_path))
                    except ScoringConfigError:
                        invalid_suffix = " (surcharges enregistrées invalides, ignorées)"
                suffix = (
                    f" ({override_count} modification(s) enregistrée(s), actuellement désactivées)"
                    if override_count
                    else invalid_suffix
                )
                message = f"Profil par défaut actif : {default_path.name}{suffix}"
        except ScoringConfigError as exc:
            message = f"Profil de pondération invalide : {exc}"
        self.scoring_status_var.set(str(self._tr(message)))

    def _refresh_skill_priorities_status(self) -> None:
        custom_text = self.skill_priorities_var.get().strip()
        if not custom_text:
            message = f"Profil par défaut actif : {default_skill_priorities_path().name}"
        else:
            custom_path = Path(custom_text).expanduser()
            if custom_path.is_file():
                message = f"Profil personnalisé actif : {custom_path}"
            else:
                message = f"Profil personnalisé introuvable : {custom_path}"
        self.skill_priorities_status_var.set(str(self._tr(message)))

    def _on_custom_scoring_toggle(self) -> None:
        if self.use_custom_scoring_var.get():
            try:
                load_effective_scoring_config(default_scoring_path(), user_scoring_overrides_path())
            except ScoringConfigError as exc:
                self.use_custom_scoring_var.set(False)
                self._show_error(exc)
        self._refresh_scoring_status()
        self._save_current_config()

    def _active_scoring_config_path(self, output: Path) -> Path:
        default_path = default_scoring_path()
        if not default_path.is_file():
            raise ScoringConfigError(f"Configuration de pondération par défaut introuvable : {default_path}")
        destination = output / "active_parent_scoring.json"
        override_path = user_scoring_overrides_path() if self.use_custom_scoring_var.get() else None
        return materialize_effective_scoring_config(
            default_path,
            override_path,
            destination,
        )

    def _active_skill_priorities_path(self, output: Path) -> Path:
        default_path = default_skill_priorities_path()
        default_payload = read_json_object(default_path)
        validate_skill_priorities_config(default_payload)
        custom_text = self.skill_priorities_var.get().strip()
        effective = default_payload
        if custom_text:
            custom_path = Path(custom_text).expanduser().resolve()
            if not custom_path.is_file():
                raise ScoringConfigError(f"Profil de priorités white introuvable : {custom_path}")
            custom_payload = read_json_object(custom_path)
            effective = deep_merge(default_payload, custom_payload)
            validate_skill_priorities_config(effective)
        return write_json_object(output / "active_skill_priorities.json", effective)

    def _browse_skill_priorities(self) -> None:
        filename = filedialog.askopenfilename(
            title=str(self._tr("Choisir un profil de priorités white")),
            filetypes=(("JSON", "*.json"), (str(self._tr("Tous les fichiers")), "*.*")),
        )
        if not filename:
            return
        try:
            default_payload = read_json_object(default_skill_priorities_path())
            custom_payload = read_json_object(filename)
            validate_skill_priorities_config(deep_merge(default_payload, custom_payload))
        except ScoringConfigError as exc:
            self._show_error(exc)
            return
        self.skill_priorities_var.set(filename)
        self._save_current_config()
        self._refresh_skill_priorities_status()

    def _create_skill_priorities_copy(self) -> None:
        source = default_skill_priorities_path()
        destination = user_skill_priorities_path()
        if destination.is_file() and not self._ask_yes_no(
            f"Écraser la copie personnalisée existante ?\n{destination}"
        ):
            self.skill_priorities_var.set(str(destination))
            self._save_current_config()
            self._refresh_skill_priorities_status()
            return
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        except OSError as exc:
            self._show_error(f"Impossible de créer la copie : {exc}")
            return
        self.skill_priorities_var.set(str(destination))
        self._save_current_config()
        self._refresh_skill_priorities_status()
        open_path(destination)

    def _open_skill_priorities_file(self) -> None:
        custom_text = self.skill_priorities_var.get().strip()
        path = Path(custom_text).expanduser() if custom_text else default_skill_priorities_path()
        if not path.is_file():
            self._show_error(f"Fichier introuvable : {path}")
            return
        open_path(path)

    def _reset_skill_priorities(self) -> None:
        self.skill_priorities_var.set("")
        self._save_current_config()
        self._refresh_skill_priorities_status()

    @staticmethod
    def _format_scoring_value(value: object) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, float):
            return f"{value:.6g}"
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))
        return str(value)

    @staticmethod
    def _parse_scoring_value(raw: str, reference: object) -> object:
        text = raw.strip()
        if isinstance(reference, str):
            if text.startswith('"'):
                parsed = json.loads(text)
                if not isinstance(parsed, str):
                    raise ValueError("Une chaîne de caractères est attendue.")
                return parsed
            return raw
        parsed = json.loads(text)
        if isinstance(reference, bool):
            if not isinstance(parsed, bool):
                raise ValueError("Utilise true ou false.")
            return parsed
        if isinstance(reference, int) and not isinstance(reference, bool):
            if isinstance(parsed, bool) or not isinstance(parsed, (int, float)) or float(parsed) % 1:
                raise ValueError("Un entier est attendu.")
            return int(parsed)
        if isinstance(reference, float):
            if isinstance(parsed, bool) or not isinstance(parsed, (int, float)):
                raise ValueError("Un nombre est attendu.")
            return float(parsed)
        if isinstance(reference, list) and not isinstance(parsed, list):
            raise ValueError("Une liste JSON est attendue.")
        if isinstance(reference, dict) and not isinstance(parsed, dict):
            raise ValueError("Un objet JSON est attendu.")
        return parsed

    def _open_scoring_editor(self) -> None:
        try:
            default, _overrides, effective = load_effective_scoring_config(
                default_scoring_path(), user_scoring_overrides_path()
            )
        except ScoringConfigError as exc:
            # A malformed saved override must not lock the user out of the editor:
            # reopen on the valid defaults so it can be repaired or replaced.
            try:
                default, _overrides, effective = load_effective_scoring_config(
                    default_scoring_path(), None
                )
            except ScoringConfigError:
                self._show_error(exc)
                return
            self._show_warning(
                f"Les surcharges enregistrées sont invalides et ont été ignorées pour cet éditeur.\n\n{exc}"
            )

        current = copy.deepcopy(effective)
        window = tk.Toplevel(self.root)
        window.title(str(self._tr("Pondérations personnalisées")))
        window.geometry("1320x780")
        window.minsize(1000, 620)
        window.transient(self.root)

        intro = ttk.Frame(window, padding=(12, 10, 12, 6))
        intro.pack(fill=tk.X)
        ttk.Label(
            intro,
            text="Double-clique une valeur pour la modifier. Les lignes en gras diffèrent du profil par défaut.",
        ).pack(anchor="w")
        ttk.Label(
            intro,
            text=(
                "Les nombres peuvent dépasser 1. Les poids d’une formule sont renormalisés entre eux. "
                "Les listes de paliers s’éditent au format JSON, par exemple [[0, 0], [50, 40], [100, 100]]."
            ),
            style="Hint.TLabel",
            wraplength=1240,
        ).pack(anchor="w", pady=(3, 0))

        tree_frame = ttk.Frame(window, padding=(12, 4, 12, 6))
        tree_frame.pack(fill=tk.BOTH, expand=True)
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        columns = ("path", "current", "default")
        tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings", selectmode="browse")
        tree.heading("#0", text="Paramètre")
        tree.heading("path", text="Chemin JSON")
        tree.heading("current", text="Valeur active")
        tree.heading("default", text="Valeur par défaut")
        tree.column("#0", width=330, minwidth=220, stretch=True)
        tree.column("path", width=390, minwidth=250, stretch=True)
        tree.column("current", width=245, minwidth=120, stretch=True)
        tree.column("default", width=245, minwidth=120, stretch=True)
        yscroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
        xscroll = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        tree.tag_configure("changed", font=("Segoe UI", 9, "bold"))
        path_by_iid: dict[str, tuple[str, ...]] = {}

        def populate() -> None:
            tree.delete(*tree.get_children())
            path_by_iid.clear()

            def add_nodes(parent_iid: str, mapping: dict[str, object], prefix: tuple[str, ...]) -> None:
                for key, value in mapping.items():
                    if key in SCORING_HIDDEN_KEYS or key.endswith("description"):
                        continue
                    path = prefix + (str(key),)
                    path_text = ".".join(path)
                    label = scoring_label(str(key), self.language_code)
                    try:
                        default_value = get_path_value(default, path)
                    except KeyError:
                        default_value = None
                    changed = value != default_value
                    if isinstance(value, dict):
                        iid = tree.insert(
                            parent_iid,
                            tk.END,
                            text=label,
                            values=(path_text, "", ""),
                            open=len(path) <= 1,
                            tags=(("changed",) if changed else ()),
                        )
                        path_by_iid[iid] = path
                        add_nodes(iid, value, path)
                    else:
                        iid = tree.insert(
                            parent_iid,
                            tk.END,
                            text=label,
                            values=(
                                path_text,
                                self._format_scoring_value(value),
                                self._format_scoring_value(default_value),
                            ),
                            tags=(("changed",) if changed else ()),
                        )
                        path_by_iid[iid] = path

            add_nodes("", current, ())

        def selected_path() -> tuple[str, ...] | None:
            selection = tree.selection()
            return path_by_iid.get(selection[0]) if selection else None

        def edit_selected(_event=None) -> None:
            path = selected_path()
            if not path:
                return
            value = get_path_value(current, path)
            if isinstance(value, dict):
                tree.item(tree.selection()[0], open=not bool(tree.item(tree.selection()[0], "open")))
                return
            raw = simpledialog.askstring(
                str(self._tr("Modifier la pondération")),
                str(self._tr(f"{'.'.join(path)}\n\nNouvelle valeur :")),
                initialvalue=self._format_scoring_value(value),
                parent=window,
            )
            if raw is None:
                return
            previous = copy.deepcopy(value)
            try:
                parsed = self._parse_scoring_value(raw, value)
                set_path_value(current, path, parsed)
                validate_scoring_config(current)
            except (ValueError, json.JSONDecodeError, ScoringConfigError) as exc:
                set_path_value(current, path, previous)
                self._show_error(f"Valeur refusée : {exc}", parent=window)
                return
            populate()

        def reset_selected() -> None:
            path = selected_path()
            if not path:
                return
            try:
                default_value = get_path_value(default, path)
            except KeyError:
                self._show_info("Ce paramètre n’existe pas dans le profil par défaut.", parent=window)
                return
            set_path_value(current, path, default_value)
            populate()

        def reset_all() -> None:
            if not self._ask_yes_no(
                "Rétablir toutes les valeurs par défaut dans l’éditeur ?",
                parent=window,
            ):
                return
            current.clear()
            current.update(copy.deepcopy(default))
            populate()

        def import_into_editor() -> None:
            filename = filedialog.askopenfilename(
                parent=window,
                title=str(self._tr("Importer un profil de pondération")),
                filetypes=(("JSON", "*.json"), (str(self._tr("Tous les fichiers")), "*.*")),
            )
            if not filename:
                return
            try:
                imported = read_json_object(filename)
                imported_effective = deep_merge(default, imported)
                validate_scoring_config(imported_effective)
            except ScoringConfigError as exc:
                self._show_error(exc, parent=window)
                return
            current.clear()
            current.update(imported_effective)
            populate()

        def export_from_editor() -> None:
            filename = filedialog.asksaveasfilename(
                parent=window,
                title=str(self._tr("Exporter le profil de pondération")),
                defaultextension=".json",
                initialfile="parent_scoring_profile.json",
                filetypes=(("JSON", "*.json"),),
            )
            if filename:
                write_json_object(filename, current)

        def save_editor() -> None:
            try:
                validate_scoring_config(current)
                overrides = build_overrides(default, current)
                path = user_scoring_overrides_path()
                if overrides:
                    write_json_object(path, overrides)
                elif path.is_file():
                    path.unlink()
                self.use_custom_scoring_var.set(True)
                self._save_current_config()
                self._refresh_scoring_status()
            except (OSError, ScoringConfigError) as exc:
                self._show_error(exc, parent=window)
                return
            window.destroy()

        tree.bind("<Double-1>", edit_selected)
        buttons = ttk.Frame(window, padding=(12, 4, 12, 12))
        buttons.pack(fill=tk.X)
        ttk.Button(buttons, text="Modifier", command=edit_selected).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Rétablir la sélection", command=reset_selected).pack(side=tk.LEFT, padx=(7, 0))
        ttk.Button(buttons, text="Tout remettre par défaut", command=reset_all).pack(side=tk.LEFT, padx=(7, 0))
        ttk.Button(buttons, text="Importer…", command=import_into_editor).pack(side=tk.LEFT, padx=(18, 0))
        ttk.Button(buttons, text="Exporter…", command=export_from_editor).pack(side=tk.LEFT, padx=(7, 0))
        ttk.Button(buttons, text="Annuler", command=window.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Enregistrer et activer", command=save_editor).pack(side=tk.RIGHT, padx=(0, 7))
        populate()
        self._apply_translations(window)

    def _import_scoring_profile(self) -> None:
        filename = filedialog.askopenfilename(
            title=str(self._tr("Importer un profil de pondération")),
            filetypes=(("JSON", "*.json"), (str(self._tr("Tous les fichiers")), "*.*")),
        )
        if not filename:
            return
        try:
            default = read_json_object(default_scoring_path())
            imported = read_json_object(filename)
            effective = deep_merge(default, imported)
            validate_scoring_config(effective)
            overrides = build_overrides(default, effective)
            path = user_scoring_overrides_path()
            if overrides:
                write_json_object(path, overrides)
            elif path.is_file():
                path.unlink()
            self.use_custom_scoring_var.set(True)
            self._save_current_config()
            self._refresh_scoring_status()
        except (OSError, ScoringConfigError) as exc:
            self._show_error(exc)

    def _export_scoring_profile(self) -> None:
        filename = filedialog.asksaveasfilename(
            title=str(self._tr("Exporter le profil effectif")),
            defaultextension=".json",
            initialfile="parent_scoring_profile.json",
            filetypes=(("JSON", "*.json"),),
        )
        if not filename:
            return
        try:
            override = user_scoring_overrides_path() if self.use_custom_scoring_var.get() else None
            _default, _overrides, effective = load_effective_scoring_config(default_scoring_path(), override)
            write_json_object(filename, effective)
        except (OSError, ScoringConfigError) as exc:
            self._show_error(exc)

    def _reset_scoring_overrides(self) -> None:
        path = user_scoring_overrides_path()
        if not path.is_file() and not self.use_custom_scoring_var.get():
            return
        if not self._ask_yes_no(
            "Supprimer toutes les pondérations personnalisées et réactiver le profil par défaut ?"
        ):
            return
        try:
            if path.is_file():
                path.unlink()
        except OSError as exc:
            self._show_error(f"Impossible de supprimer {path} : {exc}")
            return
        self.use_custom_scoring_var.set(False)
        self._save_current_config()
        self._refresh_scoring_status()

    def _path_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        browse_command: object,
        hint: str,
        entry_span: int = 1,
    ) -> int:
        ttk.Label(parent, text=label, width=20).grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=(3, 0)
        )
        ttk.Entry(parent, textvariable=variable).grid(
            row=row, column=1, columnspan=entry_span, sticky="ew", pady=(3, 0)
        )
        ttk.Button(parent, text="Parcourir…", command=browse_command).grid(
            row=row, column=1 + entry_span, padx=(8, 0), pady=(3, 0)
        )
        ttk.Label(parent, text=hint, style="Hint.TLabel").grid(
            row=row + 1, column=1, columnspan=entry_span + 1, sticky="w", pady=(0, 4)
        )
        return row + 2

    def _enable_searchable_combo(self, combo: ttk.Combobox, values_getter) -> None:
        def refresh(_event=None):
            all_values = list(values_getter() or [])
            current = combo.get().strip().lower()
            if not current:
                combo.configure(values=all_values)
                return
            filtered = [value for value in all_values if current in value.lower()]
            combo.configure(values=(filtered or all_values))

        combo.bind("<KeyRelease>", refresh)
        combo.bind("<FocusIn>", refresh)
        combo.bind("<Button-1>", lambda _event: combo.configure(values=list(values_getter() or [])))

    def _format_rank_score(self, value: object) -> str:
        try:
            integer = int(value)
        except (TypeError, ValueError):
            return ""
        return f"{integer:,}".replace(",", " ")

    def _format_stats(self, stats: dict[str, object] | None) -> str:
        if not isinstance(stats, dict):
            return ""
        keys = ("speed", "stamina", "power", "guts", "wiz")
        labels = ("Spd", "Sta", "Pow", "Gut", "Wit")
        parts = []
        for label, key in zip(labels, keys):
            value = stats.get(key)
            if value is None:
                continue
            try:
                parts.append(f"{label} {int(value)}")
            except (TypeError, ValueError):
                continue
        return " / ".join(parts)

    def _toggle_uma_moe_pair_mode(self) -> None:
        automatic = bool(self.uma_moe_auto_pairs_var.get())
        state = tk.DISABLED if automatic else tk.NORMAL
        if hasattr(self, "fixed_gp_combo"):
            self.fixed_gp_combo.configure(state="disabled" if automatic else "readonly")
        if hasattr(self, "fixed_gp_button"):
            self.fixed_gp_button.configure(state=state)

    def _refresh_local_veteran_options(self, show_errors: bool = False) -> None:
        try:
            data_path = Path(self.json_var.get().strip()).expanduser()
            if not data_path.is_file() or not self._ace_id_to_display:
                return
            payload = json.loads(data_path.read_text(encoding="utf-8-sig"))
            veterans = normalize_json_root(payload)
            records: list[dict[str, object]] = []
            selected_display: str | None = None
            for veteran in veterans:
                try:
                    trained_id = int(veteran.get("trained_chara_id"))
                    card_id = int(veteran.get("card_id"))
                except (TypeError, ValueError):
                    continue
                full_display = self._ace_id_to_display.get(card_id, f"Card {card_id}")
                if " — " in full_display:
                    card_name, uma_part = full_display.split(" — ", 1)
                    uma_name = uma_part.rsplit(" (", 1)[0]
                else:
                    card_name = full_display
                    uma_name = full_display
                try:
                    rank_score = int(veteran.get("rank_score") or 0)
                except (TypeError, ValueError):
                    rank_score = 0
                score_text = self._format_rank_score(rank_score) or "?"
                display = f"{uma_name} — {card_name} — {score_text} — #{trained_id}"
                record = {
                    "trained_chara_id": trained_id,
                    "card_id": card_id,
                    "uma_name": uma_name,
                    "card_name": card_name,
                    "rank_score": rank_score,
                    "display": display,
                }
                records.append(record)
                if trained_id == self._saved_fixed_gp_id:
                    selected_display = display
            records.sort(key=lambda record: (-int(record.get("rank_score") or 0), str(record.get("uma_name") or "").lower(), int(record.get("trained_chara_id") or 0)))
            values = [str(record["display"]) for record in records]
            mapping = {str(record["display"]): int(record["trained_chara_id"]) for record in records}
            self._fixed_gp_records = records
            self._fixed_gp_display_to_id = mapping
            self._fixed_gp_all_values = values
            self.fixed_gp_combo.configure(values=values)
            if selected_display is None and values:
                selected_display = values[0]
            if selected_display:
                self.fixed_gp_var.set(selected_display)
        except Exception as exc:
            if show_errors:
                self._show_error(f"Impossible de charger les vétérans locaux : {exc}")

    def _open_fixed_gp_picker(self) -> None:
        self._refresh_local_veteran_options(show_errors=True)
        if not self._fixed_gp_records:
            self._show_info("Aucun vétéran local disponible dans le data.json sélectionné.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Choisir le GP1 local")
        dialog.geometry("980x620")
        dialog.minsize(760, 460)
        dialog.transient(self.root)
        dialog.grab_set()

        outer = ttk.Frame(dialog, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        ttk.Label(
            outer,
            text="Choisis l'exemplaire local qui sera associé aux candidats uma.moe.",
            font=("Segoe UI", 11, "bold"),
        ).grid(row=0, column=0, sticky="w")
        search_var = tk.StringVar()
        search = ttk.Entry(outer, textvariable=search_var)
        search.grid(row=1, column=0, sticky="ew", pady=(8, 8))

        table_frame = ttk.Frame(outer)
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        columns = ("uma", "card", "score", "id")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        tree.heading("uma", text="Uma")
        tree.heading("card", text="Costume / card")
        tree.heading("score", text="Score Uma")
        tree.heading("id", text="ID entraînement")
        tree.column("uma", width=180, anchor="w")
        tree.column("card", width=420, anchor="w")
        tree.column("score", width=120, anchor="center")
        tree.column("id", width=120, anchor="center")
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        iid_to_record: dict[str, dict[str, object]] = {}

        def refill(*_args) -> None:
            query = search_var.get().strip().lower()
            current_id = self._fixed_gp_display_to_id.get(self.fixed_gp_var.get())
            tree.delete(*tree.get_children())
            iid_to_record.clear()
            selected_iid: str | None = None
            for index, record in enumerate(self._fixed_gp_records):
                haystack = " ".join(
                    str(record.get(key) or "")
                    for key in ("uma_name", "card_name", "rank_score", "trained_chara_id")
                ).lower()
                if query and query not in haystack:
                    continue
                iid = str(index)
                iid_to_record[iid] = record
                tree.insert(
                    "",
                    tk.END,
                    iid=iid,
                    values=(
                        record.get("uma_name"),
                        record.get("card_name"),
                        self._format_rank_score(record.get("rank_score")),
                        record.get("trained_chara_id"),
                    ),
                )
                if int(record.get("trained_chara_id") or 0) == int(current_id or 0):
                    selected_iid = iid
            if selected_iid:
                tree.selection_set(selected_iid)
                tree.see(selected_iid)
            elif tree.get_children():
                tree.selection_set(tree.get_children()[0])

        def choose(*_args) -> None:
            selection = tree.selection()
            if not selection:
                return
            record = iid_to_record.get(selection[0])
            if record is None:
                return
            display = str(record.get("display") or "")
            self.fixed_gp_var.set(display)
            self._saved_fixed_gp_id = int(record.get("trained_chara_id") or 0)
            dialog.destroy()

        search_var.trace_add("write", refill)
        tree.bind("<Double-1>", choose)
        buttons = ttk.Frame(outer)
        buttons.grid(row=3, column=0, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Annuler", command=dialog.destroy).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Utiliser ce GP", command=choose).pack(side=tk.LEFT, padx=(8, 0))
        refill()
        self._apply_translations(dialog)
        search.focus_set()

    def _browse_uma_moe_response(self) -> None:
        path = filedialog.askopenfilename(
            title=str(self._tr("Sélectionner une réponse JSON de l’API uma.moe")),
            filetypes=[("JSON", "*.json"), (str(self._tr("Tous les fichiers")), "*")],
        )
        if path:
            self.uma_moe_response_var.set(path)

    def _browse_master(self) -> None:
        path = filedialog.askopenfilename(
            title=str(self._tr("Sélectionner master.mdb")),
            filetypes=[("Uma master database", "*.mdb"), ("Tous les fichiers", "*")],
        )
        if path:
            self.master_var.set(path)
            self._refresh_optimizer_options(show_errors=False)

    def _browse_json(self) -> None:
        path = filedialog.askopenfilename(
            title=str(self._tr("Sélectionner data.json")),
            filetypes=[("JSON", "*.json"), (str(self._tr("Tous les fichiers")), "*")],
        )
        if path:
            self.json_var.set(path)
            self._refresh_local_veteran_options(show_errors=False)

    def _browse_batch(self) -> None:
        path = filedialog.askopenfilename(
            title=str(self._tr("Sélectionner le batch Umalator v2")),
            filetypes=[("JSON Umalator", "*.json"), ("Tous les fichiers", "*")],
        )
        if path:
            self.batch_var.set(path)

    def _browse_course_overrides(self) -> None:
        path = filedialog.askopenfilename(
            title=str(self._tr("Sélectionner les overrides de course")),
            filetypes=[("JSON", "*.json"), (str(self._tr("Tous les fichiers")), "*")],
        )
        if path:
            self.course_overrides_var.set(path)
            self._refresh_course_options()

    def _browse_extractor(self) -> None:
        path = filedialog.askopenfilename(
            title=str(self._tr("Sélectionner UmaExtractor")),
            filetypes=[
                ("UmaExtractor", "*.exe *.py"),
                (str(self._tr("Exécutable Windows")), "*.exe"),
                ("Script Python", "*.py"),
                ("Tous les fichiers", "*"),
            ],
        )
        if path:
            self.extractor_var.set(path)

    def _browse_output(self) -> None:
        path = filedialog.askdirectory(title=str(self._tr("Sélectionner le dossier de sortie")))
        if path:
            self.output_var.set(path)

    def _set_running(self, running: bool) -> None:
        self.running = running
        state = tk.DISABLED if running else tk.NORMAL
        self.extract_link_button.configure(state=state)
        self.link_button.configure(state=state)
        self.catalog_button.configure(state=state)
        self.simulator_button.configure(state=state)
        self.optimize_button.configure(state=state)
        self.transfer_helper_button.configure(state=state)
        self.uma_moe_live_button.configure(state=state)
        self.uma_moe_import_button.configure(state=state)
        if not running:
            self._toggle_uma_moe_pair_mode()

    def _render_log_entries(self) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        for timestamp, message in self._log_entries:
            self.log.insert(tk.END, f"[{timestamp}] {self._tr(message)}\n")
        self.log.configure(state=tk.DISABLED)
        self.log.see(tk.END)

    def _clear_log(self) -> None:
        self._log_entries.clear()
        self._render_log_entries()

    def _append_log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self._log_entries.append((timestamp, message))
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, f"[{timestamp}] {self._tr(message)}\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _enqueue_log(self, message: str) -> None:
        self.queue.put(("log", message))

    def _save_current_config(self) -> None:
        save_config(
            {
                "master_path": self.master_var.get().strip(),
                "json_path": self.json_var.get().strip(),
                "extractor_path": self.extractor_var.get().strip(),
                "umalator_batch_path": self.batch_var.get().strip(),
                "course_overrides_path": self.course_overrides_var.get().strip(),
                "output_dir": self.output_var.get().strip(),
                "optimizer_ace_card_id": str(self._ace_display_to_id.get(self.ace_var.get(), self._saved_ace_card_id or 0)),
                "optimizer_future_parent_card_id": str(self._ace_display_to_id.get(self.future_parent_var.get(), self._saved_future_parent_card_id or 0)),
                "optimizer_track_id": str(self._track_display_to_id.get(self.track_var.get()) or 0),
                "optimizer_rotation": self._choice_source(ROTATION_OPTIONS, self.rotation_var.get()),
                "optimizer_season": self._choice_source(SEASON_OPTIONS, self.season_var.get()),
                "optimizer_weather": self._choice_source(WEATHER_OPTIONS, self.weather_var.get()),
                "optimizer_ground": self._choice_source(GROUND_OPTIONS, self.ground_var.get()),
                "optimizer_surface": profile_code("surface", self.surface_var.get()),
                "optimizer_distance": profile_code("distance", self.distance_var.get()),
                "optimizer_style": profile_code("style", self.style_var.get()),
                "optimizer_course_key": str(self._course_display_to_key.get(self.course_var.get()) or ""),
                "optimizer_top_n": str(self.top_n_var.get()),
                "uma_moe_base_url": self.uma_moe_base_var.get().strip(),
                "uma_moe_query": self.uma_moe_query_var.get(),
                "uma_moe_response_path": self.uma_moe_response_var.get().strip(),
                "uma_moe_limit": str(self.uma_moe_limit_var.get()),
                "uma_moe_parent_g1_budget": str(self.uma_moe_parent_g1_budget_var.get()),
                "uma_moe_single_g1_weight": str(self.uma_moe_single_g1_weight_var.get()),
                "uma_moe_auto_uql": "1" if self.uma_moe_auto_uql_var.get() else "0",
                "uma_moe_auto_pairs": "1" if self.uma_moe_auto_pairs_var.get() else "0",
                "uma_moe_local_pool": str(self.uma_moe_local_pool_var.get()),
                "uma_moe_remote_pool": str(self.uma_moe_remote_pool_var.get()),
                "uql_prefer_whites": "1" if self.uql_prefer_whites_var.get() else "0",
                "uql_lineage_whites": "1" if self.uql_lineage_whites_var.get() else "0",
                "uql_require_dirt": "1" if self.uql_require_dirt_var.get() else "0",
                "uql_require_surface": "1" if self.uql_require_surface_var.get() else "0",
                "uql_require_distance": "1" if self.uql_require_distance_var.get() else "0",
                "uql_require_style": "1" if self.uql_require_style_var.get() else "0",
                "uql_pink_min_stars": str(self.uql_pink_min_stars_var.get()),
                "use_custom_scoring": "1" if self.use_custom_scoring_var.get() else "0",
                "skill_priorities_path": self.skill_priorities_var.get().strip(),
                "uma_moe_fixed_gp_id": str(self._fixed_gp_display_to_id.get(self.fixed_gp_var.get(), self._saved_fixed_gp_id or 0)),
                "ui_tab": str(self.notebook.index("current")) if hasattr(self, "notebook") else "0",
                "ui_language": self.language_code,
            }
        )

    def _refresh_optimizer_options(self, show_errors: bool = True) -> None:
        try:
            master = Path(self.master_var.get().strip()).expanduser()
            if not master.is_file():
                if show_errors:
                    raise OptimizerError("Sélectionne un master.mdb valide avant d'actualiser les Ace.")
                return
            options = load_ace_options(master)
            self._ace_display_to_id = {option.display_name: option.card_id for option in options}
            self._ace_id_to_display = {option.card_id: option.display_name for option in options}
            self._card_to_chara = {option.card_id: option.chara_id for option in options}
            values = [option.display_name for option in options]
            self._ace_all_values = values
            self.ace_combo.configure(values=values)
            self.future_parent_combo.configure(values=values)
            selected = self._ace_id_to_display.get(self._saved_ace_card_id)
            if selected is None and values:
                selected = values[0]
            if selected:
                self.ace_var.set(selected)
            future_selected = self._ace_id_to_display.get(self._saved_future_parent_card_id)
            selected_card_id = self._ace_display_to_id.get(selected or "")
            selected_chara_id = self._card_to_chara.get(selected_card_id or 0)
            if (
                future_selected is None
                or self._card_to_chara.get(self._ace_display_to_id.get(future_selected, 0)) == selected_chara_id
            ):
                future_selected = next(
                    (
                        option.display_name
                        for option in options
                        if option.chara_id != selected_chara_id
                    ),
                    values[0] if values else None,
                )
            if future_selected:
                self.future_parent_var.set(future_selected)

            tracks = load_track_options(master)
            unspecified = str(self._tr(UNSPECIFIED))
            self._track_display_to_id = {unspecified: None}
            self._track_id_to_display = {}
            for option in tracks:
                self._track_display_to_id[option.display_name] = option.track_id
                self._track_id_to_display[option.track_id] = option.display_name
            self._track_all_values = list(self._track_display_to_id)
            self.track_combo.configure(values=self._track_all_values)
            self.track_var.set(self._track_id_to_display.get(self._saved_track_id, unspecified))
            self._refresh_course_options()
            self._refresh_local_veteran_options(show_errors=False)
        except Exception as exc:
            if show_errors:
                self._show_error(exc)

    def _refresh_course_options(self) -> None:
        current_key = self._course_display_to_key.get(self.course_var.get()) or self._saved_course_key or None
        generic_profile = str(self._tr("Profil générique"))
        self._course_display_to_key = {generic_profile: None}
        self._course_definitions = {}

        bundled = app_base_dir() / "default_course_overrides.json"
        resolved_path = resolve_course_overrides_path(self.course_overrides_var.get().strip(), bundled)
        if resolved_path is not None and self.course_overrides_var.get().strip() != str(resolved_path):
            # Heal stale absolute paths saved by earlier versions.
            self.course_overrides_var.set(str(resolved_path))
        payload = load_course_preset_payload(resolved_path)
        for key, course in ordered_course_presets(payload):
            self._course_definitions[key] = course
            display = course_preset_label(key, course, self.language_code)
            if display in self._course_display_to_key:
                display = f"{display} [{key}]"
            self._course_display_to_key[display] = key

        values = list(self._course_display_to_key)
        self._course_all_values = values
        if hasattr(self, "course_combo"):
            self.course_combo.configure(values=values)
        matching_display = next(
            (display for display, key in self._course_display_to_key.items() if key == current_key),
            None,
        )
        self.course_var.set(matching_display or generic_profile)
        self._saved_course_key = str(current_key or "") if matching_display else ""

    def _on_profile_changed(self, _event=None) -> None:
        # A manual surface/distance change invalidates an exact preset. Keeping
        # it selected would create a profile mismatch at calculation time.
        self._saved_course_key = ""
        self.course_var.set(str(self._tr("Profil générique")))
        self._refresh_course_options()

    def _set_choice_from_canonical_value(
        self, options: dict[str, object], variable: tk.StringVar, value: object | None
    ) -> None:
        source = UNSPECIFIED
        if value is not None:
            for candidate, canonical in options.items():
                if canonical == value:
                    source = candidate
                    break
                if isinstance(canonical, list) and isinstance(value, list):
                    if {int(item) for item in canonical} == {int(item) for item in value}:
                        source = candidate
                        break
        variable.set(str(self._tr(source)))

    def _on_course_selected(self, _event=None) -> None:
        course_key = self._course_display_to_key.get(self.course_var.get())
        self._saved_course_key = str(course_key or "")
        if not course_key:
            return
        course = self._course_definitions.get(course_key) or {}
        profile = course.get("profile") or {}
        surface = str(profile.get("surface") or "")
        distance = str(profile.get("distance") or "")
        if surface:
            self.surface_var.set(profile_label("surface", surface, self.language_code))
        if distance:
            self.distance_var.set(profile_label("distance", distance, self.language_code))

        conditions = course_preset_conditions(course)
        self._set_choice_from_canonical_value(ROTATION_OPTIONS, self.rotation_var, conditions.get("rotation"))
        self._set_choice_from_canonical_value(SEASON_OPTIONS, self.season_var, conditions.get("season"))
        self._set_choice_from_canonical_value(WEATHER_OPTIONS, self.weather_var, conditions.get("weather"))
        self._set_choice_from_canonical_value(GROUND_OPTIONS, self.ground_var, conditions.get("ground_condition"))

        racecourse = str(((course.get("race") or {}).get("racecourse")) or "").strip().lower()
        unspecified = str(self._tr(UNSPECIFIED))
        selected_track = unspecified
        if racecourse and racecourse not in {"variable", "unknown racetrack"}:
            for display in self._track_display_to_id:
                normalized = display.strip().lower()
                if normalized == racecourse or normalized.startswith(racecourse) or racecourse.startswith(normalized):
                    selected_track = display
                    break
        self.track_var.set(selected_track)

    def _selected_course_conditions(self) -> dict[str, object]:
        conditions: dict[str, object] = {}
        course_key = self._course_display_to_key.get(self.course_var.get())
        if course_key:
            course = self._course_definitions.get(course_key) or {}
            conditions.update(course_preset_conditions(course))

        # Explicit controls override preset defaults, allowing quick what-if
        # adjustments without editing the JSON file.
        track_id = self._track_display_to_id.get(self.track_var.get())
        if track_id is not None:
            conditions["track_id"] = int(track_id)
        for key, value in (
            ("rotation", self._choice_value(ROTATION_OPTIONS, self.rotation_var.get())),
            ("season", self._choice_value(SEASON_OPTIONS, self.season_var.get())),
            ("weather", self._choice_value(WEATHER_OPTIONS, self.weather_var.get())),
            ("ground_condition", self._choice_value(GROUND_OPTIONS, self.ground_var.get())),
        ):
            if value is not None:
                conditions[key] = value
        return conditions

    def _start_optimizer(self) -> None:
        if self.running:
            return
        try:
            master, output = self._validate_common()
            data_json = Path(self.json_var.get().strip()).expanduser()
            if not data_json.is_file():
                raise OptimizerError("Sélectionne un data.json valide.")
            ace_display = self.ace_var.get()
            ace_card_id = self._ace_display_to_id.get(ace_display)
            if ace_card_id is None:
                raise OptimizerError("Sélectionne une Ace après avoir actualisé la liste depuis le MDB.")
            future_parent_card_id = self._ace_display_to_id.get(self.future_parent_var.get())
            if future_parent_card_id is None:
                raise OptimizerError("Sélectionne le parent à produire pour classer les futurs grands-parents.")
            if self._card_to_chara.get(future_parent_card_id) == self._card_to_chara.get(ace_card_id):
                raise OptimizerError("L'Ace et le parent à produire doivent être deux personnages différents.")
            course_conditions = self._selected_course_conditions()
            course_overrides_text = self.course_overrides_var.get().strip()
            course_overrides = Path(course_overrides_text).expanduser() if course_overrides_text else None
            if course_overrides is not None and not course_overrides.is_file():
                raise OptimizerError("Le fichier d'overrides de course est invalide.")
            top_n = int(self.top_n_var.get())
            scoring_config = self._active_scoring_config_path(output)
            skill_priorities = self._active_skill_priorities_path(output)
        except (LinkerError, OptimizerError, ScoringConfigError, ValueError) as exc:
            self._show_error(exc)
            return
        self._saved_ace_card_id = int(ace_card_id)
        self._saved_future_parent_card_id = int(future_parent_card_id)
        self._saved_track_id = int(self._track_display_to_id.get(self.track_var.get()) or 0)
        self._save_current_config()
        self._clear_log()
        self._set_running(True)
        self._set_status("Préparation de l'optimisation de lignée…")
        self.progress_var.set(5)
        threading.Thread(
            target=self._worker_optimizer,
            args=(
                master,
                data_json,
                output,
                course_overrides,
                scoring_config,
                skill_priorities,
                int(ace_card_id),
                int(future_parent_card_id),
                profile_code("surface", self.surface_var.get()),
                profile_code("distance", self.distance_var.get()),
                profile_code("style", self.style_var.get()),
                self._course_display_to_key.get(self.course_var.get()),
                course_conditions,
                top_n,
            ),
            daemon=True,
        ).start()

    def _start_transfer_helper(self) -> None:
        if self.running:
            return
        try:
            master, output = self._validate_common()
            data_json = Path(self.json_var.get().strip()).expanduser()
            if not data_json.is_file():
                raise TransferHelperError("Sélectionne un data.json valide.")
            course_overrides_text = self.course_overrides_var.get().strip()
            course_overrides = (
                Path(course_overrides_text).expanduser()
                if course_overrides_text
                else None
            )
            if course_overrides is not None and not course_overrides.is_file():
                raise TransferHelperError("Le fichier d'overrides de course est invalide.")
            scoring_config = self._active_scoring_config_path(output)
            skill_priorities = self._active_skill_priorities_path(output)
        except (LinkerError, TransferHelperError, ScoringConfigError, ValueError) as exc:
            self._show_error(exc)
            return
        self._save_current_config()
        self._clear_log()
        self._set_running(True)
        self._set_status("Préparation du Transfer Helper…")
        self.progress_var.set(5)
        threading.Thread(
            target=self._worker_transfer_helper,
            args=(
                master,
                data_json,
                output,
                course_overrides,
                scoring_config,
                skill_priorities,
            ),
            daemon=True,
        ).start()

    def _start_uma_moe_search(self, *, use_import: bool) -> None:
        if self.running:
            return
        try:
            master, output = self._validate_common()
            data_json = Path(self.json_var.get().strip()).expanduser()
            if not data_json.is_file():
                raise UmaMoeError("Sélectionne un data.json valide pour les grands-parents locaux.")
            ace_card_id = self._ace_display_to_id.get(self.ace_var.get())
            target_parent_card_id = self._ace_display_to_id.get(self.future_parent_var.get())
            if ace_card_id is None or target_parent_card_id is None:
                raise UmaMoeError("Sélectionne l’Ace et le parent à produire.")
            if self._card_to_chara.get(ace_card_id) == self._card_to_chara.get(target_parent_card_id):
                raise UmaMoeError("L’Ace et le parent à produire doivent être différents.")

            automatic_pairs = bool(self.uma_moe_auto_pairs_var.get())
            fixed_gp_id: int | None = None
            if not automatic_pairs:
                fixed_gp_id = self._fixed_gp_display_to_id.get(self.fixed_gp_var.get())
                if fixed_gp_id is None:
                    self._refresh_local_veteran_options(show_errors=False)
                    fixed_gp_id = self._fixed_gp_display_to_id.get(self.fixed_gp_var.get())
                if fixed_gp_id is None:
                    raise UmaMoeError("Sélectionne un GP local ou active le test automatique des paires.")

            response_path = Path(self.uma_moe_response_var.get().strip()).expanduser() if self.uma_moe_response_var.get().strip() else None
            if use_import and (response_path is None or not response_path.is_file()):
                raise UmaMoeError("Sélectionne une réponse JSON uma.moe à importer.")
            api_base = self.uma_moe_base_var.get().strip() or DEFAULT_API_BASE
            limit = max(100, min(int(self.uma_moe_limit_var.get()), MAX_FETCH_CANDIDATES))
            local_pool_size = max(1, min(int(self.uma_moe_local_pool_var.get()), 250))
            remote_pool_size = max(1, min(int(self.uma_moe_remote_pool_var.get()), 500))
            planned_g1_budget = max(0, min(int(self.uma_moe_parent_g1_budget_var.get()), 40))
            single_g1_weight = max(0.0, min(float(self.uma_moe_single_g1_weight_var.get()), 1.0))
            uql_options = {
                "prefer_profile_whites": bool(self.uql_prefer_whites_var.get()),
                "prefer_lineage_whites": bool(self.uql_lineage_whites_var.get()),
                "require_main_dirt": bool(self.uql_require_dirt_var.get()),
                "require_main_surface": bool(self.uql_require_surface_var.get()),
                "require_main_distance": bool(self.uql_require_distance_var.get()),
                "require_main_style": bool(self.uql_require_style_var.get()),
                "pink_min_stars": max(1, min(int(self.uql_pink_min_stars_var.get()), 3)),
            }
            course_conditions = self._selected_course_conditions()
            course_overrides_text = self.course_overrides_var.get().strip()
            course_overrides = Path(course_overrides_text).expanduser() if course_overrides_text else None
            if course_overrides is not None and not course_overrides.is_file():
                raise UmaMoeError("Le fichier d’overrides de course est invalide.")
            scoring_config = self._active_scoring_config_path(output)
            skill_priorities = self._active_skill_priorities_path(output)
        except (LinkerError, UmaMoeError, ScoringConfigError, ValueError) as exc:
            self._show_error(exc)
            return

        self._saved_ace_card_id = int(ace_card_id)
        self._saved_future_parent_card_id = int(target_parent_card_id)
        if fixed_gp_id is not None:
            self._saved_fixed_gp_id = int(fixed_gp_id)
        self._save_current_config()
        self._clear_log()
        self._set_running(True)
        self._set_status("Préparation de la recherche uma.moe…")
        self.progress_var.set(5)
        threading.Thread(
            target=self._worker_uma_moe,
            args=(
                master,
                data_json,
                output,
                course_overrides,
                scoring_config,
                skill_priorities,
                int(ace_card_id),
                int(target_parent_card_id),
                fixed_gp_id,
                automatic_pairs,
                local_pool_size,
                remote_pool_size,
                profile_code("surface", self.surface_var.get()),
                profile_code("distance", self.distance_var.get()),
                profile_code("style", self.style_var.get()),
                self._course_display_to_key.get(self.course_var.get()),
                course_conditions,
                int(self.top_n_var.get()),
                use_import,
                response_path,
                api_base,
                self.uma_moe_query_var.get().strip(),
                bool(self.uma_moe_auto_uql_var.get()),
                uql_options,
                limit,
                planned_g1_budget,
                single_g1_weight,
                self.uma_moe_token_var.get().strip(),
            ),
            daemon=True,
        ).start()

    def _validate_common(self) -> tuple[Path, Path]:
        master = Path(self.master_var.get().strip()).expanduser()
        output = Path(self.output_var.get().strip()).expanduser()
        if not master.is_file():
            raise LinkerError("Sélectionne un master.mdb valide.")
        if not str(output):
            raise LinkerError("Sélectionne un dossier de sortie.")
        return master, output

    def _start_extract_and_link(self) -> None:
        if self.running:
            return
        try:
            master, output = self._validate_common()
            extractor = Path(self.extractor_var.get().strip()).expanduser()
            if not extractor.is_file():
                raise LinkerError(
                    "Sélectionne umaextractor.exe, ou utilise un data.json existant."
                )
        except LinkerError as exc:
            self._show_error(exc)
            return
        self._save_current_config()
        self._clear_log()
        self._set_running(True)
        self._set_status("Extraction en cours…")
        self.progress_var.set(3)
        threading.Thread(
            target=self._worker_extract_and_link,
            args=(extractor, master, output),
            daemon=True,
        ).start()

    def _start_link_existing(self) -> None:
        if self.running:
            return
        try:
            master, output = self._validate_common()
            data_json = Path(self.json_var.get().strip()).expanduser()
            if not data_json.is_file():
                raise LinkerError("Sélectionne un data.json valide.")
        except LinkerError as exc:
            self._show_error(exc)
            return
        self._save_current_config()
        self._clear_log()
        self._set_running(True)
        self._set_status("Liaison en cours…")
        self.progress_var.set(15)
        threading.Thread(
            target=self._worker_link,
            args=(master, data_json, output),
            daemon=True,
        ).start()

    def _start_catalog_only(self) -> None:
        if self.running:
            return
        try:
            master, output = self._validate_common()
        except LinkerError as exc:
            self._show_error(exc)
            return
        self._save_current_config()
        self._clear_log()
        self._set_running(True)
        self._set_status("Génération du catalogue skills…")
        self.progress_var.set(20)
        threading.Thread(
            target=self._worker_catalog_only,
            args=(master, output),
            daemon=True,
        ).start()

    def _start_simulator_weights(self) -> None:
        if self.running:
            return
        try:
            master, output = self._validate_common()
            batch = Path(self.batch_var.get().strip()).expanduser()
            if not batch.is_file():
                raise LinkerError("Sélectionne un batch Umalator JSON valide.")
            course_overrides_text = self.course_overrides_var.get().strip()
            course_overrides = (
                Path(course_overrides_text).expanduser()
                if course_overrides_text
                else None
            )
            if course_overrides is not None and not course_overrides.is_file():
                raise LinkerError("Sélectionne un fichier d'overrides de course valide.")
        except LinkerError as exc:
            self._show_error(exc)
            return
        self._save_current_config()
        self._clear_log()
        self._set_running(True)
        self._set_status("Import et normalisation des poids Umalator…")
        self.progress_var.set(15)
        threading.Thread(
            target=self._worker_simulator_weights,
            args=(master, batch, output, course_overrides),
            daemon=True,
        ).start()

    def _run_extractor(self, extractor: Path) -> Path:
        self._enqueue_log(f"Lancement de {extractor.name} en mode CLI…")
        command = [str(extractor), "--cli"]
        if extractor.suffix.lower() == ".py":
            command = [sys.executable, str(extractor), "--cli"]
        process = subprocess.Popen(
            command,
            cwd=str(extractor.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        assert process.stdout is not None
        for line in process.stdout:
            clean = line.rstrip()
            if clean:
                self._enqueue_log(f"UmaExtractor: {clean}")
        code = process.wait()
        if code != 0:
            raise LinkerError(f"UmaExtractor s'est terminé avec le code {code}.")
        data_json = extractor.parent / "data.json"
        if not data_json.is_file():
            documents_json = Path.home() / "Documents" / "data.json"
            if documents_json.is_file():
                data_json = documents_json
            else:
                raise LinkerError(
                    "UmaExtractor a terminé, mais aucun data.json n'a été trouvé."
                )
        self._enqueue_log(f"JSON extrait : {data_json}")
        return data_json

    def _worker_extract_and_link(
        self, extractor: Path, master: Path, output: Path
    ) -> None:
        try:
            self.queue.put(("progress", (8, "Connexion au jeu et extraction…")))
            data_json = self._run_extractor(extractor)
            self.queue.put(("json_path", str(data_json)))
            self.queue.put(("progress", (45, "Extraction terminée ; liaison…")))
            result = link_veterans(master, data_json, output, self._enqueue_log)
            self.queue.put(("done", result))
        except Exception as exc:
            self.queue.put(("error", (str(exc), traceback.format_exc())))

    def _worker_link(self, master: Path, data_json: Path, output: Path) -> None:
        try:
            result = link_veterans(master, data_json, output, self._enqueue_log)
            self.queue.put(("done", result))
        except Exception as exc:
            self.queue.put(("error", (str(exc), traceback.format_exc())))

    def _worker_catalog_only(self, master: Path, output: Path) -> None:
        try:
            result = generate_skill_catalogs(master, output, self._enqueue_log)
            self.queue.put(("catalog_done", result))
        except Exception as exc:
            self.queue.put(("error", (str(exc), traceback.format_exc())))

    def _worker_simulator_weights(
        self,
        master: Path,
        batch: Path,
        output: Path,
        course_overrides: Path | None,
    ) -> None:
        try:
            self.queue.put(("progress", (25, "Actualisation du catalogue depuis le MDB…")))
            catalog = generate_skill_catalogs(master, output, self._enqueue_log)
            self.queue.put(("progress", (60, "Normalisation des résultats Umalator…")))
            adjustments = app_base_dir() / "default_manual_adjustments.json"
            result = generate_simulator_weights(
                batch,
                catalog.skills_path,
                catalog.weights_template_path,
                output,
                manual_adjustments_path=(adjustments if adjustments.is_file() else None),
                course_overrides_path=course_overrides,
                logger=self._enqueue_log,
            )
            self.queue.put(("simulator_done", result))
        except Exception as exc:
            self.queue.put(("error", (str(exc), traceback.format_exc())))

    def _worker_optimizer(
        self,
        master: Path,
        data_json: Path,
        output: Path,
        course_overrides: Path | None,
        scoring_config: Path,
        skill_priorities: Path,
        ace_card_id: int,
        future_parent_card_id: int,
        surface: str,
        distance: str,
        style: str,
        course_key: str | None,
        course_conditions: dict[str, object],
        top_n: int,
    ) -> None:
        try:
            self._enqueue_log(f"Profil de pondération utilisé : {scoring_config}")
            self._enqueue_log(f"Priorités white skills utilisées : {skill_priorities}")
            self.queue.put(("progress", (10, "Liaison des vétérans avec le MDB courant…")))
            linked = link_veterans(master, data_json, output, self._enqueue_log)
            self.queue.put(("progress", (48, "Génération des pondérations manuelles des white skills…")))
            manual_weights = generate_manual_skill_weights(
                linked.skills_catalog_path,
                skill_priorities,
                output,
                course_overrides_path=course_overrides,
                logger=self._enqueue_log,
            )
            self.queue.put(("progress", (72, "Calcul des lignées et des paires de parents…")))
            result = optimize_parents(
                master,
                linked.json_path,
                manual_weights.weights_path,
                linked.race_factor_skills_path,
                linked.skills_catalog_path,
                output,
                ace_card_id=ace_card_id,
                future_parent_card_id=future_parent_card_id,
                surface=surface,
                distance=distance,
                style=style,
                course_weights_path=manual_weights.course_weights_path,
                course_key=course_key,
                course_conditions=course_conditions,
                scoring_config_path=scoring_config,
                top_n=top_n,
                logger=self._enqueue_log,
            )
            self.queue.put(("optimizer_done", result))
        except Exception as exc:
            self.queue.put(("error", (str(exc), traceback.format_exc())))

    def _worker_transfer_helper(
        self,
        master: Path,
        data_json: Path,
        output: Path,
        course_overrides: Path | None,
        scoring_config: Path,
        skill_priorities: Path,
    ) -> None:
        try:
            self._enqueue_log(f"Profil de pondération utilisé : {scoring_config}")
            self._enqueue_log(f"Priorités white skills utilisées : {skill_priorities}")
            self.queue.put(("progress", (10, "Liaison des vétérans avec le MDB courant…")))
            linked = link_veterans(master, data_json, output, self._enqueue_log)
            self.queue.put(("progress", (38, "Génération des pondérations manuelles des white skills…")))
            manual_weights = generate_manual_skill_weights(
                linked.skills_catalog_path,
                skill_priorities,
                output,
                course_overrides_path=course_overrides,
                logger=self._enqueue_log,
            )
            self.queue.put(("progress", (58, "Analyse de tous les rôles et profils…")))
            result = analyze_transfer_candidates(
                master,
                linked.json_path,
                manual_weights.weights_path,
                linked.race_factor_skills_path,
                linked.skills_catalog_path,
                output,
                course_weights_path=manual_weights.course_weights_path,
                scoring_config_path=scoring_config,
                logger=self._enqueue_log,
            )
            self.queue.put(("transfer_helper_done", result))
        except Exception as exc:
            self.queue.put(("error", (str(exc), traceback.format_exc())))

    def _worker_uma_moe(
        self,
        master: Path,
        data_json: Path,
        output: Path,
        course_overrides: Path | None,
        scoring_config: Path,
        skill_priorities: Path,
        ace_card_id: int,
        target_parent_card_id: int,
        fixed_gp_id: int | None,
        automatic_pairs: bool,
        local_pool_size: int,
        remote_pool_size: int,
        surface: str,
        distance: str,
        style: str,
        course_key: str | None,
        course_conditions: dict[str, object],
        top_n: int,
        use_import: bool,
        response_path: Path | None,
        api_base: str,
        uql: str,
        auto_uql: bool,
        uql_options: dict[str, object],
        limit: int,
        planned_g1_budget: int,
        single_g1_weight: float,
        token: str,
    ) -> None:
        try:
            self._enqueue_log(f"Profil de pondération utilisé : {scoring_config}")
            self._enqueue_log(f"Priorités white skills utilisées : {skill_priorities}")
            self.queue.put(("progress", (10, "Liaison des vétérans locaux avec le MDB…")))
            linked = link_veterans(master, data_json, output, self._enqueue_log)
            self.queue.put(("progress", (40, "Génération des priorités manuelles…")))
            manual_weights = generate_manual_skill_weights(
                linked.skills_catalog_path,
                skill_priorities,
                output,
                course_overrides_path=course_overrides,
                logger=self._enqueue_log,
            )
            operation = None
            effective_uql = uql
            main_parent_pink_sparks: list[int] = []
            optional_main_white_factors: list[int] = []
            optional_white_sparks: list[int] = []

            # The pink/white preference checkboxes apply regardless of the "Auto"
            # toggle, which historically only controlled the free-text UQL box.
            # Resolve them unconditionally so they always reach the API.
            auto_uql_text, generated_uql_meta = generate_auto_uql(
                manual_weights.weights_path,
                linked.skills_catalog_path,
                surface=surface,
                distance=distance,
                style=style,
                course_weights_path=manual_weights.course_weights_path,
                course_key=course_key,
                course_conditions=course_conditions,
                scoring_config_path=scoring_config,
                options=uql_options,
                master_path=master,
            )
            search_filters = generated_uql_meta.get("search_filters") or {}
            main_parent_pink_sparks = list(search_filters.get("main_parent_pink_sparks") or [])
            optional_main_white_factors = list(search_filters.get("optional_main_white_factors") or [])
            optional_white_sparks = list(search_filters.get("optional_white_sparks") or [])
            if auto_uql and not use_import:
                effective_uql = auto_uql_text
                uql_path = output / "uma_moe_generated_uql.txt"
                uql_path.write_text(effective_uql + "\n", encoding="utf-8")
                meta_path = output / "uma_moe_generated_uql.json"
                meta_path.write_text(json.dumps(generated_uql_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                self.queue.put(("uma_moe_uql", effective_uql))
                self._enqueue_log(
                    "UQL automatique générée (référence / copie manuelle dans l'éditeur du site — "
                    "pas envoyée à l'API, qui n'a pas de paramètre texte libre) :"
                )
                if effective_uql:
                    for line in effective_uql.splitlines():
                        self._enqueue_log("  " + line)
                else:
                    self._enqueue_log("  (vide : recherche volontairement maximale)")
            if main_parent_pink_sparks:
                self._enqueue_log(
                    "Filtre pink strict envoyé à l'API (main_parent_pink_sparks) : "
                    + ", ".join(str(value) for value in main_parent_pink_sparks)
                )
            if optional_main_white_factors:
                self._enqueue_log(
                    "Préférence white — profil du futur parent (optional_main_white_factors) : "
                    + ", ".join(str(value) for value in optional_main_white_factors)
                )
            if optional_white_sparks:
                self._enqueue_log(
                    "Préférence white — répétition dans la lignée (optional_white_sparks) : "
                    + ", ".join(str(value) for value in optional_white_sparks)
                )
            if use_import:
                assert response_path is not None
                self.queue.put(("progress", (58, "Lecture de la réponse JSON uma.moe…")))
                raw_payload = json.loads(response_path.read_text(encoding="utf-8-sig"))
                operation = {
                    "mode": "import",
                    "path": str(response_path),
                    "effective_uql": effective_uql,
                    "generated_uql_metadata": generated_uql_meta,
                }
            else:
                self.queue.put(("progress", (55, f"Recherche uma.moe paginée — objectif {limit} candidats…")))
                client = UmaMoeApiClient(api_base, token=(token or None))
                api_filters: dict[str, list[int]] = {}
                if main_parent_pink_sparks:
                    api_filters["main_parent_pink_sparks"] = main_parent_pink_sparks
                if optional_main_white_factors:
                    api_filters["optional_main_white_factors"] = optional_main_white_factors
                if optional_white_sparks:
                    api_filters["optional_white_sparks"] = optional_white_sparks
                raw_payload, operation = client.search_many(
                    filters=api_filters,
                    desired_candidates=limit,
                    page_size=100,
                    logger=self._enqueue_log,
                )
                operation["auto_uql"] = bool(auto_uql)
                operation["generated_uql_metadata"] = generated_uql_meta
                operation["effective_uql"] = effective_uql
                api_raw_path = output / "uma_moe_api_response.json"
                api_raw_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                self.queue.put(("uma_moe_response_path", str(api_raw_path)))
            mode_text = "toutes les paires local × distant" if automatic_pairs else "le GP local fixé"
            self.queue.put(("progress", (75, f"Calcul des meilleures paires — {mode_text}…")))
            result = rank_online_grandparent_pairs(
                master,
                linked.json_path,
                manual_weights.weights_path,
                linked.skills_catalog_path,
                output,
                ace_card_id=ace_card_id,
                target_parent_card_id=target_parent_card_id,
                fixed_grandparent_trained_id=fixed_gp_id,
                exhaustive_pairs=automatic_pairs,
                local_pool_size=local_pool_size,
                remote_pool_size=remote_pool_size,
                surface=surface,
                distance=distance,
                style=style,
                raw_payload=raw_payload,
                course_weights_path=manual_weights.course_weights_path,
                course_key=course_key,
                course_conditions=course_conditions,
                scoring_config_path=scoring_config,
                planned_g1_budget=planned_g1_budget,
                single_g1_weight=single_g1_weight,
                top_n=top_n,
                api_operation=operation,
                required_main_factors=((generated_uql_meta or {}).get("hard_filters") or []),
                effective_uql=effective_uql,
                logger=self._enqueue_log,
            )
            self.queue.put(("uma_moe_done", result))
        except Exception as exc:
            self.queue.put(("error", (str(exc), traceback.format_exc())))

    def _show_transfer_helper_results(self, result: object) -> None:
        window = tk.Toplevel(self.root)
        window.title("Transfer Helper — résultats")
        window.geometry("1500x900")
        window.minsize(1080, 680)

        header = ttk.Frame(window, padding=10)
        header.pack(fill=tk.X)
        ttk.Label(
            header,
            text=(
                f"Transfert sûr : {result.safe_transfer_count}  |  "
                f"À examiner : {result.review_count}  |  "
                f"Probablement conserver : {result.likely_keep_count}  |  "
                f"Conserver : {result.keep_count}"
            ),
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            header,
            text=(
                "Le verdict « transfert sûr » exige un remplaçant de la même carte/unique, "
                "non inférieur dans chaque niche globalement viable. Les contextes où toutes "
                "les copies sont surclassées par le pool global sont ignorés."
            ),
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(3, 0))

        body = ttk.Panedwindow(window, orient=tk.VERTICAL)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        table_frame = ttk.Frame(body)
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        columns = (
            "status",
            "veteran",
            "id",
            "rank",
            "game_score",
            "copies",
            "parent",
            "parent_rank",
            "gp",
            "gp_rank",
            "replacement",
            "lead",
            "refs",
        )
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "status": "Verdict",
            "veteran": "Vétéran",
            "id": "ID",
            "rank": "Rang jeu",
            "game_score": "Score jeu",
            "copies": "Copies",
            "parent": "Meilleur parent",
            "parent_rank": "Meilleur rang parent",
            "gp": "Meilleur GP",
            "gp_rank": "Meilleur rang GP",
            "replacement": "Remplaçant",
            "lead": "Avance moy.",
            "refs": "Référencé par",
        }
        widths = {
            "status": 120,
            "veteran": 270,
            "id": 90,
            "rank": 80,
            "game_score": 95,
            "copies": 70,
            "parent": 105,
            "parent_rank": 120,
            "gp": 105,
            "gp_rank": 110,
            "replacement": 270,
            "lead": 90,
            "refs": 90,
        }
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(
                column,
                width=widths[column],
                anchor="w" if column in {"status", "veteran", "replacement"} else "center",
            )
        vsb = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        body.add(table_frame, weight=3)

        detail = scrolledtext.ScrolledText(
            body,
            wrap=tk.WORD,
            font=("Consolas", 10),
            height=16,
            state=tk.DISABLED,
        )
        body.add(detail, weight=2)

        status_labels = {
            "safe_transfer": "Transfert sûr",
            "review": "À examiner",
            "likely_keep": "Probablement conserver",
            "keep": "Conserver",
        }
        row_map: dict[str, dict[str, object]] = {}
        for index, record in enumerate(result.records):
            dominated = record.get("dominated_by") or {}
            iid = tree.insert(
                "",
                tk.END,
                values=(
                    self._tr(status_labels.get(record.get("status"), record.get("status"))),
                    record.get("card_name") or record.get("uma_name"),
                    record.get("trained_chara_id"),
                    record.get("rank") if record.get("rank") is not None else "—",
                    self._format_rank_score(record.get("rank_score")) or "—",
                    record.get("same_card_copy_count"),
                    f"{float(record.get('best_parent_score') or 0):.1f}",
                    f"top {float(record.get('best_parent_percentile') or 100):.1f}%",
                    f"{float(record.get('best_grandparent_score') or 0):.1f}",
                    f"top {float(record.get('best_grandparent_percentile') or 100):.1f}%",
                    dominated.get("card_name") or "—",
                    (
                        f"+{float(dominated.get('mean_score_lead')):.2f}"
                        if dominated.get("mean_score_lead") is not None
                        else "—"
                    ),
                    record.get("referenced_by_local_veterans") or 0,
                ),
            )
            row_map[iid] = record

        def localised_profile_name(profile: dict[str, object]) -> str:
            context_key = str(profile.get("context_key") or "")
            parts = context_key.split(":")
            if len(parts) == 4 and parts[0] == "generic":
                return (
                    f"{self._tr('Profil générique')} · "
                    f"{profile_label('surface', parts[1], self.language_code)} / "
                    f"{profile_label('distance', parts[2], self.language_code)} / "
                    f"{profile_label('style', parts[3], self.language_code)}"
                )
            if len(parts) >= 3 and parts[0] == "course":
                raw_label = str(profile.get("profile") or context_key)
                course_label = raw_label.rsplit(" · ", 1)[0]
                return f"{course_label} · {profile_label('style', parts[-1], self.language_code)}"
            return str(profile.get("profile") or context_key)

        def profile_lines(title: str, profiles: list[dict[str, object]]) -> list[str]:
            lines = [title]
            if not profiles:
                lines.append("  —")
                return lines
            for profile in profiles[:6]:
                lines.append(
                    f"  - {localised_profile_name(profile)}: {float(profile.get('score') or 0):.2f} "
                    f"(top {float(profile.get('percentile') or 100):.1f}%)"
                )
            return lines

        def update_detail(_event=None) -> None:
            selection = tree.selection()
            if not selection:
                return
            record = row_map[selection[0]]
            dominated = record.get("dominated_by") or {}
            reason_map = {
                "strictly_dominated_same_card": (
                    "Un autre exemplaire de la même carte/unique est au moins aussi bon dans toutes les "
                    "niches globalement viables, avec une avance moyenne suffisante et sans perte de support "
                    "G1 en paire. Les contextes où toutes les copies sont globalement surclassées sont ignorés."
                ),
                "no_competitive_role_detected": (
                    "Aucun profil parent ou grand-parent n'atteint les seuils de score ou de classement. "
                    "Ce verdict reste manuel : aucune copie strictement dominante n'a été trouvée."
                ),
                "grandparent_niche": "Faible comme parent, mais au moins une niche de futur grand-parent reste compétitive.",
                "parent_niche": "Faible comme futur grand-parent, mais au moins une niche de parent reste compétitive.",
                "competitive_in_multiple_roles": "Le vétéran reste compétitif dans plusieurs rôles ou profils.",
            }
            lines = [
                f"{record.get('card_name')} — {record.get('uma_name')}",
                f"Veteran ID: {record.get('trained_chara_id')} | Card ID: {record.get('card_id')}",
                f"Rang en jeu: {record.get('rank') if record.get('rank') is not None else '—'} | "
                f"Score en jeu: {self._format_rank_score(record.get('rank_score')) or '—'}",
                f"Stats: {self._format_stats(record.get('stats') or {}) or '—'}",
                f"Grands-parents: {record.get('grandparent_1') or '—'} / {record.get('grandparent_2') or '—'}",
                f"Verdict: {status_labels.get(record.get('status'), record.get('status'))}",
                f"Raison: {reason_map.get(record.get('reason_code'), record.get('reason_code'))}",
                f"Copies comparables: {record.get('same_card_copy_count')}",
                f"Référencé comme parent direct par {record.get('referenced_by_local_veterans')} vétéran(s) local(aux).",
                "",
                f"Meilleur potentiel parent: {float(record.get('best_parent_score') or 0):.2f} "
                f"(top {float(record.get('best_parent_percentile') or 100):.2f}%)",
                f"Meilleur potentiel grand-parent: {float(record.get('best_grandparent_score') or 0):.2f} "
                f"(top {float(record.get('best_grandparent_percentile') or 100):.2f}%)",
            ]
            if dominated:
                lines.extend(
                    [
                        "",
                        "Remplaçant retenu",
                        f"  {dominated.get('card_name')} [{dominated.get('trained_chara_id')}]",
                        f"  Rang/score en jeu: {dominated.get('rank') if dominated.get('rank') is not None else '—'} / "
                        f"{self._format_rank_score(dominated.get('rank_score')) or '—'}",
                        f"  Avance moyenne: +{float(dominated.get('mean_score_lead') or 0):.3f}",
                        f"  Pire écart observé: {float(dominated.get('worst_context_delta') or 0):+.3f}",
                        f"  Meilleur écart observé: {float(dominated.get('best_context_delta') or 0):+.3f}",
                        f"  Comparaisons parent viables: {int(dominated.get('viable_parent_comparisons') or 0)}",
                        f"  Comparaisons GP viables: {int(dominated.get('viable_grandparent_comparisons') or 0)}",
                    ]
                )
            lines.extend([""] + profile_lines("Meilleurs profils parent", record.get("top_parent_profiles") or []))
            lines.extend([""] + profile_lines("Meilleurs profils grand-parent", record.get("top_grandparent_profiles") or []))
            lines.extend(
                [
                    "",
                    "Attention: l'outil ne modifie pas data.json et ne supprime rien en jeu. "
                    "Les entrées « À examiner » ne sont jamais des recommandations automatiques de transfert.",
                ]
            )
            detail.configure(state=tk.NORMAL)
            detail.delete("1.0", tk.END)
            detail.insert(tk.END, self._tr("\n".join(lines)))
            detail.configure(state=tk.DISABLED)

        tree.bind("<<TreeviewSelect>>", update_detail)
        if row_map:
            first = next(iter(row_map))
            tree.selection_set(first)
            tree.focus(first)
            update_detail()

        footer = ttk.Frame(window, padding=(10, 0, 10, 10))
        footer.pack(fill=tk.X)
        ttk.Button(
            footer,
            text="Ouvrir le dossier de sortie",
            command=lambda: open_path(result.report_json_path.parent),
        ).pack(side=tk.LEFT)
        ttk.Button(footer, text="Fermer", command=window.destroy).pack(side=tk.RIGHT)
        self._apply_translations(window)

    def _show_uma_moe_results(self, result: object) -> None:
        window = tk.Toplevel(self.root)
        window.title("Résultats — paires de grands-parents uma.moe")
        window.geometry("1640x940")
        window.minsize(1180, 700)

        header = ttk.Frame(window, padding=10)
        header.pack(fill=tk.X)
        ttk.Label(
            header,
            text=f"Ace : {result.ace['card_name']} | Parent à produire : {result.target_parent['card_name']}",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")
        if getattr(result, "pair_mode", "") == "exhaustive_top_pools":
            mode_text = (
                f"Mode automatique : {result.local_pool_count} GP locaux × {result.remote_pool_count} GP distants — "
                f"{result.evaluated_pair_count} paires valides évaluées."
            )
        else:
            fixed = result.fixed_grandparent or {}
            mode_text = (
                f"GP local fixé : {fixed.get('card_name', '?')} [#{fixed.get('trained_chara_id', '?')}] — "
                f"{result.result_count} candidats classés."
            )
        ttk.Label(header, text=mode_text).pack(anchor="w", pady=(2, 0))
        ttk.Label(
            header,
            text=(
                "Le score principal estime la future branche du parent avec l’Ace. "
                "Les G1 communes aux deux GP sont comptées à plein rendement ; les G1 d’un seul côté reçoivent un bonus potentiel réduit."
            ),
            foreground="#666666",
        ).pack(anchor="w", pady=(2, 0))

        frame = ttk.Frame(window, padding=(10, 0, 10, 10))
        frame.pack(fill=tk.BOTH, expand=True)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        columns = (
            "rank", "score", "local", "local_eval", "remote", "trainer", "friend", "remote_eval",
            "final_base", "g1_plan", "final_potential", "common_g1", "local_only_g1", "remote_only_g1",
            "pink", "white", "white_gen", "blue",
        )
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        headings = {
            "rank": "#",
            "score": "Score",
            "local": "GP local",
            "local_eval": "Éval. local",
            "remote": "GP distant",
            "trainer": "Trainer",
            "friend": "Friend ID",
            "remote_eval": "Éval. distant",
            "final_base": "Base finale",
            "g1_plan": "+G1 pondéré",
            "final_potential": "Potentiel final",
            "common_g1": "G1 communes",
            "local_only_g1": "G1 seul (local)",
            "remote_only_g1": "G1 seul (distant)",
            "pink": "Pinks",
            "white": "Whites",
            "white_gen": "Support white",
            "blue": "Blues",
        }
        widths = {"local": 260, "remote": 280, "trainer": 120, "friend": 125}
        for column in columns:
            tree.heading(column, text=headings[column])
            width = widths.get(column, 92)
            tree.column(column, width=width, anchor="w" if width >= 120 else "center")
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        detail = scrolledtext.ScrolledText(frame, wrap=tk.WORD, height=19, font=("Consolas", 10), state=tk.DISABLED)
        detail.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        row_map: dict[str, dict[str, object]] = {}

        def fmt_score(value: object) -> str:
            try:
                return f"{float(value):.1f}"
            except (TypeError, ValueError):
                return ""

        for rank, row in enumerate(result.top_results, 1):
            remote = row.get("candidate") or {}
            local = row.get("fixed_grandparent") or {}
            online = remote.get("online") or {}
            final_aff = row.get("final_parent_affinity") or row.get("final_branch_affinity") or {}
            iid = str(rank)
            row_map[iid] = row
            tree.insert("", tk.END, iid=iid, values=(
                rank,
                f"{float(row.get('score') or 0):.2f}",
                local.get("card_name"),
                self._format_rank_score(local.get("rank_score")),
                remote.get("card_name"),
                online.get("trainer_name") or "",
                online.get("friend_code") or "",
                self._format_rank_score(remote.get("rank_score")),
                final_aff.get("base", 0),
                fmt_score(final_aff.get("planned_g1_bonus", 0)),
                fmt_score(final_aff.get("potential_total", final_aff.get("total", 0))),
                final_aff.get("common_g1_count", 0),
                final_aff.get("fixed_only_g1_count", 0),
                final_aff.get("candidate_only_g1_count", 0),
                fmt_score(row.get("components", {}).get("pink")),
                fmt_score(row.get("components", {}).get("white_skill")),
                fmt_score(row.get("components", {}).get("white_generation")),
                fmt_score(row.get("components", {}).get("blue")),
            ))

        def render_detail(row: dict[str, object]) -> str:
            remote = row.get("candidate") or {}
            local = row.get("fixed_grandparent") or {}
            online = remote.get("online") or {}
            final_aff = row.get("final_parent_affinity") or row.get("final_branch_affinity") or {}
            production = row.get("production_affinity") or {}
            breakdown = row.get("score_breakdown") or {}
            details = row.get("component_details") or {}
            common = final_aff.get("common_gp_g1") or []
            local_only = final_aff.get("fixed_only_g1") or []
            remote_only = final_aff.get("candidate_only_g1") or []
            single_weight = float(final_aff.get("single_g1_weight") or 0)
            lines = [
                f"GP LOCAL : {local.get('card_name')} — {local.get('uma_name')}",
                f"ID entraînement : #{local.get('trained_chara_id') or '-'} | Score Uma : {self._format_rank_score(local.get('rank_score')) or '-'}",
                "",
                f"GP DISTANT : {remote.get('card_name')} — {remote.get('uma_name')}",
                f"Trainer : {online.get('trainer_name') or '-'} | Friend ID : {online.get('friend_code') or '-'}",
                f"Dernière mise à jour : {online.get('updated_at') or '-'} | Score Uma : {self._format_rank_score(remote.get('rank_score')) or '-'}",
                "",
                "Affinité potentielle du FUTUR PARENT avec l’Ace :",
                f"- Pair(Ace, parent cible) : {final_aff.get('pair_ace_parent', 0)}",
                f"- Triple(Ace, parent, GP local) : {final_aff.get('fixed_gp_triple', 0)}",
                f"- Triple(Ace, parent, GP distant) : {final_aff.get('candidate_gp_triple', 0)}",
                f"- Base exacte : {final_aff.get('base', 0)}",
                "",
                f"Plan G1 : {final_aff.get('planned_g1_budget', 0)} courses maximum sur le futur parent",
                f"- Communes aux deux GP : {final_aff.get('planned_double_overlap_races', 0)} × 6 = {final_aff.get('planned_common_g1_bonus', 0)}",
                f"- Présentes sur un seul GP : {final_aff.get('planned_single_overlap_races', 0)} × 3 × {single_weight:.0%} = {float(final_aff.get('planned_single_g1_bonus_weighted') or 0):.1f}",
                f"- Bonus G1 pondéré utilisé : {float(final_aff.get('planned_g1_bonus') or 0):.1f}",
                f"- Bonus exact si toutes les G1 prévues sont effectivement gagnées : {final_aff.get('planned_g1_bonus_exact_if_all_won', 0)}",
                f"- TOTAL POTENTIEL PONDÉRÉ : {float(final_aff.get('potential_total') or 0):.1f}",
                f"- Total exact maximal avec ce plan : {final_aff.get('potential_total_exact_if_all_won', '-')}",
                "",
                "Courses utiles :",
                "- communes GP local / GP distant : " + (", ".join(common) if common else "aucune"),
                "- seulement GP local : " + (", ".join(local_only) if local_only else "aucune"),
                "- seulement GP distant : " + (", ".join(remote_only) if remote_only else "aucune"),
                "",
                "Compatibilité du run de fabrication — faible pondération :",
                f"- Total : {production.get('total', 0)} = base {production.get('base', 0)} + bonus G1 {production.get('g1_bonus', 0)}",
                "",
                "Décomposition du score :",
            ]
            label_map = {
                "final_parent_affinity": "Affinité potentielle du parent final",
                "production_run_affinity": "Compatibilité du run de fabrication",
                "pink": "Pinks des deux GP",
                "white_skill": "Whites propres des deux GP",
                "white_generation": "Soutien de génération des whites",
                "blue": "Blues des deux GP",
            }
            for key, item in (breakdown.get("components") or {}).items():
                label = label_map.get(key, key)
                lines.append(
                    f"- {label}: note={float(item.get('component_score') or 0):.2f}, "
                    f"poids={float(item.get('weight') or 0):.1%}, points={float(item.get('points') or 0):.2f}"
                )
            lines.extend(["", "Factors propres du GP local :"])
            for factor in (local.get("factors") or {}).get("all") or []:
                lines.append(f"- {factor.get('type')}: {factor.get('name')} {int(factor.get('stars') or 0)}★")
            lines.extend(["", "Factors propres du GP distant :"])
            for factor in (remote.get("factors") or {}).get("all") or []:
                lines.append(f"- {factor.get('type')}: {factor.get('name')} {int(factor.get('stars') or 0)}★")
            lines.extend(["", "Whites soutenues par les six membres des deux lignées :"])
            skills = ((details.get("white_generation") or {}).get("skills") or [])
            for skill in skills[:25]:
                lines.append(
                    f"- {skill.get('name')} | copies={skill.get('lineage_copy_count')} | "
                    f"poids={float(skill.get('profile_weight') or 0):.3f} | "
                    f"bonus={float(skill.get('lineage_generation_bonus') or 0):.1%} | "
                    f"contribution={float(skill.get('contribution') or 0):.4f}"
                )
            return "\n".join(lines)

        def update_detail(_event=None):
            selection = tree.selection()
            if not selection:
                return
            row = row_map.get(selection[0])
            if row is None:
                return
            detail.configure(state=tk.NORMAL)
            detail.delete("1.0", tk.END)
            detail.insert(tk.END, self._tr(render_detail(row)))
            detail.configure(state=tk.DISABLED)
            detail.see("1.0")

        tree.bind("<<TreeviewSelect>>", update_detail)
        if row_map:
            first = next(iter(row_map))
            tree.selection_set(first)
            update_detail()
        self._apply_translations(window)

    def _show_optimizer_results(self, result: object) -> None:
        window = tk.Toplevel(self.root)
        window.title("Résultats — optimisation de lignée")
        window.geometry("1540x920")
        window.minsize(1120, 700)

        component_labels = {
            "affinity": "Affinité",
            "g1_potential": "Potentiel G1",
            "blue": "Bleues",
            "pink": "Roses",
            "white_skill": "Whites propres",
            "white_generation": "Bonus de lignée white",
            "race_scenario": "Race / scénario",
            "unique": "Vertes / uniques",
        }

        def role_label(role: str) -> str:
            return {
                "parent": "Parent",
                "grandparent": "Grand-parent",
                "grandparent_1": "Grand-parent 1",
                "grandparent_2": "Grand-parent 2",
                "candidate": "Candidat",
            }.get(role, role)

        def format_identity(identity: dict[str, object] | None) -> str:
            if not identity:
                return "-"
            card_name = str(identity.get("card_name") or identity.get("uma_name") or "?")
            trained = identity.get("trained_chara_id")
            rank_score = self._format_rank_score(identity.get("rank_score"))
            suffix = []
            if trained:
                suffix.append(f"#{trained}")
            if rank_score:
                suffix.append(f"éval. {rank_score}")
            return card_name + (" [" + " / ".join(suffix) + "]" if suffix else "")

        def format_factor_list(details: dict[str, object] | None, kind: str) -> list[str]:
            details = details or {}
            factors = details.get("top_factors") or details.get("factors") or []
            lines: list[str] = []
            for factor in factors:
                if not isinstance(factor, dict):
                    continue
                name = factor.get("name")
                if not name:
                    continue
                role = role_label(str(factor.get("role") or "?"))
                stars = int(factor.get("stars") or 0)
                prefix = f"  - {role}: {name} {stars}★"
                if kind == "white_skill":
                    prefix += (
                        f" | poids profil={float(factor.get('profile_weight') or 0):.3f}"
                        f" × confort héritage étoiles={float(factor.get('star_quality') or 0):.3f}"
                        f" × position={float(factor.get('position_weight') or 0):.2f}"
                        f" => brut={float(factor.get('contribution') or 0):.4f}"
                    )
                elif kind == "blue":
                    prefix += (
                        f" | palier étoiles={float(factor.get('quality') or 0):.2f}"
                        f" × pertinence stat={float(factor.get('relevance') or 0):.2f}"
                        f" => brut={float(factor.get('contribution') or 0):.3f}"
                    )
                elif kind == "pink":
                    matched = factor.get("matched_dimension") or "hors profil"
                    prefix += (
                        f" | catégorie={matched}"
                        f" | palier étoiles={float(factor.get('star_quality') or 0):.2f}"
                        f" × valeur catégorie={float(factor.get('dimension_weight') or 0):.2f}"
                        f" × besoin={float(factor.get('need_multiplier') or 0):.2f}"
                        f" => brut={float(factor.get('contribution') or 0):.3f}"
                    )
                elif kind == "race_scenario":
                    granted = factor.get("granted_skill_keys") or []
                    if granted:
                        prefix += (
                            f" | skill donnée={', '.join(granted)}"
                            f" | poids skill={float(factor.get('granted_skill_weight') or 0):.3f}"
                        )
                    prefix += f" | brut={float(factor.get('contribution') or 0):.4f}"
                elif kind == "unique":
                    prefix += (
                        f" | palier étoiles={float(factor.get('star_quality') or 0):.2f}"
                        f" × position={float(factor.get('position_weight') or 0):.2f}"
                        f" => brut={float(factor.get('contribution') or 0):.3f}"
                    )
                lines.append(prefix)
            return lines or ["  - aucun factor de cette catégorie"]

        def render_score_breakdown(row: dict[str, object]) -> list[str]:
            breakdown = row.get("score_breakdown") or {}
            entries = breakdown.get("components") or {}
            lines = ["Calcul du score global :"]
            for key, item in entries.items():
                if not isinstance(item, dict):
                    continue
                label = component_labels.get(str(key), str(key))
                lines.append(
                    f"- {label}: {float(item.get('component_score') or 0):.2f}"
                    f" × {100 * float(item.get('weight') or 0):.1f}%"
                    f" = {float(item.get('points') or 0):.2f} points"
                )
            lines.append(f"= {float(breakdown.get('total') or row.get('score') or 0):.2f}")
            return lines

        def render_common_components(row: dict[str, object], include_race: bool = True) -> list[str]:
            lines = render_score_breakdown(row)
            components = row.get("components") or {}
            details = row.get("component_details") or {}

            lines.extend(["", "Interprétation des composantes (0–100) :"])
            for key in ("affinity", "g1_potential", "blue", "pink", "white_skill", "white_generation", "race_scenario", "unique"):
                if key not in components or (key == "race_scenario" and not include_race):
                    continue
                lines.append(f"- {component_labels[key]}: {float(components.get(key) or 0):.2f}")

            white_detail = details.get("white_skill") or {}
            if white_detail:
                lines.extend([
                    "",
                    "Whites — formule interne :",
                    f"- brut cumulé = {float(white_detail.get('raw') or 0):.4f}",
                    f"- saturation = {float(white_detail.get('scale') or 0):.2f}",
                    "- score = 100 × (1 - exp(-brut / saturation))",
                    "- chaque brut = priorité manuelle du skill pour le profil × coefficient de confort d’héritage des étoiles × coefficient parent/grand-parent",
                    "Whites principales :",
                ])
                lines.extend(format_factor_list(white_detail, "white_skill"))


            generation_detail = details.get("white_generation") or {}
            if generation_detail:
                lines.extend([
                    "",
                    "Support de génération des white genes pendant le farm du futur parent :",
                    f"- brut cumulé = {float(generation_detail.get('raw') or 0):.4f}",
                    f"- saturation = {float(generation_detail.get('scale') or 0):.2f}",
                    "- les copies sont comptées sur le candidat et ses deux parents actuels",
                    "- chaque membre de la lignée possédant le même gene ajoute +2,5 points de pourcentage",
                    "- la chance de base et la distinction skill blanche / ◎ / gold sont volontairement ignorées",
                    "- les race/scenario sparks ne participent pas à ce score",
                    "Skills soutenues par la lignée :",
                ])
                for item in generation_detail.get("skills") or []:
                    if not isinstance(item, dict):
                        continue
                    lines.append(
                        f"  - {item.get('name')} | copies={item.get('lineage_copy_count')}"
                        f" | poids profil={float(item.get('profile_weight') or 0):.3f}"
                        f" | bonus lignée=+{100 * float(item.get('lineage_generation_bonus') or 0):.1f} pp"
                        f" | contribution={float(item.get('contribution') or 0):.4f}"
                    )

            for key, label in (("blue", "Bleues"), ("pink", "Roses"), ("unique", "Vertes / uniques")):
                detail = details.get(key) or {}
                if not detail:
                    continue
                lines.extend(["", f"{label} — {detail.get('formula') or 'détail'} :"])
                lines.extend(format_factor_list(detail, key))

            race_detail = details.get("race_scenario") or {}
            if include_race and race_detail:
                lines.extend([
                    "",
                    "Race / scénario — volontairement faible :",
                    f"- brut cumulé = {float(race_detail.get('raw') or 0):.4f}",
                    f"- saturation = {float(race_detail.get('scale') or 0):.2f}",
                    "- une race spark donnant un green pertinent reste décotée face au white spark direct",
                ])
                lines.extend(format_factor_list(race_detail, "race_scenario"))
            return lines

        def render_pair_detail(row: dict[str, object]) -> str:
            parent_1 = row.get("parent_1") or {}
            parent_2 = row.get("parent_2") or {}
            affinity = row.get("affinity") or {}
            lines = [
                f"Parent 1 : {format_identity(parent_1)}",
                f"  GP1 : {parent_1.get('grandparent_1') or '-'}",
                f"  GP2 : {parent_1.get('grandparent_2') or '-'}",
                f"  Stats : {self._format_stats(parent_1.get('stats'))}",
                "",
                f"Parent 2 : {format_identity(parent_2)}",
                f"  GP1 : {parent_2.get('grandparent_1') or '-'}",
                f"  GP2 : {parent_2.get('grandparent_2') or '-'}",
                f"  Stats : {self._format_stats(parent_2.get('stats'))}",
                "",
                "Affinité exacte de la paire finale :",
                f"- Base totale : {affinity.get('base', 0)}",
                f"- Bonus G1 total : {affinity.get('g1_bonus', 0)}",
                f"- Total utilisé : {affinity.get('total', 0)}",
                f"- Base parent↔parent : {affinity.get('parent_parent_base', 0)}",
                "- Le score d'affinité plafonne progressivement à partir du seuil ◎ ; dépasser largement ce seuil rapporte peu.",
            ]
            common = affinity.get("parent_parent_common_g1") or []
            lines.append("- G1 communes entre les deux parents : " + (", ".join(common) if common else "aucune"))
            lines.extend([""] + render_common_components(row, include_race=True))
            return "\n".join(lines)

        def render_branch_detail(row: dict[str, object]) -> str:
            affinity = row.get("affinity") or {}
            details = affinity.get("details") or {}
            lines = [
                f"Parent : {format_identity(row)}",
                f"GP1 : {row.get('grandparent_1') or '-'}",
                f"GP2 : {row.get('grandparent_2') or '-'}",
                f"Stats : {self._format_stats(row.get('stats'))}",
                "",
                "Affinité de branche :",
                f"- Pair(Ace, parent) : {details.get('ace_parent_pair', 0)}",
                f"- Triple(Ace, parent, GP1) : {details.get('ace_parent_gp1_triple', 0)}",
                f"- Triple(Ace, parent, GP2) : {details.get('ace_parent_gp2_triple', 0)}",
                f"- Base : {affinity.get('base', 0)}",
                f"- Bonus G1 : {affinity.get('g1_bonus', 0)}",
                f"- Total utilisé : {affinity.get('total', 0)}",
                "- G1 communes parent↔GP1 : " + (", ".join(details.get('parent_gp1_common_g1') or []) if details.get('parent_gp1_common_g1') else "aucune"),
                "- G1 communes parent↔GP2 : " + (", ".join(details.get('parent_gp2_common_g1') or []) if details.get('parent_gp2_common_g1') else "aucune"),
                "",
            ]
            lines.extend(render_common_components(row, include_race=True))
            return "\n".join(lines)

        def render_future_detail(row: dict[str, object]) -> str:
            affinity_detail = ((row.get("component_details") or {}).get("affinity") or {})
            lines = [
                f"Candidat : {format_identity(row)}",
                f"GP actuels : utilisés pour le support de génération des whites, mais pas comme ancêtres directs de l'Ace final : {row.get('grandparent_1') or '-'} / {row.get('grandparent_2') or '-'}",
                f"Stats : {self._format_stats(row.get('stats'))}",
                "",
                "Affinité du futur grand-parent :",
                f"- Pair(Ace, parent à produire), constante : {row.get('future_parent_base_affinity') if row.get('future_parent_base_affinity') is not None else '-'}",
                f"- Contribution du candidat = triple(Ace, parent cible, candidat) : {row.get('affinity_raw', 0)}",
                f"- Base future de la branche : {row.get('future_branch_base_total', row.get('affinity_raw', 0))}",
                f"- Score d'affinité après seuil/plafond : {float((row.get('components') or {}).get('affinity') or 0):.2f}",
                f"- Même personnage que l'Ace : {'oui — contribution de compatibilité forcée à 0' if affinity_detail.get('same_as_ace') else 'non'}",
                "- Le potentiel G1 est séparé : il ne devient un bonus réel que si le nouveau parent gagne aussi ces G1.",
                f"- G1 différentes gagnées : {row.get('g1_count', 0)}",
                "",
            ]
            lines.extend(render_common_components(row, include_race=False))
            return "\n".join(lines)

        header = ttk.Frame(window, padding=10)
        header.pack(fill=tk.X)
        ace = result.ace
        profile = result.profile
        future_parent = result.future_parent
        ttk.Label(
            header,
            text=f"Ace : {ace['card_name']} — {profile['surface']} / {profile['distance']} / {profile['style']}",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")
        if future_parent:
            ttk.Label(
                header,
                text=f"Parent à produire : {future_parent['card_name']} — triple exact Ace × parent cible × candidat.",
            ).pack(anchor="w", pady=(2, 0))
        parent_weights = (result.scoring_weights or {}).get("parent_final") or {}
        future_weights = (result.scoring_weights or {}).get("future_grandparent") or {}
        ttk.Label(
            header,
            text=(
                "Score parent final : "
                + " + ".join(f"{component_labels.get(key, key)} {100 * float(value):.0f}%" for key, value in parent_weights.items())
            ),
            foreground="#555555",
        ).pack(anchor="w", pady=(4, 0))
        ttk.Label(
            header,
            text=(
                "Score futur grand-parent : "
                + " + ".join(f"{component_labels.get(key, key)} {100 * float(value):.0f}%" for key, value in future_weights.items())
            ),
            foreground="#555555",
        ).pack(anchor="w", pady=(2, 0))
        ttk.Label(
            header,
            text="Clique sur une ligne : le panneau inférieur détaille chaque contribution, notamment toutes les white skills.",
            foreground="#666666",
        ).pack(anchor="w", pady=(2, 0))

        notebook = ttk.Notebook(window)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        def add_tree(title: str, columns: tuple[str, ...], headings: dict[str, str], row_payloads: list[dict[str, object]], row_values: list[tuple[object, ...]], detail_renderer) -> None:
            frame = ttk.Frame(notebook)
            notebook.add(frame, text=title)
            frame.rowconfigure(0, weight=1)
            frame.rowconfigure(1, weight=1)
            frame.columnconfigure(0, weight=1)

            tree_frame = ttk.Frame(frame)
            tree_frame.grid(row=0, column=0, sticky="nsew")
            tree_frame.rowconfigure(0, weight=1)
            tree_frame.columnconfigure(0, weight=1)
            tree = ttk.Treeview(tree_frame, columns=columns, show="headings")
            vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
            hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=tree.xview)
            tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
            tree.grid(row=0, column=0, sticky="nsew")
            vsb.grid(row=0, column=1, sticky="ns")
            hsb.grid(row=1, column=0, sticky="ew")

            for column in columns:
                tree.heading(column, text=headings.get(column, column))
                width = 100
                if column in {"parent_1", "parent_2", "parent", "candidate"}:
                    width = 320
                tree.column(column, width=width, anchor="w" if width >= 220 else "center")

            row_map: dict[str, dict[str, object]] = {}
            for index, (payload, values) in enumerate(zip(row_payloads, row_values), 1):
                iid = str(index)
                row_map[iid] = payload
                tree.insert("", tk.END, iid=iid, values=values)

            detail = scrolledtext.ScrolledText(frame, wrap=tk.WORD, height=20, font=("Consolas", 10), state=tk.DISABLED)
            detail.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

            def update_detail(_event=None):
                selection = tree.selection()
                if not selection:
                    return
                payload = row_map.get(selection[0])
                if payload is None:
                    return
                detail.configure(state=tk.NORMAL)
                detail.delete("1.0", tk.END)
                detail.insert(tk.END, self._tr(detail_renderer(payload)))
                detail.configure(state=tk.DISABLED)
                detail.see("1.0")

            tree.bind("<<TreeviewSelect>>", update_detail)
            if row_map:
                first = next(iter(row_map))
                tree.selection_set(first)
                update_detail()

        pair_payloads = list(result.top_parent_pairs)
        pair_values = [(
            rank, f"{row['score']:.2f}", format_identity(row['parent_1']), format_identity(row['parent_2']),
            row['affinity']['base'], row['affinity']['g1_bonus'], row['affinity']['total'],
            f"{row['components']['pink']:.1f}", f"{row['components']['white_skill']:.1f}", f"{row['components']['blue']:.1f}"
        ) for rank, row in enumerate(pair_payloads, 1)]
        add_tree(
            "Paires finales",
            ("rank", "score", "parent_1", "parent_2", "aff_base", "g1_bonus", "affinity", "pink", "white", "blue"),
            {"rank": "#", "score": "Score", "parent_1": "Parent 1", "parent_2": "Parent 2", "aff_base": "Aff. base", "g1_bonus": "+G1", "affinity": "Aff. totale", "pink": "Roses", "white": "Whites", "blue": "Bleues"},
            pair_payloads, pair_values, render_pair_detail,
        )

        branch_payloads = list(result.top_parent_candidates)
        branch_values = [(
            rank, f"{row['score']:.2f}", format_identity(row), row['affinity']['base'], row['affinity']['g1_bonus'], row['affinity']['total'],
            f"{row['components']['pink']:.1f}", f"{row['components']['white_skill']:.1f}", f"{row['components']['blue']:.1f}"
        ) for rank, row in enumerate(branch_payloads, 1)]
        add_tree(
            "Lignées candidates",
            ("rank", "score", "parent", "aff_base", "g1_bonus", "affinity", "pink", "white", "blue"),
            {"rank": "#", "score": "Score", "parent": "Parent", "aff_base": "Aff. base", "g1_bonus": "+G1", "affinity": "Aff. branche", "pink": "Roses", "white": "Whites", "blue": "Bleues"},
            branch_payloads, branch_values, render_branch_detail,
        )

        future_payloads = list(result.top_future_grandparents)
        future_values = [(
            rank, f"{row['score']:.2f}", format_identity(row), row['affinity_raw'], row.get('future_branch_base_total', 0), row['g1_count'],
            f"{row['components']['affinity']:.1f}", f"{row['components']['pink']:.1f}", f"{row['components']['white_skill']:.1f}",
            f"{row['components'].get('white_generation', 0.0):.1f}", f"{row['components']['blue']:.1f}"
        ) for rank, row in enumerate(future_payloads, 1)]
        add_tree(
            "Futurs grands-parents",
            ("rank", "score", "candidate", "triple", "branch_total", "g1", "aff_score", "pink", "white", "generation", "blue"),
            {"rank": "#", "score": "Score", "candidate": "Candidat", "triple": "Triple", "branch_total": "Base branche", "g1": "G1 diff.", "aff_score": "Score aff.", "pink": "Roses", "white": "Whites propres", "generation": "Bonus lignée", "blue": "Bleues"},
            future_payloads, future_values, render_future_detail,
        )
        self._apply_translations(window)

    def _drain_queue(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "progress":
                    percent, status = payload  # type: ignore[misc]
                    self.progress_var.set(float(percent))
                    self._set_status(status)
                elif kind == "json_path":
                    self.json_var.set(str(payload))
                    self._refresh_local_veteran_options(show_errors=False)
                    self._save_current_config()
                elif kind == "uma_moe_response_path":
                    self.uma_moe_response_var.set(str(payload))
                elif kind == "uma_moe_uql":
                    self.uma_moe_query_var.set(str(payload).replace("\n", " "))
                    self._save_current_config()
                elif kind == "done":
                    result = payload
                    self.progress_var.set(100)
                    self._set_status(f"Terminé — {result.veteran_count} vétérans liés.")
                    self.last_output_dir = result.json_path.parent
                    self._append_log(f"JSON : {result.json_path}")
                    self._append_log(f"CSV : {result.csv_path}")
                    self._append_log(f"Rapport : {result.report_path}")
                    self._append_log(f"Skills/conditions : {result.skills_catalog_path}")
                    self._append_log(f"Types de conditions : {result.condition_types_path}")
                    self._append_log(f"Template de poids : {result.weights_template_path}")
                    self._append_log(f"Race factors + green skills : {result.race_factor_skills_path}")
                    if (
                        result.unresolved_factor_ids
                        or result.unresolved_card_ids
                        or result.g1_validation_mismatch_count
                    ):
                        self._append_log(
                            "Attention : le rapport contient des éléments non résolus "
                            "ou des divergences de validation."
                        )
                    self._set_running(False)
                elif kind == "catalog_done":
                    result = payload
                    self.progress_var.set(100)
                    self._set_status(
                        f"Catalogue terminé — {result.skill_count} skills, "
                        f"{result.condition_variable_count} variables."
                    )
                    self.last_output_dir = result.skills_path.parent
                    self._append_log(f"Skills/conditions : {result.skills_path}")
                    self._append_log(f"Types de conditions : {result.condition_types_path}")
                    self._append_log(f"Template de poids : {result.weights_template_path}")
                    self._append_log(f"Race factors + green skills : {result.race_factor_skills_path}")
                    self._set_running(False)
                elif kind == "simulator_done":
                    result = payload
                    self.progress_var.set(100)
                    self._set_status(
                        f"Poids terminés — {result.simulated_skill_count}/{result.skill_count} "
                        f"skills simulées, {result.review_item_count} à vérifier."
                    )
                    self.last_output_dir = result.weights_path.parent
                    self._append_log(f"Poids simulateur : {result.weights_path}")
                    self._append_log(f"File de revue : {result.review_queue_path}")
                    self._append_log(f"Synthèse CSV : {result.summary_csv_path}")
                    if result.course_weights_path:
                        self._append_log(
                            f"Poids par course : {result.course_weights_path}"
                        )
                    self._append_log(
                        f"Cellules ajustées manuellement : "
                        f"{result.manually_adjusted_cell_count}"
                    )
                    self._append_log(
                        f"Cellules avec bonus de positionnement : "
                        f"{result.positioning_adjusted_cell_count}"
                    )
                    self._append_log(
                        f"Presets de course : {result.course_preset_count}"
                    )
                    self._set_running(False)
                elif kind == "optimizer_done":
                    result = payload
                    self.progress_var.set(100)
                    self._set_status(
                        f"Optimisation terminée — {len(result.top_parent_pairs)} paires affichées."
                    )
                    self.last_output_dir = result.rankings_json_path.parent
                    self._append_log(f"Classement JSON : {result.rankings_json_path}")
                    self._append_log(f"Paires : {result.parent_pairs_csv_path}")
                    self._append_log(f"Lignées : {result.parent_candidates_csv_path}")
                    self._append_log(f"Futurs grands-parents : {result.future_grandparents_csv_path}")
                    self._set_running(False)
                    self._show_optimizer_results(result)
                elif kind == "transfer_helper_done":
                    result = payload
                    self.progress_var.set(100)
                    self._set_status(
                        f"Transfer Helper terminé — {result.safe_transfer_count} transfert(s) sûr(s), "
                        f"{result.review_count} à examiner, "
                        f"{result.likely_keep_count} probablement à conserver."
                    )
                    self.last_output_dir = result.report_json_path.parent
                    self._append_log(f"Rapport Transfer Helper : {result.report_json_path}")
                    self._append_log(f"CSV Transfer Helper : {result.candidates_csv_path}")
                    self._append_log(f"Résumé Transfer Helper : {result.summary_txt_path}")
                    self._set_running(False)
                    self._show_transfer_helper_results(result)
                elif kind == "uma_moe_done":
                    result = payload
                    self.progress_var.set(100)
                    self._set_status(f"Recherche uma.moe terminée — {result.result_count} paires classées.")
                    self.last_output_dir = result.rankings_json_path.parent
                    self._append_log(f"Classement uma.moe : {result.rankings_json_path}")
                    self._append_log(f"CSV uma.moe : {result.rankings_csv_path}")
                    self._append_log(f"Réponse brute : {result.raw_response_path}")
                    self._append_log(f"Diagnostics : {result.diagnostics_path}")
                    self._set_running(False)
                    self._show_uma_moe_results(result)
                elif kind == "error":
                    message, details = payload  # type: ignore[misc]
                    self._append_log(details)
                    self.progress_var.set(0)
                    self._set_status("Échec — consulter le journal.")
                    self._set_running(False)
                    self._show_error(message)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_queue)

    def _open_output(self) -> None:
        path = self.last_output_dir or Path(self.output_var.get().strip()).expanduser()
        if path.is_dir():
            open_path(path)
        else:
            self._show_info("Aucun dossier de sortie disponible.")

    def _on_close(self) -> None:
        self._save_current_config()
        self.root.destroy()


def run_cli(args: argparse.Namespace) -> int:
    try:
        if args.transfer_helper:
            if not args.json:
                raise TransferHelperError("--transfer-helper requiert --json.")
            linked = link_veterans(
                args.master,
                args.json,
                args.output,
                logger=lambda message: print(message, flush=True),
            )
            default_course_overrides = app_base_dir() / "default_course_overrides.json"
            course_overrides = args.course_overrides or (
                str(default_course_overrides) if default_course_overrides.is_file() else None
            )
            default_priorities = read_json_object(default_skill_priorities_path())
            effective_priorities = default_priorities
            if args.skill_priorities:
                custom_priorities = read_json_object(args.skill_priorities)
                effective_priorities = deep_merge(default_priorities, custom_priorities)
            validate_skill_priorities_config(effective_priorities)
            priorities = write_json_object(
                Path(args.output).expanduser().resolve() / "active_skill_priorities.json",
                effective_priorities,
            )
            manual_weights = generate_manual_skill_weights(
                linked.skills_catalog_path,
                priorities,
                args.output,
                course_overrides_path=course_overrides,
                logger=lambda message: print(message, flush=True),
            )
            default_payload = read_json_object(default_scoring_path())
            effective_payload = default_payload
            if args.scoring_config:
                custom_payload = read_json_object(args.scoring_config)
                effective_payload = deep_merge(default_payload, custom_payload)
            validate_scoring_config(effective_payload)
            scoring = write_json_object(
                Path(args.output).expanduser().resolve() / "active_parent_scoring.json",
                effective_payload,
            )
            result = analyze_transfer_candidates(
                args.master,
                linked.json_path,
                manual_weights.weights_path,
                linked.race_factor_skills_path,
                linked.skills_catalog_path,
                args.output,
                course_weights_path=manual_weights.course_weights_path,
                scoring_config_path=scoring,
                logger=lambda message: print(message, flush=True),
            )
            print(f"Rapport : {result.report_json_path}")
            print(f"CSV : {result.candidates_csv_path}")
            print(f"Résumé : {result.summary_txt_path}")
            print(
                f"Verdicts : {result.safe_transfer_count} transfert(s) sûr(s), "
                f"{result.review_count} à examiner, "
                f"{result.likely_keep_count} probablement à conserver, "
                f"{result.keep_count} à conserver."
            )
            return 0
        if args.rank_parents:
            if not args.json or not args.ace_card_id or not args.future_parent_card_id:
                raise OptimizerError("--rank-parents requiert --json, --ace-card-id et --future-parent-card-id.")
            linked = link_veterans(
                args.master,
                args.json,
                args.output,
                logger=lambda message: print(message, flush=True),
            )
            default_course_overrides = app_base_dir() / "default_course_overrides.json"
            course_overrides = args.course_overrides or (
                str(default_course_overrides) if default_course_overrides.is_file() else None
            )
            default_priorities = read_json_object(default_skill_priorities_path())
            effective_priorities = default_priorities
            if args.skill_priorities:
                custom_priorities = read_json_object(args.skill_priorities)
                effective_priorities = deep_merge(default_priorities, custom_priorities)
            validate_skill_priorities_config(effective_priorities)
            priorities = write_json_object(
                Path(args.output).expanduser().resolve() / "active_skill_priorities.json",
                effective_priorities,
            )
            manual_weights = generate_manual_skill_weights(
                linked.skills_catalog_path,
                priorities,
                args.output,
                course_overrides_path=course_overrides,
                logger=lambda message: print(message, flush=True),
            )
            default_payload = read_json_object(default_scoring_path())
            effective_payload = default_payload
            if args.scoring_config:
                custom_payload = read_json_object(args.scoring_config)
                effective_payload = deep_merge(default_payload, custom_payload)
            validate_scoring_config(effective_payload)
            scoring = write_json_object(
                Path(args.output).expanduser().resolve() / "active_parent_scoring.json",
                effective_payload,
            )
            result = optimize_parents(
                args.master,
                linked.json_path,
                manual_weights.weights_path,
                linked.race_factor_skills_path,
                linked.skills_catalog_path,
                args.output,
                ace_card_id=args.ace_card_id,
                future_parent_card_id=args.future_parent_card_id,
                surface=args.surface,
                distance=args.distance,
                style=args.style,
                course_weights_path=manual_weights.course_weights_path,
                course_key=args.course_key,
                course_conditions={
                    key: value for key, value in {
                        "track_id": args.track_id,
                        "rotation": args.rotation,
                        "season": ([1, 5] if args.season == 1 else args.season),
                        "weather": args.weather,
                        "ground_condition": args.ground_condition,
                    }.items() if value is not None
                },
                scoring_config_path=scoring,
                top_n=args.top,
                logger=lambda message: print(message, flush=True),
            )
            print(f"Classements : {result.rankings_json_path}")
            print(f"Paires : {result.parent_pairs_csv_path}")
            print(f"Futurs grands-parents : {result.future_grandparents_csv_path}")
            return 0
        if args.catalog_only or args.umalator_batch:
            catalog = generate_skill_catalogs(
                args.master,
                args.output,
                logger=lambda message: print(message, flush=True),
            )
            print(f"Skills/conditions : {catalog.skills_path}")
            print(f"Types de conditions : {catalog.condition_types_path}")
            print(f"Template de poids : {catalog.weights_template_path}")
            print(f"Race factors : {catalog.race_factor_skills_path}")
            if args.umalator_batch:
                adjustments = app_base_dir() / "default_manual_adjustments.json"
                default_course_overrides = app_base_dir() / "default_course_overrides.json"
                course_overrides = args.course_overrides or (
                    str(default_course_overrides)
                    if default_course_overrides.is_file()
                    else None
                )
                result = generate_simulator_weights(
                    args.umalator_batch,
                    catalog.skills_path,
                    catalog.weights_template_path,
                    args.output,
                    manual_adjustments_path=(adjustments if adjustments.is_file() else None),
                    course_overrides_path=course_overrides,
                    logger=lambda message: print(message, flush=True),
                )
                print(f"Poids simulateur : {result.weights_path}")
                print(f"File de revue : {result.review_queue_path}")
                print(f"Synthèse CSV : {result.summary_csv_path}")
                if result.course_weights_path:
                    print(f"Poids par course : {result.course_weights_path}")
            return 0
        result = link_veterans(
            args.master,
            args.json,
            args.output,
            logger=lambda message: print(message, flush=True),
        )
    except (LinkerError, OptimizerError, TransferHelperError, OSError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:  # type: ignore[name-defined]
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    print(f"JSON : {result.json_path}")
    print(f"CSV : {result.csv_path}")
    print(f"Rapport : {result.report_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--master", help="Chemin de master.mdb")
    parser.add_argument("--json", help="Chemin de data.json")
    parser.add_argument("--output", help="Dossier de sortie", default="output")
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Mode ligne de commande.",
    )
    parser.add_argument(
        "--catalog-only",
        action="store_true",
        help="Génère uniquement les catalogues skills/conditions depuis le MDB.",
    )
    parser.add_argument(
        "--umalator-batch",
        help="Mode legacy : importe un batch Skill Chart Umalator v2 pour diagnostic. Le classement utilise les poids manuels.",
    )
    parser.add_argument(
        "--course-overrides",
        help="Fichier JSON facultatif d'overrides liés au tracé exact.",
    )
    parser.add_argument("--rank-parents", action="store_true", help="Lance le classement complet des lignées.")
    parser.add_argument(
        "--transfer-helper",
        action="store_true",
        help="Analyse les vétérans locaux et identifie les doublons strictement dominés.",
    )
    parser.add_argument("--ace-card-id", type=int, help="Card ID de l'Ace cible.")
    parser.add_argument("--future-parent-card-id", type=int, help="Card ID du parent à produire pour le calcul exact des futurs grands-parents.")
    parser.add_argument("--track-id", type=int, help="Hippodrome cible (track_id MDB).")
    parser.add_argument("--rotation", type=int, choices=(1, 2), help="1=droite, 2=gauche.")
    parser.add_argument("--season", type=int, choices=(1, 2, 3, 4), help="1=printemps, 2=été, 3=automne, 4=hiver.")
    parser.add_argument("--weather", type=int, choices=(1, 2, 3, 4), help="1=soleil, 2=nuageux, 3=pluie, 4=neige.")
    parser.add_argument("--ground-condition", type=int, choices=(1, 2, 3, 4), help="1=firm, 2=good, 3=soft, 4=heavy.")
    parser.add_argument("--surface", choices=("turf", "dirt"), default="turf")
    parser.add_argument("--distance", choices=("sprint", "mile", "medium", "long"), default="medium")
    parser.add_argument("--style", choices=("front_runner", "pace_chaser", "late_surger", "end_closer"), default="pace_chaser")
    parser.add_argument("--course-key", help="Preset exact de course, par exemple cm15_hanshin_2200_turf.")
    parser.add_argument(
        "--scoring-config",
        help="Profil JSON de pondération complet ou surcharges à fusionner avec le profil par défaut.",
    )
    parser.add_argument(
        "--skill-priorities",
        help="Priorités white skills complètes ou partielles à fusionner avec le profil par défaut.",
    )
    parser.add_argument("--top", type=int, default=30, help="Nombre de résultats détaillés dans le JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.cli:
        if not args.master:
            print("--master est requis en mode CLI.", file=sys.stderr)
            return 2
        if not args.catalog_only and not args.umalator_batch and not args.rank_parents and not args.transfer_helper and not args.json:
            print(
                "--json est requis sauf avec --catalog-only ou --umalator-batch.",
                file=sys.stderr,
            )
            return 2
        return run_cli(args)
    root = tk.Tk()
    Application(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
