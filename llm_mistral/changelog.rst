16.0.1.0.3 (2026-01-14)
~~~~~~~~~~~~~~~~~~~~~~~

* [ADD] Added mistral_get_default_ocr_model() method for unified OCR model selection
* [IMP] Single source of truth for OCR model selection across all consumers

16.0.1.0.2 (2026-01-07)
~~~~~~~~~~~~~~~~~~~~~~~

* [REM] Removed provider data file - users now create providers manually
* [IMP] Provider data is now user-owned and survives module uninstall

16.0.1.0.1 (2025-11-17)
~~~~~~~~~~~~~~~~~~~~~~~

* [IMP] Moved _determine_model_use() override from wizard to provider for OCR support
* [IMP] Reordered capability detection in _openai_parse_model(): string matching before API capabilities
* [REM] Removed wizards/ directory (no longer needed)
* [ADD] Comprehensive docstrings documenting the override pattern

16.0.1.0.0 (2025-01-02)
~~~~~~~~~~~~~~~~~~~~~~~

* [INIT] Initial release of the module
