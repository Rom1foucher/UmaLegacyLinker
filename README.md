<div align="center">

<img src="resources/branding/app.png" alt="Uma Legacy Linker icon" width="80">

# Uma Legacy Linker

**Compare inheritance lineages for Umamusume: Pretty Derby using your veterans and uma.moe.**

[![Release](https://img.shields.io/github/v/release/Rom1foucher/UmaLegacyLinker?include_prereleases&label=release)](https://github.com/Rom1foucher/UmaLegacyLinker/releases)
[![Windows build](https://github.com/Rom1foucher/UmaLegacyLinker/actions/workflows/release-windows.yml/badge.svg)](https://github.com/Rom1foucher/UmaLegacyLinker/actions/workflows/release-windows.yml)
[![License: GPL-3.0-only](https://img.shields.io/badge/license-GPL--3.0--only-blue)](LICENSE)

Windows desktop application · English and French interface

[Download](#quick-start) · [Features](#features) · [Documentation](#documentation)

</div>

Choose the Ace you want to train, the course and your running style. Uma Legacy Linker ranks parent pairs and future grandparents, with a breakdown of the Sparks, aptitude probabilities, affinity and G1 compatibility behind each result.

<p align="center">
  <img src="docs/media/lineage.gif" alt="Six-member lineage view" width="900">
</p>

## Quick start

1. Open the [latest release](https://github.com/Rom1foucher/UmaLegacyLinker/releases/latest) and download `UmaLegacyLinkerQt-win64.zip`. Check the release notes and prerelease label for that version.
2. Extract the **whole ZIP** and run `UmaLegacyLinkerQt.exe`. Keep its runtime files together; Python is included.
3. Obtain your current game database, `master.mdb`, and export your veterans with [umadump](https://github.com/Werseter/umadump) or [UmaExtractor](https://github.com/xancia/UmaExtractor), following that tool's instructions.
4. On **Data**, select the MDB, the export (`trained_chara_data.json` or `data.json`) and an output directory. Select **Link an existing export**.
5. Open **Search**, set your target and race profile, choose a result tab and run the search.

These steps support local ranking without an API key. **Extract my collection** can also launch a separately configured extractor from the Data page. Relink after replacing the MDB or collection export.

This README describes the current source tree; published builds and prereleases are described by their own release notes.

### uma.moe access

To create a key for remote searches:

1. Sign in to [uma.moe](https://uma.moe/).
2. Open your [account settings](https://uma.moe/settings) and scroll to **API Keys** near the bottom.
3. Under **Create a new key**, enter a name such as `Uma Legacy Linker` and select **Create Key**.
4. Copy the key into **Settings → API key** in Uma Legacy Linker and save the settings.

The default API URL is `https://uma.moe/api`. **Remember key** stores it separately from the general configuration, encrypted with Windows DPAPI on Windows. Other platforms use a local file with restricted permissions, without encryption. `UMA_MOE_API_KEY` is also supported and takes precedence when the app starts.

Retrieval is capped at **2,000 candidates per search**. Saved responses can be imported for ranking without repeating the request. Check that a remote parent's Friend ID is still available in game before starting a career.

## Features

### Search and inspect lineages

| Search | Use |
| --- | --- |
| Final parent pairs | Compare two local parents and their four grandparents for the Ace |
| Individual parents | Evaluate a parent branch as one half of a lineage |
| Future grandparents | Find local material for producing a future parent |
| Remote parents | Pair local parents with uma.moe candidates |
| Remote GPs | Pair a local GP with remote candidates, with a local-only alternative |

Champion Meeting presets and generic Team Trials profiles fill the race context; conditions remain editable. Fix a parent or constrain the candidate pool when part of your lineage is already chosen.

Inspect factor sources, estimated inheritance probabilities and G1 schedules. Compare two candidates side by side, or compare the current result with its retained predecessor. Rankings and diagnostics are saved as JSON and CSV.

<p align="center">
  <img src="docs/media/search-results.png" alt="Lineage Search results with candidate details" width="900">
</p>

The G1 planner shows Standard schedules with mandatory character objectives and a Trackblazer variant without them. Generic GP-pair searches use a fast estimate followed by exact shortlist rescoring; this can miss a pair outside the shortlist. An exhaustive ranking mode is available. See the [scoring model](docs/SCORING.md#104-generic-gp-screening-and-exact-reranking) for scope and limits.

<p align="center">
  <img src="docs/media/optimal-planning.png" alt="Proposed optimal G1 training plan" width="900">
</p>

### Adjust the scoring

The **Weights** page edits structural scoring weights and White Skill priorities over bundled defaults. Change the emphasis on aptitude targets, Blue Sparks, skills, affinity or G1 value to suit your build. The editor previews each weight's effective share within its group.

Save a profile and rerun the search to apply it. Effective profiles are written as `active_parent_scoring.json` and `active_skill_priorities.json` in the output directory. Bundled priorities are a starting point; they do not guarantee a competitive build or an inheritance outcome.

<p align="center">
  <img src="docs/media/weights.gif" alt="Changing the Blue Spark weight and previewing its normalised share" width="620">
</p>

### Transfer Helper (work in progress)

> [!WARNING]
> Review the evidence before transferring a veteran in game. Transfer Helper is a work in progress: its verdicts depend on the evaluated contexts and configured thresholds. It never transfers veterans or modifies the source export.

The helper selects a collection of same-costume copies that covers useful parent and GP roles while preserving protected inheritance assets. The default screen is one four-column list in descending in-game score order: score, Uma, verdict and inline reason. Use **Transfer** for the recommended mass-transfer review or **Keep** for retained, protected and uncertain copies. Search by name or score; hover a reason for its evidence, click a cited score to select that retained copy, or right-click a row for **Audit…**.

The page menu holds report history, analysis scope and the output folder. Reports older than format 12 show a rerun prompt; role-level evidence is not reconstructed approximately. The scope can also protect selected White Spark loops by keeping the top configured number of local carriers, ranked by generation presence, direct ownership, and the portfolio already selected for performance. Click a reason or press Enter to open the explanation panel. Its role list shows the tightest roles first; the shared score band marks the solver's regret zone, and aligned sparks show only factors relevant to that role. **Arbre** opens the filtered lineage view. Exhaustive analysis is the default. A bounded exact portfolio search reports whether the retained count is proven minimal. Protected copies remain ineligible for transfer. Upcoming CMs follow the Global MDB calendar; unknown dates are shown explicitly.
| Verdict | Meaning |
| --- | --- |
| **Protected** | Preserved because of an in-game lock, memo or active White Loop use; still analysed |
| **Keep** | Required by the selected collection portfolio |
| **Redundant in the model** | Covered by retained copies collectively, without a verified strict individual replacement |
| **Equivalent in the model** | One retained same-costume, same-Unique replacement passes the model checks; manual cost/racing review still required |
| **Review** | Portfolio coverage could not be established |

## Data and network use

The MDB resolves game IDs, factors and race data. Exporters are separate tools that access the running game to produce the collection file; they have their own requirements. Linking and scoring read the supplied files locally and leave the originals unchanged.

Remote searches contact uma.moe. The UI can also download optional GameTora artwork, cached locally and controllable from the lineage inspector. Local scoring does not require those images or a network connection.

## Documentation

| Document | Contents |
| --- | --- |
| [User guide](docs/USER_GUIDE.md) | Setup, workflows, result states and troubleshooting |
| [Scoring](docs/SCORING.md) | Formulas, probabilities and model limits |
| [Scoring configuration](docs/SCORING_CONFIGURATION.md) | Weights, overrides and merge rules |
| [Architecture](docs/ARCHITECTURE.md) | Modules, processes, execution settings and persistence |
| [Releasing](docs/RELEASING.md) | Tests, Windows packaging and checksum verification |
| [Third-party components](docs/THIRD_PARTY.md) | Data sources, external tools and licence notices |
| [Changelog](CHANGELOG.md) | Version history |

<details>
<summary>Run from source or use the CLI</summary>

Python 3.12 is used for the Windows build. From a checkout with that interpreter:

```powershell
git clone https://github.com/Rom1foucher/UmaLegacyLinker.git
cd UmaLegacyLinker
py -m pip install -r requirements-qt.txt
py qt_app.py
```

`run.bat` starts the same interface. Headless linking, catalogue generation, local ranking and Transfer Helper are available through:

```powershell
py cli.py --help
```

The backend lives in `uma_legacy_linker/`, the desktop UI in `ui_qt/`, and bundled profiles and icons in `resources/`. Build instructions and validation commands are in [Releasing](docs/RELEASING.md).

</details>

For an unexpected ranking or crash, [open an issue](https://github.com/Rom1foucher/UmaLegacyLinker/issues/new) with the application version, selected workflow, race context and relevant diagnostics. Remove API keys and personal identifiers before sharing files.

## Credits

Thanks to [uma.moe](https://uma.moe/) for remote parent search, [umadump](https://github.com/Werseter/umadump) and [UmaExtractor](https://github.com/xancia/UmaExtractor) for collection exports, and [GameTora](https://gametora.com/umamusume) for reference material and optional artwork. Upstream tools and community inheritance references are listed in [Third-party components](docs/THIRD_PARTY.md).

Independent community project, not affiliated with or endorsed by Cygames. Umamusume: Pretty Derby and related assets belong to their respective rights holders. Game databases, collection exports, remote datasets and extractor executables are not bundled. Documentation recordings may show game artwork; the application does not bundle the downloaded artwork cache.

## License

Uma Legacy Linker is free software licensed under the [GNU General Public License, version 3](LICENSE) (`GPL-3.0-only`). You may use, modify and redistribute it under those terms. It is provided without warranty.

Third-party components retain their own licences; game artwork and other third-party material are not relicensed by this project. See [Third-party components](docs/THIRD_PARTY.md).
