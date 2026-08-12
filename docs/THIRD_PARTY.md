# Third-party tools and services

## Veteran extractors

Uma Legacy Linker does not bundle, modify or redistribute an extractor.

### UmaExtractor

Project: [xancia/UmaExtractor](https://github.com/xancia/UmaExtractor)

The application can launch a separately installed `umaextractor.exe`, then
consume the resulting `data.json`.

### umadump

Project: [Werseter/umadump](https://github.com/Werseter/umadump)

umadump is a runtime memory reader and JSON exporter. It validates declared
IL2CPP wrapper layouts against game metadata and exposes additional runtime
data through extensible export fields. Uma Legacy Linker can launch it once
with `--rerun-mode once` from the selected output directory, then consume its
`trained_chara_data.json`.

The launcher selects the backend from the executable or script name. Neither
extractor is bundled with the application.

Software that reads a running game's memory is used at the user's discretion. Review each project's documentation and warnings before use.

## uma.moe

Project: [uma.moe](https://uma.moe/)

Uma Legacy Linker can query the public API or rank an imported JSON response. No uma.moe code or dataset is bundled with the application. The service and its data may change independently from this project.

## Community inheritance reference

The inheritance-probability model is documented against
[Crazyfellow's Parenting/Gene guide](https://docs.google.com/document/d/1Q3IJKbtkplmuY-PAJMNjYiLtasv0eU0aIBEqp8_C3tg/edit?tab=t.0).
That guide attributes the lower observed grandparent proc rate to each carrier's smaller individual
compatibility calculation, not to an additional fixed grandparent multiplier. Uma Legacy Linker
therefore applies the documented type/star base rate multiplied by the carrier's individual
compatibility factor. See [`SCORING.md`](SCORING.md) for the exact application model and configured
rates.

The guide and its underlying community research are credited as references only; their text,
images and datasets are not bundled with this project.
