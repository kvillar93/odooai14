# Fal.ai Provider for Odoo LLM Integration

This module integrates Fal.ai's API with the Odoo LLM framework, enabling high-performance access to a wide variety of generative AI models including image, video, and audio generation.

## Features

- Connect to Fal.ai API with proper authentication
- Support for multiple generative AI models hosted on Fal.ai
- Text-to-image, text-to-video, and audio synthesis capabilities
- Automatic model discovery and filtering
- Async-friendly requests for long-running tasks (e.g. image/video generation)

## Configuration

1. Install the module
2. Navigate to **LLM > Configuration > Providers**
3. Create a new provider and select "Fal.ai" as the provider type
4. Enter your Fal.ai API key
5. Click "Fetch Models" to import available models

## Current Status

This module is under active development. Core functionality for connecting to Fal.ai and invoking models is working. Image and video generation features are prioritized; support for additional modalities will follow.

## Technical Details

This module extends the base LLM integration framework with Fal.ai-specific logic:

- Implements Fal.ai API client with token-based authentication
- Maps Fal.ai model schemas to the Odoo LLM format
- Supports async job polling for long-running inference tasks
- Graceful error handling and response normalization

## Dependencies

- llm (LLM Integration Base)
- aiohttp (for async HTTP requests, if needed for async inference)

## License

LGPL-3
