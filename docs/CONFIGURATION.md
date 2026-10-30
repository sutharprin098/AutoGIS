# AutoGIS configuration

## AI providers

Open **AutoGIS → Settings** and select an AI provider (Gemini, OpenAI, Claude,
DeepSeek, or OpenRouter), enter its API key, choose a model, and use **Test**
before saving. API keys are stored in the local QGIS settings profile. Do not
paste keys into issue reports, screenshots, project files, or the public web
portal. For stronger protection, use an OS credential manager and avoid sharing
the operating-system account.

## Google Earth Engine

1. Install `earthengine-api` into the Python environment used by QGIS:
   `python -m pip install earthengine-api`.
2. Create or select a Google Cloud project, enable the Earth Engine API, and
   register/request Earth Engine access for that project as required by Google.
3. In **AutoGIS → Settings → Earth Engine**, enter the Cloud Project ID.
4. For personal use, authenticate through the local Earth Engine OAuth flow.
   For unattended workflows, select a service-account JSON key and provide the
   service-account email. Grant that service account the required Earth Engine
   permissions and share any private assets with it.
5. Use **Test / Initialize** to initialize the local EE client.

Service-account JSON files contain private keys. Keep them outside the
repository and never upload them to GitHub. AutoGIS stores only the local file
path in QGIS settings; it does not copy or transmit the private key.

## OpenStreetMap and Overpass

OSM feature queries use public community Overpass instances. These are shared
services and can throttle, reject, or time out on large/high-density areas.
AutoGIS bounds concurrent mirror requests, uses POST requests, applies finite
timeouts, and provides a smaller-area retry. Zoom to a smaller area, request
one theme at a time, or retry later when an instance is overloaded. A client
cannot guarantee uptime or increase public-server capacity.

For production or repeated large-area extraction, configure and operate your
own Overpass instance or use a provider with an appropriate service agreement.
Respect OpenStreetMap's attribution and usage policies.
