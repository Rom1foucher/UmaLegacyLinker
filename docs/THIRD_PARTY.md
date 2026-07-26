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
