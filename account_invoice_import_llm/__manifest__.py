{
    "name": "Account Invoice Import LLM",
    "summary": "AI-powered invoice analysis assistant with OCR document parsing",
    "description": """
        Intelligent invoice assistant that helps analyze vendor bills and invoices using AI.
        Features document parsing with OCR, automated data extraction, and smart invoice validation.
    """,
    "category": "Accounting/AI",
    "version": "16.0.1.0.3",
    "depends": [
        "account_invoice_import",  # OCA invoice import wizard (fallback_parse_pdf_invoice)
        "llm_assistant",  # Includes llm, llm_thread, llm_tool
        "llm_mistral",  # Mistral provider (for OCR)
    ],
    "author": "Apexive Solutions LLC",
    "website": "https://github.com/apexive/odoo-llm",
    "data": [
        "data/llm_prompt_invoice_data.xml",
        "data/llm_assistant_data.xml",
        "views/account_move_views.xml",
    ],
    "license": "AGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
    "pre_init_hook": "pre_init_hook",
    "images": [
        "static/description/banner.jpeg",
    ],
}
