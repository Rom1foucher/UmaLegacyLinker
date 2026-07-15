# Third-party tools and services

## Veteran extractors

Uma Legacy Linker does not bundle, modify or redistribute an extractor.

### UmaExtractor

Project: [xancia/UmaExtractor](https://github.com/xancia/UmaExtractor)

The application can currently launch a separately installed `umaextractor.exe` with its CLI option and consume the resulting `data.json`.

### umadump

Project: [Werseter/umadump](https://github.com/Werseter/umadump)

umadump is a newer runtime memory reader and JSON exporter. It validates declared IL2CPP wrapper layouts against game metadata and exposes additional runtime data through extensible export fields.

Direct umadump integration is planned as the preferred replacement for the current UmaExtractor launcher. It is not wired into Uma Legacy Linker yet.

Software that reads a running game's memory is used at the user's discretion. Review each project's documentation and warnings before use.

## uma.moe

Project: [uma.moe](https://uma.moe/)

Uma Legacy Linker can query the public API or rank an imported JSON response. No uma.moe code or dataset is bundled with the application. The service and its data may change independently from this project.
