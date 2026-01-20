# Change Log

Release v1.2.1
- Upgraded llama-3.3-70b-instruct NIM from version 1.13.1 to 1.14.0
- Aligned Helm values and referenced Docker image tags with the new nim-llm version
- Adopted RAG 2.3.2
- Removed manual NIM_MODEL_PROFILE configuration from Helm values and Docker Compose to rely on automatic profile detection, updated documentation accordingly

Release v1.2.0
- Added support for Helm deployments
- Add support and documentation for evaluation
- Simplified the configuration and integration with RAG, removing nginx
- Adopted RAG 2.3.0
- Tested for compatability with RTX Pro 6000

Release v1.1.0 
- Tested for compatability with RAG 2.2.0 release and B200
- Adds support for NVIDIA Workbench

Release v1.0.0

Initial release of the NVIDIA AI-Q Research Assistant Blueprint featuring:
- Multi-modal PDF document upload and processing, compatible with the NVIDIA RAG 2.1 blueprint release
- Demo web application
- Deep research report writing including human-in-the-loop feedback
