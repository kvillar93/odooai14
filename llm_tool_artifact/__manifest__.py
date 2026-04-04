# -*- coding: utf-8 -*-
{
    "name": "LLM Tool Artefactos",
    "summary": "Gráficos, Excel, PDF y Word desde tools de IA",
    "version": "16.0.1.0.0",
    "depends": ["llm_tool", "web"],
    "external_dependencies": {
        "python": ["xlsxwriter", "matplotlib"],
    },
    "data": [
        "data/llm_tool_artifact_data.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
}
